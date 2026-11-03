"""§5.4 save and load. States are immutable."""

from __future__ import annotations

from bayesian_marketing.core import FunnelState


def save(state: FunnelState) -> None:
    raise NotImplementedError("P3")


def load(state_id: str) -> FunnelState:
    raise NotImplementedError("P3")
