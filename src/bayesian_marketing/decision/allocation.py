"""§8.4 allocation. Piece P9. The prophet rule is a stub (D13).

The split is proportional to p_best over the options the survival floor allows (§8.2 C3), then
held within [min_arm_share, max_arm_share] from ``bounds.yaml``. Barred options get share 0. Bounds
that n eligible options cannot meet are relaxed and disclosed (``share_bounds``).

``allocate`` takes no economics, so it resolves ``c.economics_id`` with ``core.load_economics``
(D22 item 9). Economics found but unapproved or without a loss tolerance give ``not_knowable``
(I12, D16). Economics not found at all still give a split, because the frozen tests
``test_P9_extra_allocation_floor_and_cap`` and ``test_P9_every_recommendation_templated_and_
approval_required`` call ``allocate`` with no economics file and require an allocation; the
split carries a below-floor decision feasibility and a notice that says why. An allocation is
the hedged action: it keeps every allowed arm funded, so it is not a confident single choice.
"""

from __future__ import annotations

import math
from typing import Any

from bayesian_marketing.core import (
    ClientEconomics,
    Comparison,
    Feasibility,
    NotInScope,
    Recommendation,
    load_economics,
    registries,
    utcnow,
)
from bayesian_marketing.decision.reallocation import (
    base_slots,
    build,
    check_currency,
    default_scope,
    economics_block,
    fmt_prob,
    make_guarantee,
    money,
    none_guarantee,
    survival_check,
)
from bayesian_marketing.floors.estimability import DECISION_KEY, decision_feasibility

MIN_SHARE_REF = "bounds/allocation/min_arm_share@v1"
MAX_SHARE_REF = "bounds/allocation/max_arm_share@v1"

# Requested phrasing.yaml keys (manifest open question 1).
NO_ECONOMICS = "economics {eid} not found: survival floor and loss tolerance not checked"
FLOOR_RELAXED = "minimum arm share relaxed to {lo:.4f} for {n} eligible options"
CAP_RELAXED = "maximum arm share relaxed to {hi:.4f} for {n} eligible option(s)"
UNSET_ECONOMICS = "economics {eid}: {reason}"
NO_ECONOMICS_REQUIREMENT = "approved economics with a loss tolerance are needed before allocating"

CROWDED_FLOOR_FRACTION = 0.5
"""With more options than 1 / min_arm_share, each keeps at least half an even share.
Engineering choice. Registry key requested: bounds.yaml allocation.crowded_floor_fraction."""
ALL_BLOCKED = "every option breaches the survival floor"
ALL_BLOCKED_REQUIREMENT = "no option can be funded until one clears the survival floor"


def bounded_shares(weights: dict[str, float], lo: float, hi: float) -> dict[str, float]:
    """Shares ``clip(t * w, lo, hi)`` summing to 1, with ``t`` found by bisection.

    If the positive weights cannot absorb the mass even at the cap, they sit at the cap and the
    zero-weight options share the rest equally (each then lies within [lo, hi]).
    """
    n = len(weights)
    if n == 0:
        raise ValueError("no options to split")
    bad = [k for k, v in weights.items() if not math.isfinite(v) or v < 0]
    if bad:
        raise ValueError(f"weights of {bad} are negative or not finite")
    if n * lo > 1 + 1e-12 or n * hi < 1 - 1e-12:
        raise ValueError(f"no split of {n} options fits within [{lo}, {hi}]")
    w = {k: float(v) for k, v in weights.items()}
    pos = [k for k, v in w.items() if v > 0]
    if not pos:
        return dict.fromkeys(w, 1.0 / n)

    def clip(t: float) -> dict[str, float]:
        return {k: min(max(t * v, lo), hi) for k, v in w.items()}

    top = hi / min(w[k] for k in pos)
    at_cap = clip(top)
    if sum(at_cap.values()) < 1.0:
        if len(pos) == n:  # every arm at the cap and n * hi is 1 within rounding
            total = sum(at_cap.values())
            return {k: v / total for k, v in at_cap.items()}
        rest = (1.0 - hi * len(pos)) / (n - len(pos))
        return {k: hi if k in pos else rest for k in w}
    a, b = 0.0, top
    for _ in range(200):
        mid = (a + b) / 2
        a, b = (mid, b) if sum(clip(mid).values()) < 1.0 else (a, mid)
    return clip(b)


