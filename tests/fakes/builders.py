"""Builders for valid core objects (they pass the G10 and other core validators).

Every builder takes keyword overrides. Defaults describe one Meta ad account with ads ``ad_a`` and
``ad_b`` in campaign ``c1`` of account ``acc1``, priced in USD.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from bayesian_marketing import core as C
from bayesian_marketing.core import registries
from bayesian_marketing.core.quantity import DELIVERY_ONLY

T0 = dt.datetime(2026, 11, 1, 12, 0, tzinfo=dt.UTC)
D_START = dt.date(2026, 10, 19)
D_END = dt.date(2026, 11, 1)
WINDOW = (D_START, D_END)
RATE_BOUND = "bounds/estimability/posterior_width@v1"
DECISION_BOUND = "bounds/estimability/decision_loss@v1"
META_PULL = "pull_meta_00000001"
ORDERS_PULL = "pull_orders_00000001"


def money(x: Any, cur: str = "USD") -> C.Money:
    return C.Money(amount=Decimal(str(x)), currency=cur)


def summary_from_dist(d: Any) -> dict[str, float]:
    q = d.ppf([0.05, 0.5, 0.95, 0.025, 0.975])
    return {
        "mean": float(d.mean()),
        "sd": float(d.std()),
        "q05": float(q[0]),
        "q50": float(q[1]),
        "q95": float(q[2]),
        "q025": float(q[3]),
        "q975": float(q[4]),
    }


def summary_from_draws(x: Any) -> dict[str, float]:
    x = np.asarray(x, dtype=float)
    q = np.quantile(x, [0.05, 0.5, 0.95, 0.025, 0.975])
    return {
        "mean": float(x.mean()),
        "sd": float(x.std(ddof=1)) if x.size > 1 else 0.0,
        "q05": float(q[0]),
        "q50": float(q[1]),
        "q95": float(q[2]),
        "q025": float(q[3]),
        "q975": float(q[4]),
    }


def beta_spec(a: float, b: float) -> C.DistributionSpec:
    return C.DistributionSpec(
        kind="analytic",
        family="beta",
        params={"a": float(a), "b": float(b)},
        summary=summary_from_dist(stats.beta(a, b)),
    )


def write_samples(path: Path, columns: dict[str, Any]) -> Path:
    """Parquet of joint draws: one column per name, rows are joint draws (§4.2)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({k: np.asarray(v, dtype=float) for k, v in columns.items()}).to_parquet(path)
    return path


def samples_spec(path: Path, columns: dict[str, Any], summary_of: str | None = None):
    write_samples(path, columns)
    first = summary_of or next(iter(columns))
    n = len(next(iter(columns.values())))
    return C.DistributionSpec(
        kind="samples",
        samples_path=str(path),
        n_samples=n,
        summary=summary_from_draws(columns[first]),
    )


def scope(
    ad: str | None = "ad_a",
    platform: str | None = "meta",
    level: str = "ad",
    window: tuple[dt.date, dt.date] = WINDOW,
    ids: dict[str, str] | None = None,
) -> C.Scope:
    if ids is None:
        ids = {"ad": ad} if level == "ad" else {level: ad or "c1"}
    return C.Scope(level=level, ids=ids, window=window, platform=platform)


def feasibility(
    status: str = "estimable",
    basis: str = "quantity_precision",
    *,
    available: float = 100.0,
    required: float | None = None,
    target: float | None = None,
    reasons: list[str] | None = None,
    bound_ref: str | None = None,
    supersedes: str | None = None,
) -> C.Feasibility:
    if reasons is None:
        reasons = [] if status == "estimable" else [f"fake: {status}"]
    if bound_ref is None:
        bound_ref = DECISION_BOUND if basis == "decision_loss" else RATE_BOUND
    if target is None:
        target = 0.20 if basis != "decision_loss" else 1000.0
    return C.Feasibility(
        status=status,
        basis=basis,
        bound_ref=bound_ref,
        available=available,
        required=required,
        target=target,
        reasons=reasons,
        supersedes=supersedes,
        checked_at=T0,
    )


