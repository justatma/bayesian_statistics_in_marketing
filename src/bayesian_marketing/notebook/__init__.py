"""Account notebooks (spec/notebook_format.md, bayes-notebook-1.0.0): what the engine's seat knows
about a client's account beyond its runs, as releases AtmaOS imports as claims."""

from __future__ import annotations

import os
from pathlib import Path

from bayesian_marketing.notebook.release import SCHEMA, verify, write_release

DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "notebook"


def root() -> Path:
    """``BAYES_NOTEBOOK_DIR`` or the repository's ``notebook/`` folder."""
    return Path(os.environ.get("BAYES_NOTEBOOK_DIR", DEFAULT_ROOT))


__all__ = ["SCHEMA", "root", "verify", "write_release"]
