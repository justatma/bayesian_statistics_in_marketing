"""§7.2 the exact per-ad conjugate route. Piece P3."""

from __future__ import annotations

from bayesian_marketing.core import FunnelData, FunnelState, PriorSet


def fit_conjugate(data: FunnelData, priors: PriorSet, seed: int) -> FunnelState:
    """Per-ad Beta-Binomial CTR and lag-adjusted CVR, Gamma-Poisson conversions per dollar and
    CPM, conjugate order value; analytic parameters plus seeded samples."""
    raise NotImplementedError("P3")
