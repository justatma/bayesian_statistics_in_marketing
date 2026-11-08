"""L3 view and server (live view spec v0.2 §5 L3 C1 to C8).

Rendering runs from ``FakeStore`` with ``FixedClock``. The server tests seed a SQLite file straight
from the L0 ``SCHEMA`` constant (so they do not depend on L2's store body), start ``make_server``
on port 0 in a thread and talk to it with urllib on 127.0.0.1. No network beyond loopback.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import html
import json
import os
import re
import sqlite3
import string
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
import yaml

from bayesian_marketing import core as C
from bayesian_marketing import pipeline
from bayesian_marketing.cli import _window as scenario_window
from bayesian_marketing.core import registries
from bayesian_marketing.floors.estimability import event_floor
from bayesian_marketing.live import view
from bayesian_marketing.live.config import load_client
from bayesian_marketing.live.contracts import LiveRow, PollRecord, RefreshRecord
from bayesian_marketing.live.registry import LiveRegistry, load_live_registry
from bayesian_marketing.live.serve import make_server
from bayesian_marketing.live.store import SCHEMA
from bayesian_marketing.reporting.render import finding_lines, not_knowable_lines
from bayesian_marketing.simulate.generate import MANIFEST_NAME, generate
from tests.fakes.live import FakeStore, FixedClock

pytestmark = pytest.mark.piece("L3")

REPO = Path(__file__).resolve().parents[2]
UTC = dt.UTC
NOW = dt.datetime(2026, 11, 7, 18, 0, tzinfo=UTC)  # FixedClock's default; 13:00 in New York
TZ = "America/New_York"
ACCOUNT_ID = "act_555"
ACCOUNT = {
    "name": "Acme Ads",
    "currency": "USD",
    "timezone_name": TZ,
    "account_status": "7",
    "spend_cap": "150000",
    "amount_spent": "12345",
}
H2_KEYS = ("h_account", "h_delivery", "h_conversions", "h_budget", "h_engine")
LEAD_EVENT = "offsite_conversion.fb_pixel_lead"
D = dt.date


# ------------------------------------------------------------------ registry strings


def phrasing() -> dict[str, Any]:
    return registries.load("phrasing")


def live_strings() -> dict[str, str]:
    return phrasing()["live"]


def frags(template: str) -> list[str]:
    """The literal parts of a template: what stays fixed around its slots."""
    return [lit.strip() for lit, *_ in string.Formatter().parse(template) if lit.strip()]


def assert_banner(page: str, key: str) -> None:
    for f in frags(live_strings()[key]):
        assert f in page, (key, f)


def no_banner(page: str, key: str) -> bool:
    return not all(f in page for f in frags(live_strings()[key]))


# ------------------------------------------------------------------ page parsing


class _Cells(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []  # rows with td cells
        self.header_cells: list[str] = []
        self._cur: list[str] | None = None
        self._cell: list[str] | None = None
        self._kind = ""
        self._has_td = False

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag == "tr":
            self._cur, self._has_td = [], False
        if tag in ("td", "th") and self._cur is not None:
            self._cell, self._kind = [], tag
            self._has_td = self._has_td or tag == "td"

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None and self._cur is not None:
            text = " ".join("".join(self._cell).split())
            self._cur.append(text)
            if tag == "th":
                self.header_cells.append(text)
            self._cell = None
        if tag == "tr" and self._cur is not None:
            if self._has_td:
                self.rows.append(self._cur)
            self._cur = None


def cells(fragment: str) -> _Cells:
    p = _Cells()
    p.feed(fragment)
    return p


def text_of(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


H2 = re.compile(r"<h2[^>]*>(.*?)</h2>", re.S | re.I)


def h2_titles(page: str) -> list[str]:
    return [text_of(m.group(1)) for m in H2.finditer(page)]


def section(page: str, key: str) -> str:
    """The raw HTML between the h2 whose text is live.<key> and the next h2 (or the end)."""
    title = live_strings()[key]
    ms = list(H2.finditer(page))
    for i, m in enumerate(ms):
        if text_of(m.group(1)) == title:
            end = ms[i + 1].start() if i + 1 < len(ms) else len(page)
            return page[m.end() : end]
    raise AssertionError(f"no h2 {title!r} in page; h2s are {h2_titles(page)}")


def header_of(page: str) -> str:
    m = H2.search(page)
    return page[: m.start()] if m else page


# ------------------------------------------------------------------ fixtures


def poll_rec(
    client: str = "acme",
    *,
    started: dt.datetime = NOW - dt.timedelta(minutes=30),
    status: str = "ok",
    error: str | None = None,
    tz: str = TZ,
    currency: str = "USD",
    account: dict[str, str] | None = None,
    n_rows: int = 0,
) -> PollRecord:
    ok = status == "ok"
    return PollRecord(
        poll_id="poll_" + f"{abs(hash((client, started.isoformat()))) % 10**8:08x}",
        client_id=client,
        platform="meta",
        account_id=ACCOUNT_ID,
        started_at=started,
        finished_at=started + dt.timedelta(seconds=5),
        window=(started.date() - dt.timedelta(days=6), started.date()),
        status=status,  # type: ignore[arg-type]
        error=error,
        pull_id="pull_meta_00000001" if ok else None,
        n_rows=n_rows,
        n_quarantined=0,
        empty_account=False,
        timezone=tz,
        currency=currency,
        account=dict(ACCOUNT if account is None else account),
        recording_dir=None,
    )


NAMES1 = {
    "account": "Acme Ads",
    "campaign": "Spring Promo",
    "ad_set": "Warm Audience",
    "ad": "Hero Video",
}
NAMES2 = {
    "account": "Acme Ads",
    "campaign": "Spring Promo",
    "ad_set": "Cold Audience",
    "ad": "Static Image",
}


def live_row(
    pid: str,
    ad: str,
    day: dt.date,
    impressions: int,
    clicks: int,
    spend: str,
    *,
    conversions: float | None = 0.0,
    revenue: str | None = None,
    names: dict[str, str] | None = None,
    objective: str | None = "OUTCOME_SALES",
    client: str = "acme",
    campaign: str = "camp_100",
    ad_set: str = "set_200",
) -> LiveRow:
    return LiveRow(
        poll_id=pid,
        client_id=client,
        platform="meta",
        entity_ids={"account": "555", "campaign": campaign, "ad_set": ad_set, "ad": ad},
        entity_names=names or {},
        objective=objective,
        date=day,
        impressions=impressions,
        clicks=clicks,
        spend=C.Money(amount=Decimal(spend), currency="USD"),
        conversions_reported=conversions,
        conversions_observed=None,
        revenue_reported=None
        if revenue is None
        else C.Money(amount=Decimal(revenue), currency="USD"),
        attribution_window="7d_click_1d_view",
    )


def full_rows(pid: str) -> list[LiveRow]:
    return [
        live_row(pid, "ad_300", D(2026, 11, 7), 1000, 20, "10.00", conversions=4.0, names=NAMES1),
        live_row(pid, "ad_300", D(2026, 11, 6), 500, 10, "6.00", conversions=1.0, names=NAMES1),
        live_row(pid, "ad_300", D(2026, 11, 2), 1000, 10, "8.00", conversions=0.0, names=NAMES1),
        # outside the seven account-local dates 11-01 .. 11-07: must not enter the 7-day sums
        live_row(pid, "ad_300", D(2026, 10, 31), 3, 7, "1.00", conversions=0.0, names=NAMES1),
        live_row(
            pid, "ad_400", D(2026, 11, 7), 2000, 30, "20.00", conversions=2.0, names=NAMES2,
            ad_set="set_201",
        ),
        live_row(
            pid, "ad_400", D(2026, 11, 6), 100, 1, "1.00", conversions=0.0, names=NAMES2,
            ad_set="set_201",
        ),
        # an ad with no names and nothing delivered
        live_row(
            pid, "ad_500", D(2026, 11, 7), 0, 0, "0.00", conversions=None, objective=None,
            campaign="camp_900", ad_set="set_900",
        ),
    ]  # fmt: skip


def seed(
    store: FakeStore,
    *,
    started: dt.datetime = NOW - dt.timedelta(minutes=30),
    rows: Any = None,
    **kw: Any,
) -> PollRecord:
    rec = poll_rec(started=started, **kw)
    store.begin_poll(rec)
    store.finish_poll(rec, [] if rec.status != "ok" else (rows or full_rows)(rec.poll_id))
    return rec


def config(**kw: Any) -> C.ClientConfig:
    base: dict[str, Any] = {
        "client_id": "acme",
        "timezone": TZ,
        "currency": "USD",
        "accounts": {"meta": ACCOUNT_ID},
    }
    base.update(kw)
    return C.ClientConfig(**base)


def render_page(
    store: FakeStore,
    *,
    clock: FixedClock | None = None,
    cfg: C.ClientConfig | None = None,
    data_dir: Path | None = None,
    client: str = "acme",
) -> str:
    return view.render(
        store,
        client,
        clock or FixedClock(NOW),
        registry=load_live_registry(),
        phrasing=phrasing(),
        data_dir=data_dir or Path(os.environ["BAYES_DATA_DIR"]),
        config=cfg or config(),
    )


def one_ad_rows(clicks: int, conversions: float | None = None, impressions: int = 1000) -> Any:
    def rows(pid: str) -> list[LiveRow]:
        return [
            live_row(pid, "ad_300", D(2026, 11, 7), impressions, clicks, "5.00",
                     conversions=conversions, names=NAMES1)
        ]  # fmt: skip

    return rows


def refresh_rec(
    poll: PollRecord, status: str, *, reason: str | None = None, run_id: str | None = None
) -> RefreshRecord:
    return RefreshRecord(
        refresh_id="lv_00000001",
        poll_id=poll.poll_id,
        client_id=poll.client_id,
        at=NOW - dt.timedelta(minutes=20),
        status=status,  # type: ignore[arg-type]
        reason=reason,
        run_id=run_id,
    )


@pytest.fixture
def engine_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[pipeline.RunSnapshot, Path]:
    """A real ctr run snapshot written under its own data dir (not the isolated BAYES_DATA_DIR)."""
    iso_store = os.environ["BAYES_DATA_DIR"]
    data_dir = tmp_path / "engine_data"
    monkeypatch.setenv("BAYES_DATA_DIR", str(data_dir))
    out = tmp_path / "scenario"
    generate(REPO / "data" / "scenarios" / "north_pier_day14.yaml", 1, out)
    m = C.DatasetManifest.load(out / MANIFEST_NAME)
    platform = pipeline.comparison_platform(m, sorted(m.entity_map))
    req = C.CompareRequest(
        metric="ctr",
        variants=sorted(m.entity_map),
        priors={},
        window=scenario_window(m, out, platform),
        horizon=C.Horizon(unit="impressions", amount=Decimal(1000)),
    )
    snap = pipeline.execute(m, req, manifest_dir=out).snapshot
    monkeypatch.setenv("BAYES_DATA_DIR", iso_store)
    assert (data_dir / "runs" / f"{snap.run_id}.json").exists()
    return snap, data_dir


# ------------------------------------------------------------------ C1 header, banners


def test_L3_h1_and_five_h2_strings() -> None:
    store = FakeStore()
    seed(store)
    page = render_page(store)
    live = live_strings()
    h1 = re.findall(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    assert [text_of(x) for x in h1] == [live["title"].format(client_id="acme")]  # L3 C1
    assert h2_titles(page) == [live[k] for k in H2_KEYS]  # L3 check 1: five h2 in section order
    assert '<meta http-equiv="refresh"' in page  # L3 intro
    reg = load_live_registry()
    assert f'content="{reg.page_refresh_seconds}"' in page  # L3 intro, [2.35]
    assert "<script" not in page.lower()  # L3 intro: no JavaScript


def test_L3_header_names_account_zone_currency_and_poll_times() -> None:
    store = FakeStore()
    seed(store, started=NOW - dt.timedelta(minutes=30))  # started 17:30Z, 12:30 in New York
    head = text_of(header_of(render_page(store)))
    for needle in ("meta", "Acme Ads", ACCOUNT_ID, TZ, "USD"):
        assert needle in head, needle  # L3 C1
    assert "17:30" in head  # L3 C1: last good poll, UTC
    assert "12:30" in head  # L3 C1: last good poll, account-local
    assert "18:30" in head  # L3 C1: next expected = started_at + interval_seconds (3600)


def test_L3_no_poll_says_so_and_nothing_below_the_header() -> None:
    page = render_page(FakeStore(), client="ghost", cfg=config(client_id="ghost"))
    assert live_strings()["no_poll"] in page  # L3 C1
    assert not H2.search(page)  # L3 C1: nothing below the header
    for key in ("banner_error", "banner_stale", "banner_interrupted"):
        assert no_banner(page, key), key


def test_L3_error_banner_with_the_message() -> None:
    store = FakeStore()
    seed(store, started=NOW - dt.timedelta(minutes=50))
    seed(
        store,
        started=NOW - dt.timedelta(minutes=20),
        status="error",
        error="ConnectorError: boom 4242",
    )
    page = render_page(store)
    assert_banner(page, "banner_error")  # L3 check 4
    assert "ConnectorError: boom 4242" in html.unescape(page)  # L3 check 4
    assert no_banner(page, "banner_stale")  # L3 C1: the last good poll is fresh
    assert no_banner(page, "banner_interrupted")


def test_L3_no_error_banner_when_latest_poll_is_ok() -> None:
    store = FakeStore()
    seed(store, started=NOW - dt.timedelta(minutes=50), status="error", error="ConnectorError: old")
    seed(store, started=NOW - dt.timedelta(minutes=20))
    page = render_page(store)
    assert no_banner(page, "banner_error")  # L3 C1: only the latest poll of any status counts
    assert "ConnectorError: old" not in page


def test_L3_stale_banner_at_7201_seconds_and_not_at_7199() -> None:
    limit = load_live_registry().stale_after_seconds
    assert limit == 7200
    store = FakeStore()
    seed(store, started=NOW - dt.timedelta(seconds=limit + 1))
    assert_banner(render_page(store), "banner_stale")  # L3 check 5: 7201 seconds
    store = FakeStore()
    seed(store, started=NOW - dt.timedelta(seconds=limit - 1))
    assert no_banner(render_page(store), "banner_stale")  # L3 check 5: 7199 seconds
    store = FakeStore()
    seed(store, started=NOW - dt.timedelta(seconds=limit))
    assert no_banner(render_page(store), "banner_stale")  # L3 C1: "more than"


def test_L3_interrupted_banner() -> None:
    store = FakeStore()
    seed(store, started=NOW - dt.timedelta(minutes=40))
    store.begin_poll(poll_rec(started=NOW - dt.timedelta(minutes=10)))  # no outcome
    page = render_page(store)
    assert_banner(page, "banner_interrupted")  # L3 check 6
    assert no_banner(page, "banner_error")
    assert no_banner(page, "banner_stale")


def test_L3_banners_in_order_error_interrupted_stale() -> None:
    limit = load_live_registry().stale_after_seconds
    store = FakeStore()
    seed(store, started=NOW - dt.timedelta(seconds=limit + 600))
    seed(store, started=NOW - dt.timedelta(minutes=20), status="error", error="ConnectorError: x")
    page = render_page(store)
    live = live_strings()
    first = lambda key: page.index(frags(live[key])[0])  # noqa: E731
    assert first("banner_error") < first("banner_stale")  # L3 C1: order
    store = FakeStore()
    seed(store, started=NOW - dt.timedelta(seconds=limit + 600))
    store.begin_poll(poll_rec(started=NOW - dt.timedelta(minutes=10)))
    page = render_page(store)
    assert first("banner_interrupted") < first("banner_stale")  # L3 C1: order


# ------------------------------------------------------------------ C2 account


def test_L3_account_cap_and_spend_from_minor_units() -> None:
    store = FakeStore()
    seed(store)
    acct = text_of(section(render_page(store), "h_account"))
    assert "$1,500" in acct  # L3 check 9: cap "150000" minor units of USD
    assert "$123" in acct  # L3 C2: amount_spent "12345" is $123.45, money rounds to 0 decimals
    reg = load_live_registry()
    assert reg.account_status["7"] in acct  # L3 C2: status text from live.yaml
    assert live_strings()["no_limit"] not in acct


@pytest.mark.parametrize("cap", ["0", None])
def test_L3_unlimited_account_shows_no_limit(cap: str | None) -> None:
    account = {k: v for k, v in ACCOUNT.items() if k != "spend_cap"}
    if cap is not None:
        account["spend_cap"] = cap
    store = FakeStore()
    seed(store, account=account)
    acct = text_of(section(render_page(store), "h_account"))
    assert live_strings()["no_limit"] in acct  # L3 check 8 / C2: "0" or absent


def test_L3_zero_exponent_currency_is_not_divided() -> None:
    account = {**ACCOUNT, "currency": "JPY", "spend_cap": "150000", "amount_spent": "12345"}
    store = FakeStore()
    seed(store, currency="JPY", account=account)
    acct = text_of(section(render_page(store), "h_account"))
    assert "150,000" in acct  # L3 C2: JPY has exponent 0
    assert "1,500" not in acct


def test_L3_unknown_account_status_code_shows_the_code() -> None:
    store = FakeStore()
    seed(store, account={**ACCOUNT, "account_status": "999"})
    assert "999" in text_of(section(render_page(store), "h_account"))  # L3 C2


# ------------------------------------------------------------------ C3 delivery


def test_L3_delivery_one_row_per_ad_with_names_and_ids() -> None:
    store = FakeStore()
    seed(store)
    sec = section(render_page(store), "h_delivery")
    rows = cells(sec).rows
    assert len(rows) == 3  # L3 C3: one row per ad
    named = text_of(sec)
    for needle in ("Spring Promo", "camp_100", "Warm Audience", "set_200", "Hero Video", "ad_300"):
        assert needle in named, needle  # L3 C3: name and id
    for needle in ("Cold Audience", "set_201", "Static Image", "ad_400"):
        assert needle in named, needle
    row500 = " ".join(next(r for r in rows if any("ad_500" in c for c in r)))
    assert "camp_900" in row500 and "set_900" in row500  # L3 C3: a missing name shows the id only
    live = live_strings()
    for key in ("period_today", "period_yesterday", "period_7d"):
        assert live[key] in named, key  # L3 C3, B5: column groups


def test_L3_ctr_cell_shows_percent_with_counts() -> None:
    store = FakeStore()
    seed(store)
    rows = cells(section(render_page(store), "h_delivery")).rows
    row = next(r for r in rows if any("ad_300" in c for c in r))
    ctr = [c for c in row if "%" in c]
    assert ctr[0] == "2.0% (20 / 1000)"  # L3 check 3: today
    assert ctr[1] == "2.0% (10 / 500)"  # L3 C3: yesterday
    assert ctr[2].startswith("1.6% (40 /")  # L3 C3: last 7 days, the 10-31 row left out


def test_L3_zero_denominator_shows_none_yet() -> None:
    store = FakeStore()
    seed(store)
    rows = cells(section(render_page(store), "h_delivery")).rows
    row = next(r for r in rows if any("ad_500" in c for c in r))
    none_yet = live_strings()["none_yet"]
    assert none_yet in row  # L3 C3: CTR and CPC over zero
    assert not any("%" in c for c in row)
    assert not any("nan" in c.lower() or "inf" in c.lower() for c in row)


def test_L3_periods_use_account_local_dates() -> None:
    clock = FixedClock(dt.datetime(2026, 11, 7, 3, 0, tzinfo=UTC))  # 22:00 on 11-06 in New York
    store = FakeStore()
    started = dt.datetime(2026, 11, 7, 2, 30, tzinfo=UTC)

    def rows(pid: str) -> list[LiveRow]:
        return [
            live_row(pid, "ad_300", D(2026, 11, 6), 1000, 20, "10.00", names=NAMES1),
            live_row(pid, "ad_300", D(2026, 11, 5), 400, 10, "4.00", names=NAMES1),
            live_row(pid, "ad_300", D(2026, 11, 4), 600, 10, "6.00", names=NAMES1),
        ]

    seed(store, started=started, rows=rows)
    sec = section(render_page(store, clock=clock), "h_delivery")
    row = next(r for r in cells(sec).rows if any("ad_300" in c for c in r))
    ctr = [c for c in row if "%" in c]
    assert ctr[0] == "2.0% (20 / 1000)"  # L3 C3 [2.16]: today is 11-06 where the account is
    assert ctr[1] == "2.5% (10 / 400)"  # L3 C3: yesterday is 11-05
    assert ctr[2].startswith("2.0% (40 /")  # L3 C3: seven days back from 11-06


def test_L3_evidence_text_once_before_each_table_and_platform_count() -> None:
    store = FakeStore()
    seed(store)
    page = render_page(store)
    ev = phrasing()["evidence_plain"]
    live = live_strings()
    assert page.count(ev["delivery"]) == 1  # L3 check 2
    assert page.count(ev["platform_attributed"]) == 1  # L3 check 2
    deliv = section(page, "h_delivery")
    assert deliv.count(ev["delivery"]) == 1
    assert deliv.index(ev["delivery"]) < deliv.index("<table")  # L3 check 2: before the table
    assert deliv.index(ev["delivery"]) < deliv.index(live["platform_count"])  # L3 C3: then D42
    conv = section(page, "h_conversions")
    assert conv.count(ev["platform_attributed"]) == 1
    assert conv.index(ev["platform_attributed"]) < conv.index("<table")  # L3 check 2
    assert conv.index(ev["platform_attributed"]) < conv.index(live["platform_count"])  # L3 C4


def test_L3_objective_per_campaign_or_missing() -> None:
    store = FakeStore()
    seed(store)
    sec = text_of(section(render_page(store), "h_delivery"))
    assert "OUTCOME_SALES" in sec  # L3 C3
    assert live_strings()["objective_missing"] in sec  # L3 C3: ad_500's campaign has none


# ------------------------------------------------------------------ C4 conversions


def test_L3_conversions_default_event_word_attribution_and_not_reported() -> None:
    store = FakeStore()
    seed(store)
    live = live_strings()
    sec = section(render_page(store), "h_conversions")
    text = text_of(sec)
    assert live["purchases"] in text  # L3 C4, B5: no conversion_event configured
    assert "7d_click_1d_view" in text  # L3 C4: the rows' attribution window
    assert live["not_reported"] in text  # L3 C4: ad_500's count is None
    assert live["none_yet"] in text  # L3 C4: cost per conversion with nothing to divide
    assert len(cells(sec).rows) == 3  # L3 C4: same rows
    assert live["not_shown"] in text  # L3 check 7 / C4: always
    assert live["lead_sentence"] not in text  # L3 C4: only for a lead event


def test_L3_lead_client_has_lead_sentence_provisional_and_no_revenue() -> None:
    store = FakeStore()

    def rows(pid: str) -> list[LiveRow]:
        return [
            live_row(pid, "ad_300", D(2026, 11, 7), 1000, 20, "10.00", conversions=3.0,
                     names=NAMES1),
            live_row(pid, "ad_400", D(2026, 11, 7), 2000, 30, "20.00", conversions=1.0,
                     names=NAMES2),
        ]  # fmt: skip

    seed(store, rows=rows)
    cfg = config(conversion_event={"meta": LEAD_EVENT})
    page = render_page(store, cfg=cfg)
    live = live_strings()
    conv = text_of(section(page, "h_conversions"))
    assert live["lead_sentence"] in conv  # L3 check 7, C4
    assert live["provisional"] in conv  # L3 check 7, §3.2: unconfirmed event is marked
    assert LEAD_EVENT in conv  # L3 C4: the event name
    assert live["not_shown"] in conv  # L3 check 7
    assert "ROAS" not in page and "roas" not in page.lower()  # L3 check 7: no ROAS
    parsed = cells(page)
    assert not any(
        "revenue" in c.lower() for c in parsed.header_cells
    )  # L3 check 7: no revenue cell
    assert not any("revenue" in c.lower() for r in parsed.rows for c in r)
    # the same client once the first signup confirms the label
    confirmed = config(
        conversion_event={"meta": LEAD_EVENT}, conversion_event_confirmed={"meta": True}
    )
    conv2 = text_of(section(render_page(store, cfg=confirmed), "h_conversions"))
    assert live["provisional"] not in conv2  # L3 C4
    assert live["lead_sentence"] in conv2


def test_L3_unit_costs_at_two_decimals() -> None:
    store = FakeStore()
    seed(store)
    page = render_page(store)
    drow = next(r for r in cells(section(page, "h_delivery")).rows if any("ad_300" in c for c in r))
    assert "$0.50" in drow  # L3 C3, B8: CPC today 10.00 / 20 at unit_money_decimals 2
    crow = next(
        r for r in cells(section(page, "h_conversions")).rows if any("ad_300" in c for c in r)
    )
    assert "$2.50" in crow  # L3 C4, B8: cost per conversion today 10.00 / 4


def test_L3_event_not_seen_when_configured_event_sums_to_zero() -> None:
    live = live_strings()
    cfg = config(conversion_event={"meta": LEAD_EVENT})
    store = FakeStore()
    seed(store, rows=one_ad_rows(clicks=20, conversions=0.0))
    conv = text_of(section(render_page(store, cfg=cfg), "h_conversions"))
    assert live["event_not_seen"].format(event=LEAD_EVENT) in conv  # L3 C4, B8
    seen = FakeStore()
    seed(seen, rows=one_ad_rows(clicks=20, conversions=2.0))
    conv2 = text_of(section(render_page(seen, cfg=cfg), "h_conversions"))
    assert live["event_not_seen"].format(event=LEAD_EVENT) not in conv2  # L3 C4, B8


# ------------------------------------------------------------------ C5 budget


def budget_text(clicks: int, conversions: float | None = None) -> str:
    store = FakeStore()
    seed(store, rows=one_ad_rows(clicks, conversions))
    return text_of(section(render_page(store), "h_budget"))


@pytest.mark.parametrize(
    "clicks,word",
    [(16, "below_floor"), (17, "marginal"), (67, "marginal"), (68, "estimable")],
)
def test_L3_budget_words_at_the_floors(clicks: int, word: str) -> None:
    assert event_floor("marginal") == 17 and event_floor("estimable") == 68
    labels = phrasing()["status_labels"]
    text = budget_text(clicks)
    assert str(event_floor("marginal")) in text and str(event_floor("estimable")) in text  # L3 C5
    assert labels[word] in text, (clicks, word)  # L3 check 10
    for other in set(labels) - {word}:
        assert labels[other] not in text, (clicks, other)  # L3 check 10


def test_L3_budget_conversions_have_their_own_word_and_not_reported() -> None:
    labels = phrasing()["status_labels"]
    text = budget_text(5, conversions=20.0)  # clicks below the floor, conversions marginal
    assert labels["below_floor"] in text and labels["marginal"] in text  # L3 C5
    text = budget_text(5, conversions=None)
    assert live_strings()["not_reported"] in text  # L3 C5: a None count


# ------------------------------------------------------------------ C6 engine


def test_L3_engine_none_yet() -> None:
    store = FakeStore()
    seed(store)
    assert live_strings()["no_engine"] in text_of(
        section(render_page(store), "h_engine")
    )  # L3 check 11


@pytest.mark.parametrize(
    "status,key",
    [("skipped", "engine_skipped"), ("failed", "engine_failed")],
)
def test_L3_engine_skipped_and_failed_sentences(status: str, key: str) -> None:
    store = FakeStore()
    poll = seed(store)
    store.add_refresh(refresh_rec(poll, status, reason="one ad, nothing to compare"))
    text = text_of(section(render_page(store), "h_engine"))
    expected = live_strings()[key].format(reason="one ad, nothing to compare")
    assert expected in text  # L3 check 11 / C6
    assert live_strings()["no_engine"] not in text


def test_L3_engine_renders_finding_lines_from_the_snapshot(
    engine_run: tuple[pipeline.RunSnapshot, Path],
) -> None:
    snap, data_dir = engine_run
    store = FakeStore()
    poll = seed(store)
    store.add_refresh(refresh_rec(poll, "ran", run_id=snap.run_id))
    before = os.environ["BAYES_DATA_DIR"]
    page = render_page(store, data_dir=data_dir)
    assert os.environ["BAYES_DATA_DIR"] == before  # L3 C6: the context restores the variable
    text = text_of(section(page, "h_engine"))
    phr = phrasing()
    shown = 0
    for q in snap.quantities:
        if q.feasibility.status == "below_floor":
            nk = not_knowable_lines(q, phr)["text"]
            if nk:
                assert nk in text, nk  # L3 C6: not_knowable_lines for each below-floor quantity
            continue
        lines = finding_lines(q, phr)
        for key in ("label", "estimate", "low", "high", "status_label"):
            assert str(lines[key]) in text, (key, lines[key])  # L3 check 11: finding_lines output
        shown += 1
    assert shown > 0
    assert live_strings()["no_engine"] not in text


def test_L3_engine_without_diagnostics_says_so(
    engine_run: tuple[pipeline.RunSnapshot, Path], tmp_path: Path
) -> None:
    snap, _ = engine_run
    bare = snap.model_copy(update={"diagnostics": []})
    data_dir = tmp_path / "bare_data"
    (data_dir / "runs").mkdir(parents=True)
    (data_dir / "runs" / f"{snap.run_id}.json").write_text(bare.model_dump_json())
    store = FakeStore()
    poll = seed(store)
    store.add_refresh(refresh_rec(poll, "ran", run_id=snap.run_id))
    text = text_of(section(render_page(store, data_dir=data_dir), "h_engine"))
    assert live_strings()["no_diagnostics"] in text  # L3 C6 [1.2]


# ------------------------------------------------------------------ C7 honesty


def test_L3_every_percentage_shows_its_counts() -> None:
    store = FakeStore()
    seed(store)
    text = text_of(render_page(store))
    pcts = list(re.finditer(r"\d+(?:\.\d+)?%", text))
    assert pcts
    for m in pcts:
        tail = text[m.end() : m.end() + 40]
        assert re.match(r"\s*\(\s*\d[\d,]*\s*/\s*\d[\d,]*\s*\)", tail), text[
            m.start() : m.end() + 40
        ]  # L3 C7


def test_L3_no_banned_phrase_in_page_or_templates(
    engine_run: tuple[pipeline.RunSnapshot, Path],
) -> None:
    snap, data_dir = engine_run
    store = FakeStore()
    seed(store, started=NOW - dt.timedelta(minutes=50))
    poll = seed(
        store, started=NOW - dt.timedelta(minutes=20), status="error", error="ConnectorError: x"
    )
    ok = store.latest_poll("acme")
    assert ok is not None
    store.add_refresh(refresh_rec(ok, "ran", run_id=snap.run_id))
    page = render_page(
        store, data_dir=data_dir, cfg=config(conversion_event={"meta": LEAD_EVENT})
    ).lower()
    assert poll.status == "error"
    ph = phrasing()
    banned = [
        *ph["causal_lexicon"]["negation_frames"],
        *ph["comparative_lexicon"]["generic_phrases"],
    ]
    assert banned
    for phrase in banned:
        assert phrase.lower() not in page, phrase  # L3 check 12 / C7: rendered HTML
    tdir = REPO / "src" / "bayesian_marketing" / "live" / "templates"
    templates = sorted(tdir.glob("*.html"))
    assert {t.name for t in templates} >= {"live.html", "index.html"}
    for t in templates:
        body = t.read_text().lower()
        for phrase in banned:
            assert phrase.lower() not in body, (t.name, phrase)  # L3 check 12 / C7: templates


def test_L3_footer_carries_the_internal_watermark() -> None:
    store = FakeStore()
    seed(store)
    page = render_page(store)
    mark = phrasing()["watermark"]["internal"]
    assert mark in html.unescape(page)  # L3 C7 [2.35]
    assert html.unescape(page).rindex(mark) > html.unescape(page).rindex("</table>")  # footer


def test_L3_page_strings_are_not_literal_template_leftovers() -> None:
    store = FakeStore()
    seed(store)
    page = render_page(store)
    assert "{" not in text_of(page) and "}" not in text_of(page)  # L3 C7: every slot filled
    assert "None" not in text_of(page)


def test_L3_index_lists_each_client_with_link_and_last_good_poll() -> None:
    store = FakeStore()
    seed(store, started=NOW - dt.timedelta(minutes=30))
    other = poll_rec("beta", started=NOW - dt.timedelta(hours=1))
    store.begin_poll(other)
    store.finish_poll(other, [])
    page = view.render_index(store, FixedClock(NOW), registry=load_live_registry())
    for client in ("acme", "beta"):
        assert client in page  # L3 C8
        assert f"/client/{client}" in page  # L3 C8: a link
    assert "17:30" in text_of(page)  # L3 C8: last good poll, UTC
    assert page.index("acme") < page.index("beta")  # L3 C8: store.clients() order


# ------------------------------------------------------------------ C8 server


def seed_sqlite(path: Path) -> None:
    """Two clients written straight into the L0 schema: acme has a good poll, idle only an error."""
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    started = (NOW - dt.timedelta(minutes=30)).isoformat()
    polls = "INSERT INTO polls VALUES (?,?,'meta',?,?,'2026-11-01','2026-11-07',NULL)"
    con.execute(polls, ("poll_aaaa0001", "acme", ACCOUNT_ID, started))
    con.execute(polls, ("poll_bbbb0002", "idle", ACCOUNT_ID, started))
    ok = "INSERT INTO poll_outcomes VALUES (?,?,'ok',NULL,'pull_meta_00000001',1,0,0,?,?,?)"
    con.execute(ok, ("poll_aaaa0001", started, TZ, "USD", json.dumps(ACCOUNT)))
    err = (
        "INSERT INTO poll_outcomes "
        "VALUES (?,?,'error','ConnectorError: x',NULL,0,0,0,NULL,NULL,'{}')"
    )
    con.execute(err, ("poll_bbbb0002", started))
    ids = {"account": "555", "campaign": "camp_100", "ad_set": "set_200", "ad": "ad_300"}
    row = (
        "INSERT INTO rows VALUES ('poll_aaaa0001','acme','meta','ad_300','2026-11-07',?,?,NULL,"
        "1000,20,'10.00','USD',4.0,NULL,NULL,NULL,'7d_click_1d_view')"
    )
    con.execute(row, (json.dumps(ids), json.dumps(NAMES1)))
    con.commit()
    con.close()


class Live:
    def __init__(self, base: str) -> None:
        self.base = base

    def get(self, path: str, method: str = "GET") -> tuple[int, dict[str, str], bytes]:
        req = urllib.request.Request(
            self.base + path, method=method, data=b"" if method == "POST" else None
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()


@contextlib.contextmanager
def serving(tmp_path: Path) -> Iterator[Live]:
    store_path = tmp_path / "live.sqlite"
    seed_sqlite(store_path)
    cfg_root = tmp_path / "configs"
    cfg_root.mkdir()
    (cfg_root / "acme.yaml").write_text(yaml.safe_dump(config().model_dump(mode="json")))
    (cfg_root / "idle.yaml").write_text(
        yaml.safe_dump(config(client_id="idle").model_dump(mode="json"))
    )
    assert load_client("acme", cfg_root).client_id == "acme"
    reg: LiveRegistry = load_live_registry()
    srv = make_server(
        store_path,
        registry=reg,
        clock=FixedClock(NOW),
        data_dir=Path(os.environ["BAYES_DATA_DIR"]),
        config_root=cfg_root,
        port=0,
    )
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        host, port = srv.server_address[:2]
        assert host == "127.0.0.1"  # L3 C8: loopback only
        yield Live(f"http://127.0.0.1:{port}")
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)


def test_L3_server_health_is_json(tmp_path: Path) -> None:
    with serving(tmp_path) as server:
        _server_health_is_json(server)


def _server_health_is_json(server: Live) -> None:
    status, headers, body = server.get("/health")
    assert status == 200
    assert headers["Content-Type"].split(";")[0] == "application/json"  # L3 check 13
    data = json.loads(body)
    assert data["ok"] is True  # L3 C8
    assert set(data["last_poll"]) == {"acme", "idle"}  # L3 C8: every client in the store
    assert dt.datetime.fromisoformat(data["last_poll"]["acme"]).date() == dt.date(2026, 11, 7)
    assert data["last_poll"]["idle"] is None  # L3 C8: no good poll yet


def test_L3_server_client_page_and_index(tmp_path: Path) -> None:
    with serving(tmp_path) as server:
        _server_client_page_and_index(server)


def _server_client_page_and_index(server: Live) -> None:
    status, headers, body = server.get("/client/acme")
    assert status == 200
    assert headers["Content-Type"] == "text/html; charset=utf-8"  # L3 C8
    page = body.decode()
    assert live_strings()["title"].format(client_id="acme") in page
    assert h2_titles(page) == [live_strings()[k] for k in H2_KEYS]
    status, headers, body = server.get("/")
    assert status == 200 and headers["Content-Type"] == "text/html; charset=utf-8"
    assert "/client/acme" in body.decode() and "/client/idle" in body.decode()  # L3 C8 index


def test_L3_server_unknown_client_and_path_are_404(tmp_path: Path) -> None:
    with serving(tmp_path) as server:
        _server_unknown_client_and_path_are_404(server)


def _server_unknown_client_and_path_are_404(server: Live) -> None:
    assert server.get("/client/unknown")[0] == 404  # L3 check 13
    assert server.get("/anything")[0] == 404  # L3 check 13
    assert server.get("/client/acme/extra")[0] == 404  # L3 C8: any other path


def test_L3_server_other_methods_are_405(tmp_path: Path) -> None:
    with serving(tmp_path) as server:
        _server_other_methods_are_405(server)


def _server_other_methods_are_405(server: Live) -> None:
    assert server.get("/", "POST")[0] == 405  # L3 check 13
    assert server.get("/health", "DELETE")[0] == 405  # L3 C8: any other method
    assert server.get("/client/acme", "PUT")[0] == 405


def test_L3_server_ignores_query_strings(tmp_path: Path) -> None:
    with serving(tmp_path) as server:
        _server_ignores_query_strings(server)


def _server_ignores_query_strings(server: Live) -> None:
    assert server.get("/client/acme?x=1")[0] == 200  # L3 check 13
    assert server.get("/health?x=1")[0] == 200  # L3 C8
    assert server.get("/?x=1")[0] == 200


def test_L3_server_logs_one_line_per_request(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with serving(tmp_path) as server:
        server.get("/health")
        server.get("/nowhere")
        deadline = time.time() + 5
        out = ""
        while time.time() < deadline:
            out += capsys.readouterr().out
            if re.search(r"^GET /nowhere 404 \d+(\.\d+)?ms$", out, re.M):
                break
            time.sleep(0.05)
    assert re.search(r"^GET /health 200 \d+(\.\d+)?ms$", out, re.M), out  # L3 C8
    assert re.search(r"^GET /nowhere 404 \d+(\.\d+)?ms$", out, re.M), out  # L3 C8
