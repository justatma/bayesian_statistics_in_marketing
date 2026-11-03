"""§7.5 the fallback chain. Piece P6."""

from __future__ import annotations

from bayesian_marketing.core import (
    DegradationNotice,
    DiagnosticsReport,
    FunnelData,
    FunnelSpec,
    FunnelState,
    PriorSet,
)


def fit_with_fallback(
    spec: FunnelSpec, priors: PriorSet, data: FunnelData, seed: int
) -> tuple[FunnelState, list[DiagnosticsReport], list[DegradationNotice]]:
    """NUTS full; NUTS static; NUTS unpooled above ad; conjugate per ad (caps at marginal)."""
    raise NotImplementedError("P6")
