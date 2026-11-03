"""§8.3 stopping. Piece P9.

C1. ``stop_test`` needs an estimable decision and every cited cohort mature. A cited cohort is
each (entity, day) cell of the FunnelData with clicks > 0 for a compared option; it is mature
when its ``mature_fraction`` reaches ``bounds/lag/min_maturity``.
C2. An estimable decision held back only by immature cohorts gives ``continue_test`` with the
notice "waiting for late conversions".
C3. A decision that is not estimable continues the test, priced: ``Feasibility.required`` is the
additional volume in the horizon's unit, priced at the observed unit cost of the compared options
(spend per click, per impression or per day). A cost above ``test_budget``, an unpriceable
volume, or no test budget gives ``not_knowable``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from bayesian_marketing.core import (
    ClientEconomics,
    Comparison,
    Feasibility,
    FunnelData,
    Money,
    Recommendation,
    Scope,
    registries,
)
from bayesian_marketing.decision.reallocation import (
    build,
    check_decision,
    check_economics,
    economics_block,
    fmt_money,
    fmt_number,
    loss_guarantee,
    money,
    none_guarantee,
    phrasing,
)

MIN_MATURITY_REF = "bounds/lag/min_maturity@v1"

# Requested phrasing.yaml keys (manifest open question 1).
CONTINUE_REQUIREMENT = "we need about {volume} more {unit}, costing about {cost}"
OVER_BUDGET_REQUIREMENT = (
    "we would need about {volume} more {unit}, costing about {cost}, above the test budget {budget}"
)
UNPRICED_REQUIREMENT = "the remaining volume could not be priced: {why}"
NO_BUDGET = "no test budget set"
NO_REQUIRED = "the additional volume to reach the tolerance was not projected"
NO_UNIT_COST = "the compared options have no {unit} to price from"
MATURE_REQUIREMENT = "wait until the cited cohorts reach {maturity} maturity"


def _rows(data: FunnelData, options: list[str]) -> list[int]:
    missing = [o for o in options if o not in data.entities]
    if missing:
        raise ValueError(f"options {missing} are not entities of the FunnelData")
    return [data.entities.index(o) for o in options]


def _immature(data: FunnelData, rows: list[int], min_maturity: float) -> list[dict[str, Any]]:
    out = []
    for i in rows:
        for j, d in enumerate(data.dates):
            if data.clicks[i][j] > 0 and data.mature_fraction[i][j] < min_maturity:
                out.append(
                    {
                        "entity": data.entities[i],
                        "date": d.isoformat(),
                        "mature_fraction": data.mature_fraction[i][j],
                    }
                )
    return out


def _unit_cost(data: FunnelData, rows: list[int], unit: str) -> float | None:
    """Observed spend per unit of the horizon over the compared options."""
    spend = sum(sum(data.spend[i]) for i in rows)
    if unit == "spend":
        return 1.0
    if unit == "clicks":
        denom = float(sum(sum(data.clicks[i]) for i in rows))
    elif unit == "impressions":
        denom = float(sum(sum(data.impressions[i]) for i in rows))
    else:  # days
        denom = float(len(data.dates))
    return spend / denom if denom > 0 else None


def stop_or_continue(
    c: Comparison, decision: Feasibility, data: FunnelData, econ: ClientEconomics, run_id: str
) -> Recommendation:
    check_decision(decision)
    check_economics(c, econ)
    if data.currency != econ.currency:
        raise ValueError(f"data in {data.currency}, economics in {econ.currency}")
    cur = econ.currency
    rows = _rows(data, c.options)
    scope = Scope(
        level="ad",
        ids={"options": ",".join(c.options)},
        window=(data.dates[0], data.dates[-1]),
        platform=data.platform,
    )
    min_maturity = float(registries.resolve(MIN_MATURITY_REF))
    immature = _immature(data, rows, min_maturity)
    best = min(c.options, key=lambda o: c.expected_loss[o].amount)
    notices: list[str] = []
    if immature:
        notices.append(phrasing()["notices"]["waiting_late"])
    params: dict[str, Any] = {
        "best": best,
        "min_maturity": min_maturity,
        "immature_cohorts": immature,
        "notices": notices,
    }

    def out(action: str, g, **kw: Any) -> Recommendation:
        return build(
            action=action,
            c=c,
            scope=scope,
            params=params,
            decision=decision,
            economics_id=econ.economics_id,
            guarantee=g,
            expected_benefit=kw.get("benefit"),
            expected_loss=kw.get("loss"),
            reversibility="reversible",
            run_id=run_id,
        )

    blocked = economics_block(econ)
    if blocked is not None:
        return out("not_knowable", none_guarantee(c, cur, blocked, NO_REQUIRED, notices))

    if decision.status == "estimable":
        if not immature:
            return out(
                "stop_test",
                loss_guarantee(c, econ, best, notices),
                loss=c.expected_loss[best],
            )
        req = MATURE_REQUIREMENT.format(maturity=f"{100 * min_maturity:.0f}%")
        g = none_guarantee(c, cur, notices[0], req, notices)
        return out("continue_test", g, loss=c.expected_loss[best])

    # C3: not estimable. Price the remaining volume and compare with the test budget.
    reason = "; ".join(decision.reasons)
    unit = c.objective.horizon.unit
    if decision.required is None:
        req = UNPRICED_REQUIREMENT.format(why=NO_REQUIRED)
        return out("not_knowable", none_guarantee(c, cur, reason, req, notices))
    per_unit = _unit_cost(data, rows, unit)
    if per_unit is None:
        req = UNPRICED_REQUIREMENT.format(why=NO_UNIT_COST.format(unit=unit))
        return out("not_knowable", none_guarantee(c, cur, reason, req, notices))
    cost: Money = money(round(Decimal(str(decision.required * per_unit)), 2), cur)
    params |= {
        "remaining_volume": {"unit": unit, "amount": decision.required},
        "remaining_cost": str(cost.amount),
        "test_budget": None if econ.test_budget is None else str(econ.test_budget.amount),
    }
    volume = fmt_number(decision.required)
    if econ.test_budget is None:
        req = UNPRICED_REQUIREMENT.format(why=NO_BUDGET)
        return out("not_knowable", none_guarantee(c, cur, reason, req, notices))
    if cost.amount > econ.test_budget.amount:
        req = OVER_BUDGET_REQUIREMENT.format(
            volume=volume, unit=unit, cost=fmt_money(cost), budget=fmt_money(econ.test_budget)
        )
        return out("not_knowable", none_guarantee(c, cur, reason, req, notices))
    req = CONTINUE_REQUIREMENT.format(volume=volume, unit=unit, cost=fmt_money(cost))
    return out("continue_test", none_guarantee(c, cur, reason, req, notices))
