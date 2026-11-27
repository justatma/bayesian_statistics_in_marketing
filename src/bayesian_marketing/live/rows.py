"""The canonical row form bayes-rows-c1 and the version numbering over a client's full history
(Brain join J1, J2; S28, S29). One implementation, used by the live refresh and by
``scripts/export_history.py``."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from bayesian_marketing.core import Money
from bayesian_marketing.live.contracts import LiveRow, PollRecord, Store

ROWS_FORM = "bayes-rows-c1"
HASH_PREFIX = ROWS_FORM + ":"
MEASURES = (
    "impressions",
    "clicks",
    "spend_amount",
    "spend_currency",
    "conversions_reported",
    "conversions_observed",
    "revenue_amount",
    "revenue_currency",
    "attribution_window",
    "objective",
)
"""A version is cut when any of these changes for an ad and day (J1 point 6)."""

Versioned = tuple[list[dict[str, Any]], dict[str, list[str]], list[dict[str, Any]]]

ALL_POLLS = 2**62
"""``Store.polls`` takes a limit; the version numbering reads the full history."""
ID_LEVELS = ("account", "campaign", "ad_set", "ad")


def canonical(obj: Any) -> bytes:
    """J1 point 3: keys sorted at every level, separators "," and ":", UTF-8, no ASCII escaping."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def rows_sha256(rows: list[dict[str, Any]]) -> str:
    """J1 points 4 and 5: canonical row plus a line feed, rows in ``key`` order, lowercase hex
    SHA-256. An empty list hashes the empty string."""
    ordered = sorted(rows, key=lambda r: r["key"])
    return hashlib.sha256(b"".join(canonical(r) + b"\n" for r in ordered)).hexdigest()


def versioned(store: Store, client_id: str) -> Versioned:
    """J1 point 7, S28, S29, S14: ``(rows, seen, reads)``.

    ``rows``: every version of every ad-day the client's ok polls hold, as export polls rows,
    in the order first seen. ``seen``: poll id to the sorted keys of the versions that poll read.
    ``reads``: one row per poll per ad-day, as the export's ``reads.jsonl`` rows (unsorted)."""
    polls = [p for p in store.polls(client_id, limit=ALL_POLLS) if p.status == "ok"]
    tz = _timezone(polls)
    zone = ZoneInfo(tz) if tz is not None else None
    stored = [
        _stored(p, r) for p in polls for r in store.rows(p.poll_id) if r.client_id == client_id
    ]
    # the export's query order: ad id, date, the poll's started_at as stored text, poll id
    stored.sort(key=lambda r: (r["ad_id"], r["date"], r["started_at"], r["poll_id"]))
    out: list[dict[str, Any]] = []
    last: dict[tuple[str, str], dict[str, Any]] = {}
    version: dict[tuple[str, str], int] = {}
    current: dict[tuple[str, str], str] = {}
    seen: dict[str, list[str]] = {}
    reads: list[dict[str, Any]] = []
    for r in stored:
        k = (r["ad_id"], r["date"])
        figures = {m: r[m] for m in MEASURES}
        read = {
            "key": f"read:{r['poll_id']}:{r['ad_id']}:{r['date']}",
            "describes": r["date"],
            "known_at": r["started_at"],
            "timezone": tz,
            "poll_id": r["poll_id"],
            "ad": r["ad_id"],
            "after_close": _after_close(r["date"], r["started"], zone),
        }
        if last.get(k) == figures:
            seen.setdefault(r["poll_id"], []).append(current[k])
            reads.append({**read, "version_key": current[k]})
            continue
        version[k] = n = version.get(k, 0) + 1
        key = f"meta:{r['ad_id']}:{r['date']}:v{n}"
        out.append(
            {
                "key": key,
                "restates": f"meta:{r['ad_id']}:{r['date']}:v{n - 1}" if n > 1 else None,
                "describes": r["date"],
                "known_at": r["started_at"],
                "timezone": tz,
                "poll_id": r["poll_id"],
                "platform": r["platform"],
                **{level: r["entity_ids"].get(level) for level in ID_LEVELS},
                "names": r["entity_names"],
                "link_clicks": r["clicks"],
                **{m: r[m] for m in MEASURES if m != "clicks"},
            }
        )
        last[k] = figures
        current[k] = key
        reads.append({**read, "version_key": key})
        seen.setdefault(r["poll_id"], []).append(key)
    return out, {p: sorted(v) for p, v in seen.items()}, reads


def pointer(
    rows: list[dict[str, Any]],
    seen: dict[str, list[str]],
    poll_id: str,
    window: tuple[str, str] | None = None,
) -> tuple[list[str], str]:
    """The run pointer for a poll: ``(row_keys, rows_sha256)`` over the versions that poll read.
    A poll with no rows gives ``([], sha256(b""))``. L12.2: ``window`` (ISO dates, inclusive)
    keeps only versions whose ``describes`` falls in it; None keeps all, as before L12."""
    by_key = {r["key"]: r for r in rows}
    keys = list(seen.get(poll_id, []))
    if window is not None:
        lo, hi = str(window[0]), str(window[1])  # ISO dates compare as text
        keys = [k for k in keys if lo <= by_key[k]["describes"] <= hi]
    return keys, rows_sha256([by_key[k] for k in keys])


def _timezone(polls: list[PollRecord]) -> str | None:
    """S29: the one distinct non-null time zone among the ok polls; two or more raise."""
    zones = sorted({p.timezone for p in polls if p.timezone})
    if len(zones) > 1:
        raise ValueError(f"expected one account time zone, found {zones}")
    return zones[0] if zones else None


def _after_close(day: str, started: datetime, zone: ZoneInfo | None) -> bool | None:
    """Whether the poll began after the account-local day had closed; null without a zone
    (S36 (4))."""
    if zone is None:
        return None
    return started >= datetime.combine(date.fromisoformat(day) + timedelta(days=1), time(0), zone)


def _money(m: Money | None) -> tuple[str | None, str | None]:
    return (None, None) if m is None else (str(m.amount), m.currency)


def _stored(poll: PollRecord, r: LiveRow) -> dict[str, Any]:
    """A row in the text forms ``live/store.py`` writes it, with its poll's start (S28)."""
    spend_amount, spend_currency = _money(r.spend)
    revenue_amount, revenue_currency = _money(r.revenue_reported)
    reported = r.conversions_reported
    return {
        "poll_id": poll.poll_id,
        "started": poll.started_at,
        "started_at": poll.started_at.isoformat(),
        "platform": r.platform,
        "ad_id": r.entity_ids["ad"],
        "date": r.date.isoformat(),
        "entity_ids": dict(r.entity_ids),
        "entity_names": dict(r.entity_names),
        "objective": r.objective,
        "impressions": r.impressions,
        "clicks": r.clicks,
        "spend_amount": spend_amount,
        "spend_currency": spend_currency,
        "conversions_reported": None if reported is None else float(reported),
        "conversions_observed": r.conversions_observed,
        "revenue_amount": revenue_amount,
        "revenue_currency": revenue_currency,
        "attribution_window": r.attribution_window,
    }
