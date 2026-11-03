"""§6.3 evpi, evsi, assess."""

from __future__ import annotations

from bayesian_marketing.core import (
    ClientEconomics,
    DecisionProblem,
    DesignAssessment,
    FunnelState,
    Money,
    TestDesign,
)


def evpi(p: DecisionProblem) -> Money:
    raise NotImplementedError("P3")


def evsi(p: DecisionProblem, d: TestDesign) -> Money:
    """Preposterior method, Manuscript ch. 6 (C1)."""
    raise NotImplementedError("P3")


def assess(
    p: DecisionProblem, d: TestDesign, econ: ClientEconomics, state: FunnelState
) -> DesignAssessment:
    raise NotImplementedError("P3")


def sample_size_two_proportions(p1: float, p2: float, alpha: float, power: float) -> float:
    """Per-arm n for a two-sided two-proportion test (oracle: 3% vs 4% -> 5,300.74)."""
    raise NotImplementedError("P3")