def share_bounds(n: int) -> tuple[float, float, list[str]]:
    """The registry's [min_arm_share, max_arm_share], relaxed when n options cannot meet them.

    Too many options for the floor (n * floor > 1): the floor drops to
    ``crowded_floor_fraction / n``, so shares stay proportional to p_best above it. Too few for
    the cap (n * cap < 1): the cap rises to 1 / n. Either relaxation is disclosed.
    """
    lo = float(registries.resolve(MIN_SHARE_REF))
    hi = float(registries.resolve(MAX_SHARE_REF))
    notices: list[str] = []
    if n * lo > 1:
        lo = CROWDED_FLOOR_FRACTION / n
        notices.append(FLOOR_RELAXED.format(lo=lo, n=n))
    if n * hi < 1:
        hi = 1.0 / n
        notices.append(CAP_RELAXED.format(hi=hi, n=n))
    return lo, hi, notices


def _no_economics_feasibility(c: Comparison) -> Feasibility:
    version = registries.load("bounds")["version"]
    best = min(c.expected_loss, key=lambda o: c.expected_loss[o].amount)
    return Feasibility(
        status="below_floor",
        basis="decision_loss",
        bound_ref=f"{DECISION_KEY}@{version}",
        available=float(c.expected_loss[best].amount),
        required=None,
        target=0.0,
        reasons=[NO_ECONOMICS.format(eid=c.economics_id)],
        checked_at=utcnow(),
    )


def allocate(c: Comparison, run_id: str) -> Recommendation:
    """Split in proportion to p_best, floored at min_arm_share, capped per arm."""
    if not c.options:
        raise ValueError("allocate needs at least one option")
    econ: ClientEconomics | None
    try:
        econ = load_economics(c.economics_id)
    except FileNotFoundError:
        econ = None
    decision = decision_feasibility(c, econ) if econ is not None else _no_economics_feasibility(c)
    cur = econ.currency if econ is not None else next(iter(c.expected_value.values())).currency
    check_currency(c, cur)
    notices: list[str] = [] if econ is not None else [NO_ECONOMICS.format(eid=c.economics_id)]

    reason = economics_block(econ) if econ is not None else None
    if reason is not None:  # I12, D16: found but unapproved or without a loss tolerance
        reason = UNSET_ECONOMICS.format(eid=c.economics_id, reason=reason)
        return build(
            action="not_knowable",
            c=c,
            scope=default_scope(c, decision.checked_at.date()),
            params={"allocation": {}, "notices": notices},
            decision=decision,
            economics_id=c.economics_id,
            guarantee=none_guarantee(c, cur, reason, NO_ECONOMICS_REQUIREMENT, notices),
            expected_benefit=None,
            expected_loss=None,
            reversibility="reversible",
            run_id=run_id,
        )

    blocked, floor_notices = survival_check(
        c, econ.survival_floor if econ is not None else None, list(c.options)
    )
    notices.extend(floor_notices)
    eligible = [o for o in c.options if o not in blocked]
    scope = default_scope(c, decision.checked_at.date())

    if not eligible:
        g = none_guarantee(c, cur, ALL_BLOCKED, ALL_BLOCKED_REQUIREMENT, notices)
        return build(
            action="not_knowable",
            c=c,
            scope=scope,
            params={"allocation": dict.fromkeys(c.options, 0.0), "notices": notices},
            decision=decision,
            economics_id=c.economics_id,
            guarantee=g,
            expected_benefit=None,
            expected_loss=None,
            reversibility="reversible",
            run_id=run_id,
        )

    lo, hi, relaxed = share_bounds(len(eligible))
    notices.extend(relaxed)
    shares = bounded_shares({o: c.p_best[o] for o in eligible}, lo, hi)
    allocation = {o: shares.get(o, 0.0) for o in c.options}

    top = max(eligible, key=lambda o: c.p_best[o])
    slots = base_slots(c, cur) | {"option": top, "probability": fmt_prob(c.p_best[top])}
    stmt = f"P(best = {top}) = {c.p_best[top]:.6g}; shares proportional to p_best in [{lo}, {hi}]"
    g = make_guarantee("posterior_probability", slots, stmt, [slots["assumption"], *notices])
    loss = sum(allocation[o] * float(c.expected_loss[o].amount) for o in eligible)
    params: dict[str, Any] = {"allocation": allocation, "notices": notices}
    return build(
        action="allocate",
        c=c,
        scope=scope,
        params=params,
        decision=decision,
        economics_id=c.economics_id,
        guarantee=g,
        expected_benefit=None,
        expected_loss=money(round(loss, 2), cur),
        reversibility="reversible",
        run_id=run_id,
    )


def prophet_allocation(*args: object, **kwargs: object) -> None:
    raise NotInScope("the one-sample prophet allocation is out of scope (D13)")
