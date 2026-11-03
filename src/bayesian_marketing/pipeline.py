"""§13.2 the pipeline. Piece P11.

``run`` executes, in order::

    read (G1) -> lag -> route -> [conjugate | compile + priors (G8) -> NUTS (G3, fallback)]
      -> funnel_state.save -> derive (G10) -> quantity feasibility -> publish (G2)
      -> compare (G9) -> decision feasibility -> recommend (guarantee templates)
      -> run_record.append -> return

Rules the pipeline adds (D28, D30, I10, I12): a client run (``manifest.synthetic`` False) is
refused before anything is fitted unless its economics are approved and carry a loss tolerance
(G9), and unless every prior it would use is approved (G8). On synthetic data a G9 failure gives a
``not_knowable`` recommendation instead.

One comparison runs on one ad platform: the platform the requested variants map to in
``entity_map``. Only the compared ads are fitted, so the route follows D11's count of ads in a
comparison. Orders join to ads through ``utm_map`` only (§5.1 C7); their counts are observed
conversions on the click date (C8, §5.6 C2) and their values feed the order-value stage.

Every run writes a snapshot under ``<BAYES_DATA_DIR>/runs/<run_id>.json`` (write-once) so the
socket can answer later calls (evidence, narrative check, render) for that run id.
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from bayesian_marketing import __version__
from bayesian_marketing.claims.vocab import METRIC_LABELS
from bayesian_marketing.core import (
    ClientEconomics,
    CompareRequest,
    Comparison,
    DatasetManifest,
    DiagnosticsReport,
    Feasibility,
    FunnelData,
    FunnelSpec,
    FunnelState,
    GateFailure,
    GateResult,
    Horizon,
    KnowabilitySection,
    LagModel,
    NotInScope,
    Objective,
    OrderRow,
    PerformanceRow,
    PlatformPull,
    PriorSet,
    Quantity,
    Recommendation,
    Route,
    RunRecord,
    RunResult,
    Scope,
    StageSpec,
    inputs_hash,
    load_economics,
    make_id,
    registries,
    utcnow,
    worst_status,
)
from bayesian_marketing.data_contract.readers.read import read_export
from bayesian_marketing.decision import run_record
from bayesian_marketing.decision.allocation import allocate
from bayesian_marketing.decision.compare import PLANNED_TARGETS, compare
from bayesian_marketing.decision.compare import SUPPORTED as COMPARE_SUPPORTED
from bayesian_marketing.decision.reallocation import base_slots, make_guarantee
from bayesian_marketing.decision.stopping import MIN_MATURITY_REF, stop_or_continue
from bayesian_marketing.derived_metrics.derive import NotEstimable, derive
from bayesian_marketing.diagnostics.run import run_diagnostics
from bayesian_marketing.floors.estimability import (
    DECISION_KEY,
    RATE_KEY,
    SIGNED_QUANTITIES,
    decision_feasibility,
    quantity_feasibility,
    registry_target,
)
from bayesian_marketing.funnel_state import store
from bayesian_marketing.inference import conjugate, fallback, router
from bayesian_marketing.lag.model import (
    NO_CLICK_WINDOW_CODES,
    lag_model,
    lag_notices,
    longest_default_window,
    mature_fraction,
)
from bayesian_marketing.prior_registry import registry as prior_registry
from bayesian_marketing.status_registry.registry import StatusImmutableError, publish

AD_PLATFORMS = ("meta", "google_ads", "linkedin")
FUNNEL_SPEC_VERSION = "funnel@v1"
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "generated"
RUNS_DIR = "runs"

METRICS = ("ctr", "cvr", "cpa", "roas", "contribution_per_click", "contribution")
"""§11.1: the metrics AtmaOS may ask for."""
RATE_METRICS = ("ctr", "cvr")
"""§11.1: the objective is contribution unless the metric names a rate."""
DISPLAY = ("ctr", "cvr", "cpa", "aov", "roas", "contribution_per_click")
"""Quantities derived per compared ad, besides the metric itself (§5.5)."""
CONVERSION_BASED = frozenset({"cvr", "cpa", "roas", "contribution_per_click"})
SIGNED_INPUTS = ("cvr", "aov")
"""D10: a signed money quantity carries the worst status of these inputs of the same ad."""

# Wording with no phrasing.yaml key yet (manifest open questions). One place, plain words.
LAG_NOT_MODELED = "conversion lag not adjusted: no lag curve for attribution window {code} ({why})"
WINDOW_CHANGED = "attribution window changed in the data window: {changes}"
NO_ECONOMICS = "economics {eid} not found"
CLIENT_NEEDS_ECONOMICS = (
    "client run refused: approved economics with a loss tolerance are required (G9, D30)"
)
G9_REQUIREMENT = "approved economics with a loss tolerance are needed before any decision"
NOT_ESTIMABLE_REASON = "{quantity} not estimable for {options}: {why}"
DATA_REQUIREMENT = "{quantity} has to become estimable for every compared ad"
PLANNED_OBJECTIVE = "objective {metric!r} needs its value model ({model}); not built yet (D33)"
INHERITED_REASON = "inherits the worst status of its inputs ({inputs}) (D10)"
NON_FINITE_REASON = (
    "the posterior has no finite spread for this quantity with the data seen (too few events)"
)
NO_INPUTS_REASON = "no input status to inherit: {inputs} not estimable for this ad"


Stage = Callable[[str, dict[str, Any]], None]
"""Progress hook: ``on_stage(name, info)`` after each pipeline stage (the demo CLI prints it)."""


def data_dir() -> Path:
    return Path(os.environ.get("BAYES_DATA_DIR", DEFAULT_DATA_DIR))


# ------------------------------------------------------------------------------- snapshot


class RunSnapshot(BaseModel):
    """What later socket calls need about a run. Not a core type: it never crosses a module
    boundary except back into this piece (socket, CLI, replay)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    client_id: str
    synthetic: bool
    manifest_id: str
    dataset_hashes: list[str]
    platform: str
    window: tuple[date, date]
    as_of: date
    metric: str
    compare_quantity: str
    horizon: Horizon
    segments: dict[str, Any]
    variants: dict[str, str]  # variant -> ad id on the platform
    priors: dict[str, str]  # parameter path -> prior id used
    configuration: dict[str, Any]
    config_hash: str
    tool_version: str
    currency: str
    economics_id: str | None
    route: Route
    quantities: list[Quantity]
    not_estimable: dict[str, dict[str, str]]  # variant -> quantity name -> reason
    published: dict[str, bool]  # quantity id -> published by G2
    comparison: Comparison | None
    decision: Feasibility | None
    recommendations: list[Recommendation]
    diagnostics: list[DiagnosticsReport]
    gate_results: list[GateResult]
    knowability: KnowabilitySection
    notices: list[str]


