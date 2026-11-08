"""Blind review of L3 at 9af7158. test_F* fail against it; test_P* are probes that pass."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import socket
import sqlite3
import threading
import time
import urllib.parse
from pathlib import Path

import pytest
import yaml
from tests.acceptance.conftest import iso  # noqa: F401  (autouse isolation)
from tests.acceptance.test_L3 import (
    ACCOUNT,
    ACCOUNT_ID,
    LEAD_EVENT,
    NAMES1,
    NOW,
    TZ,
    D,
    cells,
    config,
    live_row,
    live_strings,
    one_ad_rows,
    poll_rec,
    refresh_rec,
    render_page,
    section,
    seed,
    seed_sqlite,
    text_of,
)
from tests.fakes.live import FakeStore, FixedClock

from bayesian_marketing import pipeline
from bayesian_marketing.core import registries
from bayesian_marketing.live import view
from bayesian_marketing.live.registry import load_live_registry
from bayesian_marketing.live.serve import make_server

UTC = dt.UTC


def _server(tmp_path: Path):
    store_path = tmp_path / "live.sqlite"
    if not store_path.exists():
        seed_sqlite(store_path)
    cfg_root = tmp_path / "configs"
    cfg_root.mkdir(exist_ok=True)
    (cfg_root / "acme.yaml").write_text(yaml.safe_dump(config().model_dump(mode="json")))
    srv = make_server(
        store_path,
        registry=load_live_registry(),
        clock=FixedClock(NOW),
        data_dir=Path(os.environ["BAYES_DATA_DIR"]),
        config_root=cfg_root,
        port=0,
    )
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, t, cfg_root


def _stop(srv, t):
    srv.shutdown()
    srv.server_close()
    t.join(timeout=5)


def _raw(port: int, data: bytes) -> bytes:
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(data)
    out = b""
    while True:
        try:
            chunk = s.recv(65536)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
    s.close()
    return out


def _add_client(store_path: Path, cid: str) -> None:
    con = sqlite3.connect(store_path)
    started = (NOW - dt.timedelta(minutes=30)).isoformat()
    pid = "poll_" + hashlib.md5(cid.encode()).hexdigest()[:8]
    con.execute(
        "INSERT INTO polls VALUES (?,?,'meta',?,?,'2026-11-01','2026-11-07',NULL)",
        (pid, cid, ACCOUNT_ID, started),
    )
    con.execute(
        "INSERT INTO poll_outcomes VALUES (?,?,'ok',NULL,'pull_meta_00000001',0,0,0,?,?,?)",
        (pid, started, TZ, "USD", json.dumps(ACCOUNT)),
    )
    con.commit()
    con.close()


def _render(store, **kw):
    return view.render(
        store,
        "acme",
        FixedClock(NOW),
        registry=kw.get("registry", load_live_registry()),
        phrasing=registries.load("phrasing"),
        data_dir=kw["data_dir"] if "data_dir" in kw else Path(os.environ["BAYES_DATA_DIR"]),
        config=config(),
    )


# ---------------------------------------------------------------- findings


def test_F1_period_with_only_unreported_rows_reads_not_reported() -> None:
    """C4: 'not reported when the count is None' per period. A counted row 3 days ago and an
    uncounted (None) row today: today's count shows 0 / none yet."""

    def rows(pid: str):
        return [
            live_row(
                pid, "ad_300", D(2026, 11, 7), 1000, 20, "10.00", conversions=None, names=NAMES1
            ),
            live_row(
                pid, "ad_300", D(2026, 11, 4), 1000, 20, "10.00", conversions=3.0, names=NAMES1
            ),
        ]

    store = FakeStore()
    seed(store, rows=rows)
    conv = cells(section(render_page(store), "h_conversions")).rows
    row = next(r for r in conv if any("ad_300" in c for c in r))
    assert row[3:5] == [live_strings()["not_reported"]] * 2, row[3:5]


def test_F2_budget_conversions_not_reported_when_window_rows_all_none() -> None:
    """C5: conversions 'not reported when None'. Counted row 13 days ago, None row today."""

    def rows(pid: str):
        return [
            live_row(
                pid, "ad_300", D(2026, 11, 7), 1000, 20, "10.00", conversions=None, names=NAMES1
            ),
            live_row(
                pid, "ad_300", D(2026, 10, 25), 1000, 20, "10.00", conversions=30.0, names=NAMES1
            ),
        ]

    store = FakeStore()
    seed(store, rows=rows)
    b = cells(section(render_page(store), "h_budget")).rows
    row = next(r for r in b if any("ad_300" in c for c in r))
    assert row[-3] == live_strings()["not_reported"], row


def test_F3_fractional_count_below_floor_is_not_shown_as_the_floor() -> None:
    """C5/C7: 16.96 conversions (below the floor of 17) is displayed '17.0' beside 'below floor'."""
    store = FakeStore()
    seed(store, rows=one_ad_rows(clicks=20, conversions=16.96))
    assert "17.0" not in text_of(render_page(store))


