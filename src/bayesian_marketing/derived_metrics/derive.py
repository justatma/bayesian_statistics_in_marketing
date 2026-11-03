"""§5.5 derive."""

from __future__ import annotations

from bayesian_marketing.core import ClientEconomics, FunnelState, Quantity, Scope


def derive(name: str, state: FunnelState, scope: Scope, econ: ClientEconomics | None) -> Quantity:
    """Pure function of the state. Refuses a quarantined state."""
    raise NotImplementedError("P3")


def mix_weighted_rate(rates: dict[str, float], clicks: dict[str, float]) -> float:
    """Click-mix-weighted rate (D22; oracle: 800/200 -> 300/700 clicks at 5% / 1% gives 42 -> 22
    orders per 1,000 clicks). Deterministic."""
    raise NotImplementedError("P3")
