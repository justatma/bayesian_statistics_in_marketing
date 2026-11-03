"""§8.2 reallocation and the hold rule. Piece P9.

``Comparison.options[0]`` is the incumbent; every other option is a switch candidate. The hold
test (C2) is: expected benefit of the best eligible candidate over the incumbent, minus the
switching cost, must be > 0, and the decision basis must not be below floor. An option whose
``value_q05`` breaches ``survival_floor`` is never recommended (C3).

The module also holds the helpers that ``stopping`` and ``allocation`` share (guarantee slots,
formatting, the Recommendation builder), because the piece's file list has no shared module.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from bayesian_marketing.channels.model import load_channel_model
from bayesian_marketing.core import (
    ClientEconomics,
    Comparison,
    Feasibility,
    Guarantee,
    Horizon,
    Money,
    Recommendation,
    Scope,
    make_id,
    registries,
)
from bayesian_marketing.decision.guarantees import render_guarantee
from bayesian_marketing.floors.estimability import NO_TOLERANCE_REASON

# Phrases with no registry key yet. Each is a requested phrasing.yaml key (manifest open
# question 1); the text is kept here, in one place, until the registry carries it.
ASSUMPTION = "the next {horizon} behave like the data so far"
"""Requested key: phrasing.yaml assumption_stationary."""
SWITCH_UNKNOWN = (
    "switching cost unknown for {platforms}: the hold test used a switching cost of zero, and the "
    "switch is treated as costly"
)
"""§8.2 C1. Requested key: phrasing.yaml notices.switching_cost_unknown."""
SURVIVAL_BLOCKED = (
    "{option} not recommended: its 5th-percentile value {q05} is below the survival floor {floor}"
)
"""§8.2 C3. Requested key: phrasing.yaml notices.survival_floor_blocked."""
SURVIVAL_UNCHECKED = "{option} not recommended: the survival floor {floor} is set but the comparison has no 5th-percentile value for it"  # noqa: E501
"""§8.2 C3 without value_q05. Requested key: phrasing.yaml notices.survival_floor_unchecked."""
SURVIVAL_INCUMBENT = (
    "the incumbent {option} breaches the survival floor {floor} and no eligible switch beats it"
)
"""Requested key: phrasing.yaml notices.survival_floor_incumbent."""
UNAPPROVED_REASON = "economics not approved"
"""I12. Requested key: phrasing.yaml reasons.economics_unapproved."""
NO_SCOPE_NOTICE = "scope not given: the platform and window of this recommendation are unknown"
"""D22 item 10 with scope=None. Requested key: phrasing.yaml notices.scope_unknown."""
HOLD_REQUIREMENT = "keep {option} and re-run the comparison as data arrives"
"""Requirement slot of the 'none' template for a below-floor hold. Requested key."""

EVIDENCE_BY_TARGET = {
    "clicks": "delivery",
    "orders": "platform_attributed",
    "contribution": "platform_attributed",
}
"""Comparison carries no evidence class (manifest open question 2). Clicks rest on delivery;
orders and contribution rest on conversions, taken at the lowest class they can have here."""
ROUTE_BY_METHOD = {"exact_integration": "conjugate", "joint_draws": "nuts"}
"""Comparison carries no route (manifest open question 2); its method is the nearest proxy."""


# ---------------------------------------------------------------- shared helpers (P9 modules)


def phrasing() -> dict[str, Any]:
    return registries.load("phrasing")


def fmt_money(m: Money) -> str:
    d = int(phrasing()["rounding"]["money_decimals"])
    return f"{float(m.amount):,.{d}f} {m.currency}"


def fmt_prob(p: float) -> str:
    d = int(phrasing()["rounding"]["percent_decimals"])
    return f"{100.0 * p:.{d}f}%"


def fmt_number(x: float | Decimal) -> str:
    x = float(x)
    return f"{x:,.0f}" if x == int(x) else f"{x:,.2f}"


def horizon_text(h: Horizon, currency: str) -> str:
    if h.unit == "spend":
        return f"{fmt_money(Money(amount=h.amount, currency=currency))} of spend"
    return f"{fmt_number(h.amount)} {h.unit}"


def money(x: float | Decimal, currency: str) -> Money:
    return Money(amount=Decimal(str(x)), currency=currency)


def check_decision(decision: Feasibility) -> None:
    if decision.basis != "decision_loss":
        raise ValueError(
            f"decision feasibility basis is {decision.basis!r}, not decision_loss (D9)"
        )


def check_economics(c: Comparison, econ: ClientEconomics) -> None:
    if c.economics_id != econ.economics_id:
        raise ValueError(
            f"comparison uses economics {c.economics_id!r}, given {econ.economics_id!r}"
        )


def economics_block(econ: ClientEconomics) -> str | None:
    """The reason no dollar decision may run (I12, D16), or None."""
    if not econ.approved:
        return UNAPPROVED_REASON
    if econ.loss_tolerance is None:
        return NO_TOLERANCE_REASON
    return None


def default_scope(c: Comparison, when: date) -> Scope:
    """A scope for a recommendation made without one: the compared options, no platform."""
    return Scope(
        level="ad", ids={"options": ",".join(c.options)}, window=(when, when), platform=None
    )


def survival_check(
    c: Comparison, floor: Money | None, options: list[str]
) -> tuple[set[str], list[str]]:
    """Options barred by the survival floor (§8.2 C3), and the notice for each."""
    if floor is None:
        return set(), []
    blocked: set[str] = set()
    notices: list[str] = []
    q05s = c.value_q05 or {}
    for o in options:
        q = q05s.get(o)
        if q is None:
            blocked.add(o)
            notices.append(SURVIVAL_UNCHECKED.format(option=o, floor=fmt_money(floor)))
            continue
        if q.currency != floor.currency:
            raise ValueError(
                f"value_q05 of {o} is in {q.currency}, survival floor in {floor.currency}"
            )
        if q.amount < floor.amount:
            blocked.add(o)
            notices.append(
                SURVIVAL_BLOCKED.format(option=o, q05=fmt_money(q), floor=fmt_money(floor))
            )
    return blocked, notices


def base_slots(c: Comparison, currency: str) -> dict[str, str]:
    ph = phrasing()
    h = horizon_text(c.objective.horizon, currency)
    return {
        "evidence_plain": ph["evidence_plain"][EVIDENCE_BY_TARGET[c.objective.target]],
        "route_plain": ph["route_plain"][ROUTE_BY_METHOD[c.method]],
        "horizon": h,
        "assumption": ASSUMPTION.format(horizon=h),
    }


def make_guarantee(
    kind: str, slots: dict[str, str], statement_math: str, assumptions: list[str]
) -> Guarantee:
    g = Guarantee(
        kind=kind,
        statement_math=statement_math,
        template_id=kind,
        slots=slots,
        assumptions=assumptions,
    )
    render_guarantee(g)  # I8: a guarantee that cannot be rendered is never issued
    return g


def loss_guarantee(
    c: Comparison, econ: ClientEconomics, option: str, notices: list[str]
) -> Guarantee:
    assert econ.loss_tolerance is not None
    slots = base_slots(c, econ.currency) | {
        "option": option,
        "expected_loss": fmt_money(c.expected_loss[option]),
        "tolerance": fmt_money(econ.loss_tolerance),
    }
    math = (
        f"E[loss | choose {option}] = {c.expected_loss[option].amount} "
        f"; tolerance = {econ.loss_tolerance.amount} ({econ.currency})"
    )
    return make_guarantee("expected_loss", slots, math, [slots["assumption"], *notices])


def none_guarantee(
    c: Comparison, currency: str, reason: str, requirement: str, notices: list[str]
) -> Guarantee:
    slots = base_slots(c, currency) | {"reason": reason, "requirement": requirement}
    slots = {k: v.replace("{", "(").replace("}", ")") for k, v in slots.items()}
    return make_guarantee(
        "none", slots, f"no recommendation: {reason}", [slots["assumption"], *notices]
    )


def build(
    *,
    action: str,
    c: Comparison,
    scope: Scope,
    params: dict[str, Any],
    decision: Feasibility,
    economics_id: str | None,
    guarantee: Guarantee,
    expected_benefit: Money | None,
    expected_loss: Money | None,
    reversibility: str,
    run_id: str,
) -> Recommendation:
    payload = {
        "run": run_id,
        "action": action,
        "options": c.options,
        "params": params,
        "g": guarantee.statement_math,
    }
    return Recommendation(
        recommendation_id=make_id("rec_", payload),
        action=action,
        scope=scope,
        params=params,
        basis=[],  # Comparison carries no quantity ids (manifest open question 3)
        decision_feasibility=decision,
        economics_id=economics_id,
        guarantee=guarantee,
        expected_benefit=expected_benefit,
        expected_loss=expected_loss,
        horizon=c.objective.horizon,
        reversibility=reversibility,
        run_id=run_id,
    )


# ---------------------------------------------------------------- switching cost (C1)


def ad_platforms() -> list[str]:
    """Platforms with a switching-cost entry in decision_defaults.yaml (the ad platforms)."""
    return list(registries.load("decision_defaults")["learning_phase_switching_cost"])


def switching_cost(scope: Scope | None, currency: str) -> tuple[Money | None, list[str]]:
    """The switching cost from the ChannelModel of the scope's platform (C1).

    Without a platform the cost is the largest over the ad platforms, and unknown if any of
    them is unknown. Returns (cost or None when unknown, the platforms consulted).
    """
    platforms = [scope.platform] if scope is not None and scope.platform else ad_platforms()
    costs: list[Money] = []
    for p in platforms:
        cost = load_channel_model(p).learning_phase_switching_cost
        if cost is None:
            return None, platforms
        if cost.currency != currency:
            raise ValueError(
                f"switching cost for {p} is in {cost.currency}, economics in {currency}"
            )
        costs.append(cost)
    return max(costs, key=lambda m: m.amount), platforms


# ---------------------------------------------------------------- reallocate


def reallocate(
    c: Comparison,
    decision: Feasibility,
    econ: ClientEconomics,
    run_id: str,
    *,
    scope: Scope | None = None,
) -> Recommendation:
    """options[0] is the incumbent. ``scope`` names the platform for the switching cost (D22)."""
    check_decision(decision)
    check_economics(c, econ)
    if len(c.options) < 2:
        raise ValueError("reallocate needs an incumbent and at least one candidate")
    cur = econ.currency
    incumbent, candidates = c.options[0], c.options[1:]
    notices: list[str] = []
    if scope is None:
        notices.append(NO_SCOPE_NOTICE)
    rec_scope = scope or default_scope(c, decision.checked_at.date())

    blocked_reason = economics_block(econ)
    if blocked_reason is not None:
        g = none_guarantee(
            c, cur, blocked_reason, HOLD_REQUIREMENT.format(option=incumbent), notices
        )
        return build(
            action="not_knowable",
            c=c,
            scope=rec_scope,
            params={"keep": incumbent, "notices": notices},
            decision=decision,
            economics_id=econ.economics_id,
            guarantee=g,
            expected_benefit=None,
            expected_loss=None,
            reversibility="reversible",
            run_id=run_id,
        )

    cost, platforms = switching_cost(scope, cur)
    reversibility = "reversible"
    if cost is None:
        notices.append(SWITCH_UNKNOWN.format(platforms=", ".join(platforms)))
        reversibility = "costly"
        cost_amt = Decimal(0)
    else:
        cost_amt = cost.amount
        if cost_amt > 0:
            reversibility = "costly"

    blocked, floor_notices = survival_check(c, econ.survival_floor, list(c.options))
    notices.extend(floor_notices)
    eligible = [o for o in candidates if o not in blocked]
    ev = {o: c.expected_value[o].amount for o in c.options}
    target = max(eligible, key=lambda o: ev[o]) if eligible else None
    benefit = ev[target] - ev[incumbent] if target is not None else None
    net = benefit - cost_amt if benefit is not None else None

    params: dict[str, Any] = {
        "incumbent": incumbent,
        "candidate": target,
        "switching_cost": None if cost is None else str(cost.amount),
        "switching_cost_assumed": str(cost_amt),
        "currency": cur,
        "expected_benefit_before_switching_cost": None if benefit is None else str(benefit),
        "net_benefit": None if net is None else str(net),
    }

    if decision.status == "below_floor":
        reason = "; ".join(decision.reasons)
        g = none_guarantee(c, cur, reason, HOLD_REQUIREMENT.format(option=incumbent), notices)
        params |= {"keep": incumbent, "notices": notices}
        return build(
            action="hold",
            c=c,
            scope=rec_scope,
            params=params,
            decision=decision,
            economics_id=econ.economics_id,
            guarantee=g,
            expected_benefit=None,
            expected_loss=c.expected_loss[incumbent],
            reversibility=reversibility,
            run_id=run_id,
        )

    if target is not None and net is not None and net > 0:
        params |= {"from": incumbent, "to": target, "notices": notices}
        return build(
            action="reallocate",
            c=c,
            scope=rec_scope,
            params=params,
            decision=decision,
            economics_id=econ.economics_id,
            guarantee=loss_guarantee(c, econ, target, notices),
            expected_benefit=money(net, cur),
            expected_loss=c.expected_loss[target],
            reversibility=reversibility,
            run_id=run_id,
        )

    if incumbent in blocked:
        assert econ.survival_floor is not None
        notices.append(
            SURVIVAL_INCUMBENT.format(option=incumbent, floor=fmt_money(econ.survival_floor))
        )
    params |= {"keep": incumbent, "notices": notices}
    return build(
        action="hold",
        c=c,
        scope=rec_scope,
        params=params,
        decision=decision,
        economics_id=econ.economics_id,
        guarantee=loss_guarantee(c, econ, incumbent, notices),
        expected_benefit=None,
        expected_loss=c.expected_loss[incumbent],
        reversibility=reversibility,
        run_id=run_id,
    )
