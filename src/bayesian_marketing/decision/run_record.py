"""§8.6 append-only SQLite run record. Piece P4."""

from __future__ import annotations

from pydantic import BaseModel

from bayesian_marketing.core import ApprovalRecord, OutcomeRecord, Recommendation, RunRecord


def append(obj: RunRecord | Recommendation | ApprovalRecord | OutcomeRecord) -> None:
    raise NotImplementedError("P4")


def read(kind: str, **filters: object) -> list[BaseModel]:
    raise NotImplementedError("P4")
