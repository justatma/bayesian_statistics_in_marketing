"""§8.1 compare. Gate G9."""

from __future__ import annotations

from bayesian_marketing.core import ClientEconomics, Comparison, Objective, Quantity


def compare(options: list[Quantity], objective: Objective, econ: ClientEconomics) -> Comparison:
    """Exact quadrature for independent analytic posteriors, else joint draws with MC error."""
    raise NotImplementedError("P3")