def snapshot_path(run_id: str) -> Path:
    if not run_id.startswith("run_") or "/" in run_id or "\\" in run_id:
        raise ValueError(f"bad run id {run_id!r}")
    return data_dir() / RUNS_DIR / f"{run_id}.json"


def load_snapshot(run_id: str) -> RunSnapshot:
    path = snapshot_path(run_id)
    if not path.exists():
        raise KeyError(f"no run {run_id!r} under {path.parent}")
    return RunSnapshot.model_validate_json(path.read_text())


def _write_snapshot(s: RunSnapshot) -> None:
    path = snapshot_path(s.run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"run {s.run_id} already has a snapshot")
    tmp = path.with_suffix(f".json.{os.getpid()}.tmp")
    tmp.write_text(s.model_dump_json())
    os.replace(tmp, path)


@dataclass
class RunContext:
    result: RunResult
    snapshot: RunSnapshot
    data: FunnelData
    pulls: list[PlatformPull] = field(default_factory=list)


# ------------------------------------------------------------------------------- helpers


def _gate(gate: str, passed: bool, reasons: list[str], payload: Any) -> GateResult:
    return GateResult(
        gate=gate,
        passed=passed,
        blocking=not passed,
        reasons=reasons,
        inputs_hash=inputs_hash(payload),
        checked_at=utcnow(),
    )


def _emit(on_stage: Stage | None, name: str, **info: Any) -> None:
    if on_stage is not None:
        on_stage(name, info)


def tool_version() -> str:
    regs = registries.versions()
    return f"bayesian-marketing {__version__}; registries " + ", ".join(
        f"{k}@{v}" for k, v in sorted(regs.items())
    )


def compare_quantity(metric: str) -> str:
    """The quantity the decision compares for a metric (§11.1). A D33 objective (leads,
    subscription contribution) raises NotInScope naming the value model it waits for."""
    if metric in PLANNED_TARGETS:
        raise NotInScope(PLANNED_OBJECTIVE.format(metric=metric, model=PLANNED_TARGETS[metric]))
    if metric not in METRICS:
        raise ValueError(f"metric {metric!r} is not one of {METRICS}")
    return metric if metric in RATE_METRICS else "contribution_per_click"


def metric_quantity(metric: str) -> str:
    return "contribution_per_click" if metric == "contribution" else metric


def comparison_platform(manifest: DatasetManifest, variants: list[str]) -> str:
    """The one ad platform every requested variant maps to."""
    if len(variants) < 2:
        raise ValueError("a comparison needs at least two variants")
    if len(set(variants)) != len(variants):
        raise ValueError("variants repeat")
    missing = [v for v in variants if v not in manifest.entity_map]
    if missing:
        raise ValueError(f"variants {missing} are not keys of the dataset's entity_map")
    platforms: set[str] = set()
    for v in variants:
        ads = [p for p in manifest.entity_map[v] if p in AD_PLATFORMS]
        if len(ads) != 1:
            raise ValueError(f"variant {v!r} must map to exactly one ad platform, got {ads}")
        platforms.add(ads[0])
    if len(platforms) != 1:
        raise ValueError(
            f"variants span platforms {sorted(platforms)}; one comparison runs on one platform"
        )
    return platforms.pop()


def _economics(manifest: DatasetManifest, manifest_dir: Path) -> ClientEconomics | None:
    try:
        return load_economics(manifest.economics_id, manifest_dir)
    except FileNotFoundError:
        return None


def _economics_block(econ: ClientEconomics | None, eid: str) -> list[str]:
    if econ is None:
        return [NO_ECONOMICS.format(eid=eid)]
    out = []
    if not econ.approved:
        out.append("economics not approved")
    if econ.loss_tolerance is None:
        out.append("no loss tolerance set")  # D16, verbatim
    return out


@contextmanager
def _economics_visible(manifest_dir: Path, economics_id: str) -> Iterator[None]:
    """``allocate`` resolves economics by id alone (D22 item 9). When the economics sit beside the
    manifest, point ``BAYES_CONFIG_DIR`` there for the call so allocate finds the same file."""
    local = manifest_dir / "economics" / f"{economics_id}.json"
    if not local.exists():
        yield
        return
    old = os.environ.get("BAYES_CONFIG_DIR")
    os.environ["BAYES_CONFIG_DIR"] = str(manifest_dir)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("BAYES_CONFIG_DIR", None)
        else:
            os.environ["BAYES_CONFIG_DIR"] = old


