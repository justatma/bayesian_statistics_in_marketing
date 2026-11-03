"""What a connector hands to ``pull``: typed-as-text records plus the account facts (C2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

# Target fields a connector fills, named as in the channel export maps (C3) so the P1 row
# validators read them unchanged.
PERF_TARGETS = (
    "date",
    "entity_ids.account",
    "entity_ids.campaign",
    "entity_ids.ad_set",
    "entity_ids.ad",
    "entity_ids.account_name",  # names land in PerformanceRow.entity_names (D34)
    "entity_ids.campaign_name",
    "entity_ids.ad_set_name",
    "entity_ids.ad_name",
    "objective",  # campaign objective / optimization event as the API states it (D34)
    "impressions",
    "clicks",
    "spend",
    "currency",
    "conversions_reported",
    "revenue_reported",
    "attribution_window",
)
SITE_TARGETS = (
    "date",
    "utm.source",
    "utm.medium",
    "utm.campaign",
    "sessions",
    "purchases",
    "revenue",
    "currency",
)


@dataclass
class Record:
    """One API row as target-field text (None = absent), the raw element, pre-check reasons."""

    values: dict[str, str | None]
    source: dict[str, Any]
    reasons: list[str] = field(default_factory=list)


@dataclass
class Fetched:
    timezone: str  # zone the row dates are in (C2)
    currency: str | None  # account / property currency, the fallback for rows that carry none
    records: list[Record]
    n_elements: int  # data elements the API returned, before any check (C6 empty account)
    notes: list[str] = field(default_factory=list)
    attribution_windows: list[str] = field(default_factory=list)  # requested or default (C4)


def text(v: Any) -> str | None:
    """A JSON scalar as plain decimal text, never exponent form. None and "" stay None."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        v = repr(v)
    s = str(v).strip()
    try:
        d = Decimal(s)
    except InvalidOperation:
        return s  # left for the row validator to quarantine
    if not d.is_finite():
        return s
    out = format(d, "f")
    return out


def micros(v: Any) -> str | None:
    """Google Ads ``cost_micros`` (int64, often a JSON string) as currency units (F3 §4)."""
    t = text(v)
    if t is None:
        return None
    try:
        return format(Decimal(t) / Decimal(1_000_000), "f")
    except InvalidOperation:
        return t


def window_check(d: str | None, window: tuple[date, date]) -> list[str]:
    if d is None:
        return []
    try:
        day = date.fromisoformat(d)
    except ValueError:
        return []  # the row validator reports the bad date
    if not window[0] <= day <= window[1]:
        return [f"date {d} outside the requested window {window[0]} to {window[1]}"]
    return []


def halves(window: tuple[date, date]) -> tuple[tuple[date, date], tuple[date, date]] | None:
    """Split a window in two for a platform's per-call size limit; None for a single day."""
    a, b = window
    if a >= b:
        return None
    mid = a + timedelta(days=(b - a).days // 2)
    return (a, mid), (mid + timedelta(days=1), b)


# ISO 4217 minor-unit exponents that are not 2. The X-codes for metals, funds and "no currency"
# have no minor unit and are left unrounded.
MINOR_UNITS: dict[str, int] = {
    **dict.fromkeys(
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
        ],
        0,
    ),
    **dict.fromkeys(["BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"], 3),
    **dict.fromkeys(["CLF", "UYW"], 4),
}
NO_MINOR_UNIT = frozenset(
    ["XAG", "XAU", "XBA", "XBB", "XBC", "XBD", "XDR", "XPD", "XPT", "XSU", "XTS", "XUA", "XXX"]
)


def to_minor_units(v: str | None, currency: str | None) -> str | None:
    """An amount as text rounded half-up to the currency's minor units (no float noise)."""
    if v is None or currency is None or currency in NO_MINOR_UNIT:
        return v
    try:
        d = Decimal(v)
    except InvalidOperation:
        return v  # left for the row validator to quarantine
    if not d.is_finite():
        return v
    exp = Decimal(1).scaleb(-MINOR_UNITS.get(currency, 2))
    return format(d.quantize(exp, rounding=ROUND_HALF_UP), "f")
