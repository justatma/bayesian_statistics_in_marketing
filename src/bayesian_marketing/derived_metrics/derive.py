"""§5.5 derive.

Conjugate states give exact analytic quantities where the posterior is closed-form (CTR, CVR,
CPA, CPM, compound-gamma order value, and contribution per click at a fixed price). Everything
else is computed row by row from the state's joint draws (contract assumption 17) and written as a
one-column parquet under ``<BAYES_DATA_DIR>/quantities/`` (contract assumption 16).

``derive`` stamps a provisional rate Feasibility (``below_floor``, "not yet assessed"); the rate
status itself is ``floors.estimability.quantity_feasibility``'s job (§6.1, P4).

A quantity the data cannot support (no conversions, no impressions, no order values) raises
``NotEstimable``, which carries the reason and a below-floor Feasibility. A quantity whose
posterior is the prior alone (no events for that ad) is returned with that reason added.

Disclosures the phrasing registry does not yet hold are module constants below; each names the
registry key requested for it (spec/manifests/P3.md, open questions).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from bayesian_marketing.core import (
    ClientEconomics,
    DistributionSpec,
    Feasibility,
    FunnelState,
    GateFailure,
    GateResult,
    Provenance,
    Quantity,
    Scope,
    inputs_hash,
    make_id,
    registries,
    utcnow,
)
from bayesian_marketing.core.quantity import DELIVERY_ONLY, pull_platform
from bayesian_marketing.derived_metrics.dist import (
    PER_MILLE,
    analytic,
    decode_currency,
    read_draws,
    write_draws,
)
from bayesian_marketing.funnel_state.store import data_dir

RATE_BOUND = "bounds/estimability/posterior_width@v1"
RATE_TARGET = "bounds/estimability/posterior_width/rel_half_width@v1"
UNASSESSED = "rate precision not yet assessed by floors/estimability (§6.1)"
PRIOR_ONLY = "no events for this ad: the posterior is the prior"

# Requested phrasing.yaml notices keys in brackets.
NOTICE_CPA_LAG_SPEND = "CPA spend exposure scaled by conversion maturity"  # [lag_spend_exposure]
NOTICE_CPM_REFERENCE = "CPM from a reference prior: no approved CPM prior"  # [cpm_reference_prior]
NOTICE_AOV_REFERENCE = (
    "order value from an improper reference prior on the orders file"  # [aov_reference_prior]
)
NOTICE_COMPOUND_GAMMA = (
    "order value from daily totals with a placeholder compound-gamma k"  # [compound_gamma_k]
)
NOTICE_UNAPPROVED_PRIORS = "unapproved priors used on synthetic data"  # [unapproved_priors]
# [reported_above_clicks] (D34): per quantity, naming what its own calculation did with them.
_ABOVE = "reported conversions exceeded clicks on some days; "
NOTICE_REPORTED_ABOVE_CLICKS = {
    "cvr": _ABOVE + "those days are left out of this conversion rate",
    "contribution_per_click": _ABOVE
    + "those days are left out of the conversion rate behind this contribution per click",
    "cpa": _ABOVE + "those conversions are counted in this cost per acquisition",
    "roas": _ABOVE + "those days are left out of the conversion rate inside this ROAS",
}

CONVERSION_BASED = frozenset({"cvr", "cpa", "roas", "contribution_per_click"})
VALUE_BASED = frozenset({"aov", "roas"})
CPM_BASED = frozenset({"cpm", "cpc", "roas"})
EVENTS = {
    "ctr": "n.clicks",
    "cpc": "n.clicks",
    "cpm": "n.impressions",
    "cvr": "n.conversions",
    "cpa": "n.conversions",
    "roas": "n.conversions",
    "contribution_per_click": "n.conversions",
    "aov": "n.orders",
}
MISSING_WHY = {
    "ctr": "no click-through draws",
    "cvr": "no conversion data on days with spend",
    "cpa": "no conversion data on days with spend",
    "cpm": "no impressions or no spend",
    "aov": "no orders file with two or more distinct orders and no reported revenue",
}


class QuarantinedStateError(ValueError):
    """derive was handed a quarantined FunnelState (§5.4)."""


class NotEstimable(ValueError):
    """The state holds no posterior for this quantity. ``feasibility`` is below floor with the
    reason, for the caller to report as not knowable."""

    def __init__(self, name: str, ad: str, reason: str, target: float) -> None:
        super().__init__(f"{name} for ad {ad!r} is not estimable: {reason}")
        self.name = name
        self.ad = ad
        self.reason = reason
        self.feasibility = Feasibility(
            status="below_floor",
            basis="quantity_precision",
            bound_ref=RATE_BOUND,
            available=0.0,
            required=None,
            target=target,
            reasons=[reason],
            checked_at=utcnow(),
        )


def _notice(key: str) -> str:
    return str(registries.resolve(f"phrasing/notices/{key}@v1"))


class _View:
    """One ad's slice of a FunnelState."""

    def __init__(self, state: FunnelState, ad: str, name: str, target: float) -> None:
        self.state = state
        self.ad = ad
        self.name = name
        self.target = target
        self.params: dict[str, float] = dict(state.posterior.params or {})
        self.exact = state.route == "conjugate" and state.posterior.family == "conjugate"
        self._cols: dict[str, np.ndarray] = {}
        self.used: set[str] = set()

    def p(self, key: str) -> float | None:
        return self.params.get(f"{self.ad}.{key}")

    def flag(self, key: str) -> bool:
        return bool(self.p(f"flag.{key}"))

    def col(self, param: str) -> np.ndarray:
        self.used.add(param)
        if param not in self._cols:
            spec = self.state.posterior
            if spec.kind != "samples":
                raise ValueError(f"state {self.state.state_id} has no joint draws")
            try:
                self._cols[param] = read_draws(spec, f"{self.ad}.{param}")
            except KeyError:
                why = MISSING_WHY.get(param, f"no {param} draws")
                raise NotEstimable(self.name, self.ad, why, self.target) from None
        return self._cols[param]

    def has(self, param: str) -> bool:
        try:
            self.col(param)
        except NotEstimable:
            self.used.discard(param)
            return False
        return True

    def observed_cpc(self) -> float | None:
        spend, clicks = self.p("spend"), self.p("n.clicks")
        if spend is None or not clicks:
            return None
        return spend / clicks


