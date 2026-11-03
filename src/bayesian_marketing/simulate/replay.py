"""§9.4 shadow replay. Piece P11."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from bayesian_marketing.core import AuditReport


def replay(scenario_path: Path, seed: int, start: date, end: date) -> AuditReport:
    raise NotImplementedError("P11")
