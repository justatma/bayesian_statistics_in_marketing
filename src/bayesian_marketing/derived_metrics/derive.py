"""§5.5 derive.

Conjugate states give exact analytic quantities where the posterior is closed-form (CTR, CVR,
CPA, CPM, compound-gamma order value, and contribution per click at a fixed price). Everything
else is computed row by row from the state's joint draws (contract assumption 17) and written as a
one-column parquet under ``<BAYES_DATA_DIR>/quantities/`` (contract assumption 16).

``derive`` stamps a provisional rate Feasibility (``below_floor``, "not yet assessed"); the rate
status itself is ``floors.estimability.quantity_feasibility``'s job (§6.1, P4).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from bayesian_marketing.core import (
    ClientEconomics,
    DistributionSpec,
    Feasibility,
    FunnelState,
    Provenance,
    Quantity,
    Scope,
    make_id,
    registries,
    utcnow,
)
from bayesian_marketing.core.quantity import DELIVERY_ONLY, pull_platform
from bayesian_marketing.derived_metrics.dist import analytic, read_draws, write_draws
from bayesian_marketing.funnel_state.store import data_dir

RATE_BOUND = "bounds/estimability/posterior_width@v1"
RATE_TARGET = "bounds/estimability/posterior_width/rel_half_width@v1"
UNASSESSED = "rate precision not yet assessed by floors/estimability (§6.1)"
CONVERSION_BASED = frozenset({"cvr", "cpa", "roas", "contribution_per_click"})
VALUE_BASED = frozenset({"aov", "roas"})
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


class QuarantinedStateError(ValueError):
    """derive was handed a quarantined FunnelState (§5.4)."""


def _notice(key: str) -> str:
    return str(registries.resolve(f"phrasing/notices/{key}@v1"))


class _View:
    """One ad's slice of a FunnelState."""

    def __init__(self, state: FunnelState, ad: str) -> None:
        self.state = state
        self.ad = ad
        self.params: dict[str, float] = dict(state.posterior.params or {})
        self.exact = state.route == "conjugate" and state.posterior.family == "conjugate"
        self._cols: dict[str, np.ndarray] = {}

    def p(self, key: str) -> float | None:
        return self.params.get(f"{self.ad}.{key}")

    def flag(self, key: str) -> bool:
        return bool(self.p(f"flag.{key}"))

    def col(self, name: str) -> np.ndarray:
        if name not in self._cols:
            spec = self.state.posterior
            if spec.kind != "samples":
                raise ValueError(f"state {self.state.state_id} has no joint draws")
            try:
                self._cols[name] = read_draws(spec, f"{self.ad}.{name}")
            except KeyError:
                raise ValueError(
                    f"state {self.state.state_id} has no {name!r} draws for ad {self.ad!r}"
                ) from None
        return self._cols[name]

    def has(self, name: str) -> bool:
        try:
            self.col(name)
        except ValueError:
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
            return analytic("beta", {"a": v.p(f"{name}.a"), "b": v.p(f"{name}.b")})  # type: ignore[dict-item]
        if name in ("cpa", "cpm", "aov") and v.p(f"{name}.a") is not None:
            return analytic("invgamma", {"a": v.p(f"{name}.a"), "scale": v.p(f"{name}.scale")})  # type: ignore[dict-item]
    if name in ("ctr", "cvr", "cpm", "aov"):
        return v.col(name)
    if name == "cpa":
        if v.has("cpa"):
            return v.col("cpa")
        return v.col("cpm") / (1000.0 * v.col("ctr") * v.col("cvr"))
    if name == "cpc":
        return v.col("cpm") / (1000.0 * v.col("ctr"))
    if name == "roas":
        return (1000.0 / v.col("cpm")) * v.col("ctr") * v.col("cvr") * v.col("aov")
    if name == "contribution_per_click":
        if econ is None:
            raise ValueError("contribution_per_click needs ClientEconomics")
        margin = _contribution_per_order(econ, v)
        cpc = v.observed_cpc()
        exact_beta = v.exact and v.p("cvr.a") is not None
        if exact_beta and cpc is not None and isinstance(margin, float) and margin > 0:
            params = {"a": v.p("cvr.a"), "b": v.p("cvr.b"), "loc": -cpc, "scale": margin}
            return analytic("beta", params)  # type: ignore[arg-type]
        if cpc is None:
            cpc_draws: Any = v.col("cpm") / (1000.0 * v.col("ctr"))
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
    if v.params.get("route.too_few_ads"):
        out.append(_notice("too_few_ads"))
    conv = name in CONVERSION_BASED
    value_from_platform = name in VALUE_BASED and v.p("flag.aov_source") == 2.0
    if conv and v.flag("lag_adjusted"):
        out.append(_notice("lag_approx"))
    if (conv or value_from_platform) and v.flag("platform_modeled"):
        out.append(_notice("platform_modeled"))
    return out


def derive(name: str, state: FunnelState, scope: Scope, econ: ClientEconomics | None) -> Quantity:
    """Pure function of the state. Refuses a quarantined state."""
    if state.quarantined:
        raise QuarantinedStateError(f"state {state.state_id} is quarantined")
    if scope.level != "ad" or "ad" not in scope.ids:
        raise ValueError("derive works per ad: scope.level 'ad' with ids['ad']")
    v = _View(state, scope.ids["ad"])
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
    target = float(registries.resolve(RATE_TARGET))
    feas = Feasibility(
        status="below_floor",
        basis="quantity_precision",
        bound_ref=RATE_BOUND,
        available=float(n_events or 0.0),
        required=None,
        target=target,
        reasons=[UNASSESSED],
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
