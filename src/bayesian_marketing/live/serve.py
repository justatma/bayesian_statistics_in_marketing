"""Loopback HTTP server for the live view (spec v0.2 §5 L3 C8). Piece L3. Standard library only."""

from __future__ import annotations

from http.server import ThreadingHTTPServer
from pathlib import Path

from bayesian_marketing.live.contracts import Clock
from bayesian_marketing.live.registry import LiveRegistry


def make_server(
    store_path: Path,
    *,
    registry: LiveRegistry,
    clock: Clock,
    data_dir: Path,
    config_root: Path,
    port: int | None = None,
) -> ThreadingHTTPServer:
    """Bound to ``registry.bind`` and ``port`` (``registry.port`` when None; 0 for ephemeral),
    not yet serving."""
    raise NotImplementedError("L3")


def serve(
    store_path: Path, *, registry: LiveRegistry, clock: Clock, data_dir: Path, config_root: Path
) -> None:
    """``make_server`` then ``serve_forever``; SIGTERM shuts down cleanly."""
    raise NotImplementedError("L3")