def provenance(
    route: str = "conjugate",
    pulls: list[str] | None = None,
    synthetic: bool = False,
    state_id: str | None = "fs_00000001",
) -> C.Provenance:
    return C.Provenance(
        funnel_state_id=None if route == "deterministic" else state_id,
        model_version="test",
        data_pull_ids=[META_PULL] if pulls is None else list(pulls),
        derived_by="tests.fakes",
        route=route,
        synthetic=synthetic,
        computed_at=T0,
    )


def quantity(
    name: str = "ctr",
    ad: str = "ad_a",
    *,
    estimate: C.DistributionSpec | None = None,
    status: str = "estimable",
    feas: C.Feasibility | None = None,
    route: str = "conjugate",
    evidence: str | None = None,
    design: str = "observational",
    pulls: list[str] | None = None,
    synthetic: bool = False,
    diagnostics_ref: str | None = None,
    notices: list[str] | None = None,
    quantity_id: str | None = None,
    platform: str | None = "meta",
    sc: C.Scope | None = None,
) -> C.Quantity:
    if evidence is None:
        if route == "deterministic":
            evidence = "deterministic"
        elif name in DELIVERY_ONLY:
            evidence = "delivery"
        else:
            evidence = "platform_attributed"
    if route == "nuts" and diagnostics_ref is None:
        diagnostics_ref = "dg_00000001"
    estimate = estimate or beta_spec(42, 2058)
    sc = sc or scope(ad, platform)
    if quantity_id is None:
        quantity_id = C.make_id("q_", {"n": name, "ad": ad, "s": estimate.summary, "st": status})
    return C.Quantity(
        quantity_id=quantity_id,
        name=name,
        scope=sc,
        estimate=estimate,
        feasibility=feas or feasibility(status),
        provenance=provenance(route, pulls, synthetic),
        evidence_class=evidence,
        design=design,
        diagnostics_ref=diagnostics_ref,
        notices=notices or [],
    )


def economics(
    *,
    approved: bool = True,
    loss_tolerance: Any = 1000,
    fixed_price: Any = 80,
    variable_cost: Any = 48,
    survival_floor: Any = None,
    test_budget: Any = None,
    currency: str = "USD",
    economics_id: str = "econ_00000001",
    client_id: str = "client_x",
) -> C.ClientEconomics:
    return C.ClientEconomics(
        economics_id=economics_id,
        client_id=client_id,
        currency=currency,
        variable_cost_per_order=money(variable_cost, currency),
        price_source="fixed" if fixed_price is not None else "modeled_aov",
        fixed_price=None if fixed_price is None else money(fixed_price, currency),
        loss_tolerance=None if loss_tolerance is None else money(loss_tolerance, currency),
        survival_floor=None if survival_floor is None else money(survival_floor, currency),
        test_budget=None if test_budget is None else money(test_budget, currency),
        source="tests.fakes",
        approved_by="owner" if approved else None,
        approved_at=T0 if approved else None,
    )


def horizon(unit: str = "clicks", amount: Any = 1000) -> C.Horizon:
    return C.Horizon(unit=unit, amount=Decimal(str(amount)))


def objective(target: str = "contribution", unit: str = "clicks", amount: Any = 1000):
    return C.Objective(target=target, horizon=horizon(unit, amount))