def _contribution_per_order(econ: ClientEconomics, v: _View) -> float | np.ndarray:
    vc = float(econ.variable_cost_per_order.amount)
    if econ.price_source == "fixed" and econ.fixed_price is not None:
        return float(econ.fixed_price.amount) - vc
    return v.col("aov") - vc  # D14: per draw


def _estimate(name: str, v: _View, econ: ClientEconomics | None) -> DistributionSpec | np.ndarray:
    """An analytic spec, or a draw vector to be written."""
    if v.exact:
        if name in ("ctr", "cvr") and v.p(f"{name}.a") is not None:
            v.used.add(name)
            return analytic("beta", {"a": v.p(f"{name}.a"), "b": v.p(f"{name}.b")})  # type: ignore[dict-item]
        if name in ("cpa", "cpm", "aov") and v.p(f"{name}.a") is not None:
            v.used.add(name)
            return analytic("invgamma", {"a": v.p(f"{name}.a"), "scale": v.p(f"{name}.scale")})  # type: ignore[dict-item]
    if name in ("ctr", "cvr", "cpm", "aov"):
        return v.col(name)
    if name == "cpa":
        if v.has("cpa"):
            return v.col("cpa")
        return v.col("cpm") / (PER_MILLE * v.col("ctr") * v.col("cvr"))
    if name == "cpc":
        return v.col("cpm") / (PER_MILLE * v.col("ctr"))
    if name == "roas":
        return (PER_MILLE / v.col("cpm")) * v.col("ctr") * v.col("cvr") * v.col("aov")
    if name == "contribution_per_click":
        if econ is None:
            raise ValueError("contribution_per_click needs ClientEconomics")
        margin = _contribution_per_order(econ, v)
        cpc = v.observed_cpc()
        exact_beta = v.exact and v.p("cvr.a") is not None
        if exact_beta and cpc is not None and isinstance(margin, float) and margin > 0:
            v.used.add("cvr")
            params = {"a": v.p("cvr.a"), "b": v.p("cvr.b"), "loc": -cpc, "scale": margin}
            return analytic("beta", params)  # type: ignore[arg-type]
        if cpc is None:
            cpc_draws: Any = v.col("cpm") / (PER_MILLE * v.col("ctr"))
        else:
            cpc_draws = cpc
        return v.col("cvr") * margin - cpc_draws
    raise ValueError(f"derive does not compute {name!r}")


def _evidence(name: str, v: _View) -> str:
    if name in DELIVERY_ONLY:
        return "delivery"
    if name == "aov" and v.p("flag.aov_source") == 1.0:
        platforms = {pull_platform(p) for p in v.state.data_pull_ids}
        if "orders" in platforms:
            return "commercially_realized"
    return "platform_attributed"


