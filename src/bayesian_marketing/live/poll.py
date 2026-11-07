"""One poll: one read of one client's account into the store (spec v0.2 §5 L2 C1-C6). Piece L2."""

from __future__ import annotations

from pathlib import Path

from bayesian_marketing.core.base import Platform
from bayesian_marketing.core.records import ClientConfig
from bayesian_marketing.live.contracts import Clock, PollRecord, Store
from bayesian_marketing.live.registry import LiveRegistry


def poll_id(client_id: str, platform: str, started_at_iso: str) -> str:
    """``poll_<sha8>`` over ``client_id|platform|started_at.isoformat()`` (§2)."""
    raise NotImplementedError("L2")


def poll(
    config: ClientConfig,
    store: Store,
    clock: Clock,
    *,
    platform: Platform = "meta",
    registry: LiveRegistry,
    record_root: Path | None,
) -> PollRecord:
    """Never raises (C3). Returns the finished record, ok or error."""
    raise NotImplementedError("L2")
