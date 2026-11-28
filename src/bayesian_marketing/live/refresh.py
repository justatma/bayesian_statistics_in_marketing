"""Engine refresh after a good poll (spec v0.2 §5 L4). Piece L4."""

from __future__ import annotations

import hashlib
import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
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
)
from bayesian_marketing.core.records import ClientConfig
from bayesian_marketing.data_contract.connectors import meta
from bayesian_marketing.live import horizon as live_horizon
from bayesian_marketing.live import markers
from bayesian_marketing.live import rows as live_rows
from bayesian_marketing.live.contracts import Clock, LiveRow, PollRecord, RefreshRecord, Store
from bayesian_marketing.live.registry import LiveRegistry, load_live_registry

log = logging.getLogger(__name__)

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
    registry: LiveRegistry | None = None,
) -> RefreshRecord:
    """Runs ``ctr`` through ``pipeline.execute`` with the poll's rows in the analysis window
    (L12); stores and returns the record. ``registry`` gives ``analysis_days``, loaded from
    ``registries/live.yaml`` when not given. Never raises (C2)."""
    at = clock.now()
    refresh_id = (
        "lv_" + hashlib.sha256(f"{poll_rec.poll_id}|{at.isoformat()}".encode()).hexdigest()[:8]
    )
    if poll_rec.status != "ok":
        # B12: no engine run and nothing stored after an error or interrupted poll (C3)
        return RefreshRecord(
            refresh_id=refresh_id,
            poll_id=poll_rec.poll_id,
            client_id=poll_rec.client_id,
            at=at,
            status="skipped",
            reason=f"poll {poll_rec.poll_id} is {poll_rec.status}; no engine run",
            run_id=None,
        )
    status, reason, run_id = _outcome(config, poll_rec, store, data_dir, config_root, registry)
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
    registry: LiveRegistry | None,
) -> tuple[str, str | None, str | None]:
    try:
        reg = registry if registry is not None else load_live_registry()
        window = analysis_window(poll_rec.window, reg.analysis_days)
        # L12.1: every input below comes from the poll's rows dated in the analysis window
        rows = [r for r in store.rows(poll_rec.poll_id) if window[0] <= r.date <= window[1]]
        ads = sorted({r.entity_ids["ad"] for r in rows if r.entity_ids.get("ad")})
        if len(ads) < 2:
            return "skipped", ONE_AD, None
        if not config.economics_path:
            return "skipped", NO_ECONOMICS_PATH, None
        manifest = _manifest(config, poll_rec, rows, ads)
        pull = _pull(poll_rec, rows, window)
        horizon, basis = _budget_horizon(manifest, config_root, poll_rec, rows, store)
        request = CompareRequest(
            metric=METRIC,
            variants=ads,
            priors=dict(config.priors),
            window=window,
            horizon=horizon,
            conversion_kind=_conversion_kind(config),
            horizon_basis=basis,
        )
        # J2 (S30): no live run without its pointer; a raise here fails the refresh
        t0 = time.perf_counter()
        history, seen, _ = live_rows.versioned(store, poll_rec.client_id)
        # L12.7 (3), follow-up M2: the hourly job measures versioned's cost
        log.info(
            "refresh %s: versioned %d versions in %.3f s",
            poll_rec.poll_id,
            len(history),
            time.perf_counter() - t0,
        )
        # L12.2: the versions the poll read for dates in the run's window
        row_keys, sha = live_rows.pointer(
            history, seen, poll_rec.poll_id, (window[0].isoformat(), window[1].isoformat())
        )
        with data_dir_env(data_dir):
            ctx = pipeline.execute(
                manifest,
                request,
                manifest_dir=config_root,
                pulls=[pull],
                entity_names=_entity_names(rows),
                entity_parents=_entity_parents(rows),
                extra_dataset_hashes=[live_rows.HASH_PREFIX + sha],
                row_keys=row_keys,
                rows_form=live_rows.ROWS_FORM,
            )
            run_id = ctx.result.run.run_id
            # J3: the last step after the run is saved; a failure leaves the run ran (S34)
            try:
                markers.engine_run_marker(run_id)
            except Exception as exc:
                return "ran", f"marker not written: {type(exc).__name__}: {exc}", run_id
        return "ran", None, run_id
    except GateFailure as exc:
        return "skipped", _gate_text(exc), None
    except Exception as exc:  # C2: refresh never raises
        return "failed", f"{type(exc).__name__}: {exc}", None


def analysis_window(poll_window: tuple[date, date], analysis_days: int) -> tuple[date, date]:
    """L12.4: the last ``analysis_days`` of the poll's window, never wider than the poll's."""
    start, end = poll_window
    return max(start, end - timedelta(days=analysis_days - 1)), end


NAMED_LEVELS = ("campaign", "ad_set", "ad")


def _entity_names(rows: list[LiveRow]) -> dict[str, str]:
    """J4 (S16): id -> name for the ads, ad sets and campaigns the pull read, the latest day's
    name when a name changed within the pull."""
    names: dict[str, str] = {}
    for r in sorted(rows, key=lambda r: r.date):
        for level in NAMED_LEVELS:
            eid, name = r.entity_ids.get(level), r.entity_names.get(level)
            if eid and name:
                names[str(eid)] = str(name)
    return names


def _entity_parents(rows: list[LiveRow]) -> dict[str, str]:
    """J4R.2 (10): ad id -> ad set id as the pull read them, the latest day's when an ad moved
    within the pull."""
    parents: dict[str, str] = {}
    for r in sorted(rows, key=lambda r: r.date):
        ad, adset = r.entity_ids.get("ad"), r.entity_ids.get("ad_set")
        if ad and adset:
            parents[str(ad)] = str(adset)
    return parents


def _conversion_kind(config: ClientConfig) -> str:
    """D46: a lead event is counted, never valued; anything else is a purchase."""
    return "lead" if meta.is_lead_event(config.conversion_event.get(PLATFORM)) else "purchase"


def _gate_text(exc: GateFailure) -> str:
    """C2: the gate's reasons joined with "; ", from the GateResult the exception carries."""
    return "; ".join(str(r) for r in exc.result.reasons)


@contextmanager
def data_dir_env(path: Path) -> Iterator[None]:
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
    """The default CTR horizon, built as ``cli.demo_horizon("ctr")`` builds it; the fallback's
    horizon (fix v0.2 C6) is this one."""
    return live_horizon.default_horizon(pipeline.horizon_unit(METRIC))


def _budget_horizon(
    manifest: DatasetManifest,
    config_root: Path,
    poll_rec: PollRecord,
    rows: list[LiveRow],
    store: Store,
) -> tuple[Horizon, str]:
    """D53 (1), fix v0.2 C7: the horizon from the test budget left and its basis. Economics that
    cannot be read give the fallback (S8); the pipeline then skips or fails as before."""
    unit = pipeline.horizon_unit(METRIC)
    try:
        econ = pipeline._economics(manifest, config_root)
    except Exception:  # S8: any exception from the load
        econ = None
    if econ is None:
        return live_horizon.fallback(unit, live_horizon.WHY_NO_ECONOMICS)
    spent, since = live_horizon.spend_to_date(
        store, poll_rec.client_id, PLATFORM, poll_rec.started_at
    )
    return live_horizon.budget_horizon(econ.test_budget, spent, since, rows, unit)


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


def _pull(poll_rec: PollRecord, rows: list[LiveRow], window: tuple[date, date]) -> PlatformPull:
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
        window=window,
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
