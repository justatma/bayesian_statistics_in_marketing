"""Export a live client's full history as JSONL for Arkwright's client data inflow (D54).

    ( set -a; . ~/.secrets/keys.env; set +a; python -I scripts/export_history.py jovannah [--since YYYY-MM-DD] )

Writes `data/live/exports/<client_id>/<UTC stamp>/` (outside git):

  polls.jsonl     one row per ad per day per version. A row's first appearance in the live store is
                  version 1; a later poll that changes any figure for that ad and day is a new row,
                  version n+1, naming the key it restates. Never an overwrite.
  runs.jsonl      one row per engine run: window, metric, horizon, every quantity with its
                  posterior summary and feasibility, the comparison (p_best, expected loss and
                  value), recommendations, gate results, and the poll the run read.
  reads.jsonl     one row per poll per ad-day it read: which version that poll saw, when, and
                  whether the day had already closed in the account's time zone. A version is
                  keyed by when it first appeared; these rows show every later poll that confirmed it.
  backfill.jsonl  the days before the live store began, read from Meta now at ad and day level,
                  with every action Meta reports. Each export's read is its own keys
                  (meta:<ad>:<date>:read_<stamp>), so a later read never changes a stored key.
  changes.jsonl   the ad account's change history from Meta (no actor fields are requested).
  manifest.json   counts and a sha256 for each file.

Every row carries `key` (stable across exports, since the store is append-only), `describes` (the
day or window it is about), `timezone` (the ad account's, as Meta names it), `known_at` (when the figure became known: the poll's start, the run's
start, or the read) and the account, campaign, ad set and ad ids. No personal data is read.
Each run row also carries `row_keys` (for every ad-day in the poll it read, the version known at
that poll) and `rows_sha256`, computed under the canonical form `bayes-rows-c1`: each polls row as
JSON with keys sorted, separators "," and ":", UTF-8 without ASCII escaping, numbers as stored
(integers bare, figures such as spend as the strings Meta gives), dates as ISO 8601 text; one row
per line ending in a line feed; rows ordered by `key`. The pointer a claim names is these keys
and this hash; the stored file is the first one holding them.

`--since` keeps the days from that date on (polls by the day described, runs by their window's
end, changes by event time, backfill not at all once the store covers the date). Versions are
always numbered over the full history, so keys agree with a full export.
Meta reads need META_ACCESS_TOKEN in the environment; without it, backfill and changes are skipped
and the manifest says so.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LIVE = REPO / "data" / "live"
GRAPH = "https://graph.facebook.com/v21.0/"
MEASURES = (
    "impressions", "clicks", "spend_amount", "spend_currency", "conversions_reported",
    "conversions_observed", "revenue_amount", "revenue_currency", "attribution_window", "objective",
)
BACKFILL_FIELDS = (
    "account_id,campaign_id,adset_id,ad_id,account_name,campaign_name,adset_name,ad_name,objective,"
    "impressions,reach,frequency,inline_link_clicks,clicks,spend,account_currency,actions,"
    "action_values,attribution_setting"
)


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def ids(entity_ids: dict) -> dict:
    return {k: entity_ids.get(k) for k in ("account", "campaign", "ad_set", "ad")}


ROWS_FORM = "bayes-rows-c1"
POLL_READS: list[dict] = []


def rows_sha256(rows: list[dict]) -> str:
    """bayes-rows-c1: canonical JSON per row, a line feed after each, rows in key order."""
    return hashlib.sha256(b"".join(canonical(r) + b"\n" for r in sorted(rows, key=lambda r: r["key"]))).hexdigest()


def polls(store: sqlite3.Connection, client_id: str, tz: str) -> tuple[list[dict], dict[str, list[str]]]:
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
            "describes": r["date"], "known_at": r["started_at"], "timezone": tz,
            "poll_id": r["poll_id"], "ad": r["ad_id"],
            "after_close": datetime.fromisoformat(r["started_at"]) >= close,
        }
        if last.get(k) == figures:
            seen.setdefault(r["poll_id"], []).append(current[k])
            reads.append({**read, "version_key": current[k]})
            continue
        version[k] = version.get(k, 0) + 1
        key = f"meta:{r['ad_id']}:{r['date']}:v{version[k]}"
        out.append({
            "key": key,
            "restates": f"meta:{r['ad_id']}:{r['date']}:v{version[k] - 1}" if version[k] > 1 else None,
            "describes": r["date"],
            "known_at": r["started_at"],
            "timezone": tz,
            "poll_id": r["poll_id"],
            "platform": r["platform"],
            **ids(json.loads(r["entity_ids_json"])),
            "names": json.loads(r["entity_names_json"]),
            "link_clicks": r["clicks"],
            **{m: r[m] for m in MEASURES if m != "clicks"},
        })
        last[k] = figures
        current[k] = key
        reads.append({**read, "version_key": key})
        seen.setdefault(r["poll_id"], []).append(key)
    POLL_READS[:] = reads
    return out, {p: sorted(v) for p, v in seen.items()}


def runs(
    store: sqlite3.Connection, client_id: str, tz: str, poll_rows: list[dict], seen: dict[str, list[str]]
) -> list[dict]:
    by_key = {r["key"]: r for r in poll_rows}
    record = sqlite3.connect(f"file:{LIVE / 'engine' / 'run_record.sqlite'}?mode=ro", uri=True)
    started = {}
    for (payload,) in record.execute("SELECT payload FROM run_records"):
        p = json.loads(payload)
        started[p["run_id"]] = p["started_at"]
    poll_of = {
        r["run_id"]: r["poll_id"]
        for r in store.execute(
            "SELECT run_id, poll_id FROM refreshes WHERE client_id = ? AND run_id IS NOT NULL", (client_id,)
        )
    }
    out = []
    for path in sorted((LIVE / "engine" / "runs").glob("run_*.json")):
        d = json.loads(path.read_text())
        if d.get("client_id") != client_id:
            continue
        keys = seen.get(poll_of.get(d["run_id"]), [])
        out.append({
            "key": d["run_id"],
            "describes": {"start": d["window"][0], "end": d["window"][1]},
            "known_at": started.get(d["run_id"]),
            "timezone": tz,
            "poll_id": poll_of.get(d["run_id"]),
            "row_keys": keys,
            "rows_form": ROWS_FORM,
            "rows_sha256": rows_sha256([by_key[k] for k in keys]),
            "account": None,
            "metric": d["metric"],
            "horizon": d.get("horizon"),
            "tool_version": d.get("tool_version"),
            "config_hash": d.get("config_hash"),
            "quantities": [
                {
                    "quantity_id": q["quantity_id"],
                    "name": q["name"],
                    "ad": q["scope"]["ids"].get("ad"),
                    "window": q["scope"].get("window"),
                    "summary": q["estimate"]["summary"],
                    "family": q["estimate"].get("family"),
                    "params": q["estimate"].get("params"),
                    "feasibility": q["feasibility"],
                    "data_pull_ids": q.get("provenance", {}).get("data_pull_ids"),
                }
                for q in d["quantities"]
            ],
            "not_estimable": d.get("not_estimable"),
            "comparison": d.get("comparison"),
            "decision": d.get("decision"),
            "recommendations": d.get("recommendations"),
            "gate_results": d.get("gate_results"),
            "knowability": d.get("knowability"),
            "notices": d.get("notices"),
        })
    return out


def _get(path: str, token: str, **params) -> list[dict]:
    url = GRAPH + path + "?" + urllib.parse.urlencode({**params, "access_token": token})
    data = []
    while url:
        with urllib.request.urlopen(url, timeout=120) as r:
            d = json.load(r)
        data += d.get("data", [])
        url = d.get("paging", {}).get("next")
    return data


def backfill(account: str, before: str, token: str, read_at: str, tz: str) -> list[dict]:
    rows = _get(
        f"act_{account}/insights", token, level="ad", fields=BACKFILL_FIELDS, time_increment=1,
        time_range=json.dumps({"since": "2026-01-01", "until": (date.fromisoformat(before) - timedelta(days=1)).isoformat()}),
        limit=500,
    )
    return [
        {
            "key": f"meta:{r['ad_id']}:{r['date_start']}:read_{read_at.replace('-', '').replace(':', '')[:15]}Z",
            "restates": None,
            "describes": r["date_start"],
            "known_at": read_at,
            "timezone": tz,
            "account": r.get("account_id"), "campaign": r.get("campaign_id"),
            "ad_set": r.get("adset_id"), "ad": r.get("ad_id"),
            "meta": r,
        }
        for r in rows
    ]


_SIGNED = re.compile(
    r'(https?:(?:\\?/){2}[^"\s?]*(?:fbcdn\.net|facebook\.com(?:\\?/)ads(?:\\?/)image)[^"\s?]*)\?[^"\s]*'
)


def _unsigned(r: dict) -> dict:
    """Meta signs image urls afresh on every read (_nc_gid, oh, oe on fbcdn; the d token on
    /ads/image). The signature is not part of
    the change, so it is cut and the image's path kept, or the same change would hash differently."""
    if isinstance(r.get("extra_data"), str):
        r = {**r, "extra_data": _SIGNED.sub(r"\1", r["extra_data"])}
    return r


