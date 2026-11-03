"""§8.3 stopping. Piece P9."""

from __future__ import annotations

from bayesian_marketing.core import (
    ClientEconomics,
    Comparison,
    Feasibility,
    FunnelData,
    Recommendation,
)


def stop_or_continue(
    c: Comparison, decision: Feasibility, data: FunnelData, econ: ClientEconomics, run_id: str
) -> Recommendation:
    raise NotImplementedError("P9")