# ------------------------------------------------------------------------------- read (G1)


def read_pulls(
    manifest: DatasetManifest, manifest_dir: Path, platform: str, as_of: date
) -> tuple[list[PlatformPull], list[GateResult]]:
    """G1 on the comparison platform's exports and the orders file. A failure on the platform
    blocks the run; a failure on the orders file is recorded and the run goes on without it."""
    pulls: list[PlatformPull] = []
    gates: list[GateResult] = []
    for f in manifest.files:
        if f.platform not in (platform, "orders"):
            continue
        try:
            pull = read_export(f.platform, manifest_dir / f.path, manifest, as_of=as_of)
        except GateFailure as e:
            if f.platform == platform:
                raise
            gates.append(e.result)
            continue
        reasons = [f"{len(pull.quarantined)} rows quarantined"] if pull.quarantined else []
        gates.append(
            GateResult(
                gate="G1",
                passed=True,
                blocking=False,
                reasons=reasons,
                inputs_hash=inputs_hash({"pull": pull.pull_id, "file": f.sha256}),
                checked_at=utcnow(),
            )
        )
        pulls.append(pull)
    if not any(p.platform == platform for p in pulls):
        raise ValueError(f"the dataset has no {platform} export")
    return pulls, gates


# ------------------------------------------------------------------------------- assemble


def _local_date(ts: datetime, zone: ZoneInfo) -> date:
    return ts.astimezone(zone).date()


def joined_orders(
    orders: list[OrderRow], utm_map: dict[str, dict[str, str]] | None, platform: str
) -> dict[str, list[OrderRow]]:
    """Ad id -> orders joined through ``utm_map`` (utm campaign or content, §5.1 C7)."""
    out: dict[str, list[OrderRow]] = {}
    if not utm_map:
        return out
    for o in orders:
        utm = o.utm or {}
        for key in ("campaign", "utm_campaign", "content", "utm_content"):
            target = utm_map.get(utm.get(key, "")) if utm.get(key) else None
            if target and platform in target:
                out.setdefault(target[platform], []).append(o)
                break
    return out


def assemble_funnel_data(
    pulls: list[PlatformPull],
    lag: LagModel | None,
    as_of: date,
    *,
    utm_map: dict[str, dict[str, str]] | None = None,
    start: date | None = None,
    end: date | None = None,
    ads: list[str] | None = None,
) -> FunnelData:
    """One platform's pulls (and its orders pull, if any) into FunnelData (D22).

    ``as_of`` is when the data were observed (mature fractions, §5.6). Rows dated after ``end``
    (default ``as_of``) or before ``start`` are left out. Several rows for one ad and day
    are summed; a day's observed or reported count stays None unless every row carries it.
    Orders joined to an ad through ``utm_map`` are observed conversions on their click date
    (``first_click_at``, else the order date) in the account timezone, and their values are the
    ad's order values. ``lag`` None means no lag adjustment (mature fraction 1, disclosed by the
    caller). ``ads`` restricts and orders the entities.
    """
    perf = [p for p in pulls if p.platform in AD_PLATFORMS]
    platforms = {p.platform for p in perf}
    if len(platforms) != 1:
        raise ValueError(f"assemble_funnel_data takes one ad platform, got {sorted(platforms)}")
    platform = platforms.pop()
    orders_pulls = [p for p in pulls if p.platform == "orders"]

    rows: list[PerformanceRow] = []
    for p in perf:
        for r in p.rows:
            assert isinstance(r, PerformanceRow)
            if r.date > (end or as_of) or (start is not None and r.date < start):
                continue
            if ads is not None and r.entity_ids.get("ad") not in ads:
                continue
            rows.append(r)
    if not rows:
        raise ValueError(f"no {platform} rows in the window ending {(end or as_of).isoformat()}")
    currencies = {r.spend.currency for r in rows}
    if len(currencies) != 1:
        raise ValueError(f"{platform} rows mix currencies {sorted(currencies)}")
    currency = currencies.pop()

    entities = list(ads) if ads is not None else sorted({r.entity_ids["ad"] for r in rows})
    seen = {r.entity_ids["ad"] for r in rows}
    absent = [a for a in entities if a not in seen]
    if absent:
        raise ValueError(f"no {platform} rows for ads {absent}")
    dates = sorted({r.date for r in rows})
    e_idx = {a: i for i, a in enumerate(entities)}
    d_idx = {d: j for j, d in enumerate(dates)}
    n_e, n_d = len(entities), len(dates)

    spend = [[0.0] * n_d for _ in range(n_e)]
    imps = [[0] * n_d for _ in range(n_e)]
    clicks = [[0] * n_d for _ in range(n_e)]
    obs: list[list[int | None]] = [[None] * n_d for _ in range(n_e)]
    rep: list[list[float | None]] = [[None] * n_d for _ in range(n_e)]
    rev: list[list[float | None]] = [[None] * n_d for _ in range(n_e)]
    seen_cells: set[tuple[int, int]] = set()
    parents: dict[str, dict[str, str]] = {}

    def add(cur: Any, x: Any, first: bool) -> Any:
        if first:
            return x
        return None if cur is None or x is None else cur + x

    for r in rows:
        i, j = e_idx[r.entity_ids["ad"]], d_idx[r.date]
        first = (i, j) not in seen_cells
        seen_cells.add((i, j))
        spend[i][j] += float(r.spend.amount)
        imps[i][j] += r.impressions
        clicks[i][j] += r.clicks
        obs[i][j] = add(obs[i][j], r.conversions_observed, first)
        rep[i][j] = add(rep[i][j], r.conversions_reported, first)
        rv = None if r.revenue_reported is None else float(r.revenue_reported.amount)
        rev[i][j] = add(rev[i][j], rv, first)
        parents.setdefault(
            entities[i],
            {k: v for k, v in r.entity_ids.items() if k in ("campaign", "account", "ad_set")},
        )

    tz = next((p.timezone for p in perf if p.timezone), None)
    zone = ZoneInfo(tz or "UTC")
    order_values: dict[str, list[float]] = {}
    used_orders = False
    orders = [o for p in orders_pulls for o in p.rows if isinstance(o, OrderRow)]
    by_ad = joined_orders(orders, utm_map, platform)
    for ad, joined in by_ad.items():
        if ad not in e_idx:
            continue
        i = e_idx[ad]
        counts = [0] * n_d
        values: list[float] = []
        for o in joined:
            ordered = _local_date(o.ordered_at, zone)
            if ordered > as_of:
                continue  # not yet observed
            clicked = _local_date(o.first_click_at, zone) if o.first_click_at else ordered
            if clicked not in d_idx:
                continue  # clicked outside the window
            counts[d_idx[clicked]] += 1
            if o.value.currency == currency and o.value.amount > 0:
                values.append(float(o.value.amount))
        for j in range(n_d):
            obs[i][j] = counts[j]
        order_values[ad] = values
        used_orders = True

    if lag is None:
        mature = [[1.0] * n_d for _ in range(n_e)]
    else:
        mature = [[mature_fraction(d, as_of, lag) for d in dates] for _ in range(n_e)]

    pull_ids = [p.pull_id for p in perf]
    if used_orders:
        pull_ids += [p.pull_id for p in orders_pulls]
    return FunnelData(
        platform=platform,
        currency=currency,
        entities=entities,
        parents={a: parents.get(a, {}) for a in entities},
        dates=dates,
        spend=spend,
        impressions=imps,
        clicks=clicks,
        conversions_observed=obs,
        conversions_reported=rep,
        mature_fraction=mature,
        revenue_reported=rev,
        order_values={a: v for a, v in order_values.items() if v},
        pull_ids=pull_ids,
        synthetic=any(p.synthetic for p in pulls),
    )


