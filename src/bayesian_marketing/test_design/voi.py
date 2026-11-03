"""§6.3 evpi, evsi, assess.

Payoffs are per option at the horizon. Sampled payoffs read the parquet column named after the
option and are joint by row (contract assumption 18). Independent analytic payoffs use exact
quadrature for EVPI. A DecisionProblem carries no currency, so ``evpi`` and ``evsi`` return Money
in ``XXX`` (ISO 4217 "no currency"); ``assess`` restates them in the economics' currency.

EVSI follows the preposterior method (Manuscript ch. 6, §6.3 C1) for signal-type designs: on each
joint draw an arm signals positive with probability ``sensitivity`` if its payoff is > 0, else
``false_positive_rate``; arms signal independently given the draw. EVSI is
Σ_s P(s) max_j E[V_j | s] - max_j E[V_j].
"""

from __future__ import annotations

import itertools
from decimal import Decimal

import numpy as np
from scipy import stats

from bayesian_marketing.core import (
    ClientEconomics,
    DecisionProblem,
    DesignAssessment,
    FunnelState,
    Money,
    MoneyInterval,
    TestDesign,
    inputs_hash,
    registries,
)
from bayesian_marketing.derived_metrics.dist import draws_of as _draws_of
from bayesian_marketing.derived_metrics.dist import exact_max_moments, frozen, read_draws

NO_CURRENCY = "XXX"


def _money(x: float, cur: str = NO_CURRENCY) -> Money:
    return Money(amount=Decimal(repr(float(x))), currency=cur)


def _payoff_draws(p: DecisionProblem) -> np.ndarray:
    """Rows of joint payoff draws, one column per option (in p.options order)."""
    specs = [p.payoffs[o] for o in p.options]
    sampled = [s for s in specs if s.kind == "samples"]
    lengths = {s.n_samples for s in sampled}
    if len(lengths) > 1:
        raise ValueError(f"sampled payoffs have different draw counts {sorted(lengths)}")
    n = lengths.pop() if lengths else int(registries.resolve("decision_defaults/joint_draws@v1"))
    rng = np.random.default_rng(int(inputs_hash(p)[:8], 16))
    cols = []
    for o, s in zip(p.options, specs, strict=True):
        x = read_draws(s, o) if s.kind == "samples" else _draws_of(s, n, rng)
        if x.shape[0] != n:
            raise ValueError(f"payoff {o!r} has {x.shape[0]} draws, expected {n}")
        cols.append(x)
    return np.column_stack(cols)


def _check(p: DecisionProblem) -> None:
    if not p.options:
        raise ValueError("a decision problem needs at least one option")
    missing = [o for o in p.options if o not in p.payoffs]
    if missing:
        raise ValueError(f"no payoff for {missing}")


def evpi(p: DecisionProblem) -> Money:
    """E[max_j V_j] - max_j E[V_j]."""
    _check(p)
    specs = [p.payoffs[o] for o in p.options]
    if all(s.kind == "analytic" for s in specs):
        tol = float(registries.resolve("decision_defaults/quadrature_abs_tol@v1"))
        dists = [frozen(s) for s in specs]
        _, e_max = exact_max_moments(dists, tol)
        return _money(max(0.0, e_max - max(float(d.mean()) for d in dists)))
    x = _payoff_draws(p)
    return _money(max(0.0, float(x.max(axis=1).mean() - x.mean(axis=0).max())))


def evsi(p: DecisionProblem, d: TestDesign) -> Money:
    """Preposterior method, Manuscript ch. 6 (C1)."""
    _check(p)
    if d.sensitivity is None or d.false_positive_rate is None:
        raise ValueError(
            "EVSI needs a signal model: TestDesign.sensitivity and false_positive_rate"
        )
    unknown = [a for a in d.arms if a not in p.options]
    if unknown:
        raise ValueError(f"arms {unknown} are not options of the decision problem")
    x = _payoff_draws(p)
    n = x.shape[0]
    arm_cols = [p.options.index(a) for a in d.arms]
    p_pos = [np.where(x[:, j] > 0, d.sensitivity, d.false_positive_rate) for j in arm_cols]
    value = 0.0
    for signals in itertools.product((True, False), repeat=len(arm_cols)):
        w = np.ones(n)
        for pp, s in zip(p_pos, signals, strict=True):
            w = w * (pp if s else 1.0 - pp)
        total = float(w.sum())
        if total <= 0:
            continue
        cond_means = (w[:, None] * x).sum(axis=0) / total
        value += (total / n) * float(cond_means.max())
    return _money(max(0.0, value - float(x.mean(axis=0).max())))


def _cost_draws(d: TestDesign, state: FunnelState) -> np.ndarray:
    """Spend the design needs, per joint draw of the state (§6.3 C2: CPC and CPM posteriors)."""
    vol = float(d.volume.amount)
    unit = d.volume.unit
    if unit == "spend":
        return np.array([vol])
    if unit == "days":
        raise ValueError("a test volume in days cannot be priced from CPC or CPM")
    path = state.posterior.samples_path
    if state.posterior.kind != "samples" or path is None:
        raise ValueError(f"state {state.state_id} has no joint draws to price the test")
    total = 0.0
    shares = d.allocation or {a: 1.0 / len(d.arms) for a in d.arms}
    for arm, share in shares.items():
        cpm = read_draws(state.posterior, f"{arm}.cpm")
        if unit == "impressions":
            per_unit = cpm / 1000.0
        else:
            per_unit = cpm / (1000.0 * read_draws(state.posterior, f"{arm}.ctr"))
        total = total + share * vol * per_unit
    return np.asarray(total, dtype=float)


def assess(
    p: DecisionProblem, d: TestDesign, econ: ClientEconomics, state: FunnelState
) -> DesignAssessment:
    cur = econ.currency
    v_pi = float(evpi(p).amount)
    v_si = float(evsi(p, d).amount)
    cost = _cost_draws(d, state)
    lo, mid, hi = (float(v) for v in np.quantile(cost, [0.05, 0.5, 0.95]))
    net = v_si - mid
    label = "holdout" if d.holdout else "randomized" if d.randomized else "observational"
    # §6.3 C3: no redesign is searched, because the signal model has no link from volume to
    # sensitivity; a cheaper volume would carry the same EVSI and the search would be degenerate.
    verdict = "buy" if net >= 0 else "do_not_buy"
    return DesignAssessment(
        evpi=_money(v_pi, cur),
        evsi=_money(v_si, cur),
        cost=MoneyInterval(low=_money(lo, cur), mid=_money(mid, cur), high=_money(hi, cur)),
        net_value=_money(net, cur),
        verdict=verdict,
        redesign=None,
        design_label=label,
    )


def sample_size_two_proportions(p1: float, p2: float, alpha: float, power: float) -> float:
    """Per-arm n for a two-sided two-proportion test (oracle: 3% vs 4% -> 5,300.74)."""
    if p1 == p2:
        raise ValueError("p1 and p2 must differ")
    for v in (p1, p2, alpha, power):
        if not 0 < v < 1:
            raise ValueError("p1, p2, alpha and power must lie in (0, 1)")
    z_a = float(stats.norm.isf(alpha / 2))
    z_b = float(stats.norm.ppf(power))
    pbar = (p1 + p2) / 2
    num = z_a * np.sqrt(2 * pbar * (1 - pbar)) + z_b * np.sqrt(p1 * (1 - p1) + p2 * (1 - p2))
    return float(num**2 / (p1 - p2) ** 2)
