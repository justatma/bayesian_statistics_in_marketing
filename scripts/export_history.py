"""Export a live client's full history as JSONL for Arkwright's client data inflow (D54).

    ( set -a; . ~/.secrets/keys.env; set +a; python -I scripts/export_history.py jovannah )

Writes `data/live/exports/<client_id>/<UTC stamp>/` (outside git):

  polls.jsonl     one row per ad per day per version. A row's first appearance in the live store is
                  version 1; a later poll that changes any figure for that ad and day is a new row,
                  version n+1, naming the key it restates. Never an overwrite.
  runs.jsonl      one row per engine run: window, metric, horizon, every quantity with its
                  posterior summary and feasibility, the comparison (p_best, expected loss and
                  value), recommendations, gate results, and the poll the run read.
  backfill.jsonl  the days before the live store began, read from Meta now at ad and day level,
                  with every action Meta reports. Known on the day of the read.
  changes.jsonl   the ad account's change history from Meta (no actor fields are requested).
  manifest.json   counts and a sha256 for each file.

Every row carries `key` (stable across exports, since the store is append-only), `describes` (the
day or window it is about), `known_at` (when the figure became known: the poll's start, the run's
start, or the read) and the account, campaign, ad set and ad ids. No personal data is read.
Meta reads need META_ACCESS_TOKEN in the environment; without it, backfill and changes are skipped
and the manifest says so.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta
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


def polls(store: sqlite3.Connection, client_id: str) -> list[dict]:
    q = """SELECT r.*, p.started_at FROM rows r JOIN polls p USING (poll_id)
           WHERE r.client_id = ? ORDER BY r.ad_id, r.date, p.started_at, r.poll_id"""
    out, last, version = [], {}, {}
    for r in store.execute(q, (client_id,)):
        k = (r["ad_id"], r["date"])
        figures = {m: r[m] for m in MEASURES}
        if last.get(k) == figures:
            continue
        version[k] = version.get(k, 0) + 1
        key = f"meta:{r['ad_id']}:{r['date']}:v{version[k]}"
        out.append({
            "key": key,
            "restates": f"meta:{r['ad_id']}:{r['date']}:v{version[k] - 1}" if version[k] > 1 else None,
            "describes": r["date"],
            "known_at": r["started_at"],
            "poll_id": r["poll_id"],
            "platform": r["platform"],
            **ids(json.loads(r["entity_ids_json"])),
            "names": json.loads(r["entity_names_json"]),
            "link_clicks": r["clicks"],
            **{m: r[m] for m in MEASURES if m != "clicks"},
        })
        last[k] = figures
    return out


def runs(store: sqlite3.Connection, client_id: str) -> list[dict]:
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
        out.append({
            "key": d["run_id"],
            "describes": {"start": d["window"][0], "end": d["window"][1]},
            "known_at": started.get(d["run_id"]),
            "poll_id": poll_of.get(d["run_id"]),
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


def backfill(account: str, before: str, token: str, read_at: str) -> list[dict]:
    rows = _get(
        f"act_{account}/insights", token, level="ad", fields=BACKFILL_FIELDS, time_increment=1,
        time_range=json.dumps({"since": "2026-01-01", "until": (date.fromisoformat(before) - timedelta(days=1)).isoformat()}),
        limit=500,
    )
    return [
        {
            "key": f"meta:{r['ad_id']}:{r['date_start']}:backfill",
            "restates": None,
            "describes": r["date_start"],
            "known_at": read_at,
            "account": r.get("account_id"), "campaign": r.get("campaign_id"),
            "ad_set": r.get("adset_id"), "ad": r.get("ad_id"),
            "meta": r,
        }
        for r in rows
    ]


def changes(account: str, token: str, read_at: str) -> list[dict]:
    rows = _get(
        f"act_{account}/activities", token,
        fields="event_type,event_time,object_id,object_name,object_type,extra_data,translated_event_type",
        since="2026-01-01", limit=500,
    )
    return [
        {
            "key": "chg:" + hashlib.sha256(canonical(r)).hexdigest()[:16],
            "describes": r["event_time"],
            "known_at": read_at,
            "account": account,
            "object_id": r.get("object_id"),
            "meta": r,
        }
        for r in sorted(rows, key=lambda r: r["event_time"])
    ]


def main(client_id: str) -> Path:
    store = sqlite3.connect(f"file:{LIVE / 'live.sqlite'}?mode=ro", uri=True)
    store.row_factory = sqlite3.Row
    now = datetime.now(UTC)
    read_at = now.isoformat(timespec="seconds")
    out = LIVE / "exports" / client_id / now.strftime("%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True)
    files = {"polls.jsonl": polls(store, client_id), "runs.jsonl": runs(store, client_id)}
    account = store.execute(
        "SELECT account_id FROM polls WHERE client_id = ? LIMIT 1", (client_id,)
    ).fetchone()["account_id"].removeprefix("act_")
    first = store.execute("SELECT min(date) FROM rows WHERE client_id = ?", (client_id,)).fetchone()[0]
    token = os.environ.get("META_ACCESS_TOKEN")
    skipped = []
    if token:
        files["backfill.jsonl"] = backfill(account, first, token, read_at)
        files["changes.jsonl"] = changes(account, token, read_at)
    else:
        skipped = ["backfill.jsonl", "changes.jsonl"]
    manifest = {"client_id": client_id, "written_at": read_at, "store_first_day": first,
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
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    folder = main(sys.argv[1])
    print(folder)
    print((folder / "manifest.json").read_text())