def test_F4_concurrent_renders_keep_BAYES_DATA_DIR(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """C6/C8: the server is threaded. Render A's env context ends while render B still loads, and
    B sees BAYES_DATA_DIR unset."""
    store = FakeStore()
    poll = seed(store)
    store.add_refresh(refresh_rec(poll, "ran", run_id="run_x"))
    dd = tmp_path / "dd"
    seen: dict[str, str | None] = {}
    a_in, b_in, a_done = threading.Event(), threading.Event(), threading.Event()
    calls: list[int] = []
    lock = threading.Lock()

    def fake_load(run_id: str):
        with lock:
            n = len(calls)
            calls.append(1)
        if n == 0:
            a_in.set()
            b_in.wait(5)
            raise KeyError("a")
        b_in.set()
        a_done.wait(5)
        seen["b"] = os.environ.get("BAYES_DATA_DIR")
        raise KeyError("b")

    monkeypatch.setattr(pipeline, "load_snapshot", fake_load)
    monkeypatch.delenv("BAYES_DATA_DIR", raising=False)

    def run(first: bool):
        if not first:
            a_in.wait(5)
        _render(store, data_dir=dd)
        if first:
            a_done.set()

    ta = threading.Thread(target=run, args=(True,))
    tb = threading.Thread(target=run, args=(False,))
    ta.start()
    tb.start()
    ta.join(10)
    tb.join(10)
    assert seen.get("b") == str(dd), seen


def test_F5_non_ascii_client_id_is_reachable_by_its_link(tmp_path: Path) -> None:
    """C8: the index links each client. A browser sends 'café' percent-encoded; the server does not
    decode it and answers 404."""
    srv, t, cfg_root = _server(tmp_path)
    try:
        cid = "café"
        _add_client(tmp_path / "live.sqlite", cid)
        (cfg_root / f"{cid}.yaml").write_text(
            yaml.safe_dump(config(client_id=cid).model_dump(mode="json")), encoding="utf-8"
        )
        port = srv.server_address[1]
        quoted = urllib.parse.quote(cid)
        resp = _raw(port, f"GET /client/{quoted} HTTP/1.0\r\n\r\n".encode())
        assert resp.startswith(b"HTTP/1.0 200"), resp[:60]
    finally:
        _stop(srv, t)


def test_F6_overlong_request_line_is_logged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """C8: one stdout line per request. A 70k-character path gets a 414 and no line."""
    srv, t, _ = _server(tmp_path)
    try:
        port = srv.server_address[1]
        resp = _raw(port, b"GET /" + b"a" * 70000 + b" HTTP/1.0\r\n\r\n")
        assert b" 414 " in resp.split(b"\r\n")[0]
        time.sleep(0.3)
        out = capsys.readouterr().out
        assert re.search(r"^\S+ \S* 414 ", out, re.M), repr(out[:200])
    finally:
        _stop(srv, t)


# ---------------------------------------------------------------- probes (no defect)


def test_P_escaping_of_api_strings() -> None:
    evil = "<script>alert(1)</script>"
    names = {"account": evil, "campaign": evil, "ad_set": evil, "ad": evil}
    store = FakeStore()
    rec = poll_rec(account={**ACCOUNT, "name": evil})
    store.begin_poll(rec)
    store.finish_poll(
        rec, [live_row(rec.poll_id, "ad_9", D(2026, 11, 7), 10, 1, "1.00", names=names)]
    )
    e = poll_rec(started=NOW - dt.timedelta(minutes=5), status="error", error=evil)
    store.begin_poll(e)
    store.finish_poll(e, [])
    page = render_page(store)
    assert "<script>" not in page and "&lt;script&gt;" in page


def test_P_lead_client_with_revenue_rows_shows_no_value() -> None:
    def rows(pid: str):
        return [
            live_row(
                pid,
                "ad_300",
                D(2026, 11, 7),
                1000,
                20,
                "10.00",
                conversions=4.0,
                revenue="987.65",
                names=NAMES1,
            )
        ]

    store = FakeStore()
    seed(store, rows=rows)
    page = render_page(store, cfg=config(conversion_event={"meta": LEAD_EVENT}))
    t = text_of(page)
    assert "987" not in t and "roas" not in t.lower()


@pytest.mark.parametrize(
    "cur,cap,expect",
    [
        ("JPY", "150000", "150,000 JPY"),
        ("KWD", "1500000", "1,500 KWD"),
        ("USD", "150000", "$1,500"),
    ],
)
def test_P_exponents(cur, cap, expect) -> None:
    store = FakeStore()
    seed(store, currency=cur, account={**ACCOUNT, "spend_cap": cap})
    assert expect in text_of(render_page(store, cfg=config(currency=cur)))


@pytest.mark.parametrize("cap", ["0", None, ""])
def test_P_no_limit(cap) -> None:
    acct = {k: v for k, v in ACCOUNT.items() if k != "spend_cap"}
    if cap is not None:
        acct["spend_cap"] = cap
    store = FakeStore()
    seed(store, account=acct)
    assert live_strings()["no_limit"] in render_page(store)


def test_P_unknown_status_raw() -> None:
    store = FakeStore()
    seed(store, account={**ACCOUNT, "account_status": "999"})
    assert "999" in text_of(render_page(store))


@pytest.mark.parametrize("delta,stale", [(7200, False), (7201, True), (7199, False)])
def test_P_stale_threshold(delta, stale) -> None:
    store = FakeStore()
    seed(store, started=NOW - dt.timedelta(seconds=delta))
    frag = live_strings()["banner_stale"].split("{at}")[0].strip()
    assert (frag in render_page(store)) is stale


@pytest.mark.parametrize(
    "now_utc,today",
    [
        (dt.datetime(2026, 11, 1, 5, 30, tzinfo=UTC), D(2026, 11, 1)),
        (dt.datetime(2026, 11, 1, 6, 30, tzinfo=UTC), D(2026, 11, 1)),
        (dt.datetime(2026, 11, 2, 4, 59, tzinfo=UTC), D(2026, 11, 1)),
        (dt.datetime(2026, 11, 2, 5, 0, tzinfo=UTC), D(2026, 11, 2)),
    ],
)
def test_P_periods_across_dst(now_utc, today) -> None:
    def rows(pid):
        return [
            live_row(pid, "ad_300", today, 100, 10, "5.00", conversions=1.0),
            live_row(pid, "ad_300", today - dt.timedelta(days=6), 40, 4, "2.00", conversions=1.0),
            live_row(pid, "ad_300", today - dt.timedelta(days=7), 900, 90, "9.00", conversions=1.0),
        ]

    store = FakeStore()
    seed(store, started=now_utc - dt.timedelta(minutes=10), rows=rows)
    t = text_of(render_page(store, clock=FixedClock(now_utc)))
    assert "140" in t and "1040" not in t


def test_P_missing_snapshot_does_not_crash(tmp_path) -> None:
    store = FakeStore()
    p = seed(store)
    for i, rid in enumerate(("run_nope", "../../x", "run_/../a")):
        rec = refresh_rec(p, "ran", run_id=rid).model_copy(
            update={"refresh_id": f"lv_0000000{i + 1}"}
        )
        store.add_refresh(rec)
        assert live_strings()["h_engine"] in render_page(store, data_dir=tmp_path)


def test_P_only_error_poll_page_and_index() -> None:
    store = FakeStore()
    seed(store, status="error", error="boom")
    page = render_page(store)
    assert "boom" in page and "<h2" not in page
    idx = view.render_index(store, FixedClock(NOW), registry=load_live_registry())
    assert live_strings()["none_yet"] in idx


def test_P_server_paths_and_methods(tmp_path) -> None:
    srv, t, _ = _server(tmp_path)
    try:
        port = srv.server_address[1]
        assert srv.server_address[0] == "127.0.0.1"
        paths = [
            "/client/../health",
            "/client/%2e%2e",
            "/client/..",
            "/client/",
            "/client",
            "/client/acme%2Fx",
            "/client/acme/",
            "/health/",
            "/client/%00",
            "/client/" + "a" * 5000,
        ]
        for path in paths:
            r = _raw(port, b"GET " + path.encode() + b" HTTP/1.0\r\n\r\n")
            assert r.split(b"\r\n")[0].split()[1] in (b"404", b"400"), (path, r[:40])
        r = _raw(port, b"GET /health?x=1 HTTP/1.0\r\n\r\n")
        assert b"Content-Type: application/json\r\n" in r and b'"ok": true' in r
        for m in (b"HEAD", b"OPTIONS", b"PATCH", b"POST"):
            assert _raw(port, m + b" /health HTTP/1.0\r\n\r\n").startswith(b"HTTP/1.0 405")
    finally:
        _stop(srv, t)


def test_P_client_without_config_404_and_store_untouched(tmp_path) -> None:
    srv, t, _ = _server(tmp_path)
    sp = tmp_path / "live.sqlite"
    _add_client(sp, "noconf")

    def digest():
        return {
            p.name: hashlib.md5(p.read_bytes()).hexdigest() for p in tmp_path.glob("live.sqlite*")
        }

    before = digest()
    try:
        port = srv.server_address[1]
        assert _raw(port, b"GET /client/noconf HTTP/1.0\r\n\r\n").startswith(b"HTTP/1.0 404")
        for p in ("/", "/health", "/client/acme"):
            _raw(port, f"GET {p} HTTP/1.0\r\n\r\n".encode())
    finally:
        _stop(srv, t)
    assert before == digest()


def test_P_refresh_seconds_from_registry() -> None:
    store = FakeStore()
    seed(store)
    reg = load_live_registry().model_copy(update={"page_refresh_seconds": 17})
    assert 'content="17"' in _render(store, registry=reg)
