"""§7.1 route."""

from __future__ import annotations

from bayesian_marketing.core import FunnelData, FunnelSpec, Route, registries


def route(spec: FunnelSpec, data: FunnelData) -> Route:
    """Conjugate below min_ads_for_coupling with the D11 notice, else NUTS. Piece P5."""
    threshold = int(registries.resolve("bounds/coupling/min_ads_for_coupling@v1"))
    n = len(data.entities)
    if n < threshold:
        return Route(
            kind="conjugate",
            reason=f"{n} ads is below min_ads_for_coupling {threshold} (D11): exact per-ad model",
            notices=[str(registries.resolve("phrasing/notices/too_few_ads@v1"))],
        )
    return Route(
        kind="nuts",
        reason=f"{n} ads meets min_ads_for_coupling {threshold}: joint model {spec.version}",
        notices=[],
    )