# ------------------------------------------------------------------------------- lag


def observed_as_of(perf: list[PlatformPull], orders: list[OrderRow], end: date) -> date:
    """When the data were observed: the window end, or the latest order date in the account
    timezone if the orders file runs past it (late conversions already seen, §5.6 C2)."""
    tz = next((p.timezone for p in perf if p.timezone), None)
    zone = ZoneInfo(tz or "UTC")
    latest = max((_local_date(o.ordered_at, zone) for o in orders), default=end)
    return max(end, latest)


def window_code(perf: list[PlatformPull], as_of: date) -> str:
    """The attribution window in force at the end of the data: the latest row's code."""
    rows = [r for p in perf for r in p.rows if isinstance(r, PerformanceRow) and r.date <= as_of]
    if not rows:
        raise ValueError("no performance rows to read the attribution window from")
    return max(rows, key=lambda r: r.date).attribution_window


def fit_lag(
    platform: str,
    perf: list[PlatformPull],
    orders: list[OrderRow],
    utm_map: dict[str, dict[str, str]] | None,
    as_of: date,
    end: date,
) -> tuple[LagModel | None, list[str]]:
    """lag_model with right-censoring at ``as_of`` (P7 follow-up), and its notices. The window
    code is the one in force on ``end``. A code that names no click window (Google Ads
    ``per_conversion_action``) takes the registry's longest click window (D38.3): lag from the
    orders' ``first_click_at`` when enough orders carry it, else that window's default curve."""
    code = window_code(perf, end)
    history = [o for rows in joined_orders(orders, utm_map, platform).values() for o in rows]
    tz = next((p.timezone for p in perf if p.timezone), None)
    days = longest_default_window() if code in NO_CLICK_WINDOW_CODES else None
    try:
        lag = lag_model(
            platform,  # type: ignore[arg-type]
            code,
            history or None,
            None,
            timezone=tz,
            as_of=as_of,
            click_window_days=days,
        )
    except (ValueError, KeyError) as e:
        return None, [LAG_NOT_MODELED.format(code=code, why=e)]
    return lag, lag_notices(lag)


# ------------------------------------------------------------------------------- priors (G8)


PRIOR_PATHS_CONJUGATE = (*conjugate.REQUIRED_PRIORS, conjugate.CPM_PRIOR)


def prior_paths() -> list[str]:
    return list(registries.load("priors/default").get("records") or {})


def resolve_priors(
    requested: dict[str, str], client_id: str, synthetic: bool, when: datetime
) -> tuple[PriorSet, GateResult]:
    """Framework defaults through ``prior_registry.resolve`` (client, vertical, default); a
    requested id must be the approved prior that path resolves to, else G8 (§11.1). On client
    data every prior used must be approved (D28, I10)."""
    paths = prior_paths()
    unknown = [p for p in requested if p not in paths]
    reasons: list[str] = []
    if unknown:
        reasons += [f"no prior path {p!r} in the registry" for p in unknown]
    records = {}
    for path in paths:
        rec = prior_registry.resolve(path, client_id, when)  # raises G8 on an unapproved client
        want = requested.get(path)
        if want is not None and want != rec.prior_id:
            reasons.append(
                f"prior {want!r} for {path!r} is unknown or not the approved prior for this "
                f"client (resolves to {rec.prior_id})"
            )
        if not rec.approved and not synthetic:
            reasons.append(f"prior {rec.prior_id} for {path!r} is not approved (I10, D28)")
        records[path] = rec
    payload = {"requested": requested, "resolved": {p: r.prior_id for p, r in records.items()}}
    if reasons:
        raise GateFailure(_gate("G8", False, reasons, payload))
    return PriorSet(records=records), _gate("G8", True, [], payload)


