"""§8.2 reallocation and the hold rule. Piece P9."""

from __future__ import annotations

from bayesian_marketing.core import ClientEconomics, Comparison, Feasibility, Recommendation, Scope


def reallocate(
    c: Comparison,
    decision: Feasibility,
    econ: ClientEconomics,
    run_id: str,
    *,
    scope: Scope | None = None,
) -> Recommendation:
    """options[0] is the incumbent. ``scope`` names the platform for the switching cost (D22)."""
    raise NotImplementedError("P9")
