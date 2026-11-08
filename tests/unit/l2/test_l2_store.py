"""L2 unit tests: store round trips, read-only open, poll edge cases, prune edges."""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest
from tests.fakes.live import FixedClock

from bayesian_marketing import core as C
from bayesian_marketing.core import Money
from bayesian_marketing.data_contract.connectors import http as H
from bayesian_marketing.live.contracts import LiveRow, PollRecord, RefreshRecord
from bayesian_marketing.live.poll import poll, poll_id
from bayesian_marketing.live.prune import prune
from bayesian_marketing.live.registry import load_live_registry
from bayesian_marketing.live.store import APPEND_ONLY, SqliteStore

NOON = dt.datetime(2026, 11, 7, 18, 0, 0, 123456, tzinfo=dt.UTC)


def _rec(client: str, started: dt.datetime, status: str = "ok") -> PollRecord:
    return PollRecord(
        poll_id=poll_id(client, "meta", started.isoformat()),
        client_id=client,
        platform="meta",
        account_id="act_1",
        started_at=started,
        finished_at=started + dt.timedelta(seconds=3),
        window=(started.date() - dt.timedelta(days=6), started.date()),
        status=status,  # type: ignore[arg-type]
        error=None if status == "ok" else "ConnectorError: x",
        pull_id="pull_meta_1" if status == "ok" else None,
        n_rows=1,
        n_quarantined=2,
        empty_account=True,
        timezone="Europe/Berlin",
        currency="EUR",
        account={"currency": "EUR", "name": "Acme"},
        recording_dir="/x/y",
    )


def _row(pid: str, revenue: Money | None) -> LiveRow:
    return LiveRow(
        poll_id=pid,
        client_id="c",
        platform="meta",
        entity_ids={"account": "1", "campaign": "2", "ad_set": "3", "ad": "4"},
        entity_names={"ad": "Ad four"},
        objective="OUTCOME_SALES",
        date=dt.date(2026, 11, 7),
        impressions=100,
        clicks=7,
        spend=Money(amount=Decimal("12.30"), currency="EUR"),
        conversions_reported=1.5,
        conversions_observed=None,
        revenue_reported=revenue,
        attribution_window="7d_click",
    )


def test_round_trip_poll_row_and_refresh(tmp_path: Path) -> None:
    store = SqliteStore.open(tmp_path / "s.sqlite")
    rec = _rec("c", NOON)
    store.begin_poll(rec)
    row = _row(rec.poll_id, Money(amount=Decimal("40.00"), currency="EUR"))
    store.finish_poll(rec, [row])
    assert store.latest_poll("c") == rec
    assert store.rows(rec.poll_id) == [row]
    assert store.rows(rec.poll_id)[0].spend.amount == Decimal("12.30")  # decimal text kept
    assert store.latest_refresh("c") is None
    early = RefreshRecord(
        refresh_id="lv_1", poll_id=rec.poll_id, client_id="c", at=NOON, status="ran",
        reason=None, run_id="run_1",
    )  # fmt: skip
    late = early.model_copy(update={"refresh_id": "lv_2", "at": NOON + dt.timedelta(hours=1)})
    store.add_refresh(late)
    store.add_refresh(early)
    assert store.latest_refresh("c") == late
    with pytest.raises(sqlite3.IntegrityError):
        store.add_refresh(early)  # same id twice
    with pytest.raises(sqlite3.IntegrityError):
        store.finish_poll(rec, [])  # a second outcome
    store.close()


def test_revenue_none_round_trips(tmp_path: Path) -> None:
    store = SqliteStore.open(tmp_path / "s.sqlite")
    rec = _rec("c", NOON)
    store.begin_poll(rec)
    store.finish_poll(rec, [_row(rec.poll_id, None)])
    assert store.rows(rec.poll_id)[0].revenue_reported is None


def test_open_twice_is_idempotent_and_wal(tmp_path: Path) -> None:
    path = tmp_path / "s.sqlite"
    SqliteStore.open(path).close()
    store = SqliteStore.open(path)
    assert store._conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert store._conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    store.close()


def test_read_only_never_creates_and_never_writes(tmp_path: Path) -> None:
    path = tmp_path / "s.sqlite"
    with pytest.raises(FileNotFoundError):
        SqliteStore.open(path, read_only=True)
    assert not path.exists()
    rw = SqliteStore.open(path)
    rec = _rec("c", NOON)
    rw.begin_poll(rec)
    rw.finish_poll(rec, [])
    ro = SqliteStore.open(path, read_only=True)
    assert ro.clients() == ["c"]
    assert ro.latest_poll("c") == rec
    with pytest.raises(sqlite3.OperationalError):
        ro.begin_poll(_rec("c", NOON + dt.timedelta(hours=1)))
    ro.close()
    rw.close()


