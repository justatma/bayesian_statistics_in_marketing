"""Recording retention (spec v0.2 §5 L2 C4). Piece L2."""

from __future__ import annotations

import logging
import shutil
from datetime import timedelta
from pathlib import Path

from bayesian_marketing.live.contracts import Clock, Store

log = logging.getLogger(__name__)


def prune(record_root: Path, store: Store, clock: Clock, keep_days: int) -> list[Path]:
    """Remove ``<record_root>/<client_id>/<poll_id>`` directories whose poll started more than
    ``keep_days`` before ``clock.now()``. Age from the store, never from the file system. A
    directory naming no poll in the store is left alone. Returns the removed directories."""
    root = Path(record_root)
    if not root.is_dir():
        return []
    cutoff = clock.now() - timedelta(days=keep_days)
    removed: list[Path] = []
    for client_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        started = {r.poll_id: r.started_at for r in store.polls(client_dir.name, limit=10**9)}
        for poll_dir in sorted(p for p in client_dir.iterdir() if p.is_dir()):
            when = started.get(poll_dir.name)
            if when is None:
                log.info("prune: %s names no poll in the store; left alone", poll_dir)
                continue
            if when < cutoff:
                shutil.rmtree(poll_dir)
                removed.append(poll_dir)
    return removed