def changes(account: str, token: str, read_at: str, tz: str) -> list[dict]:
    rows = _get(
        f"act_{account}/activities", token,
        fields="event_type,event_time,object_id,object_name,object_type,extra_data,translated_event_type",
        since="2026-01-01", limit=500,
    )
    return [
        {
            "key": "chg:" + hashlib.sha256(canonical(r)).hexdigest()[:16],
            "describes": r["event_time"],
            "known_at": r["event_time"],  # Meta records a change when it is made
            "timezone": tz,
            "account": account,
            "object_id": r.get("object_id"),
            "meta": r,
        }
        for r in sorted(map(_unsigned, rows), key=lambda r: r["event_time"])
    ]


def main(client_id: str, since: str | None = None) -> Path:
    store = sqlite3.connect(f"file:{LIVE / 'live.sqlite'}?mode=ro", uri=True)
    store.row_factory = sqlite3.Row
    now = datetime.now(UTC)
    read_at = now.isoformat(timespec="seconds")
    out = LIVE / "exports" / client_id / now.strftime("%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True)
    zones = {r[0] for r in store.execute(
        "SELECT DISTINCT o.timezone FROM poll_outcomes o JOIN polls p USING (poll_id) "
        "WHERE p.client_id = ? AND o.status = 'ok'", (client_id,)) if r[0]}
    if len(zones) != 1:
        raise RuntimeError(f"expected one account time zone, found {sorted(zones)}")
    tz = zones.pop()
    poll_rows, seen = polls(store, client_id, tz)
    files = {"polls.jsonl": poll_rows, "runs.jsonl": runs(store, client_id, tz, poll_rows, seen),
             "reads.jsonl": sorted(POLL_READS, key=lambda r: r["key"])}
    account = store.execute(
        "SELECT account_id FROM polls WHERE client_id = ? LIMIT 1", (client_id,)
    ).fetchone()["account_id"].removeprefix("act_")
    first = store.execute("SELECT min(date) FROM rows WHERE client_id = ?", (client_id,)).fetchone()[0]
    token = os.environ.get("META_ACCESS_TOKEN")
    skipped = []
    if token:
        files["backfill.jsonl"] = [] if since and since >= first else backfill(account, first, token, read_at, tz)
        files["changes.jsonl"] = changes(account, token, read_at, tz)
    else:
        skipped = ["backfill.jsonl", "changes.jsonl"]
    if since:
        files["polls.jsonl"] = [r for r in files["polls.jsonl"] if r["describes"] >= since]
        files["reads.jsonl"] = [r for r in files["reads.jsonl"] if r["describes"] >= since]
        files["runs.jsonl"] = [r for r in files["runs.jsonl"] if r["describes"]["end"] >= since]
        if "changes.jsonl" in files:
            files["changes.jsonl"] = [r for r in files["changes.jsonl"] if r["describes"][:10] >= since]
    manifest = {"client_id": client_id, "written_at": read_at, "store_first_day": first,
                "timezone": tz, "since": since, "rows_form": ROWS_FORM,
                "skipped_without_token": skipped, "files": {}}
    for name, rows in files.items():
        body = b"".join(canonical(r) + b"\n" for r in rows)
        if token and token.encode() in body:
            raise RuntimeError("token found in export; nothing kept")
        (out / name).write_bytes(body)
        manifest["files"][name] = {"rows": len(rows), "sha256": hashlib.sha256(body).hexdigest()}
    (out / "manifest.json").write_bytes(canonical(manifest) + b"\n")
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    since = None
    if len(args) == 3 and args[1] == "--since":
        since = date.fromisoformat(args[2]).isoformat()
        args = args[:1]
    if len(args) != 1:
        sys.exit(__doc__)
    folder = main(args[0], since)
    print(folder)
    print((folder / "manifest.json").read_text())