def comparison(
    options: tuple[str, ...] = ("ad_a", "ad_b"),
    *,
    p_best: dict[str, float] | None = None,
    expected_value: dict[str, Any] | None = None,
    expected_loss: dict[str, Any] | None = None,
    p_exceeds: dict[str, float] | None = None,
    obj: C.Objective | None = None,
    method: str = "exact_integration",
    economics_id: str = "econ_00000001",
) -> C.Comparison:
    opts = list(options)
    p_best = p_best or {o: 1.0 / len(opts) for o in opts}
    ev = expected_value or dict.fromkeys(opts, 0)
    el = expected_loss or dict.fromkeys(opts, 0)
    return C.Comparison(
        options=opts,
        objective=obj or objective(),
        economics_id=economics_id,
        p_best=p_best,
        expected_value={k: money(v) for k, v in ev.items()},
        expected_loss={k: money(v) for k, v in el.items()},
        p_exceeds_break_even=p_exceeds or dict.fromkeys(opts, 0.5),
        method=method,
        mc_standard_error=None if method == "exact_integration" else dict.fromkeys(opts, 0.01),
    )


def guarantee(kind: str = "posterior_probability") -> C.Guarantee:
    return C.Guarantee(
        kind=kind,
        statement_math="P(best=ad_b) = 0.96",
        template_id=kind,
        slots={"option": "ad_b", "probability": "96%"},
        assumptions=["the next 1000 clicks behave like the last"],
    )


def recommendation(
    action: str = "allocate",
    *,
    run_id: str = "run_00000001",
    recommendation_id: str = "rec_00000001",
    status: str = "estimable",
    economics_id: str | None = "econ_00000001",
    basis: list[str] | None = None,
) -> C.Recommendation:
    return C.Recommendation(
        recommendation_id=recommendation_id,
        action=action,
        scope=scope("c1", level="campaign"),
        params={"allocation": {"ad_b": 0.7, "ad_a": 0.3}},
        basis=basis or [],
        decision_feasibility=feasibility(status, "decision_loss"),
        economics_id=economics_id,
        guarantee=guarantee(),
        expected_benefit=money(170),
        expected_loss=money(5),
        horizon=horizon(),
        reversibility="reversible",
        run_id=run_id,
    )


def gate_result(gate: str = "G10", passed: bool = True, reasons: list[str] | None = None):
    return C.GateResult(
        gate=gate,
        passed=passed,
        blocking=True,
        reasons=reasons or ([] if passed else ["fake failure"]),
        inputs_hash=C.inputs_hash({"g": gate}),
        checked_at=T0,
    )


def diagnostics_report(
    *,
    rhat: float | None = 1.001,
    ess_bulk: float | None = 1500.0,
    ess_tail: float | None = 1200.0,
    divergences: int | None = 0,
    ppc: dict[str, float] | None = None,
    passed: bool | None = None,
    sampler: str = "numpyro_nuts",
    report_id: str = "dg_00000001",
) -> C.DiagnosticsReport:
    return C.DiagnosticsReport(
        report_id=report_id,
        sampler=sampler,
        rhat_max=rhat,
        ess_bulk_min=ess_bulk,
        ess_tail_min=ess_tail,
        n_divergences=divergences,
        ppc=ppc if ppc is not None else {"delivery": 0.5, "ctr": 0.45, "cvr": 0.55, "value": 0.5},
        loo=None,
        seeds=[11, 12, 13, 14],
        thresholds_ref="diagnostics/thresholds@v1",
        passed=passed,
    )


def run_record(run_id: str = "run_00000001") -> C.RunRecord:
    return C.RunRecord(
        run_id=run_id,
        started_at=T0,
        engine_version="0.2.0.dev0",
        registry_versions={"bounds": "v1"},
        config_hash=C.inputs_hash({"run": run_id}),
        manifest_id="ds_00000001",
        dataset_hashes=["0" * 64],
        gate_results=[gate_result()],
        quantity_ids=["q_00000001"],
        recommendation_ids=["rec_00000001"],
        route_log=["conjugate: funnel link not estimated: too few ads"],
        seeds={"fit": 1},
    )


def approval_record(rec_id: str = "rec_00000001") -> C.ApprovalRecord:
    return C.ApprovalRecord(
        recommendation_id=rec_id,
        approval_ref="apr_1",
        decision="approved",
        decided_by="Atma",
        decided_at=T0,
    )


