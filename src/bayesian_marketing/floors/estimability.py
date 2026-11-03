"""§6.1 rate basis (D10) and decision basis (D9)."""

from __future__ import annotations

from bayesian_marketing.core import (
    ClientEconomics,
    Comparison,
    Feasibility,
    PrecisionTarget,
    Quantity,
)


def quantity_feasibility(q: Quantity, target: PrecisionTarget) -> Feasibility:
    raise NotImplementedError("P4")


def decision_feasibility(c: Comparison, econ: ClientEconomics) -> Feasibility:
    raise NotImplementedError("P4")
