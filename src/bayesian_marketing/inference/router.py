"""§7.1 route."""

from __future__ import annotations

from bayesian_marketing.core import FunnelData, FunnelSpec, Route


def route(spec: FunnelSpec, data: FunnelData) -> Route:
    """Conjugate below min_ads_for_coupling with the D11 notice, else NUTS. Piece P5."""
    raise NotImplementedError("P5")