def outcome_record(rec_id: str = "rec_00000001", source: str = "atmaos") -> C.OutcomeRecord:
    return C.OutcomeRecord(
        recommendation_id=rec_id, source=source, realized={"benefit": 150.0}, recorded_at=T0
    )


def manifest(
    files: list[C.ManifestFile] | None = None,
    *,
    synthetic: bool = False,
    attribution_window: dict[str, str] | None = None,
    entity_map: dict[str, dict[str, str]] | None = None,
) -> C.DatasetManifest:
    return C.DatasetManifest(
        manifest_id="ds_00000001",
        client_id="client_x",
        economics_id="econ_00000001",
        files=files or [],
        attribution_window=attribution_window
        or {
            "meta": "7d_click_1d_view",
            "google_ads": "per_conversion_action",
            "linkedin": "90d_click_90d_view",
            "ga4": "property_setting",
            "orders": "none",
        },
        entity_map=entity_map or {"A": {"meta": "ad_a"}, "B": {"meta": "ad_b"}},
        utm_map={"np_a": {"meta": "ad_a"}, "np_b": {"meta": "ad_b"}},
        synthetic=synthetic,
    )


def performance_row(**kw: Any) -> C.PerformanceRow:
    base: dict[str, Any] = {
        "entity_ids": {"account": "acc1", "campaign": "c1", "ad": "ad_a"},
        "date": D_END,
        "impressions": 2000,
        "clicks": 40,
        "spend": money("50.00"),
        "conversions_observed": None,
        "conversions_reported": 2.0,
        "conversions_modeled_share": None,
        "attribution_window": "7d_click_1d_view",
        "revenue_reported": money("160.00"),
    }
    base.update(kw)
    return C.PerformanceRow(**base)


def order_row(**kw: Any) -> C.OrderRow:
    base: dict[str, Any] = {
        "order_id": "o1",
        "ordered_at": T0,
        "value": money("80.00"),
        "refunded": money("0.00"),
        "utm": {"campaign": "np_a"},
        "click_id": None,
        "first_click_at": T0 - dt.timedelta(days=2),
    }
    base.update(kw)
    return C.OrderRow(**base)


def site_row(**kw: Any) -> C.SiteRow:
    base: dict[str, Any] = {
        "date": D_END,
        "utm": {"source": "facebook", "medium": "paid", "campaign": "np_a"},
        "sessions": 100,
        "purchases": 3,
        "revenue": money("240.00"),
    }
    base.update(kw)
    return C.SiteRow(**base)


def platform_pull(platform: str = "meta", rows: list | None = None, **kw: Any) -> C.PlatformPull:
    base: dict[str, Any] = {
        "pull_id": f"pull_{platform}_00000001",
        "platform": platform,
        "channel_ref": f"channels/channels/{platform}@v1",
        "account_id": "acc1",
        "window": WINDOW,
        "rows": rows if rows is not None else [performance_row()],
        "quarantined": [],
        "partial_truth": True,
        "measurement_changes": [],
        "pulled_at": T0,
        "synthetic": False,
        "timezone": "America/New_York",
    }
    base.update(kw)
    return C.PlatformPull(**base)


def channel_model(platform: str = "meta", **kw: Any) -> C.ChannelModel:
    base: dict[str, Any] = {
        "platform": platform,
        "version": "2026-11-03",
        "export_map": {"Impressions": "impressions"},
        "conversion_field_may_be_modeled": True,
        "default_attribution_window": "7d_click_1d_view",
        "learning_phase_switching_cost": None,
        "freshness_date": dt.date(2026, 11, 3),
        "max_age_days": 90,
    }
    base.update(kw)
    return C.ChannelModel(**base)


