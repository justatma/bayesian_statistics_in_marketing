"""D51 (units spec v0.2 §2, §5): pricing a count comparison's amounts in money. Piece L8."""

from __future__ import annotations

from bayesian_marketing.core import Comparison, Money

SINGULAR = {"clicks": "click", "orders": "order", "leads": "lead"}
NO_REPLACEMENT_COST = "no observed cost per {singular} to value a lost {singular}"
SURVIVAL_NOT_APPLIED = "survival floor not applied: this comparison is in {unit}, not money"
VALUED_AT = (
    "lost {unit} valued at their observed cost, {cost} per {singular} "
    "(observed, not adjusted for late conversions)"
)


def in_money(c: Comparison, amount: Money) -> Money | None:
    """Unit money: the amount. A count unit: amount times replacement_cost, or None without one."""
    raise NotImplementedError("L8")
