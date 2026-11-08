"""The internal page, rendered from the store on each request (spec v0.2 §5 L3 C1-C7). Piece L3.

Every sentence on the page comes from ``phrasing.yaml`` (the ``live`` block, ``status_labels``,
``evidence_plain``, ``watermark``) or from the reporting helpers. Table and header labels come
from ``live_columns`` (B13, B15), the engine and diagnostics headings included.
"""

from __future__ import annotations

import contextlib
import os
import threading
import urllib.parse
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import jinja2

from bayesian_marketing import pipeline
from bayesian_marketing.core import registries
from bayesian_marketing.core.records import ClientConfig
from bayesian_marketing.floors.estimability import event_floor
from bayesian_marketing.live.contracts import Clock, LiveRow, PollRecord, Store
from bayesian_marketing.live.registry import LiveRegistry
from bayesian_marketing.reporting.render import finding_lines, not_knowable_lines

TEMPLATES = Path(__file__).resolve().parent / "templates"
DATA_ENV = "BAYES_DATA_DIR"
LEVELS = ("campaign", "ad_set", "ad")
# The server is threaded and BAYES_DATA_DIR is process-wide: one lock spans set, load, restore (F4).
_ENV_LOCK = threading.Lock()

# ISO 4217 minor-unit exponents (facts pack L3): 2 unless listed here.
_EXPONENT_0 = frozenset(
    [
        "BIF",
        "CLP",
        "DJF",
        "GNF",
        "ISK",
        "JPY",
        "KMF",
        "KRW",
        "PYG",
        "RWF",
        "UGX",
        "UYI",
        "VND",
        "VUV",
        "XAF",
        "XOF",
        "XPF",
    ]
)
_EXPONENT_3 = frozenset(["BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"])
# Currencies printed with a leading symbol; the rest print as "1,500 EUR" (fmt_money's shape).
_SYMBOL = {"USD": "$"}

# Engine-section headings: the keys of ``finding_lines`` and of ``DiagnosticsReport``.
_FINDING_KEYS = ("entity", "label", "estimate", "low", "high", "status_label", "evidence", "route")
_DIAG_KEYS = ("rhat_max", "ess_bulk_min", "ess_tail_min", "n_divergences")
_SAMPLER_ROUTE = {"numpyro_nuts": "nuts", "conjugate": "conjugate"}


# ------------------------------------------------------------------ formatting


def minor_exponent(currency: str) -> int:
    c = currency.upper()
    if c in _EXPONENT_0:
        return 0
    if c in _EXPONENT_3:
        return 3
    return 2


def from_minor(value: str, currency: str) -> Decimal:
    return Decimal(value).scaleb(-minor_exponent(currency))


@dataclass(frozen=True)
class Fmt:
    rounding: dict[str, int]
    currency: str

    def money(self, amount: Decimal | float, *, unit: bool = False) -> str:
        places = self.rounding["unit_money_decimals" if unit else "money_decimals"]
        text = f"{Decimal(str(amount)):,.{places}f}"
        symbol = _SYMBOL.get(self.currency.upper())
        if symbol is None:
            return f"{text} {self.currency}"
        if text.startswith("-"):
            return f"-{symbol}{text[1:]}"
        return f"{symbol}{text}"

    def percent(self, num: int, den: int) -> str:
        pct = f"{num / den * 100:.{self.rounding['percent_decimals']}f}%"
        return f"{pct} ({num} / {den})"


def plain_count(x: float) -> str:
    """Counts as plain digits (B8). A fractional count (Meta may report one) prints in full, the
    shortest text that reads back as the same float, so the number shown is the number compared
    against the floors (review F3): 16.96 never prints as 17."""
    x = float(x)
    return str(int(x)) if x.is_integer() else repr(x)


def fmt_utc(t: datetime) -> str:
    return t.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M")


def fmt_local(t: datetime, tz: str) -> str:
    return t.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M")


# ------------------------------------------------------------------ templates


@cache
def _env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES)),
        autoescape=True,
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


# ------------------------------------------------------------------ periods and sums


