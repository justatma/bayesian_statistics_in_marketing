"""The oracle for J2 check (f) (S28): ``polls()`` from ``scripts/export_history.py`` exactly as it
stood at commit e983942, before J2 moved the version numbering into ``live.rows``. Copied with
the module globals it reads (``MEASURES``, ``canonical``, ``ids``, ``POLL_READS``); only the
layout was changed, by ``ruff format``. Never edit the logic: ``versioned`` is held to it.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

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


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def ids(entity_ids: dict) -> dict:
    return {k: entity_ids.get(k) for k in ("account", "campaign", "ad_set", "ad")}


POLL_READS: list[dict] = []


def polls(
    store: sqlite3.Connection, client_id: str, tz: str
) -> tuple[list[dict], dict[str, list[str]]]:
    """The versioned rows, and for each poll the keys of the versions it saw."""
    q = """SELECT r.*, p.started_at FROM rows r JOIN polls p USING (poll_id)
           WHERE r.client_id = ? ORDER BY r.ad_id, r.date, p.started_at, r.poll_id"""
    out, last, version, current, seen, reads = [], {}, {}, {}, {}, []
    zone = ZoneInfo(tz)
    for r in store.execute(q, (client_id,)):
        k = (r["ad_id"], r["date"])
        figures = {m: r[m] for m in MEASURES}
        close = datetime.combine(date.fromisoformat(r["date"]) + timedelta(days=1), time(0), zone)
        read = {
            "key": f"read:{r['poll_id']}:{r['ad_id']}:{r['date']}",
            "describes": r["date"],
            "known_at": r["started_at"],
            "timezone": tz,
            "poll_id": r["poll_id"],
            "ad": r["ad_id"],
            "after_close": datetime.fromisoformat(r["started_at"]) >= close,
        }
        if last.get(k) == figures:
            seen.setdefault(r["poll_id"], []).append(current[k])
            reads.append({**read, "version_key": current[k]})
            continue
        version[k] = version.get(k, 0) + 1
        key = f"meta:{r['ad_id']}:{r['date']}:v{version[k]}"
        out.append(
            {
                "key": key,
                "restates": f"meta:{r['ad_id']}:{r['date']}:v{version[k] - 1}"
                if version[k] > 1
                else None,
                "describes": r["date"],
                "known_at": r["started_at"],
                "timezone": tz,
                "poll_id": r["poll_id"],
                "platform": r["platform"],
                **ids(json.loads(r["entity_ids_json"])),
                "names": json.loads(r["entity_names_json"]),
                "link_clicks": r["clicks"],
                **{m: r[m] for m in MEASURES if m != "clicks"},
            }
        )
        last[k] = figures
        current[k] = key
        reads.append({**read, "version_key": key})
        seen.setdefault(r["poll_id"], []).append(key)
    POLL_READS[:] = reads
    return out, {p: sorted(v) for p, v in seen.items()}
