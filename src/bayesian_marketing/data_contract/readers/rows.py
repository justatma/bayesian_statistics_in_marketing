"""Row-level validation and typing (§5.1 C1, C2, C7). A bad row is quarantined, never coerced."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from bayesian_marketing.core import Money, OrderRow, SiteRow
from bayesian_marketing.data_contract.readers.currencies import is_iso_4217
from bayesian_marketing.data_contract.readers.table import EMPTY_MARKERS, Table

_INT = re.compile(r"^-?\d+$")
_NUM = re.compile(r"^-?\d+(\.\d+)?$")
# Strict comma grouping only: 1,000 / 12,345,678 / 1,500.50. Anything else stays quarantined.
# The first group has no leading zero, so "0,001" is not a grouped number.
_GROUPED_INT = re.compile(r"^-?[1-9]\d{0,2}(,\d{3})+$")
_GROUPED_NUM = re.compile(r"^-?[1-9]\d{0,2}(,\d{3})+(\.\d+)?$")


def ungroup(v: str, grouped: re.Pattern[str]) -> str:
    """Strip thousands separators from a strictly grouped number; leave anything else alone."""
    return v.replace(",", "") if grouped.match(v) else v


ENTITY_KEYS = ("account", "campaign", "ad_set", "ad")


@dataclass
class Context:
    """What a row needs beyond its own cells."""

    table: Table
    fallback_currency: str | None  # manifest / economics currency, when the export carries none
    attribution_window: str  # used when the export has no attribution column


class RowReader:
    """Reads one row's cells by target field and collects reasons."""

    def __init__(self, ctx: Context, cells: list[str]) -> None:
        self.ctx = ctx
        self.cells = cells
        self.reasons: list[str] = []

    def get(self, target: str) -> str | None:
        col = self.ctx.table.columns.get(target)
        if col is None or col >= len(self.cells):
            return None
        v = self.cells[col]
        return None if v in EMPTY_MARKERS else v

    def need(self, target: str) -> str | None:
        v = self.get(target)
        if v is None:
            self.reasons.append(f"{target}: missing")
        return v

    def date(self, target: str = "date") -> date | None:
        v = self.need(target)
        if v is None:
            return None
        try:
            return date.fromisoformat(v)
        except ValueError:
            self.reasons.append(f"{target}: not an ISO date ({v!r})")
            return None

    def count(self, target: str, *, required: bool = True) -> int | None:
        v = self.need(target) if required else self.get(target)
        if v is None:
            return None
        v = ungroup(v, _GROUPED_INT)
        if not _INT.match(v):
            self.reasons.append(f"{target}: not an integer ({v!r})")
            return None
        n = int(v)
        if n < 0:
            self.reasons.append(f"{target}: negative ({n})")
            return None
        return n

    def number(self, target: str, *, required: bool = True) -> Decimal | None:
        v = self.need(target) if required else self.get(target)
        if v is None:
            return None
        v = ungroup(v, _GROUPED_NUM)
        if not _NUM.match(v):
            self.reasons.append(f"{target}: not a plain number ({v!r})")
            return None
        d = Decimal(v)
        if d < 0:
            self.reasons.append(f"{target}: negative ({v})")
            return None
        return d

    def timestamp(self, target: str, *, required: bool = True) -> datetime | None:
        """ISO-8601 with an offset, normalized to UTC (C2). A naive timestamp is quarantined."""
        v = self.need(target) if required else self.get(target)
        if v is None:
            return None
        try:
            t = datetime.fromisoformat(v)
        except ValueError:
            self.reasons.append(f"{target}: not an ISO-8601 timestamp ({v!r})")
            return None
        if t.tzinfo is None or t.utcoffset() is None:
            self.reasons.append(f"{target}: no UTC offset ({v!r})")
            return None
        return t.astimezone(UTC)

    def currency(self) -> str | None:
        """Row currency column, else the header slot, else the fallback. Must be ISO 4217."""
        row_cur = self.get("currency")
        row_cur = row_cur.upper() if row_cur is not None else None
        head_cur = self.ctx.table.header_currency
        if row_cur is not None and head_cur is not None and row_cur != head_cur:
            self.reasons.append(f"currency: column {row_cur!r} conflicts with header {head_cur!r}")
            return None
        cur = row_cur or head_cur or self.ctx.fallback_currency
        if cur is None:
            self.reasons.append("currency: none in the row, header, manifest or economics")
            return None
        if not is_iso_4217(cur):
            self.reasons.append(f"currency: unknown currency {cur!r} (not ISO 4217)")
            return None
        return cur

    def text(self, target: str) -> str | None:
        return self.get(target)

    def utm(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for target, col in self.ctx.table.columns.items():
            if (
                target.startswith("utm.")
                and col < len(self.cells)
                and self.cells[col] not in EMPTY_MARKERS
            ):
                out[target.removeprefix("utm.")] = self.cells[col]
        return out


def performance_fields(ctx: Context, cells: list[str]) -> tuple[dict[str, Any] | None, list[str]]:
    """PerformanceRow fields (without conversions_observed, set by C8 later), or reasons."""
    r = RowReader(ctx, cells)
    d = r.date()
    ids = {k: v for k in ENTITY_KEYS if (v := r.get(f"entity_ids.{k}")) is not None}
    if "ad" not in ids:
        r.reasons.append("entity_ids.ad: missing")
    imp = r.count("impressions")
    clk = r.count("clicks")
    spend = r.number("spend")
    conv_d = r.number("conversions_reported", required=False)
    rev = r.number("revenue_reported", required=False)
    cur = r.currency()
    if imp is not None and clk is not None and clk > imp:
        r.reasons.append(f"clicks above impressions ({clk} > {imp})")
    if conv_d is not None and clk is not None and conv_d > clk:
        r.reasons.append(f"conversions above clicks ({conv_d} > {clk})")
    if r.reasons:
        return None, r.reasons
    assert cur is not None and spend is not None
    return {
        "entity_ids": ids,
        "date": d,
        "impressions": imp,
        "clicks": clk,
        "spend": Money(amount=spend, currency=cur),
        "conversions_reported": None if conv_d is None else float(conv_d),
        "conversions_integral": conv_d is not None and conv_d == conv_d.to_integral_value(),
        "attribution_window": r.text("attribution_window") or ctx.attribution_window,
        "revenue_reported": None if rev is None else Money(amount=rev, currency=cur),
    }, []


def order_row(ctx: Context, cells: list[str]) -> tuple[OrderRow | None, list[str]]:
    r = RowReader(ctx, cells)
    oid = r.need("order_id")
    at = r.timestamp("ordered_at")
    value = r.number("value")
    refunded = r.number("refunded")
    first = r.timestamp("first_click_at", required=False)
    cur = r.currency()
    if value is not None and refunded is not None and refunded > value:
        r.reasons.append(f"refunded above value ({refunded} > {value})")
    if r.reasons:
        return None, r.reasons
    assert oid is not None and at is not None and cur is not None
    assert value is not None and refunded is not None
    utm = r.utm()
    return OrderRow(
        order_id=oid,
        ordered_at=at,
        value=Money(amount=value, currency=cur),
        refunded=Money(amount=refunded, currency=cur),
        utm=utm or None,
        click_id=r.text("click_id"),
        first_click_at=first,
    ), []


def site_row(ctx: Context, cells: list[str]) -> tuple[SiteRow | None, list[str]]:
    r = RowReader(ctx, cells)
    d = r.date()
    sessions = r.count("sessions")
    purchases = r.count("purchases")
    revenue = r.number("revenue")
    cur = r.currency()
    if sessions is not None and purchases is not None and purchases > sessions:
        r.reasons.append(f"purchases above sessions ({purchases} > {sessions})")
    if r.reasons:
        return None, r.reasons
    assert d is not None and sessions is not None and purchases is not None
    assert revenue is not None and cur is not None
    return SiteRow(
        date=d,
        utm=r.utm(),
        sessions=sessions,
        purchases=purchases,
        revenue=Money(amount=revenue, currency=cur),
    ), []
