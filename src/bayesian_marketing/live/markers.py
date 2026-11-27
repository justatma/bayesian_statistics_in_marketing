"""Hand-off markers for AtmaOS (Brain join J3; S33 to S35). The engine writes markers and never
reads, moves or deletes them, except to see that one already exists."""

from __future__ import annotations

from pathlib import Path

MARKERS_DIR = "markers"
DONE_DIR = "done"


def markers_dir() -> Path:
    """``pipeline.data_dir() / "markers"`` at the time of the call."""
    raise NotImplementedError


def engine_run_marker(run_id: str) -> Path:
    """Write the ``engine_run`` marker for a saved run, read from its snapshot file. Returns the
    marker's path; an existing marker in ``markers/`` or ``markers/done/`` is left as it is and
    its path returned. Raises ``KeyError`` when the run has no snapshot file."""
    raise NotImplementedError


def notebook_release_marker(folder: Path, release_hash: str) -> Path:
    """Write the ``notebook_release`` marker for a verified release folder. Same existence rule."""
    raise NotImplementedError


def backfill() -> dict[str, int]:
    """S35: write every missing marker. Returns ``{"engine_run": n, "notebook_release": m}``."""
    raise NotImplementedError
