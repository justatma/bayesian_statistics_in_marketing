"""Engine refresh after a good poll (spec v0.2 §5 L4). Piece L4."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path, PurePosixPath

from bayesian_marketing import pipeline
from bayesian_marketing.channels.model import channel_ref
from bayesian_marketing.core import (
    CompareRequest,
    DatasetManifest,
    GateFailure,
    Horizon,
    PerformanceRow,
    PlatformPull,
    registries,
)
from bayesian_marketing.core.records import ClientConfig
from bayesian_marketing.live.contracts import Clock, LiveRow, PollRecord, RefreshRecord, Store

ONE_AD = "one ad, nothing to compare"
NO_ECONOMICS_PATH = "no economics file in the client config"

METRIC = "ctr"  # C4: ctr only
PLATFORM = "meta"


def refresh(
    config: ClientConfig,
    poll_rec: PollRecord,
    store: Store,
    clock: Clock,
    *,
    data_dir: Path,
    config_root: Path,
) -> RefreshRecord:
    """Runs ``ctr`` through ``pipeline.execute`` with the poll's rows; stores and returns the
    record. Never raises (C2)."""
    at = clock.now()
    refresh_id = (
        "lv_" + hashlib.sha256(f"{poll_rec.poll_id}|{at.isoformat()}".encode()).hexdigest()[:8]
    )
    status, reason, run_id = _outcome(config, poll_rec, store, data_dir, config_root)
    rec = RefreshRecord(
        refresh_id=refresh_id,
        poll_id=poll_rec.poll_id,
        client_id=poll_rec.client_id,
        at=at,
        status=status,
        reason=reason,
        run_id=run_id,
    )
    store.add_refresh(rec)
    return rec


def _outcome(
    config: ClientConfig,
    poll_rec: PollRecord,
    store: Store,
    data_dir: Path,
    config_root: Path,
) -> tuple[str, str | None, str | None]:
    try:
        rows = store.rows(poll_rec.poll_id)
        ads = sorted({r.entity_ids["ad"] for r in rows if r.entity_ids.get("ad")})
        if len(ads) < 2:
            return "skipped", ONE_AD, None
        if not config.economics_path:
            return "skipped", NO_ECONOMICS_PATH, None
        manifest = _manifest(config, poll_rec, rows, ads)
        pull = _pull(poll_rec, rows)
        request = CompareRequest(
            metric=METRIC,
            variants=ads,
            priors=dict(config.priors),
            window=poll_rec.window,
            horizon=_horizon(),
        )
        with _data_dir(data_dir):
            ctx = pipeline.execute(manifest, request, manifest_dir=config_root, pulls=[pull])
        return "ran", None, ctx.result.run.run_id
    except GateFailure as exc:
        return "skipped", _gate_text(exc), None
    except Exception as exc:  # C2: refresh never raises
        return "failed", f"{type(exc).__name__}: {exc}", None


def _gate_text(exc: GateFailure) -> str:
    return str(exc.args[0]) if exc.args else str(exc)


@contextmanager
def _data_dir(path: Path) -> Iterator[None]:
    """Point the engine at ``path`` for the call; put the variable back, even on an exception."""
    before = os.environ.get("BAYES_DATA_DIR")
    os.environ["BAYES_DATA_DIR"] = str(path)
    try:
        yield
    finally:
        if before is None:
            os.environ.pop("BAYES_DATA_DIR", None)
        else:
            os.environ["BAYES_DATA_DIR"] = before


def _horizon() -> Horizon:
    """The default CTR horizon, built as ``cli.demo_horizon("ctr")`` builds it."""
    h = registries.resolve("decision_defaults/horizon_default@v1")
    unit = pipeline.horizon_unit(METRIC)
    return Horizon(unit=unit, amount=Decimal(str(h["amount"])))  # type: ignore[arg-type]


def _manifest(
    config: ClientConfig, poll_rec: PollRecord, rows: list[LiveRow], ads: list[str]
) -> DatasetManifest:
    sha8 = hashlib.sha256(f"{config.client_id}|{poll_rec.poll_id}".encode()).hexdigest()[:8]
    windows = sorted({r.attribution_window for r in rows})
    currencies = sorted({r.spend.currency for r in rows})
    return DatasetManifest(
        manifest_id=f"ds_{sha8}",
        client_id=config.client_id,
        economics_id=PurePosixPath(str(config.economics_path)).stem,
        files=[],
        attribution_window={PLATFORM: windows[0]},
        entity_map={ad: {PLATFORM: ad} for ad in ads},
        synthetic=False,
        currency=currencies[0] if currencies else poll_rec.currency,
    )


def _pull(poll_rec: PollRecord, rows: list[LiveRow]) -> PlatformPull:
    perf = [
        PerformanceRow(
            entity_ids=dict(r.entity_ids),
            entity_names=dict(r.entity_names),
            objective=r.objective,
            date=r.date,
            impressions=r.impressions,
            clicks=r.clicks,
            spend=r.spend,
            conversions_observed=r.conversions_observed,
            conversions_reported=r.conversions_reported,
            attribution_window=r.attribution_window,
            revenue_reported=r.revenue_reported,
        )
        for r in rows
    ]
    # as pull() computes it (C8); a LiveRow carries no modeled share, so every share is None
    partial = any(r.conversions_observed is None for r in perf) and all(
        r.conversions_modeled_share is None for r in perf
    )
    return PlatformPull(
        pull_id=str(poll_rec.pull_id),
        platform=PLATFORM,
        channel_ref=channel_ref(PLATFORM),
        account_id=poll_rec.account_id,
        window=poll_rec.window,
        rows=perf,
        quarantined=[],
        partial_truth=partial,
        measurement_changes=[],
        empty_account=poll_rec.empty_account,
        timezone=poll_rec.timezone,
        account=dict(poll_rec.account),
        pulled_at=poll_rec.finished_at or poll_rec.started_at,
        synthetic=False,
    )