def funnel_state(
    *,
    route: str = "conjugate",
    posterior: C.DistributionSpec | None = None,
    quarantined: bool = False,
    synthetic: bool = False,
    state_id: str = "fs_00000001",
    diagnostics_id: str | None = None,
) -> C.FunnelState:
    if route == "nuts" and diagnostics_id is None:
        diagnostics_id = "dg_00000001"
    return C.FunnelState(
        state_id=state_id,
        spec_version=None if route == "conjugate" else "funnel@test",
        route=route,
        prior_ids={"cvr": "pr_00000001"},
        data_window=WINDOW,
        posterior=posterior or beta_spec(9, 441),
        diagnostics_id=diagnostics_id,
        quarantined=quarantined,
        created_at=T0,
        synthetic=synthetic,
    )


def samples_state(path: Path, columns: dict[str, Any], **kw: Any) -> C.FunnelState:
    """A sampled FunnelState; parquet columns ``<entity>.<parameter>`` (or global names)."""
    return funnel_state(route=kw.pop("route", "nuts"), posterior=samples_spec(path, columns), **kw)


def elicitation(*, approved: bool, source: str = "human", promotion_id: str | None = None):
    return C.ElicitationRecord(
        source=source,
        rationale="test prior",
        evidence_refs=[],
        author="tests",
        created_at=T0,
        approved_by="owner" if approved else None,
        approved_at=T0 if approved else None,
        promotion_id=promotion_id,
    )


def prior_record(
    path: str = "cvr",
    family: str = "beta",
    params: dict[str, float] | None = None,
    *,
    approved: bool = False,
    client_id: str | None = "client_x",
    source: str = "human",
    promotion_id: str | None = None,
) -> C.PriorRecord:
    params = params or {"a": 2.0, "b": 60.0}
    hop = f"client:{client_id}" if client_id else "default"
    payload = {"path": path, "family": family, "params": params, "hop": hop}
    return C.PriorRecord(
        prior_id=C.make_id("pr_", payload),
        parameter_path=path,
        family=family,
        params=params,
        elicitation=elicitation(approved=approved, source=source, promotion_id=promotion_id),
        version="v1",
        resolution_path=[hop],
        predictive_check=None,
    )


def default_prior_set() -> C.PriorSet:
    """Every record in ``registries/priors/default.yaml``, approved, keyed by its path."""
    reg = registries.load("priors/default")
    out = {}
    for path, rec in reg["records"].items():
        params = {k: float(v) for k, v in rec["params"].items()}
        out[path] = C.PriorRecord(
            prior_id=C.make_id("pr_", {"default": path, "params": params}),
            parameter_path=path,
            family=rec["family"],
            params=params,
            elicitation=elicitation(approved=True),
            version=str(reg["version"]),
            resolution_path=["default"],
            predictive_check=None,
        )
    return C.PriorSet(records=out)


def funnel_spec(dynamics: str = "static", **kw: Any) -> C.FunnelSpec:
    base: dict[str, Any] = {
        "version": "funnel@test",
        "stages": [
            C.StageSpec(name="delivery", likelihood="poisson", pooled=True),
            C.StageSpec(name="ctr", likelihood="binomial", pooled=True),
            C.StageSpec(name="cvr", likelihood="binomial", pooled=True),
            C.StageSpec(name="value", likelihood="lognormal", pooled=True),
        ],
        "hierarchy": ["ad", "campaign"],
        "coupling": "lkj_bivariate",
        "dynamics": dynamics,
    }
    base.update(kw)
    return C.FunnelSpec(**base)


def knowability(**kw: Any) -> C.KnowabilitySection:
    base: dict[str, Any] = {
        "observed": ["impressions", "clicks", "spend"],
        "platform_modeled": [],
        "attribution_windows": {"meta": "7d_click_1d_view"},
        "not_knowable": [],
    }
    base.update(kw)
    return C.KnowabilitySection(**base)


