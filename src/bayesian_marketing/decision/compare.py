"""§8.1 compare. Gate G9.

Each option's value at the horizon is ``horizon.amount x quantity``: CTR per impression, CVR per
click, contribution per click per click. Expected values and losses are in the objective's target
unit (clicks, orders, or currency for contribution) and carried as Money in the economics'
currency, because Comparison types them as Money.

Exact integration runs for fewer than ``min_ads_for_coupling`` independent analytic options. If
quadrature misses its tolerance (registry ``quadrature_abs_tol``) the comparison falls back to joint
draws, and ``method="joint_draws"`` with ``mc_standard_error`` records it.

``p_exceeds_break_even`` is P(contribution per click > 0), i.e. P(CVR > CPC / contribution per
order) (contract assumption 14). CTR and CVR alone carry no cost, so the dict is empty for them.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import numpy as np

from bayesian_marketing.core import (
    ClientEconomics,
    Comparison,
    GateFailure,
    GateResult,
    Money,
    Objective,
    Quantity,
    inputs_hash,
    registries,
    utcnow,
)
from bayesian_marketing.derived_metrics.dist import (
    QuadratureError,
    draws_of,
    exact_max_moments,
    frozen,
)

VALUE_QUANTILE = 0.05
"""§8.2 C3: value_q05 is the 5th percentile of value at the horizon. Registry key requested:
decision_defaults.yaml value_quantile: 0.05."""

LOSS_SE_PREFIX = "expected_loss:"
"""mc_standard_error carries p_best's SE under each option name and the expected loss's SE (at
the horizon, in the value unit) under ``"expected_loss:<option>"``; Comparison has one dict."""

# quantity name -> (objective target, horizon unit)
SUPPORTED: dict[str, tuple[str, str]] = {
    "ctr": ("clicks", "impressions"),
    "cvr": ("orders", "clicks"),
    "contribution_per_click": ("contribution", "clicks"),
}


def _g9(econ: ClientEconomics) -> None:
    reasons = []
    if not econ.approved:
        reasons.append("economics not approved")
    if econ.loss_tolerance is None:
        reasons.append("no loss tolerance set")
    if reasons:
        res = GateResult(
            gate="G9",
            passed=False,
            blocking=True,
            reasons=reasons,
            inputs_hash=inputs_hash(econ),
            checked_at=utcnow(),
        )
        raise GateFailure(res)


def _names(options: list[Quantity]) -> list[str]:
    names = [q.scope.ids.get(q.scope.level, q.quantity_id) for q in options]
    if len(set(names)) != len(names):
        names = [q.quantity_id for q in options]
    return names


def _break_even(name: str) -> tuple[str, float] | None:
    """(direction, threshold) on the quantity, or None if it has no break-even."""
    if name == "contribution_per_click":
        return (">", 0.0)
    return None


def _money(x: float, cur: str) -> Money:
    return Money(amount=Decimal(repr(float(x))), currency=cur)


def compare(options: list[Quantity], objective: Objective, econ: ClientEconomics) -> Comparison:
    """Exact quadrature for independent analytic posteriors, else joint draws with MC error."""
    _g9(econ)
    if len(options) < 2:
        raise ValueError("compare needs at least two options")
    kinds = {q.name for q in options}
    if len(kinds) != 1:
        raise ValueError(f"options mix quantities {sorted(kinds)}")
    name = options[0].name
    if name not in SUPPORTED:
        raise ValueError(f"compare does not value {name!r} at a horizon")
    target, unit = SUPPORTED[name]
    if (objective.target, objective.horizon.unit) != (target, unit):
        raise ValueError(
            f"{name} compares under Objective(target={target!r}, horizon in {unit}), "
            f"got ({objective.target!r}, {objective.horizon.unit!r})"
        )
    scopes = [q.scope.model_dump_json() for q in options]
    if len(set(scopes)) != len(scopes):
        raise ValueError("options must have distinct scopes")

    names = _names(options)
    h = float(objective.horizon.amount)
    cur = econ.currency
    be = _break_even(name)
    max_exact = int(registries.resolve("bounds/coupling/min_ads_for_coupling@v1")) - 1
    exact = len(options) <= max_exact and all(
        q.estimate.kind == "analytic" and q.provenance.route != "nuts" for q in options
    )

    p_exceeds: dict[str, float] = {}
    mc_se: dict[str, float] | None = None
    result = None
    if exact:
        tol = float(registries.resolve("decision_defaults/quadrature_abs_tol@v1"))
        dists = [frozen(q.estimate) for q in options]
        try:
            result = exact_max_moments(dists, tol)
        except QuadratureError:
            result = None  # falls back to joint draws; method and mc_standard_error say so
    if result is not None:
        p_best_l, loss = result
        means = [float(d.mean()) for d in dists]
        q05 = [float(d.ppf(VALUE_QUANTILE)) for d in dists]
        if be is not None:
            op, thr = be
            for n, d in zip(names, dists, strict=True):
                p_exceeds[n] = float(d.sf(thr) if op == ">" else d.cdf(thr))
        method = "exact_integration"
    else:
        x = _joint_draws(options)
        n_rows = x.shape[0]
        best = np.argmax(x, axis=1)
        p_best_l = [float(np.mean(best == j)) for j in range(len(options))]
        regret = np.max(x, axis=1)[:, None] - x
        loss = [float(v) for v in regret.mean(axis=0)]
        means = [float(v) for v in x.mean(axis=0)]
        q05 = [float(v) for v in np.quantile(x, VALUE_QUANTILE, axis=0)]
        if be is not None:
            op, thr = be
            for j, n in enumerate(names):
                p_exceeds[n] = float(np.mean(x[:, j] > thr if op == ">" else x[:, j] < thr))
        sd_loss = regret.std(axis=0, ddof=1) if n_rows > 1 else np.zeros(len(options))
        mc_se = {}
        for j, n in enumerate(names):
            p = p_best_l[j]
            mc_se[n] = float(np.sqrt(p * (1 - p) / n_rows))
            mc_se[f"{LOSS_SE_PREFIX}{n}"] = float(h * sd_loss[j] / np.sqrt(n_rows))
        method = "joint_draws"

    return Comparison(
        options=names,
        objective=objective,
        economics_id=econ.economics_id,
        p_best=dict(zip(names, p_best_l, strict=True)),
        expected_value={n: _money(h * m, cur) for n, m in zip(names, means, strict=True)},
        expected_loss={n: _money(h * v, cur) for n, v in zip(names, loss, strict=True)},
        p_exceeds_break_even=p_exceeds,
        method=method,
        mc_standard_error=mc_se,
        value_q05={n: _money(h * v, cur) for n, v in zip(names, q05, strict=True)},
    )


def _joint_draws(options: list[Quantity]) -> np.ndarray:
    """Rows of joint draws. Sampled options are read as aligned rows (contract assumption 16);
    analytic options are independent of them and drawn with a seed derived from the inputs."""
    sampled = [q.estimate for q in options if q.estimate.kind == "samples"]
    lengths = {s.n_samples for s in sampled}
    if len(lengths) > 1:
        raise ValueError(f"sampled options have different draw counts {sorted(lengths)}")
    n = lengths.pop() if lengths else int(registries.resolve("decision_defaults/joint_draws@v1"))
    seed = int(inputs_hash([q.quantity_id for q in options])[:8], 16)
    rng = np.random.default_rng(seed)
    cols: list[Any] = []
    for q in options:
        x = draws_of(q.estimate, n, rng)
        if x.shape[0] != n:
            raise ValueError(f"{q.quantity_id} has {x.shape[0]} draws, expected {n}")
        cols.append(x)
    return np.column_stack(cols)
