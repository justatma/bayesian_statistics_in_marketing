"""Hand-off markers for AtmaOS (Brain join J3; S33 to S35). The engine writes markers and never
reads, moves or deletes them, except to see that one already exists."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bayesian_marketing import pipeline
from bayesian_marketing.live.rows import HASH_PREFIX

MARKERS_DIR = "markers"
DONE_DIR = "done"


def markers_dir() -> Path:
    """``pipeline.data_dir() / "markers"`` at the time of the call."""
    return pipeline.data_dir() / MARKERS_DIR


def engine_run_marker(run_id: str) -> Path:
    """Write the ``engine_run`` marker for a saved run, read from its snapshot file. Returns the
    marker's path; an existing marker in ``markers/`` or ``markers/done/`` is left as it is and
    its path returned. Raises ``KeyError`` when the run has no snapshot file."""
    snap_file = pipeline.snapshot_path(run_id)
    if not snap_file.is_file():
        raise KeyError(f"no run {run_id!r} under {snap_file.parent}")
    name = f"{run_id}.json"  # S36 (2): the id carries its run_ prefix
    existing = _existing(name)
    if existing is not None:
        return existing
    data = snap_file.read_bytes()
    snap = json.loads(data)
    rows_form = snap.get("rows_form")
    if rows_form is None:  # S6, S33: a run saved before J2 names no rows
        rows_sha256: str | None = None
        row_keys: list[str] | None = None
    else:
        hexes = [
            h.removeprefix(HASH_PREFIX)
            for h in snap.get("dataset_hashes", [])
            if h.startswith(HASH_PREFIX)
        ]
        rows_sha256 = hexes[0] if hexes else None
        row_keys = list(snap.get("row_keys", []))
    return _write(
        name,
        {
            "kind": "engine_run",
            "client_id": snap["client_id"],
            "run_id": run_id,
            "snapshot_path": str(snap_file.resolve()),
            "snapshot_sha256": hashlib.sha256(data).hexdigest(),
            "rows_form": rows_form,
            "rows_sha256": rows_sha256,
            "row_keys": row_keys,
            "written_at": _now(),
        },
    )


def notebook_release_marker(folder: Path, release_hash: str) -> Path:
    """Write the ``notebook_release`` marker for a verified release folder. Same existence rule."""
    folder = Path(folder)
    release_id = folder.name
    name = f"{release_id}.json"  # S36 (2): the id carries its nb_ prefix
    existing = _existing(name)
    if existing is not None:
        return existing
    catalog = json.loads((folder / "catalog.json").read_text())
    return _write(
        name,
        {
            "kind": "notebook_release",
            "client_id": catalog["client_id"],
            "release_id": release_id,
            "release_path": str(folder.resolve()),
            "release_hash": release_hash,
            "written_at": _now(),
        },
    )


def backfill() -> dict[str, int]:
    """S35: write every missing marker. Returns ``{"engine_run": n, "notebook_release": m}``."""
    from bayesian_marketing import notebook
    from bayesian_marketing.notebook import release as nb_release

    counts = {"engine_run": 0, "notebook_release": 0}
    runs = pipeline.data_dir() / pipeline.RUNS_DIR
    for path in sorted(runs.glob("run_*.json")) if runs.is_dir() else []:
        if _existing(path.name) is not None:
            continue
        try:
            engine_run_marker(path.stem)
        except (ValueError, KeyError, TypeError) as exc:  # S37: named, and no marker
            print(f"{path.name}: not marked: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        counts["engine_run"] += 1
    root = notebook.root()
    folders = sorted(root.glob("*/releases/nb_*")) if root.is_dir() else []
    for folder in folders:
        if not folder.is_dir() or _existing(f"{folder.name}.json") is not None:
            continue
        try:
            h = nb_release.verify(folder)
        except Exception as exc:  # S35: named, and no marker
            print(f"{folder.name}: not verified: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        notebook_release_marker(folder, h)
        counts["notebook_release"] += 1
    return counts


def _existing(name: str) -> Path | None:
    """S12, S33: a marker already in ``markers/`` or ``markers/done/``."""
    folder = markers_dir()
    for path in (folder / name, folder / DONE_DIR / name):
        if path.is_file():
            return path
    return None


def _write(name: str, marker: dict[str, Any]) -> Path:
    """S33: canonical JSON and one line feed, written to ``.<name>.tmp`` and moved into place, so
    a reader never sees half a marker."""
    folder = markers_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path, tmp = folder / name, folder / f".{name}.tmp"
    body = json.dumps(marker, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    tmp.write_bytes(body.encode() + b"\n")
    try:
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return path


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