def bundle(
    kind: str = "internal",
    quantities: list[C.Quantity] | None = None,
    *,
    recommendations: list[C.Recommendation] | None = None,
    comparisons: list[C.Comparison] | None = None,
    diagnostics: list[C.DiagnosticsReport] | None = None,
    narrative: list[C.NarrativeBlock] | None = None,
    know: C.KnowabilitySection | None = None,
    run_id: str = "run_00000001",
) -> C.ReportBundle:
    return C.ReportBundle(
        kind=kind,
        client_id="client_x",
        run_id=run_id,
        quantities=quantities if quantities is not None else [quantity()],
        recommendations=recommendations or [],
        comparisons=comparisons or [],
        gate_results=[gate_result()],
        diagnostics=diagnostics or [],
        knowability=know or knowability(),
        narrative_blocks=narrative or [],
    )


def funnel_data(
    ads: dict[str, dict[str, Any]],
    *,
    dates: list[dt.date] | None = None,
    platform: str = "meta",
    pull_ids: list[str] | None = None,
    parents: dict[str, dict[str, str]] | None = None,
    synthetic: bool = False,
) -> C.FunnelData:
    """FunnelData from per-ad dicts. Each value is a per-day list, or a scalar for one day.

    Keys: impressions, clicks, spend, conv_obs, conv_rep, mature, revenue. ``order_values`` is a
    flat list per ad.
    """
    n_days = len(dates) if dates else 1
    dates = dates or [D_END]

    def per_day(v: Any, default: Any) -> list:
        if v is None:
            return [default] * n_days
        if isinstance(v, list | tuple | np.ndarray):
            return list(v)
        return [v] + [default if default is None else type(v)(0)] * (n_days - 1)

    keys = (
        ("spend", "spend", 0.0),
        ("impressions", "impressions", 0),
        ("clicks", "clicks", 0),
        ("conversions_observed", "conv_obs", None),
        ("conversions_reported", "conv_rep", None),
        ("revenue_reported", "revenue", None),
    )
    arrays: dict[str, list] = {k: [] for k, _, _ in keys}
    mature: list[list[float]] = []
    for spec in ads.values():
        for field, key, default in keys:
            vals = per_day(spec.get(key), default)
            if field == "spend":
                vals = [float(v) for v in vals]
            arrays[field].append(vals)
        m = spec.get("mature", 1.0)
        mature.append(list(m) if isinstance(m, list | tuple) else [float(m)] * n_days)
    return C.FunnelData(
        platform=platform,
        currency="USD",
        entities=list(ads),
        parents=parents or {a: {"campaign": "c1", "account": "acc1"} for a in ads},
        dates=dates,
        mature_fraction=mature,
        order_values={a: list(s["order_values"]) for a, s in ads.items() if "order_values" in s},
        pull_ids=pull_ids or [META_PULL, ORDERS_PULL],
        synthetic=synthetic,
        **arrays,
    )


def north_pier_day2() -> C.FunnelData:
    """Day two: A 40/2,000 and B 34/2,000 (§9.2 CTR row)."""
    return funnel_data(
        {
            "ad_a": {"impressions": 2000, "clicks": 40, "spend": 50.0, "conv_obs": 1,
                     "conv_rep": 1.0},
            "ad_b": {"impressions": 2000, "clicks": 34, "spend": 42.5, "conv_obs": 1,
                     "conv_rep": 1.0},
        }
    )  # fmt: skip


def north_pier_day14() -> C.FunnelData:
    """Day fourteen: A 8/400 at CPC $1.25 ($500), B 18/340 for $500 (§9.2 CVR and money rows)."""
    return funnel_data(
        {
            "ad_a": {"impressions": 20000, "clicks": 400, "spend": 500.0, "conv_obs": 8,
                     "conv_rep": 8.0},
            "ad_b": {"impressions": 17000, "clicks": 340, "spend": 500.0, "conv_obs": 18,
                     "conv_rep": 18.0},
        }
    )  # fmt: skip