# ------------------------------------------------------------------------------- route + fit


def funnel_spec(data: FunnelData) -> FunnelSpec:
    """The joint-route spec for this data: gamma_obs CVR when conversions are fractional and
    platform-reported (§5.2 C6), log-normal value with an orders file, else compound gamma."""
    fractional = any(
        data.conversions_observed[i][j] is None
        and data.conversions_reported[i][j] is not None
        and abs(data.conversions_reported[i][j] - round(data.conversions_reported[i][j])) > 1e-9  # type: ignore[operator, arg-type]
        for i in range(len(data.entities))
        for j in range(len(data.dates))
    )
    hierarchy: list[Any] = ["ad"]
    for level in ("campaign", "account"):
        if all(level in data.parents.get(a, {}) for a in data.entities):
            hierarchy.append(level)
    return FunnelSpec(
        version=FUNNEL_SPEC_VERSION,
        stages=[
            StageSpec(name="delivery", likelihood="poisson", pooled=True),
            StageSpec(name="ctr", likelihood="binomial", pooled=True),
            StageSpec(
                name="cvr", likelihood="gamma_obs" if fractional else "binomial", pooled=True
            ),
            StageSpec(
                name="value",
                likelihood="lognormal" if data.order_values else "compound_gamma",
                pooled=True,
            ),
        ],
        hierarchy=hierarchy,
        coupling="lkj_bivariate",
        dynamics="static",
    )


@dataclass
class Fit:
    route: Route
    state: FunnelState
    reports: list[DiagnosticsReport]
    notices: list[str]
    spec: FunnelSpec
    step: str
    """The step that produced the state: ``conjugate`` (D11 route), ``nuts_full``,
    ``nuts_static``, ``nuts_unpooled`` or ``fallback_conjugate`` (§7.5)."""


def fit(data: FunnelData, priors: PriorSet, seed: int) -> Fit:
    spec = funnel_spec(data)
    r = router.route(spec, data)
    notices = list(r.notices)
    if r.kind == "conjugate":
        state = conjugate.fit_conjugate(data, priors, seed)
        reports = [run_diagnostics(state, data)]  # PPC on the exact route; no sampler ran
        step = "conjugate"
    else:
        state, reports, degr = fallback.fit_with_fallback(spec, priors, data, seed)
        notices += [f"{n.step}: {n.reason}" for n in degr]
        step = degr[-1].step if degr else "nuts_full"
        if step == "conjugate":
            step = "fallback_conjugate"
    store.save(state)
    return Fit(r, state, reports, notices, spec, step)


# ------------------------------------------------------------------------------- derive + floors


def _rate_ref() -> str:
    return f"{RATE_KEY}@{registries.load('bounds')['version']}"


def _decision_ref() -> str:
    return f"{DECISION_KEY}@{registries.load('bounds')['version']}"


def _inherited(q: Quantity, inputs: list[Quantity], names: list[str]) -> Feasibility:
    if not inputs:
        return Feasibility(
            status="below_floor",
            basis="inherited",
            bound_ref=_rate_ref(),
            available=float(q.n_events or 0.0),
            required=None,
            target=q.feasibility.target,
            reasons=[NO_INPUTS_REASON.format(inputs=", ".join(names))],
            checked_at=utcnow(),
        )
    status = worst_status([x.feasibility.status for x in inputs])
    reasons = []
    if status != "estimable":
        reasons.append(INHERITED_REASON.format(inputs=", ".join(x.name for x in inputs)))
        for x in inputs:
            reasons += [f"{x.name}: {why}" for why in x.feasibility.reasons]
    return Feasibility(
        status=status,
        basis="inherited",
        bound_ref=_rate_ref(),
        available=float(q.n_events or 0.0),
        required=None,
        target=q.feasibility.target,
        reasons=reasons,
        checked_at=utcnow(),
    )


def derive_all(
    state: FunnelState,
    variants: dict[str, str],
    names: list[str],
    window: tuple[date, date],
    platform: str,
    econ: ClientEconomics | None,
    extra_notices: list[str],
) -> tuple[dict[str, dict[str, Quantity]], dict[str, dict[str, str]]]:
    """Derive (G10 at construction), then the floor's status for each quantity (§6.1)."""
    target = registry_target()
    out: dict[str, dict[str, Quantity]] = {}
    missing: dict[str, dict[str, str]] = {}
    for variant, ad in variants.items():
        scope = Scope(level="ad", ids={"ad": ad}, window=window, platform=platform)  # type: ignore[arg-type]
        got: dict[str, Quantity] = {}
        for name in names:
            try:
                q = derive(name, state, scope, econ)
            except NotEstimable as e:
                missing.setdefault(variant, {})[name] = e.reason
                continue
            if not all(math.isfinite(v) for v in q.estimate.summary.values()):
                missing.setdefault(variant, {})[name] = NON_FINITE_REASON
                continue
            if name in CONVERSION_BASED and extra_notices:
                q = q.model_copy(update={"notices": [*q.notices, *extra_notices]})
            if name not in SIGNED_QUANTITIES:
                try:
                    feas = quantity_feasibility(q, target)
                except ArithmeticError as e:  # e.g. an overflowing width projection
                    missing.setdefault(variant, {})[name] = f"{NON_FINITE_REASON} ({e})"
                    continue
                q = q.model_copy(update={"feasibility": feas})
            got[name] = q
        for name, q in list(got.items()):
            if name in SIGNED_QUANTITIES:
                inputs = [got[n] for n in SIGNED_INPUTS if n in got]
                feas = _inherited(q, inputs, list(SIGNED_INPUTS))
                got[name] = q.model_copy(update={"feasibility": feas})
        out[variant] = got
    return out, missing


