"""Recording retention (spec v0.2 §5 L2 C4). Piece L2."""

from __future__ import annotations

from pathlib import Path

from bayesian_marketing.live.contracts import Clock, Store


def prune(record_root: Path, store: Store, clock: Clock, keep_days: int) -> list[Path]:
    """Remove ``<record_root>/<client_id>/<poll_id>`` directories whose poll started more than
    ``keep_days`` before ``clock.now()``. Age from the store, never from the file system. A
    directory naming no poll in the store is left alone. Returns the removed directories."""
    raise NotImplementedError("L2")