def all_examples(tmp: Path) -> dict[type, Any]:
    """One valid instance of every pydantic model exported by ``bayesian_marketing.core``."""
    q = quantity()
    gr = gate_result()
    dr = diagnostics_report()
    comp = comparison()
    td = C.TestDesign(
        arms=["ad_a", "ad_b"],
        allocation={"ad_a": 0.5, "ad_b": 0.5},
        volume=horizon(),
        randomized=True,
        holdout=False,
    )
    rr = run_record()
    ex: list[Any] = [
        money(1),
        C.MoneyInterval(low=money(1), mid=money(2), high=money(3)),
        beta_spec(2, 98),
        samples_spec(tmp / "s.parquet", {"ad_a": [0.1, 0.2, 0.3]}),
        scope(),
        provenance(),
        feasibility(),
        gr,
        q,
        dr,
        guarantee(),
        recommendation(),
        horizon(),
        objective(),
        economics(),
        rr,
        approval_record(),
        outcome_record(),
        C.ManifestFile(path="meta.csv", platform="meta", sha256="0" * 64, export_kind="export"),
        manifest(),
        knowability(),
        C.NarrativeBlock(block_id="nb1", text="Hello.", author="atmaos", gate=gr),
        bundle(),
        performance_row(),
        order_row(),
        site_row(),
        C.QuarantinedRow(raw={"Clicks": "-1"}, reasons=["negative clicks"]),
        platform_pull(),
        north_pier_day14(),
        C.PrecisionTarget(rel_half_width=0.2, caveat_rel_half_width=0.4),
        C.DegradationNotice(notice_id="n1", step="nuts_static", reason="G3 failed", affected=[]),
        C.StageSpec(name="ctr", likelihood="binomial", pooled=True),
        funnel_spec(),
        default_prior_set(),
        prior_record(),
        elicitation(approved=True),
        C.CompiledModel(spec_version="funnel@test", model_fn_ref="m:f", data_shape={"ads": 2}),
        C.FitConfig(chains=4, draws=1000, warmup=1000, target_accept=0.9, seed=1),
        funnel_state(),
        C.LagModel(
            platform="meta",
            attribution_window="7d_click_1d_view",
            cdf=[0.3, 0.6, 0.9, 1.0],
            source="registry_default",
            n_lagged_conversions=0,
        ),
        channel_model(),
        C.Route(kind="conjugate", reason="2 ads < 8", notices=["funnel link not estimated"]),
        comp,
        C.DecisionProblem(
            options=["ad_a"], payoffs={"ad_a": beta_spec(2, 3)}, objective=objective()
        ),
        td,
        C.DesignAssessment(
            evpi=money(600),
            evsi=money(250),
            cost=C.MoneyInterval(low=money(100), mid=money(150), high=money(200)),
            net_value=money(100),
            verdict="buy",
            redesign=None,
            design_label="randomized",
        ),
        C.ClientConfig(
            client_id="client_x",
            timezone="America/New_York",
            currency="USD",
            accounts={"meta": "acc1"},
        ),
        C.RenderedReport(html_path="r.html", pdf_path=None, inputs_hash="0" * 64, watermark=None),
        C.AuditReport(
            since=D_START,
            n_recommendations=1,
            by_source={"atmaos": {"regret": 0.0}},
            coverage_90={"atmaos": 1.0},
            regret={"atmaos": 0.0},
            not_knowable_correct_share=None,
        ),
        C.CompareRequest(
            metric="cvr", variants=["A", "B"], priors={}, window=WINDOW, horizon=horizon()
        ),
        C.RunResult(run=rr, quantities=[q], comparison=comp, recommendations=[], diagnostics=[dr]),
        C.GroundTruth(
            scenario="north_pier_day14",
            seed=1,
            params={},
            true_quantities={"A.cvr": 0.02},
            true_best={"contribution": "B"},
        ),
    ]
    return {type(x): x for x in ex}
