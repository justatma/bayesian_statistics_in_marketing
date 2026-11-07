"""Fakes for the live view (spec v0.2 §5 L0): an in-memory ``Store`` and a fixed ``Clock``.

``FakeStore`` keeps the contract's semantics, not SQLite's: append-only (a second begin or finish
of the same poll raises), a begun poll with no outcome reads back ``interrupted``, ``latest_poll``
orders by ``started_at``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from bayesian_marketing.live.contracts import LiveRow, PollRecord, RefreshRecord


class AppendOnlyError(RuntimeError):
    pass


@dataclass
class FixedClock:
    at: datetime = field(default_factory=lambda: datetime(2026, 11, 7, 18, 0, tzinfo=UTC))

    def now(self) -> datetime:
        return self.at

    def advance(self, **kw: float) -> None:
        self.at = self.at + timedelta(**kw)


_OUTCOME = (
    "finished_at",
    "status",
    "error",
    "pull_id",
    "n_rows",
    "n_quarantined",
    "empty_account",
    "timezone",
    "currency",
    "account",
)


class FakeStore:
    def __init__(self) -> None:
        self._begun: dict[str, PollRecord] = {}
        self._outcomes: dict[str, PollRecord] = {}
        self._rows: dict[str, list[LiveRow]] = {}
        self._refreshes: list[RefreshRecord] = []

    def begin_poll(self, rec: PollRecord) -> None:
        if rec.poll_id in self._begun:
            raise AppendOnlyError(f"poll {rec.poll_id} already begun")
        self._begun[rec.poll_id] = rec

    def finish_poll(self, rec: PollRecord, rows: list[LiveRow]) -> None:
        if rec.poll_id not in self._begun:
            raise KeyError(f"poll {rec.poll_id} was never begun")
        if rec.poll_id in self._outcomes:
            raise AppendOnlyError(f"poll {rec.poll_id} already finished")
        if rec.status not in ("ok", "error"):
            raise ValueError("an outcome is ok or error")
        self._outcomes[rec.poll_id] = rec
        self._rows[rec.poll_id] = list(rows)

    def _read(self, poll_id: str) -> PollRecord:
        begun = self._begun[poll_id]
        out = self._outcomes.get(poll_id)
        if out is None:
            return begun.model_copy(
                update={
                    "status": "interrupted",
                    "finished_at": None,
                    "error": None,
                    "pull_id": None,
                    "n_rows": 0,
                    "n_quarantined": 0,
                }
            )
        return begun.model_copy(update={k: getattr(out, k) for k in _OUTCOME})

    def polls(self, client_id: str, *, limit: int) -> list[PollRecord]:
        ids = [p for p, r in self._begun.items() if r.client_id == client_id]
        recs = sorted((self._read(p) for p in ids), key=lambda r: r.started_at, reverse=True)
        return recs[:limit]

    def latest_poll(self, client_id: str, *, ok_only: bool = True) -> PollRecord | None:
        for r in self.polls(client_id, limit=10**9):
            if not ok_only or r.status == "ok":
                return r
        return None

    def rows(self, poll_id: str) -> list[LiveRow]:
        return list(self._rows.get(poll_id, []))

    def add_refresh(self, rec: RefreshRecord) -> None:
        if any(r.refresh_id == rec.refresh_id for r in self._refreshes):
            raise AppendOnlyError(f"refresh {rec.refresh_id} already stored")
        self._refreshes.append(rec)

    def latest_refresh(self, client_id: str) -> RefreshRecord | None:
        mine = [r for r in self._refreshes if r.client_id == client_id]
        return max(mine, key=lambda r: r.at) if mine else None

    def refreshes(self, client_id: str) -> list[RefreshRecord]:
        """Test helper, not in the contract."""
        return [r for r in self._refreshes if r.client_id == client_id]

    def clients(self) -> list[str]:
        return sorted({r.client_id for r in self._begun.values()})