@dataclass
class Sums:
    impressions: int = 0
    clicks: int = 0
    spend: Decimal = Decimal(0)
    conversions: float = 0.0
    n_rows: int = 0
    any_reported: bool = False

    @property
    def not_reported(self) -> bool:
        """The period has rows and none of them carries a conversion count (review F1, F2)."""
        return self.n_rows > 0 and not self.any_reported

    def add(self, r: LiveRow) -> None:
        self.n_rows += 1
        self.impressions += r.impressions
        self.clicks += r.clicks
        self.spend += r.spend.amount
        if r.conversions_reported is not None:
            self.conversions += r.conversions_reported
            self.any_reported = True


@dataclass
class Ad:
    ids: dict[str, str]
    names: dict[str, str]
    objective: str | None
    windows: set[str] = field(default_factory=set)
    periods: dict[str, Sums] = field(default_factory=dict)

    def entity_cells(self) -> list[dict[str, str]]:
        out = []
        for level in LEVELS:
            ident = self.ids.get(level, "")
            name = self.names.get(level, "")
            out.append({"name": name if name and name != ident else "", "id": ident})
        return out


def _periods(today: date) -> dict[str, tuple[date, date]]:
    return {
        "period_today": (today, today),
        "period_yesterday": (today - timedelta(days=1), today - timedelta(days=1)),
        "period_7d": (today - timedelta(days=6), today),
    }


def _ads(rows: Iterable[LiveRow], periods: dict[str, tuple[date, date]]) -> list[Ad]:
    ads: dict[str, Ad] = {}
    latest: dict[str, date] = {}
    for r in sorted(rows, key=lambda r: r.date):
        key = r.entity_ids.get("ad", "")
        ad = ads.get(key)
        if ad is None:
            ad = ads[key] = Ad(ids={}, names={}, objective=None)
            ad.periods = {p: Sums() for p in periods}
        if key not in latest or r.date >= latest[key]:
            latest[key] = r.date
            ad.ids = dict(r.entity_ids)
            ad.names = {**ad.names, **{k: v for k, v in r.entity_names.items() if v}}
            if r.objective:
                ad.objective = r.objective
        elif ad.objective is None and r.objective:
            ad.objective = r.objective
        ad.windows.add(r.attribution_window)
        for p, (lo, hi) in periods.items():
            if lo <= r.date <= hi:
                ad.periods[p].add(r)
    return sorted(ads.values(), key=lambda a: tuple(a.ids.get(k, "") for k in LEVELS))


# ------------------------------------------------------------------ sections


