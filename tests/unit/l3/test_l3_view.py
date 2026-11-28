"""L3 unit tests: minor units, money shapes, error-only client, missing snapshot, HEAD is 405."""

from __future__ import annotations

import datetime as dt
import os
import threading
import urllib.error
import urllib.request
from decimal import Decimal
from pathlib import Path

import pytest
from tests.fakes.live import FakeStore, FixedClock

from bayesian_marketing import core as C
from bayesian_marketing.core import registries
from bayesian_marketing.live import view
from bayesian_marketing.live.contracts import PollRecord, RefreshRecord
from bayesian_marketing.live.registry import load_live_registry
from bayesian_marketing.live.serve import make_server
from bayesian_marketing.live.store import SqliteStore

NOW = dt.datetime(2026, 11, 7, 18, 0, tzinfo=dt.UTC)
ROUNDING = {"money_decimals": 0, "unit_money_decimals": 2, "percent_decimals": 1}


def rec(status: str = "ok", minutes: int = 30, error: str | None = None) -> PollRecord:
    started = NOW - dt.timedelta(minutes=minutes)
    return PollRecord(
        poll_id=f"poll_{minutes:08d}",
        client_id="acme",
        platform="meta",
        account_id="act_1",
        started_at=started,
        finished_at=started + dt.timedelta(seconds=3),
        window=(started.date() - dt.timedelta(days=6), started.date()),
        status=status,  # type: ignore[arg-type]
        error=error,
        pull_id="pull_meta_1" if status == "ok" else None,
        n_rows=0,
        n_quarantined=0,
        empty_account=False,
        timezone="UTC",
        currency="USD",
        account={"name": "A", "spend_cap": "0", "amount_spent": "0", "account_status": "1"},
        recording_dir=None,
    )


def cfg() -> C.ClientConfig:
    return C.ClientConfig(
        client_id="acme", timezone="UTC", currency="USD", accounts={"meta": "act_1"}
    )


def page(store: FakeStore, data_dir: Path) -> str:
    return view.render(
        store, "acme", FixedClock(NOW), registry=load_live_registry(),
        phrasing=registries.load("phrasing"), data_dir=data_dir, config=cfg(),
    )  # fmt: skip


@pytest.mark.parametrize(
    "value,currency,expected",
    [("150000", "USD", Decimal("1500")), ("150000", "JPY", Decimal("150000")),
     ("150000", "BHD", Decimal("150")), ("150000", "krw", Decimal("150000"))],
)  # fmt: skip
def test_minor_units(value: str, currency: str, expected: Decimal) -> None:
    assert view.from_minor(value, currency) == expected


def test_money_shapes() -> None:
    usd = view.Fmt(rounding=ROUNDING, currency="USD")
    assert usd.money(Decimal("1500")) == "$1,500"
    assert usd.money(Decimal("0.5"), unit=True) == "$0.50"
    assert view.Fmt(rounding=ROUNDING, currency="EUR").money(Decimal("1500")) == "1,500 EUR"
    assert usd.percent(20, 1000) == "2.0% (20 / 1000)"


def test_error_only_client_shows_the_banner_and_no_sections(tmp_path: Path) -> None:
    store = FakeStore()
    r = rec("error", error="ConnectorError: nope")
    store.begin_poll(r)
    store.finish_poll(r, [])
    html = page(store, tmp_path)
    assert "ConnectorError: nope" in html
    assert "<h2" not in html
    assert registries.load("phrasing")["live"]["no_poll"] not in html


def test_missing_snapshot_reads_as_a_failed_engine_run(tmp_path: Path) -> None:
    store = FakeStore()
    r = rec()
    store.begin_poll(r)
    store.finish_poll(r, [])
    store.add_refresh(
        RefreshRecord(refresh_id="lv_1", poll_id=r.poll_id, client_id="acme", at=NOW,
                      status="ran", reason=None, run_id="run_missing")
    )  # fmt: skip
    before = os.environ.get("BAYES_DATA_DIR")
    html = page(store, tmp_path)
    assert os.environ.get("BAYES_DATA_DIR") == before
    failed = registries.load("phrasing")["live"]["engine_failed"].split("{")[0]
    assert failed in html


def test_head_is_405(tmp_path: Path) -> None:
    path = tmp_path / "live.sqlite"
    SqliteStore.open(path).close()
    srv = make_server(
        path, registry=load_live_registry(), clock=FixedClock(NOW), data_dir=tmp_path,
        config_root=tmp_path, port=0,
    )  # fmt: skip
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        port = srv.server_address[1]
        req = urllib.request.Request(f"http://127.0.0.1:{port}/", method="HEAD")
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=5)
        assert e.value.code == 405
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
            assert r.status == 200
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)