def publish_all(quantities: list[Quantity]) -> tuple[dict[str, bool], list[GateResult]]:
    """G2. A refused quantity is not published; the run records why and goes on (§13.1)."""
    published: dict[str, bool] = {}
    gates: list[GateResult] = []
    for q in quantities:
        try:
            publish(q)
        except GateFailure as e:
            published[q.quantity_id] = False
            gates.append(e.result)
            continue
        except StatusImmutableError as e:
            published[q.quantity_id] = False
            gates.append(_gate("G2", False, [str(e)], {"q": q.quantity_id}))
            continue
        published[q.quantity_id] = True
    ok = [qid for qid, v in published.items() if v]
    if ok:
        gates.append(_gate("G2", True, [], {"published": ok}))
    return published, gates


# ------------------------------------------------------------------------------- decide


def not_knowable(
    run_id: str,
    reason: str,
    objective: Objective,
    scope: Scope,
    economics_id: str | None,
    currency: str,
    requirement: str,
) -> Recommendation:
    """A ``not_knowable`` recommendation when no Comparison exists. It states its own reason
    and requirement once (D38.1); the G9 requirement only when G9 is the reason."""
    horizon = objective.horizon
    probe = Comparison(
        options=[],
        objective=objective,
        economics_id=economics_id or "none",
        p_best={},
        expected_value={},
        expected_loss={},
        p_exceeds_break_even={},
        method="exact_integration",
    )
    slots = base_slots(probe, currency) | {"reason": reason, "requirement": requirement}
    g = make_guarantee("none", slots, f"no recommendation: {reason}", [slots["assumption"]])
    decision = Feasibility(
        status="below_floor",
        basis="decision_loss",
        bound_ref=_decision_ref(),
        available=0.0,
        required=None,
        target=0.0,
        reasons=[reason],
        checked_at=utcnow(),
    )
    return Recommendation(
        recommendation_id=make_id("rec_", {"run": run_id, "action": "not_knowable", "r": reason}),
        action="not_knowable",
        scope=scope,
        params={"reason": reason},
        basis=[],
        decision_feasibility=decision,
        economics_id=economics_id,
        guarantee=g,
        expected_benefit=None,
        expected_loss=None,
        horizon=horizon,
        reversibility="reversible",
        run_id=run_id,
    )


def not_estimable_reason(
    quantity: str, variants: dict[str, str], missing: dict[str, dict[str, str]]
) -> str:
    """One clause per distinct reason, naming the ads (the report's option names) it holds for,
    so a reason shared by every ad is said once (D38.1)."""
    by_reason: dict[str, list[str]] = {}
    for v, ad in variants.items():
        why = missing.get(v, {}).get(quantity)
        if why is not None:
            by_reason.setdefault(why, []).append(ad)
    return "; ".join(
        NOT_ESTIMABLE_REASON.format(
            quantity=METRIC_LABELS.get(quantity, quantity), options=", ".join(ads), why=why
        )
        for why, ads in by_reason.items()
    )


def horizon_unit(metric: str) -> str:
    """The horizon unit the metric's comparison needs (§8.1): impressions for CTR, else clicks."""
    return COMPARE_SUPPORTED[compare_quantity(metric)][1]


def objective_for(metric: str, horizon: Horizon) -> Objective:
    """The comparison objective for a metric and horizon, validated before anything is fitted,
    saved or published (D38.2). An incompatible pair raises ValueError."""
    name = compare_quantity(metric)
    target, unit = COMPARE_SUPPORTED[name]
    if horizon.unit != unit:
        raise ValueError(
            f"metric {metric} compares {name}, which needs a horizon in {unit}; "
            f"got {horizon.unit} (§8.1)"
        )
    return Objective(target=target, horizon=horizon)  # type: ignore[arg-type]


def _immature_cohorts(data: FunnelData, ads: list[str]) -> int:
    """Cited cohorts (an ad's day with clicks) below the registry's minimum maturity (§5.6 C3)."""
    floor = float(registries.resolve(MIN_MATURITY_REF))
    rows = [data.entities.index(a) for a in ads if a in data.entities]
    return sum(
        1
        for i in rows
        for j in range(len(data.dates))
        if data.clicks[i][j] > 0 and data.mature_fraction[i][j] < floor
    )


# ------------------------------------------------------------------------------- run


def _seed(manifest: DatasetManifest, request: CompareRequest) -> int:
    return int(inputs_hash({"manifest": manifest.manifest_id, "request": request})[:8], 16)


def _count_rows(pulls: list[PlatformPull]) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in pulls:
        out[p.platform] = out.get(p.platform, 0) + len(p.rows)
    return out


def _knowability(
    data: FunnelData,
    pulls: list[PlatformPull],
    quantities: list[Quantity],
    platform: str,
) -> KnowabilitySection:
    observed = ["impressions", "clicks", "spend"]
    n_orders = sum(len(v) for v in data.order_values.values())
    if n_orders:
        observed.append(f"orders file: {n_orders} orders joined to the compared ads")
    modeled = []
    if any(
        data.conversions_observed[i][j] is None and data.conversions_reported[i][j] is not None
        for i in range(len(data.entities))
        for j in range(len(data.dates))
    ):
        modeled.append(f"{platform} reported conversions")
    windows: dict[str, str] = {}
    for p in pulls:
        codes: list[str] = []
        for r in sorted((r for r in p.rows if isinstance(r, PerformanceRow)), key=lambda r: r.date):
            if not codes or codes[-1] != r.attribution_window:
                codes.append(r.attribution_window)
        if codes:
            windows[p.platform] = " then ".join(codes)
    nk = [q.quantity_id for q in quantities if q.feasibility.status == "below_floor"]
    return KnowabilitySection(
        observed=observed, platform_modeled=modeled, attribution_windows=windows, not_knowable=nk
    )


