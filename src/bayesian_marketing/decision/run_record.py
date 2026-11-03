"""§8.6 append-only SQLite run record. Piece P4.

One SQLite file under ``BAYES_DATA_DIR``. One table per record kind, each row the canonical JSON
of the object. Triggers reject every UPDATE and DELETE (I7).
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from bayesian_marketing.core import (
    ApprovalRecord,
    OutcomeRecord,
    Recommendation,
    RunRecord,
    canonical_json,
)

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "generated"
DB_NAME = "run_record.sqlite"

KINDS: dict[str, type[BaseModel]] = {
    "RunRecord": RunRecord,
    "Recommendation": Recommendation,
    "ApprovalRecord": ApprovalRecord,
    "OutcomeRecord": OutcomeRecord,
}
TABLES = {
    "RunRecord": "run_records",
    "Recommendation": "recommendations",
    "ApprovalRecord": "approval_records",
    "OutcomeRecord": "outcome_records",
}


def _db_path() -> Path:
    return Path(os.environ.get("BAYES_DATA_DIR", DEFAULT_DATA_DIR)) / DB_NAME


def _schema() -> str:
    parts = []
    for table in TABLES.values():
        parts.append(
            f"CREATE TABLE IF NOT EXISTS {table} "
            "(seq INTEGER PRIMARY KEY, payload TEXT NOT NULL);"
            f"CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'run record is append-only'); END;"
            f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'run record is append-only'); END;"
        )
    return "".join(parts)


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(_schema())
    return con


def _kind_of(obj: BaseModel) -> str:
    for name, cls in KINDS.items():
        if type(obj) is cls:
            return name
    raise TypeError(f"run record does not store {type(obj).__name__}")


def append(obj: RunRecord | Recommendation | ApprovalRecord | OutcomeRecord) -> None:
    table = TABLES[_kind_of(obj)]
    con = _connect()
    try:
        with con:
            con.execute(f"INSERT INTO {table} (payload) VALUES (?)", (canonical_json(obj),))
    finally:
        con.close()


def _matches(row: dict[str, Any], obj: BaseModel, filters: dict[str, object]) -> bool:
    for key, want in filters.items():
        got = getattr(obj, key)
        if got == want:
            continue
        if row[key] == json.loads(canonical_json({"v": want}))["v"]:
            continue
        return False
    return True


def read(kind: str, **filters: object) -> list[BaseModel]:
    """Every stored object of ``kind`` (a class name) whose fields equal the filters, in
    insertion order."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}; one of {sorted(KINDS)}")
    cls = KINDS[kind]
    unknown = [k for k in filters if k not in cls.model_fields]
    if unknown:
        raise ValueError(f"{kind} has no fields {unknown}")
    con = _connect()
    try:
        rows = con.execute(f"SELECT payload FROM {TABLES[kind]} ORDER BY seq").fetchall()
    finally:
        con.close()
    out: list[BaseModel] = []
    for (payload,) in rows:
        row = json.loads(payload)
        obj = cls.model_validate(row)
        if _matches(row, obj, filters):
            out.append(obj)
    return out
