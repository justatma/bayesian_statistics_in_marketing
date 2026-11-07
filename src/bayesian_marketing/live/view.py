"""The internal page, rendered from the store on each request (spec v0.2 §5 L3 C1-C7). Piece L3."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bayesian_marketing.core.records import ClientConfig
from bayesian_marketing.live.contracts import Clock, Store
from bayesian_marketing.live.registry import LiveRegistry


def render(
    store: Store,
    client_id: str,
    clock: Clock,
    *,
    registry: LiveRegistry,
    phrasing: dict[str, Any],
    data_dir: Path,
    config: ClientConfig,
) -> str:
    raise NotImplementedError("L3")


def render_index(store: Store, clock: Clock, *, registry: LiveRegistry) -> str:
    raise NotImplementedError("L3")