def test_append_only_message(tmp_path: Path) -> None:
    store = SqliteStore.open(tmp_path / "s.sqlite")
    rec = _rec("c", NOON)
    store.begin_poll(rec)
    with pytest.raises(sqlite3.IntegrityError, match=APPEND_ONLY):
        store._conn.execute("DELETE FROM polls")


def test_latest_ok_skips_error_and_orders_by_time(tmp_path: Path) -> None:
    store = SqliteStore.open(tmp_path / "s.sqlite")
    ok = _rec("c", NOON - dt.timedelta(hours=2))
    bad = _rec("c", NOON - dt.timedelta(hours=1), status="error")
    for r in (bad, ok):  # inserted out of order
        store.begin_poll(r)
        store.finish_poll(r, [])
    assert store.latest_poll("c") == ok
    assert store.latest_poll("c", ok_only=False) == bad
    assert [p.poll_id for p in store.polls("c", limit=1)] == [bad.poll_id]
    assert store.polls("nobody", limit=5) == []


@pytest.fixture
def no_record_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in (H.REPLAY_ENV, H.RECORD_ENV, *H.CREDENTIAL_ENV):
        monkeypatch.delenv(k, raising=False)


def test_poll_missing_account_is_an_error_row(no_record_env: None, tmp_path: Path) -> None:
    store = SqliteStore.open(tmp_path / "s.sqlite")
    cfg = C.ClientConfig(client_id="c", timezone="UTC", currency="USD", accounts={})
    rec = poll(cfg, store, FixedClock(NOON), registry=load_live_registry(), record_root=None)
    assert rec.status == "error" and rec.error and rec.error.startswith("ValueError: ")
    assert store.latest_poll("c", ok_only=False) == rec
    assert rec.account_id == ""


def test_poll_bad_zone_is_an_error_row(no_record_env: None, tmp_path: Path) -> None:
    store = SqliteStore.open(tmp_path / "s.sqlite")
    cfg = C.ClientConfig(
        client_id="c", timezone="Not/AZone", currency="USD", accounts={"meta": "act_1"}
    )
    rec = poll(cfg, store, FixedClock(NOON), registry=load_live_registry(), record_root=None)
    assert rec.status == "error"
    assert rec.window[1] == NOON.date()


def test_poll_error_with_record_root_restores_env(no_record_env: None, tmp_path: Path) -> None:
    store = SqliteStore.open(tmp_path / "s.sqlite")
    cfg = C.ClientConfig(client_id="c", timezone="UTC", currency="USD", accounts={"meta": "a"})
    root = tmp_path / "rec"
    rec = poll(cfg, store, FixedClock(NOON), registry=load_live_registry(), record_root=root)
    assert rec.status == "error"  # no credential in env
    assert H.RECORD_ENV not in os.environ
    assert rec.recording_dir == str(root / "c" / rec.poll_id)
    assert not Path(rec.recording_dir).exists()  # a failed pull commits no recording


def test_prune_missing_root_and_boundary(tmp_path: Path) -> None:
    store = SqliteStore.open(tmp_path / "s.sqlite")
    clock = FixedClock(NOON)
    assert prune(tmp_path / "absent", store, clock, 7) == []
    just_over = _rec("c", NOON - dt.timedelta(days=7, microseconds=1))
    store.begin_poll(just_over)
    store.finish_poll(just_over, [])
    d = tmp_path / "r" / "c" / just_over.poll_id
    d.mkdir(parents=True)
    (tmp_path / "r" / "c" / "stray.txt").write_text("x")  # files are not poll directories
    assert prune(tmp_path / "r", store, clock, 7) == [d]
    assert (tmp_path / "r" / "c" / "stray.txt").exists()


# Review F1 (review/L2 481be59): the REFERENCES in SCHEMA are enforced.


def test_finish_poll_never_begun_rejected_like_fake(tmp_path: Path) -> None:
    """tests/fakes/live.py: finishing a never-begun poll raises; rows must not orphan."""
    from tests.fakes.live import FakeStore

    rec = _rec("c", NOON)
    with pytest.raises(KeyError):
        FakeStore().finish_poll(rec, [])
    s = SqliteStore.open(tmp_path / "s.sqlite")
    with pytest.raises(sqlite3.IntegrityError):
        s.finish_poll(rec, [_row(rec.poll_id, None)])
    assert s.rows(rec.poll_id) == []


def test_add_refresh_for_unknown_poll_rejected(tmp_path: Path) -> None:
    """§4.1: refreshes.poll_id REFERENCES polls(poll_id)."""
    s = SqliteStore.open(tmp_path / "s.sqlite")
    r = RefreshRecord(
        refresh_id="lv_1", poll_id="poll_nope", client_id="c", at=NOON,
        status="skipped", reason=None, run_id=None,
    )  # fmt: skip
    with pytest.raises(sqlite3.IntegrityError):
        s.add_refresh(r)
    assert s.latest_refresh("c") is None