def execute(
    manifest: DatasetManifest,
    request: CompareRequest,
    *,
    manifest_dir: Path | None = None,
    pulls: list[PlatformPull] | None = None,
    on_stage: Stage | None = None,
) -> RunContext:
    """The pipeline with its context. ``pulls`` given (shadow replay) skips the read stage."""
    started = utcnow()
    manifest_dir = Path(manifest_dir) if manifest_dir is not None else Path.cwd()
    start, end = request.window
    metric = request.metric
    cq = compare_quantity(metric)
    mq = metric_quantity(metric)
    objective = objective_for(metric, request.horizon)  # D38.2: before any fit, save, publish
    platform = comparison_platform(manifest, request.variants)
    variants = {v: manifest.entity_map[v][platform] for v in request.variants}
    variants = _segment(variants, request.segments, manifest)

    # D30 / I12: a client run without approved economics and a loss tolerance never starts.
    econ = _economics(manifest, manifest_dir)
    blocked = _economics_block(econ, manifest.economics_id)
    if blocked and not manifest.synthetic:
        raise GateFailure(
            _gate("G9", False, [CLIENT_NEEDS_ECONOMICS, *blocked], manifest.economics_id)
        )

    # read (G1)
    gates: list[GateResult] = []
    if pulls is None:
        pulls, g1 = read_pulls(manifest, manifest_dir, platform, end)
        gates += g1
    perf = [p for p in pulls if p.platform == platform]
    orders = [o for p in pulls if p.platform == "orders" for o in p.rows if isinstance(o, OrderRow)]
    as_of = observed_as_of(perf, orders, end)
    _emit(
        on_stage,
        "pulled",
        rows=_count_rows(pulls),
        quarantined={p.platform: len(p.quarantined) for p in pulls},
        synthetic=manifest.synthetic,
        changes=[c for p in perf for c in p.measurement_changes],
        notes=[n for p in pulls for n in p.notes],
    )

    # priors (G8): before anything is fitted
    priors, g8 = resolve_priors(request.priors, manifest.client_id, manifest.synthetic, started)
    gates.append(g8)

    # lag
    lag, lag_notes = fit_lag(platform, perf, orders, manifest.utm_map, as_of, end)
    data = assemble_funnel_data(
        pulls,
        lag,
        as_of,
        utm_map=manifest.utm_map,
        start=start,
        end=end,
        ads=list(variants.values()),
    )

    # route and fit (G3 inside the fallback chain)
    seed = _seed(manifest, request)
    fitted = fit(data, priors, seed)
    route, state, reports, fit_notices, spec = (
        fitted.route,
        fitted.state,
        fitted.reports,
        fitted.notices,
        fitted.spec,
    )
    for rep in reports:
        if rep.sampler == "numpyro_nuts":
            gates.append(
                _gate("G3", bool(rep.passed), [] if rep.passed else ["failed G3"], rep.report_id)
            )
    fell_back = bool((state.posterior.params or {}).get(fallback.FALLBACK_FLAG))
    _emit(
        on_stage,
        "fitted",
        route=route.kind,
        reason=route.reason,
        final_route=state.route,
        fell_back=fell_back,
        step=fitted.step,
        n_ads=len(data.entities),
        n_days=len(data.dates),
        lag_source=None if lag is None else lag.source,
        lag_window=None if lag is None else len(lag.cdf) - 1,
        lag_n=None if lag is None else lag.n_lagged_conversions,
        lag_notices=lag_notes,
        reports=reports,
        notices=fit_notices,
    )

    # derive (G10), quantity feasibility, publish (G2)
    names = list(dict.fromkeys([mq, cq, *DISPLAY]))
    by_variant, missing = derive_all(
        state, variants, names, (start, end), platform, econ, [n for n in lag_notes]
    )
    quantities = [q for v in by_variant.values() for q in v.values()]
    gates.append(_gate("G10", True, [], [q.quantity_id for q in quantities]))
    published, g2 = publish_all(quantities)
    gates += g2

    # compare (G9), decision feasibility, recommend
    run_id = make_id(
        "run_", {"manifest": manifest.manifest_id, "request": request, "at": started.isoformat()}
    )
    currency = econ.currency if econ is not None else data.currency
    comparison: Comparison | None = None
    decision: Feasibility | None = None
    recs: list[Recommendation] = []
    options = [by_variant[v].get(cq) for v in variants]
    rec_scope = Scope(
        level="ad",
        ids={"options": ",".join(variants.values())},
        window=(start, end),
        platform=platform,  # type: ignore[arg-type]
    )
    immature = 0
    if blocked:
        reason = "; ".join(blocked)
        gates.append(_gate("G9", False, blocked, manifest.economics_id))
        recs.append(
            not_knowable(
                run_id,
                reason,
                objective,
                rec_scope,
                econ and econ.economics_id,
                currency,
                G9_REQUIREMENT,
            )
        )
    elif any(o is None for o in options):
        recs.append(
            not_knowable(
                run_id,
                not_estimable_reason(cq, variants, missing),
                objective,
                rec_scope,
                econ.economics_id,  # type: ignore[union-attr]
                currency,
                DATA_REQUIREMENT.format(quantity=cq),
            )
        )
    else:
        assert econ is not None
        comparison = compare(options, objective, econ)  # type: ignore[arg-type]
        gates.append(_gate("G9", True, [], econ.economics_id))
        decision = decision_feasibility(comparison, econ)
        with _economics_visible(manifest_dir, econ.economics_id):
            rec = allocate(comparison, run_id)
        basis = [o.quantity_id for o in options]  # type: ignore[union-attr]
        recs.append(rec.model_copy(update={"basis": basis}))
        # §5.6 C3, §8.3: a split is never a stop. With immature cohorts the run also says
        # whether the test may stop (it may not: continue, or not knowable). Lag delays
        # conversions only, so a CTR comparison is not held back by it.
        if cq in CONVERSION_BASED:
            immature = _immature_cohorts(data, comparison.options)
        if immature and data.currency == econ.currency:
            stop = stop_or_continue(comparison, decision, data, econ, run_id)
            recs.append(stop.model_copy(update={"basis": basis}))

    for rec in recs:
        run_record.append(rec)
    _emit(
        on_stage,
        "decided",
        comparison=comparison,
        decision=decision,
        recommendations=recs,
        variants=variants,
        quantities=quantities,
        not_estimable=missing,
        compare_quantity=cq,
        metric_quantity=mq,
        tolerance=None if econ is None else econ.loss_tolerance,
        immature_cohorts=immature,
    )

    notices = [*fit_notices, *lag_notes]
    changes = [c for p in perf for c in p.measurement_changes]
    if changes:
        notices.append(WINDOW_CHANGED.format(changes="; ".join(changes)))
    configuration = {
        "engine_version": __version__,
        "registry_versions": registries.versions(),
        "platform": platform,
        "metric": metric,
        "compare_quantity": cq,
        "horizon": request.horizon.model_dump(mode="json"),
        "window": [start.isoformat(), end.isoformat()],
        "segments": request.segments,
        "route": route.kind,
        "final_route": state.route,
        "fit_step": fitted.step,
        "spec": spec.model_dump(mode="json") if route.kind == "nuts" else None,
        "priors": {p: r.prior_id for p, r in priors.records.items()},
        "lag": None if lag is None else {"source": lag.source, "window": lag.attribution_window},
        "seed": seed,
    }
    config_hash = inputs_hash(configuration)
    dataset_hashes = sorted(f.sha256 for f in manifest.files)
    record = RunRecord(
        run_id=run_id,
        started_at=started,
        engine_version=__version__,
        registry_versions=registries.versions(),
        config_hash=config_hash,
        manifest_id=manifest.manifest_id,
        dataset_hashes=dataset_hashes,
        gate_results=gates,
        quantity_ids=[q.quantity_id for q in quantities],
        recommendation_ids=[r.recommendation_id for r in recs],
        route_log=[f"route {route.kind}: {route.reason}", *notices, f"state {state.state_id}"],
        seeds={"fit": seed},
    )
    run_record.append(record)
    result = RunResult(
        run=record,
        quantities=quantities,
        comparison=comparison,
        recommendations=recs,
        diagnostics=reports,
    )
    snap = RunSnapshot(
        run_id=run_id,
        client_id=manifest.client_id,
        synthetic=manifest.synthetic,
        manifest_id=manifest.manifest_id,
        dataset_hashes=dataset_hashes,
        platform=platform,
        window=(start, end),
        as_of=as_of,
        metric=metric,
        compare_quantity=cq,
        horizon=request.horizon,
        segments=request.segments,
        variants=variants,
        priors=configuration["priors"],
        configuration=configuration,
        config_hash=config_hash,
        tool_version=tool_version(),
        currency=currency,
        economics_id=econ.economics_id if econ is not None else None,
        route=Route(kind=state.route, reason=route.reason, notices=route.notices),
        quantities=quantities,
        not_estimable=missing,
        published=published,
        comparison=comparison,
        decision=decision,
        recommendations=recs,
        diagnostics=reports,
        gate_results=gates,
        knowability=_knowability(data, perf, quantities, platform),
        notices=notices,
    )
    _write_snapshot(snap)
    return RunContext(result=result, snapshot=snap, data=data, pulls=pulls)


def _segment(
    variants: dict[str, str], segments: dict[str, Any], manifest: DatasetManifest
) -> dict[str, str]:
    """§11.1: segments filter Scope.ids. Only the ad level is known before reading the data, so
    a segment may name ``ad`` ids; any other key is refused rather than ignored."""
    if not segments:
        return variants
    unknown = [k for k in segments if k != "ad"]
    if unknown:
        raise ValueError(f"segments on {unknown} are not supported; only 'ad'")
    allowed = segments["ad"]
    allowed = {allowed} if isinstance(allowed, str) else set(allowed)
    kept = {v: a for v, a in variants.items() if a in allowed}
    if len(kept) != len(variants):
        dropped = sorted(set(variants) - set(kept))
        raise ValueError(f"segments exclude requested variants {dropped}")
    return kept


def run(
    manifest: DatasetManifest,
    request: CompareRequest,
    *,
    manifest_dir: Path | None = None,
    on_stage: Stage | None = None,
) -> RunResult:
    """read (G1) -> lag -> route -> fit -> save -> derive (G10) -> feasibility -> publish (G2)
    -> compare (G9) -> decision feasibility -> recommend -> run_record.append."""
    return execute(manifest, request, manifest_dir=manifest_dir, on_stage=on_stage).result