def _banners(
    store: Store, client_id: str, last_ok: PollRecord | None, now: datetime, reg: LiveRegistry,
    live: dict[str, str],
) -> list[str]:  # fmt: skip
    out: list[str] = []
    latest = store.latest_poll(client_id, ok_only=False)
    if latest is not None and latest.status == "error":
        at = latest.finished_at or latest.started_at
        out.append(live["banner_error"].format(at=fmt_utc(at), error=latest.error or ""))
    if latest is not None and latest.status == "interrupted":
        out.append(live["banner_interrupted"].format(at=fmt_utc(latest.started_at)))
    if last_ok is not None:
        age = (now - last_ok.started_at).total_seconds()
        if age > reg.stale_after_seconds:
            hours = int(age // 3600)
            out.append(live["banner_stale"].format(at=fmt_utc(last_ok.started_at), hours=hours))
    return out


def _account(poll: PollRecord, fmt: Fmt, reg: LiveRegistry, live: dict[str, str]) -> list:
    acct = poll.account
    cur = fmt.currency
    rows: list[tuple[str, str]] = []
    spent = acct.get("amount_spent")
    if spent not in (None, ""):
        rows.append(("amount_spent", fmt.money(from_minor(spent, cur))))
    cap = acct.get("spend_cap")
    if cap in (None, "") or Decimal(cap) == 0:
        rows.append(("spend_cap", live["no_limit"]))
    else:
        rows.append(("spend_cap", fmt.money(from_minor(cap, cur))))
    code = acct.get("account_status")
    if code not in (None, ""):
        rows.append(("account_status", reg.account_status.get(str(code), str(code))))
    return rows


def _delivery(ads: list[Ad], fmt: Fmt, live: dict[str, str]) -> list[dict[str, Any]]:
    out = []
    for ad in ads:
        groups = []
        for s in ad.periods.values():
            groups.append(
                [
                    str(s.impressions),
                    str(s.clicks),
                    fmt.money(s.spend),
                    fmt.percent(s.clicks, s.impressions) if s.impressions else live["none_yet"],
                    fmt.money(s.spend / s.clicks, unit=True) if s.clicks else live["none_yet"],
                ]
            )
        out.append(
            {
                "entities": ad.entity_cells(),
                "objective": ad.objective or live["objective_missing"],
                "groups": groups,
            }
        )
    return out


def _conversions(ads: list[Ad], fmt: Fmt, live: dict[str, str]) -> list[dict[str, Any]]:
    out = []
    for ad in ads:
        groups = []
        for s in ad.periods.values():
            if s.not_reported:
                groups.append([live["not_reported"], live["not_reported"]])
            elif s.conversions == 0:
                groups.append([plain_count(0), live["none_yet"]])
            else:
                per = s.spend / Decimal(str(s.conversions))
                groups.append([plain_count(s.conversions), fmt.money(per, unit=True)])
        out.append(
            {
                "entities": ad.entity_cells(),
                "groups": groups,
                "window": ", ".join(sorted(ad.windows)),
            }
        )
    return out


def budget_word(n: float, labels: dict[str, str]) -> str:
    if n >= event_floor("estimable"):
        return labels["estimable"]
    if n >= event_floor("marginal"):
        return labels["marginal"]
    return labels["below_floor"]


def _budget(
    ads: list[Ad], live: dict[str, str], labels: dict[str, str]
) -> tuple[str, list[dict[str, Any]]]:
    floors = f"{event_floor('marginal')} / {event_floor('estimable')}"
    out = []
    for ad in ads:
        s = ad.periods["period_7d"]
        if s.not_reported:
            conv = [live["not_reported"], floors, ""]
        else:
            conv = [plain_count(s.conversions), floors, budget_word(s.conversions, labels)]
        out.append(
            {
                "entities": ad.entity_cells(),
                "clicks": [str(s.clicks), floors, budget_word(s.clicks, labels)],
                "conversions": conv,
            }
        )
    return floors, out


@contextlib.contextmanager
def data_dir_env(data_dir: Path) -> Iterator[None]:
    before = os.environ.get(DATA_ENV)
    os.environ[DATA_ENV] = str(data_dir)
    try:
        yield
    finally:
        if before is None:
            os.environ.pop(DATA_ENV, None)
        else:
            os.environ[DATA_ENV] = before


def _engine(
    store: Store, client_id: str, phrasing: dict[str, Any], data_dir: Path, live: dict[str, str]
) -> dict[str, Any]:
    rec = store.latest_refresh(client_id)
    engine: dict[str, Any] = {"sentence": None, "findings": [], "not_knowable": [], "diag": None}
    if rec is None:
        engine["sentence"] = live["no_engine"]
        return engine
    if rec.status == "skipped":
        engine["sentence"] = live["engine_skipped"].format(reason=rec.reason or "")
        return engine
    if rec.status == "failed" or rec.run_id is None:
        engine["sentence"] = live["engine_failed"].format(reason=rec.reason or "")
        return engine
    try:
        with _ENV_LOCK, data_dir_env(data_dir):
            snap = pipeline.load_snapshot(rec.run_id)
    except (KeyError, ValueError, OSError) as e:
        engine["sentence"] = live["engine_failed"].format(reason=str(e).strip("'\""))
        return engine
    for q in snap.quantities:
        if q.feasibility.status == "below_floor":
            nk = not_knowable_lines(q, phrasing)
            if nk["text"]:
                engine["not_knowable"].append(nk)
            continue
        lines = finding_lines(q, phrasing)
        engine["findings"].append(
            {
                "cells": [str(lines[k]) for k in _FINDING_KEYS],
                "caveat": lines["caveat"],
                "notices": [str(n) for n in lines["notices"]],
            }
        )
    if not snap.diagnostics:
        engine["diag"] = {"none": live["no_diagnostics"], "rows": []}
    else:
        route_plain = phrasing["route_plain"]
        rows = []
        for d in snap.diagnostics:
            route = _SAMPLER_ROUTE.get(d.sampler, d.sampler)
            vals = [
                live["not_reported"] if getattr(d, k) is None else f"{getattr(d, k):g}"
                for k in _DIAG_KEYS
            ]
            rows.append([route_plain.get(route, route), *vals])
        engine["diag"] = {"none": None, "rows": rows}
    return engine


# ------------------------------------------------------------------ pages


def render(
    store: Store,
    client_id: str,
    clock: Clock,
    *,
    registry: LiveRegistry,
    phrasing: dict[str, Any],
    data_dir: Path,
    config: ClientConfig,
) -> str:
    live: dict[str, str] = phrasing["live"]
    cols: dict[str, str] = phrasing["live_columns"]
    labels: dict[str, str] = phrasing["status_labels"]
    evidence: dict[str, str] = phrasing["evidence_plain"]
    rounding = {k: int(v) for k, v in phrasing["rounding"].items()}
    now = clock.now()
    last_ok = store.latest_poll(client_id, ok_only=True)
    ctx: dict[str, Any] = {
        "title": live["title"].format(client_id=client_id),
        "refresh": registry.page_refresh_seconds,
        "watermark": phrasing["watermark"]["internal"],
        "live": live,
        "cols": cols,
        "banners": _banners(store, client_id, last_ok, now, registry, live),
        "header": [],
        "poll": None,
    }
    if store.latest_poll(client_id, ok_only=False) is None:
        ctx["no_poll"] = live["no_poll"]
        return _env().get_template("live.html").render(**ctx)
    ctx["no_poll"] = None
    if last_ok is None:
        return _env().get_template("live.html").render(**ctx)

    tz = last_ok.timezone or config.timezone
    currency = last_ok.currency or config.currency
    fmt = Fmt(rounding=rounding, currency=currency)
    nxt = last_ok.started_at + timedelta(seconds=registry.interval_seconds)
    header = [
        ("platform", last_ok.platform),
        ("account", " ".join(x for x in (last_ok.account.get("name"), last_ok.account_id) if x)),
        ("timezone", tz),
        ("currency", currency),
        ("last_good_poll", f"{fmt_utc(last_ok.started_at)} UTC"),
        ("last_good_poll", f"{fmt_local(last_ok.started_at, tz)} {tz}"),
        ("next_expected", f"{fmt_utc(nxt)} UTC"),
    ]  # fmt: skip
    ctx["header"] = [(cols[k], v) for k, v in header]

    platform = last_ok.platform
    today = now.astimezone(ZoneInfo(tz)).date()
    periods = _periods(today)
    rows = store.rows(last_ok.poll_id)
    ads = _ads(rows, periods)

    event = config.conversion_event.get(platform)
    confirmed = bool(config.conversion_event_confirmed.get(platform, False))
    event_label = event or live["purchases"]
    if event and not confirmed:
        event_label = f"{event_label} {live['provisional']}"
    notes: list[str] = []
    if event and rows and sum(r.conversions_reported or 0 for r in rows) == 0:
        notes.append(live["event_not_seen"].format(event=event))
    if event and "lead" in event.lower():
        notes.append(live["lead_sentence"])
    notes.append(live["not_shown"])

    floors, budget = _budget(ads, live, labels)
    ctx["poll"] = {
        "account": [(cols[k], v) for k, v in _account(last_ok, fmt, registry, live)],
        "periods": [live[p] for p in periods],
        "evidence_delivery": evidence["delivery"],
        "evidence_conversions": evidence["platform_attributed"],
        "platform_count": live["platform_count"],
        "delivery": _delivery(ads, fmt, live),
        "event_label": event_label,
        "conversions": _conversions(ads, fmt, live),
        "conversion_notes": notes,
        "floors": floors,
        "budget": budget,
        "engine": _engine(store, client_id, phrasing, data_dir, live),
        "levels": LEVELS,
        "finding_keys": _FINDING_KEYS,
        "diag_keys": ("route", *_DIAG_KEYS),
    }
    return _env().get_template("live.html").render(**ctx)


def render_index(store: Store, clock: Clock, *, registry: LiveRegistry) -> str:
    phrasing = registries.load("phrasing")
    live: dict[str, str] = phrasing["live"]
    entries = []
    for client_id in store.clients():
        last = store.latest_poll(client_id, ok_only=True)
        entries.append(
            {
                "client_id": client_id,
                "href": "/client/" + urllib.parse.quote(client_id, safe=""),
                "last": f"{fmt_utc(last.started_at)} UTC" if last else live["none_yet"],
            }
        )
    return (
        _env()
        .get_template("index.html")
        .render(
            entries=entries,
            cols=phrasing["live_columns"],
            refresh=registry.page_refresh_seconds,
            watermark=phrasing["watermark"]["internal"],
        )
    )
