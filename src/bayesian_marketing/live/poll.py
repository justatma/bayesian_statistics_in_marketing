"""One poll: one read of one client's account into the store (spec v0.2 §5 L2 C1-C6). Piece L2."""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from bayesian_marketing.core.base import Platform
from bayesian_marketing.core.data import PerformanceRow, PlatformPull
from bayesian_marketing.core.records import ClientConfig
from bayesian_marketing.data_contract.connectors import http
from bayesian_marketing.data_contract.connectors.pull import pull
from bayesian_marketing.live.contracts import Clock, LiveRow, PollRecord, Store
from bayesian_marketing.live.prune import prune
from bayesian_marketing.live.registry import LiveRegistry

log = logging.getLogger(__name__)


def poll_id(client_id: str, platform: str, started_at_iso: str) -> str:
    """``poll_<sha8>`` over ``client_id|platform|started_at.isoformat()`` (§2)."""
    digest = hashlib.sha256(f"{client_id}|{platform}|{started_at_iso}".encode()).hexdigest()
    return "poll_" + digest[:8]


def _window(
    config: ClientConfig, store: Store, platform: Platform, now: datetime, lookback_days: int
) -> tuple[date, date]:
    """C1: ``lookback_days`` account-local dates ending today inclusive."""
    last = store.latest_poll(config.client_id)
    tz = last.timezone if last is not None and last.platform == platform else None
    today = now.astimezone(ZoneInfo(tz or config.timezone)).date()
    return today - timedelta(days=lookback_days - 1), today


@contextmanager
def _record_env(target: Path | None) -> Iterator[None]:
    """C1: ``BAYES_RECORD_DIR`` set for the pull only; the previous value comes back."""
    if target is None:
        yield
        return
    previous = os.environ.get(http.RECORD_ENV)
    os.environ[http.RECORD_ENV] = str(target)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(http.RECORD_ENV, None)
        else:
            os.environ[http.RECORD_ENV] = previous


def _live_rows(rec: PollRecord, got: PlatformPull) -> list[LiveRow]:
    out = []
    for r in got.rows:
        if not isinstance(r, PerformanceRow):
            raise TypeError(f"live view stores performance rows, got {type(r).__name__}")
        out.append(
            LiveRow(
                poll_id=rec.poll_id,
                client_id=rec.client_id,
                platform=rec.platform,
                entity_ids=r.entity_ids,
                entity_names=r.entity_names,
                objective=r.objective,
                date=r.date,
                impressions=r.impressions,
                clicks=r.clicks,
                spend=r.spend,
                conversions_reported=r.conversions_reported,
                conversions_observed=r.conversions_observed,
                revenue_reported=r.revenue_reported,
                attribution_window=r.attribution_window,
            )
        )
    return out


def _error_text(exc: BaseException) -> str:
    """C3: ``<ExceptionClass>: <message>`` with every credential value and token blanked."""
    return http.redact_text(f"{type(exc).__name__}: {exc}")


def poll(
    config: ClientConfig,
    store: Store,
    clock: Clock,
    *,
    platform: Platform = "meta",
    registry: LiveRegistry,
    record_root: Path | None,
) -> PollRecord:
    """Never raises (C3). Returns the finished record, ok or error."""
    started = clock.now()
    pid = poll_id(config.client_id, platform, started.isoformat())
    target = None if record_root is None else Path(record_root) / config.client_id / pid
    setup_error: Exception | None = None
    try:
        window = _window(config, store, platform, started, registry.lookback_days)
    except Exception as exc:  # e.g. an unknown zone name: still an error row, never a raise
        setup_error = exc
        d = started.date()
        window = (d - timedelta(days=registry.lookback_days - 1), d)
    begun = PollRecord(
        poll_id=pid,
        client_id=config.client_id,
        platform=platform,
        account_id=config.accounts.get(platform, ""),
        started_at=started,
        finished_at=None,
        window=window,
        status="interrupted",
        error=None,
        pull_id=None,
        n_rows=0,
        n_quarantined=0,
        empty_account=False,
        timezone=None,
        currency=None,
        account={},
        recording_dir=None if target is None else str(target),
    )
    store.begin_poll(begun)
    try:
        if setup_error is not None:
            raise setup_error
        with _record_env(target):
            got = pull(platform, config, window)
        rec = begun.model_copy(
            update={
                "finished_at": clock.now(),
                "status": "ok",
                "pull_id": got.pull_id,
                "n_rows": len(got.rows),
                "n_quarantined": len(got.quarantined),
                "empty_account": got.empty_account,
                "timezone": got.timezone,
                "currency": got.account.get("currency") or config.currency,
                "account": dict(got.account),
            }
        )
        rows = _live_rows(rec, got)
    except Exception as exc:
        rec = begun.model_copy(
            update={"finished_at": clock.now(), "status": "error", "error": _error_text(exc)}
        )
        rows = []
    store.finish_poll(rec, rows)
    if record_root is not None:
        try:
            prune(Path(record_root), store, clock, registry.recordings_keep_days)
        except Exception as exc:  # retention never turns a stored poll into a failure
            log.warning("prune after %s failed: %s", pid, _error_text(exc))
    return rec
