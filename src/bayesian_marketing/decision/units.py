"""D51 (units spec v0.2 §2, §5): pricing a count comparison's amounts in money. Piece L8.

A count comparison (unit clicks, orders or leads) carries its amounts as ``Money`` in the
economics currency although they are counts per horizon. Before any of them meets a money
threshold (loss tolerance, switching cost) it is priced here at the comparison's
``replacement_cost``: the observed cost of one unit, pooled over the compared ads (U4). That is a
cost, never a sale value (D33, D46 (2)). Unit money passes through untouched, so contribution
runs are unchanged (U5).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from bayesian_marketing.core import Comparison, FunnelData, Money, registries

SINGULAR = {"clicks": "click", "orders": "order", "leads": "lead"}
NO_REPLACEMENT_COST = "no observed cost per {singular} to value a lost {singular}"
SURVIVAL_NOT_APPLIED = "survival floor not applied: this comparison is in {unit}, not money"
VALUED_AT = (
    "lost {unit} valued at their observed cost, {cost} per {singular} "
    "(observed, not adjusted for late conversions)"
)


def in_money(c: Comparison, amount: Money) -> Money | None:
    """Unit money: the amount. A count unit: amount times replacement_cost, or None without one."""
    if c.unit == "money":
        return amount
    cost = c.replacement_cost
    if cost is None:
        return None
    return Money(amount=amount.amount * cost.amount, currency=cost.currency)


def is_count(c: Comparison) -> bool:
    return c.unit != "money"


def no_cost_reason(c: Comparison) -> str:
    """NO_REPLACEMENT_COST for the comparison's unit (U9)."""
    return NO_REPLACEMENT_COST.format(singular=SINGULAR[c.unit])


def fmt_unit_cost(m: Money) -> str:
    """The cost of one unit at ``phrasing.rounding.unit_money_decimals`` (build log B23 (2))."""
    d = int(registries.load("phrasing")["rounding"]["unit_money_decimals"])
    return f"{float(m.amount):,.{d}f} {m.currency}"


def unit_params(c: Comparison) -> dict[str, Any]:
    """Recommendation params for a count unit (C6); nothing for unit money (U5)."""
    if not is_count(c):
        return {}
    cost = c.replacement_cost
    return {
        "unit": c.unit,
        "replacement_cost": None
        if cost is None
        else {"amount": str(cost.amount), "currency": cost.currency},
    }


def unit_assumptions(c: Comparison) -> list[str]:
    """The VALUED_AT assumption for a priced count unit (C6, U9); nothing for unit money (U5)."""
    if not is_count(c) or c.replacement_cost is None:
        return []
    return [
        VALUED_AT.format(
            unit=c.unit, cost=fmt_unit_cost(c.replacement_cost), singular=SINGULAR[c.unit]
        )
    ]


def replacement_cost(
    data: FunnelData, options: list[str], unit: str, currency: str
) -> Money | None:
    """U4: the observed cost of one ``unit``, pooled over the compared ads, per FunnelData cell.

    Clicks: spend over all cells divided by clicks. Orders or leads: over the cells whose
    conversion count is known (observed if not None, else reported if not None), spend divided by
    that count; a cell with no known count contributes neither. Not lag-adjusted. None for unit
    money, zero units, spend <= 0, or data in another currency than ``currency``. Stored unrounded.
    """
    if unit == "money" or data.currency != currency:
        return None
    spend = 0.0
    units = 0.0
    for o in options:
        i = data.entities.index(o)
        for j in range(len(data.dates)):
            if unit == "clicks":
                spend += data.spend[i][j]
                units += data.clicks[i][j]
                continue
            obs, rep = data.conversions_observed[i][j], data.conversions_reported[i][j]
            known = obs if obs is not None else rep
            if known is None:
                continue
            spend += data.spend[i][j]
            units += float(known)
    if units <= 0 or spend <= 0:
        return None
    return Money(amount=Decimal(repr(spend / units)), currency=currency)
