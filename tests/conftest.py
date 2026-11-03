"""The piece gate.

An acceptance test module declares its piece with `pytestmark = pytest.mark.piece("P3")`. The frozen
set is written before the piece exists, so the gate skips those tests until the piece is listed in
`tests/merged_pieces.txt` (integrator only) or named in the `BAYES_PIECES` environment variable
(a builder sets it in its worktree; `all` runs every piece).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

MERGED_PIECES_FILE = Path(__file__).parent / "merged_pieces.txt"


def merged_pieces() -> set[str]:
    lines = MERGED_PIECES_FILE.read_text().splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def requested_pieces() -> set[str]:
    raw = os.environ.get("BAYES_PIECES", "")
    return {p.strip() for p in raw.split(",") if p.strip()}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    merged = merged_pieces()
    requested = requested_pieces()
    run_all = "all" in requested
    for item in items:
        marker = item.get_closest_marker("piece")
        if marker is None:
            continue
        piece = marker.args[0]
        if run_all or piece in merged or piece in requested:
            continue
        item.add_marker(pytest.mark.skip(reason=f"{piece} not merged (tests/merged_pieces.txt)"))
