"""L2 store, poll, prune (live view spec v0.2 §4.1, §5 L2 C1 to C6).

Polls run against ``meta_handler`` on an httpx mock transport with fake credential values in the
environment. Stores are ``SqliteStore.open`` on ``tmp_path``. No network.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest

from bayesian_marketing import core as C
from bayesian_marketing.data_contract.connectors import http as H
from bayesian_marketing.live.contracts import PollRecord, RefreshRecord
from bayesian_marketing.live.poll import poll
from bayesian_marketing.live.prune import prune
from bayesian_marketing.live.registry import load_live_registry
from bayesian_marketing.live.store import SqliteStore
from tests.fakes.live import FixedClock
from tests.fakes.meta_api import ACCOUNT, META_TOKEN, _json, _meta_row, meta_handler

pytestmark = pytest.mark.piece("L2")

UTC = dt.UTC
REAL_CLIENT = httpx.Client
FAKE_SECRETS = {
    "META_ACCESS_TOKEN": META_TOKEN,
    "META_APP_SECRET": "appsecret" + "q" * 24,
    "META_CLIENT_TOKEN": "clienttok" + "z" * 24,
}
TABLES = ("polls", "poll_outcomes", "rows", "refreshes")
# microseconds are non-zero so isoformat() is unambiguous (spec §2)
NOON = dt.datetime(2026, 11, 7, 18, 0, 0, 123456, tzinfo=UTC)


def _config(tz: str = "America/Los_Angeles", client: str = "unit_client") -> C.ClientConfig:
    return C.ClientConfig(
        client_id=client, timezone=tz, currency="USD", accounts={"meta": "act_111"}
    )


@pytest.fixture
def creds(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in (H.REPLAY_ENV, H.RECORD_ENV):
        monkeypatch.delenv(k, raising=False)
    for k, v in FAKE_SECRETS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(H, "BACKOFF_BASE_S", 0.0)


def _mock(monkeypatch: pytest.MonkeyPatch, handler: Any) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(
        H.httpx, "Client", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(wrapped), **kw)
    )
    return seen


def _rows(days: list[str], ads: tuple[str, ...] = ("a1", "a2", "a3")) -> list[dict[str, Any]]:
    return [_meta_row(ad, day) for day in days for ad in ads]


def _store(tmp_path: Path) -> SqliteStore:
    return SqliteStore.open(tmp_path / "live.sqlite")


def _poll(
    store: SqliteStore,
    clock: FixedClock,
    *,
    record_root: Path | None = None,
    config: C.ClientConfig | None = None,
) -> PollRecord:
    return poll(
        config or _config(),
        store,
        clock,
        platform="meta",
        registry=load_live_registry(),
        record_root=record_root,
    )


def _rec(client: str, started: dt.datetime, *, status: str = "ok", n_rows: int = 0) -> PollRecord:
    pid = "poll_" + hashlib.sha256(f"{client}|meta|{started.isoformat()}".encode()).hexdigest()[:8]
    return PollRecord(
        poll_id=pid,
        client_id=client,
        platform="meta",
        account_id="act_111",
        started_at=started,
        finished_at=started + dt.timedelta(seconds=5),
        window=(started.date() - dt.timedelta(days=6), started.date()),
        status=status,  # type: ignore[arg-type]
        error=None if status == "ok" else "ConnectorError: x",
        pull_id="pull_meta_00000001" if status == "ok" else None,
        n_rows=n_rows,
        n_quarantined=0,
        empty_account=False,
        timezone="America/New_York",
        currency="USD",
        account={"currency": "USD"},
        recording_dir=None,
    )


# ------------------------------------------------------------------ polls


def test_L2_poll_stores_nine_rows_and_one_ok_poll(
    creds: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock(monkeypatch, meta_handler(_rows(["2026-11-05", "2026-11-06", "2026-11-07"])))
    store = _store(tmp_path)
    rec = _poll(store, FixedClock(NOON))
    assert rec.status == "ok" and rec.error is None
    assert rec.n_rows == 9  # L2 check 1
    polls = store.polls("unit_client", limit=10)
    assert len(polls) == 1 and polls[0].status == "ok"  # L2 check 1
    assert len(store.rows(rec.poll_id)) == 9  # L2 check 1
    got = store.latest_poll("unit_client")
    assert got is not None and got.poll_id == rec.poll_id
    assert got.timezone == ACCOUNT["timezone_name"]  # L2 C1: the zone the dates were read in
    assert store.clients() == ["unit_client"]
    # §2: poll_<sha8> over client|platform|started_at.isoformat()
    want = hashlib.sha256(f"unit_client|meta|{NOON.isoformat()}".encode()).hexdigest()[:8]
    assert rec.poll_id == f"poll_{want}"  # L2 §2 [2.23]


def test_L2_auth_error_stores_error_poll_without_token(
    creds: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    err = {"message": f"Error validating access token {META_TOKEN}", "type": "OAuthException"}
    err["code"] = 190  # type: ignore[assignment]
    _mock(monkeypatch, meta_handler(_rows(["2026-11-07"]), fail_first=err))
    store = _store(tmp_path)
    rec = _poll(store, FixedClock(NOON))  # L2 C3: poll never raises
    assert rec.status == "error"  # L2 C3
    assert rec.error and rec.error.startswith("ConnectorError: ")  # L2 C3 "<ExceptionClass>: "
    assert META_TOKEN not in rec.error  # L2 C3
    stored = store.latest_poll("unit_client", ok_only=False)
    assert stored is not None and stored.status == "error"
    assert stored.error is not None and META_TOKEN not in stored.error
    assert store.rows(rec.poll_id) == []  # L2 C3: no rows
    assert store.latest_poll("unit_client") is None  # L2 C3: no ok poll exists


def test_L2_error_text_redacts_access_token_pairs(
    creds: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    other = "OTHERTOKENVALUE0123456789"

    def handle(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/insights"):
            msg = f"bad call https://graph.facebook.com/x?access_token={other}&y=1"
            return _json({"error": {"message": msg, "code": 190}}, 400)
        return meta_handler([])(req)

    _mock(monkeypatch, handle)
    store = _store(tmp_path)
    rec = _poll(store, FixedClock(NOON))
    assert rec.status == "error"
    assert other not in (rec.error or "")  # L2 C3: access_token=<value> never survives
    assert META_TOKEN not in (rec.error or "")


# ------------------------------------------------------------------ append-only, interrupted


def test_L2_update_and_delete_raise_append_only_on_each_table(
    creds: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock(monkeypatch, meta_handler(_rows(["2026-11-07"])))
    store = _store(tmp_path)
    rec = _poll(store, FixedClock(NOON))
    store.add_refresh(
        RefreshRecord(
            refresh_id="lv_00000001",
            poll_id=rec.poll_id,
            client_id="unit_client",
            at=NOON,
            status="skipped",
            reason="x",
            run_id=None,
        )
    )
    store.close()
    con = sqlite3.connect(tmp_path / "live.sqlite")
    try:
        for table in TABLES:
            assert con.execute(f"SELECT count(*) FROM {table}").fetchone()[0] >= 1, table
            with pytest.raises(
                (sqlite3.IntegrityError, sqlite3.DatabaseError), match="append-only"
            ):
                con.execute(f"UPDATE {table} SET poll_id = poll_id")  # L2 check 3, §4.1
            with pytest.raises(
                (sqlite3.IntegrityError, sqlite3.DatabaseError), match="append-only"
            ):
                con.execute(f"DELETE FROM {table}")  # L2 check 3, §4.1
    finally:
        con.close()


def test_L2_second_poll_stores_second_set_and_is_latest(
    creds: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock(monkeypatch, meta_handler(_rows(["2026-11-06", "2026-11-07"])))
    store = _store(tmp_path)
    clock = FixedClock(NOON)
    first = _poll(store, clock)
    clock.advance(hours=1)
    second = _poll(store, clock)
    assert first.poll_id != second.poll_id
    latest = store.latest_poll("unit_client")
    assert latest is not None and latest.poll_id == second.poll_id  # L2 check 4
    assert len(store.rows(second.poll_id)) == 6  # L2 check 4
    assert len(store.rows(first.poll_id)) == 6  # L2 C2: the first set is still there
    assert [p.poll_id for p in store.polls("unit_client", limit=10)] == [
        second.poll_id,
        first.poll_id,
    ]  # newest first


def test_L2_poll_without_outcome_reads_interrupted(tmp_path: Path) -> None:
    store = _store(tmp_path)
    older = _rec("c1", NOON - dt.timedelta(hours=2), n_rows=0)
    store.begin_poll(older)
    store.finish_poll(older, [])
    newer = _rec("c1", NOON - dt.timedelta(hours=1))
    store.begin_poll(newer)  # no finish_poll: the process died
    got = store.latest_poll("c1", ok_only=False)
    assert got is not None and got.poll_id == newer.poll_id
    assert got.status == "interrupted"  # L2 check 5, §4.1
    ok = store.latest_poll("c1", ok_only=True)
    assert ok is not None and ok.poll_id == older.poll_id  # L2 check 5: ok_only skips it
    assert [p.status for p in store.polls("c1", limit=5)] == ["interrupted", "ok"]


# ------------------------------------------------------------------ window


def test_L2_window_ends_on_account_local_date(
    creds: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ny = dict(ACCOUNT, timezone_name="America/New_York")
    seen = _mock(monkeypatch, meta_handler(_rows(["2026-11-05", "2026-11-06"]), account=ny))
    store = _store(tmp_path)
    clock = FixedClock(dt.datetime(2026, 11, 7, 3, 0, tzinfo=UTC))  # 22:00 on 11-06 in New York
    rec = _poll(store, clock, config=_config(tz="America/New_York"))
    assert rec.status == "ok"
    assert rec.window[1] == dt.date(2026, 11, 6)  # L2 check 7, C1
    assert rec.window == (dt.date(2026, 10, 31), dt.date(2026, 11, 6))  # L2 C1: 7 dates inclusive
    ranges = [
        json.loads(v)
        for r in seen
        for k, v in httpx.QueryParams(r.url.query).multi_items()
        if k == "time_range"
    ]
    assert ranges and ranges[0] == {"since": "2026-10-31", "until": "2026-11-06"}  # L2 C1 pull call
    assert len(store.rows(rec.poll_id)) == 6


# ------------------------------------------------------------------ prune and recordings


def _mk_dir(root: Path, client: str, poll_id: str) -> Path:
    d = root / client / poll_id
    d.mkdir(parents=True)
    (d / "exchange_0001.json").write_text("{}")
    return d


def test_L2_prune_removes_exactly_the_old_directories(tmp_path: Path) -> None:
    store = _store(tmp_path)
    clock = FixedClock(NOON)
    started = {
        ("c1", "old"): NOON - dt.timedelta(days=8),
        ("c1", "edge"): NOON - dt.timedelta(days=7),
        ("c1", "new"): NOON - dt.timedelta(days=1),
        ("c2", "old"): NOON - dt.timedelta(days=30),
    }
    root = tmp_path / "recordings"
    dirs = {}
    for (client, tag), when in started.items():
        rec = _rec(client, when)
        store.begin_poll(rec)
        store.finish_poll(rec, [])
        dirs[(client, tag)] = _mk_dir(root, client, rec.poll_id)
    stranger = _mk_dir(root, "c1", "poll_deadbeef")  # names no poll in the store
    removed = prune(root, store, clock, 7)
    assert {Path(p) for p in removed} == {dirs[("c1", "old")], dirs[("c2", "old")]}  # L2 check 6
    assert not dirs[("c1", "old")].exists() and not dirs[("c2", "old")].exists()  # L2 check 6
    assert dirs[("c1", "edge")].exists()  # L2 C4: exactly keep_days old is not "more than"
    assert dirs[("c1", "new")].exists()  # L2 check 6
    assert stranger.exists()  # L2 C4: a directory naming no poll is left alone
    assert len(store.polls("c1", limit=10)) == 3  # L2 C4: the store keeps every row
    assert len(store.polls("c2", limit=10)) == 1


def test_L2_poll_records_to_per_poll_directory_and_prunes(
    creds: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock(monkeypatch, meta_handler(_rows(["2026-11-07"])))
    monkeypatch.setenv(H.RECORD_ENV, "previous-value")  # L2 C1: restored after the call
    store = _store(tmp_path)
    root = tmp_path / "recordings"
    old = _rec("unit_client", NOON - dt.timedelta(days=10))
    store.begin_poll(old)
    store.finish_poll(old, [])
    old_dir = _mk_dir(root, "unit_client", old.poll_id)
    rec = _poll(store, FixedClock(NOON), record_root=root)
    want = root / "unit_client" / rec.poll_id
    assert want.is_dir() and any(want.iterdir())  # L2 C1: BAYES_RECORD_DIR set for the call
    assert rec.recording_dir is not None
    assert Path(rec.recording_dir).resolve() == want.resolve()
    assert os.environ[H.RECORD_ENV] == "previous-value"  # L2 C1: context manager restores
    assert not old_dir.exists()  # L2 C4: poll prunes after finish_poll with keep_days from registry
    assert want.exists()
    monkeypatch.delenv(H.RECORD_ENV)
    _mock(monkeypatch, meta_handler(_rows(["2026-11-07"])))
    clock = FixedClock(NOON + dt.timedelta(minutes=1))
    _poll(store, clock, record_root=root)
    assert H.RECORD_ENV not in os.environ  # L2 C1: unset again if it was unset before


# ------------------------------------------------------------------ secrets


def test_L2_no_credential_value_in_store_or_recordings(
    creds: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock(monkeypatch, meta_handler(_rows(["2026-11-06", "2026-11-07"])))
    work = tmp_path / "work"
    work.mkdir()
    store = SqliteStore.open(work / "live.sqlite")
    root = work / "recordings"
    clock = FixedClock(NOON)
    _poll(store, clock, record_root=root)
    clock.advance(hours=1)
    err = {"message": f"Error validating access token {META_TOKEN}", "code": 190}
    _mock(monkeypatch, meta_handler([], fail_first=err))
    _poll(store, clock, record_root=root)  # an error poll too
    store.close()
    files = [p for p in work.rglob("*") if p.is_file()]
    assert any(p.name.startswith("live.sqlite") for p in files)
    assert any(root in p.parents for p in files)
    for p in files:
        data = p.read_bytes()
        for name, value in FAKE_SECRETS.items():
            assert value.encode() not in data, f"{name} in {p}"  # L2 C6 / check 8
        for m in re.finditer(rb"access_token=([^&\s\"']*)", data):
            assert m.group(1) == b"REDACTED", f"raw access_token in {p}"  # L2 C6
