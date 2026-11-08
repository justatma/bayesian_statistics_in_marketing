"""The live store: SQLite, append-only (spec v0.2 §4.1, §5 L2). Piece L2 fills the bodies.

L0 owns ``SCHEMA`` and ``SCHEMA_VERSION``; L2 must not change them (a schema change is a spec
change). WAL on a read-write open, ``busy_timeout`` 5000 ms on every connection, the view opens
read-only through a ``file:<path>?mode=ro`` URI.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from bayesian_marketing.core import Money
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
        path = Path(path)
        if read_only:
            if not path.is_file():
                raise FileNotFoundError(f"no live store at {path}")
            conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        if not read_only:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
        return cls(conn, path, read_only)

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ writes

    def begin_poll(self, rec: PollRecord) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO polls (poll_id, client_id, platform, account_id, started_at,"
                " window_start, window_end, recording_dir) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rec.poll_id,
                    rec.client_id,
                    rec.platform,
                    rec.account_id,
                    rec.started_at.isoformat(),
                    rec.window[0].isoformat(),
                    rec.window[1].isoformat(),
                    rec.recording_dir,
                ),
            )

    def finish_poll(self, rec: PollRecord, rows: list[LiveRow]) -> None:
        if rec.status not in ("ok", "error"):
            raise ValueError("an outcome is ok or error")
        if rec.finished_at is None:
            raise ValueError("an outcome needs finished_at")
        with self._conn:
            self._conn.execute(
                "INSERT INTO poll_outcomes (poll_id, finished_at, status, error, pull_id, n_rows,"
                " n_quarantined, empty_account, timezone, currency, account_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rec.poll_id,
                    rec.finished_at.isoformat(),
                    rec.status,
                    rec.error,
                    rec.pull_id,
                    rec.n_rows,
                    rec.n_quarantined,
                    int(rec.empty_account),
                    rec.timezone,
                    rec.currency,
                    json.dumps(rec.account, sort_keys=True),
                ),
            )
            self._conn.executemany(
                "INSERT INTO rows (poll_id, client_id, platform, ad_id, date, entity_ids_json,"
                " entity_names_json, objective, impressions, clicks, spend_amount,"
                " spend_currency, conversions_reported, conversions_observed, revenue_amount,"
                " revenue_currency, attribution_window)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [_row_params(rec.poll_id, r) for r in rows],
            )

    def add_refresh(self, rec: RefreshRecord) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO refreshes (refresh_id, poll_id, client_id, at, status, reason,"
                " run_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    rec.refresh_id,
                    rec.poll_id,
                    rec.client_id,
                    rec.at.isoformat(),
                    rec.status,
                    rec.reason,
                    rec.run_id,
                ),
            )

    # ------------------------------------------------------------------ reads

    def _polls(self, client_id: str) -> list[PollRecord]:
        cur = self._conn.execute(
            "SELECT p.*, o.poll_id AS o_poll_id, o.finished_at, o.status, o.error, o.pull_id,"
            " o.n_rows, o.n_quarantined, o.empty_account, o.timezone, o.currency, o.account_json"
            " FROM polls p LEFT JOIN poll_outcomes o ON o.poll_id = p.poll_id"
            " WHERE p.client_id = ?",
            (client_id,),
        )
        recs = [_poll_record(r) for r in cur.fetchall()]
        # started_at parsed, not compared as text: newest first (§4.1)
        return sorted(recs, key=lambda r: r.started_at, reverse=True)

    def latest_poll(self, client_id: str, *, ok_only: bool = True) -> PollRecord | None:
        for r in self._polls(client_id):
            if not ok_only or r.status == "ok":
                return r
        return None

    def rows(self, poll_id: str) -> list[LiveRow]:
        cur = self._conn.execute(
            "SELECT * FROM rows WHERE poll_id = ? ORDER BY date, ad_id", (poll_id,)
        )
        return [_live_row(r) for r in cur.fetchall()]

    def polls(self, client_id: str, *, limit: int) -> list[PollRecord]:
        return self._polls(client_id)[: max(limit, 0)]

    def latest_refresh(self, client_id: str) -> RefreshRecord | None:
        cur = self._conn.execute("SELECT * FROM refreshes WHERE client_id = ?", (client_id,))
        recs = [_refresh_record(r) for r in cur.fetchall()]
        return max(recs, key=lambda r: r.at) if recs else None

    def clients(self) -> list[str]:
        cur = self._conn.execute("SELECT DISTINCT client_id FROM polls ORDER BY client_id")
        return [r[0] for r in cur.fetchall()]


def _money_text(m: Money | None) -> tuple[str | None, str | None]:
    return (None, None) if m is None else (str(m.amount), m.currency)


def _row_params(poll_id: str, r: LiveRow) -> tuple[Any, ...]:
    rev_amount, rev_currency = _money_text(r.revenue_reported)
    return (
        poll_id,
        r.client_id,
        r.platform,
        r.entity_ids["ad"],
        r.date.isoformat(),
        json.dumps(r.entity_ids, sort_keys=True),
        json.dumps(r.entity_names, sort_keys=True),
        r.objective,
        r.impressions,
        r.clicks,
        str(r.spend.amount),
        r.spend.currency,
        r.conversions_reported,
        r.conversions_observed,
        rev_amount,
        rev_currency,
        r.attribution_window,
    )


def _poll_record(r: sqlite3.Row) -> PollRecord:
    base: dict[str, Any] = {
        "poll_id": r["poll_id"],
        "client_id": r["client_id"],
        "platform": r["platform"],
        "account_id": r["account_id"],
        "started_at": datetime.fromisoformat(r["started_at"]),
        "window": (date.fromisoformat(r["window_start"]), date.fromisoformat(r["window_end"])),
        "recording_dir": r["recording_dir"],
    }
    if r["o_poll_id"] is None:  # begun, never finished: the process died (§4.1)
        return PollRecord(
            **base,
            finished_at=None,
            status="interrupted",
            error=None,
            pull_id=None,
            n_rows=0,
            n_quarantined=0,
            empty_account=False,
            timezone=None,
            currency=None,
            account={},
        )
    return PollRecord(
        **base,
        finished_at=datetime.fromisoformat(r["finished_at"]),
        status=r["status"],
        error=r["error"],
        pull_id=r["pull_id"],
        n_rows=r["n_rows"],
        n_quarantined=r["n_quarantined"],
        empty_account=bool(r["empty_account"]),
        timezone=r["timezone"],
        currency=r["currency"],
        account=json.loads(r["account_json"]),
    )


def _live_row(r: sqlite3.Row) -> LiveRow:
    revenue = (
        None
        if r["revenue_amount"] is None
        else Money(amount=Decimal(r["revenue_amount"]), currency=r["revenue_currency"])
    )
    return LiveRow(
        poll_id=r["poll_id"],
        client_id=r["client_id"],
        platform=r["platform"],
        entity_ids=json.loads(r["entity_ids_json"]),
        entity_names=json.loads(r["entity_names_json"]),
        objective=r["objective"],
        date=date.fromisoformat(r["date"]),
        impressions=r["impressions"],
        clicks=r["clicks"],
        spend=Money(amount=Decimal(r["spend_amount"]), currency=r["spend_currency"]),
        conversions_reported=r["conversions_reported"],
        conversions_observed=r["conversions_observed"],
        revenue_reported=revenue,
        attribution_window=r["attribution_window"],
    )


def _refresh_record(r: sqlite3.Row) -> RefreshRecord:
    return RefreshRecord(
        refresh_id=r["refresh_id"],
        poll_id=r["poll_id"],
        client_id=r["client_id"],
        at=datetime.fromisoformat(r["at"]),
        status=r["status"],
        reason=r["reason"],
        run_id=r["run_id"],
    )
