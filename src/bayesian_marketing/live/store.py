"""The live store: SQLite, append-only (spec v0.2 §4.1, §5 L2). Piece L2 fills the bodies.

L0 owns ``SCHEMA`` and ``SCHEMA_VERSION``; L2 must not change them (a schema change is a spec
change). WAL on a read-write open, ``busy_timeout`` 5000 ms on every connection, the view opens
read-only through a ``file:<path>?mode=ro`` URI.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from bayesian_marketing.live.contracts import LiveRow, PollRecord, RefreshRecord

SCHEMA_VERSION = "1"
APPEND_ONLY = "live store is append-only"
TABLES = ("polls", "poll_outcomes", "rows", "refreshes")
BUSY_TIMEOUT_MS = 5000

_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS schema_info (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS polls (
  poll_id TEXT PRIMARY KEY, client_id TEXT NOT NULL, platform TEXT NOT NULL,
  account_id TEXT NOT NULL, started_at TEXT NOT NULL,
  window_start TEXT NOT NULL, window_end TEXT NOT NULL, recording_dir TEXT);
CREATE TABLE IF NOT EXISTS poll_outcomes (
  poll_id TEXT PRIMARY KEY REFERENCES polls(poll_id), finished_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ok','error')), error TEXT,
  pull_id TEXT, n_rows INTEGER NOT NULL, n_quarantined INTEGER NOT NULL,
  empty_account INTEGER NOT NULL, timezone TEXT, currency TEXT, account_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rows (
  poll_id TEXT NOT NULL REFERENCES polls(poll_id), client_id TEXT NOT NULL, platform TEXT NOT NULL,
  ad_id TEXT NOT NULL, date TEXT NOT NULL,
  entity_ids_json TEXT NOT NULL, entity_names_json TEXT NOT NULL, objective TEXT,
  impressions INTEGER NOT NULL, clicks INTEGER NOT NULL,
  spend_amount TEXT NOT NULL, spend_currency TEXT NOT NULL,
  conversions_reported REAL, conversions_observed INTEGER,
  revenue_amount TEXT, revenue_currency TEXT, attribution_window TEXT NOT NULL,
  PRIMARY KEY (poll_id, ad_id, date));
CREATE TABLE IF NOT EXISTS refreshes (
  refresh_id TEXT PRIMARY KEY, poll_id TEXT NOT NULL REFERENCES polls(poll_id),
  client_id TEXT NOT NULL, at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ran','skipped','failed')), reason TEXT, run_id TEXT);
CREATE INDEX IF NOT EXISTS polls_client_started ON polls(client_id, started_at);
CREATE INDEX IF NOT EXISTS refreshes_client_at ON refreshes(client_id, at);
INSERT OR IGNORE INTO schema_info (key, value) VALUES ('schema_version', '1');
"""
_TRIGGERS_SQL = "".join(
    f"""
CREATE TRIGGER IF NOT EXISTS {t}_no_update BEFORE UPDATE ON {t}
  BEGIN SELECT RAISE(ABORT, '{APPEND_ONLY}'); END;
CREATE TRIGGER IF NOT EXISTS {t}_no_delete BEFORE DELETE ON {t}
  BEGIN SELECT RAISE(ABORT, '{APPEND_ONLY}'); END;
"""
    for t in (*TABLES, "schema_info")
)
SCHEMA = _TABLES_SQL + _TRIGGERS_SQL


class SqliteStore:
    """Implements ``live.contracts.Store``."""

    def __init__(self, conn: sqlite3.Connection, path: Path, read_only: bool) -> None:
        self._conn = conn
        self.path = path
        self.read_only = read_only

    @classmethod
    def open(cls, path: Path, *, read_only: bool = False) -> SqliteStore:
        """Create the schema when read-write (idempotent). Read-only never creates a file."""
        raise NotImplementedError("L2")

    def close(self) -> None:
        raise NotImplementedError("L2")

    def begin_poll(self, rec: PollRecord) -> None:
        raise NotImplementedError("L2")

    def finish_poll(self, rec: PollRecord, rows: list[LiveRow]) -> None:
        raise NotImplementedError("L2")

    def latest_poll(self, client_id: str, *, ok_only: bool = True) -> PollRecord | None:
        raise NotImplementedError("L2")

    def rows(self, poll_id: str) -> list[LiveRow]:
        raise NotImplementedError("L2")

    def polls(self, client_id: str, *, limit: int) -> list[PollRecord]:
        raise NotImplementedError("L2")

    def add_refresh(self, rec: RefreshRecord) -> None:
        raise NotImplementedError("L2")

    def latest_refresh(self, client_id: str) -> RefreshRecord | None:
        raise NotImplementedError("L2")

    def clients(self) -> list[str]:
        raise NotImplementedError("L2")