def _notices(name: str, v: _View) -> list[str]:
    out: list[str] = []
    if v.params.get("route.fallback_conjugate"):  # §7.5 step 4; floors caps it at marginal (D26)
        out.append(_notice("joint_failed"))
    if v.params.get("route.too_few_ads"):
        out.append(_notice("too_few_ads"))
    if v.params.get("route.unapproved_priors"):
        out.append(NOTICE_UNAPPROVED_PRIORS)
    conv = name in CONVERSION_BASED
    uses_aov = "aov" in v.used
    if conv and v.flag("lag_adjusted"):
        out.append(_notice("lag_approx"))
        if name == "cpa":
            out.append(NOTICE_CPA_LAG_SPEND)
    if (conv or (uses_aov and v.p("flag.aov_source") == 2.0)) and v.flag("platform_modeled"):
        out.append(_notice("platform_modeled"))
    if conv and v.flag("reported_above_clicks"):
        out.append(NOTICE_REPORTED_ABOVE_CLICKS[name])
    if "cpm" in v.used and v.flag("cpm_reference_prior"):
        out.append(NOTICE_CPM_REFERENCE)
    if uses_aov and v.p("flag.aov_source") == 1.0:
        out.append(NOTICE_AOV_REFERENCE)
    if uses_aov and v.p("flag.aov_source") == 2.0:
        out.append(NOTICE_COMPOUND_GAMMA)
    return out


def _check_currency(state: FunnelState, econ: ClientEconomics) -> None:
    """G9: economics in one currency must not price data in another."""
    code = (state.posterior.params or {}).get("currency.code")
    if code is None:
        return  # states that do not carry it (see manifest: FunnelState.currency)
    data_cur = decode_currency(code)
    if data_cur != econ.currency:
        res = GateResult(
            gate="G9",
            passed=False,
            blocking=True,
            reasons=[f"currency mismatch: data in {data_cur}, economics in {econ.currency}"],
            inputs_hash=inputs_hash({"state": state.state_id, "econ": econ.economics_id}),
            checked_at=utcnow(),
        )
        raise GateFailure(res)


def derive(name: str, state: FunnelState, scope: Scope, econ: ClientEconomics | None) -> Quantity:
    """Pure function of the state. Refuses a quarantined state."""
    if state.quarantined:
        raise QuarantinedStateError(f"state {state.state_id} is quarantined")
    if scope.level != "ad" or "ad" not in scope.ids:
        raise ValueError("derive works per ad: scope.level 'ad' with ids['ad']")
    if name not in EVENTS:
        raise ValueError(f"derive does not compute {name!r}")
    if econ is not None:
        _check_currency(state, econ)
    target = float(registries.resolve(RATE_TARGET))
    v = _View(state, scope.ids["ad"], name, target)
    if v.exact and v.p("ctr.a") is None:
        raise ValueError(f"state {state.state_id} has no ad {v.ad!r}")

    qid = make_id(
        "q_",
        {
            "name": name,
            "state": state.state_id,
            "scope": scope,
            "econ": econ.economics_id if econ else None,
        },
    )
    est = _estimate(name, v, econ)
    if not isinstance(est, DistributionSpec):
        est = write_draws(data_dir() / "quantities" / f"{qid}.parquet", v.ad, est)

    n_events = v.p(EVENTS[name])
    reasons = [UNASSESSED]
    if n_events == 0:
        reasons.append(PRIOR_ONLY)
    feas = Feasibility(
        status="below_floor",
        basis="quantity_precision",
        bound_ref=RATE_BOUND,
        available=float(n_events or 0.0),
        required=None,
        target=target,
        reasons=reasons,
        checked_at=utcnow(),
    )
    prov = Provenance(
        funnel_state_id=state.state_id,
        model_version=state.spec_version or "conjugate",
        data_pull_ids=list(state.data_pull_ids),
        derived_by="derived_metrics.derive",
        route=state.route,
        synthetic=state.synthetic,
        computed_at=utcnow(),
    )
    return Quantity(
        quantity_id=qid,
        name=name,  # type: ignore[arg-type]
        scope=scope,
        estimate=est,
        feasibility=feas,
        provenance=prov,
        evidence_class=_evidence(name, v),  # type: ignore[arg-type]
        design="observational",
        diagnostics_ref=state.diagnostics_id,
        notices=_notices(name, v),
        n_events=n_events,
    )


def mix_weighted_rate(rates: dict[str, float], clicks: dict[str, float]) -> float:
    """Click-mix-weighted rate (D22; oracle: 800/200 -> 300/700 clicks at 5% / 1% gives 42 -> 22
    orders per 1,000 clicks). Deterministic."""
    if set(rates) != set(clicks):
        raise ValueError("rates and clicks must name the same ads")
    total = float(sum(clicks.values()))
    if total <= 0:
        raise ValueError("total clicks must be positive")
    return float(sum(rates[k] * clicks[k] for k in rates)) / total
