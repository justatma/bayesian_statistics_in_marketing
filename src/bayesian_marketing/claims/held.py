"""The held status (Brain join J7, S39): a quantity's status damped so that a drop shows at once
and a rise shows only once it has held for a full account-local day. A pure function of a run and
the client's earlier runs; never stored."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ORDER = ("below_floor", "marginal", "estimable")
"""S39 (J7 (1)): less certain first."""

HeldKey = tuple[str, str, str, str, str]
"""S39 (4): (level, subject id, quantity name, conversion kind, metric). The decision status uses
("decision", "", "", conversion kind, metric)."""

HELD_REASON = "held at {held} until {raw} has held for a day"
"""S39 (8): added to a posterior entry's ``status_reasons`` when held is below raw."""

_RANK = {s: i for i, s in enumerate(ORDER)}
_UTC = dt.UTC


def rank(status: str) -> int:
    """A status's place in ``ORDER``; anything else raises."""
    try:
        return _RANK[status]
    except KeyError:
        raise ValueError(f"unknown status {status!r}") from None


def quantity_key(level: str, subject: str | None, name: str, kind: str, metric: str) -> HeldKey:
    """S39 (4): a quantity's identity across runs."""
    return (str(level), "" if subject is None else str(subject), str(name), str(kind), str(metric))


def decision_key(kind: str, metric: str) -> HeldKey:
    """S39 (5): the decision status's identity across runs."""
    return ("decision", "", "", str(kind), str(metric))


def run_kind(conversion_kind: str | None, synthetic: bool, client_id: str) -> str:
    """The conversion kind in a held key: the snapshot's own, and for one saved before J5 the
    renderer's R9 rule (a synthetic run is "purchase"; else the client config's, else "lead" if
    any of the client's runs says lead, else "purchase"), so the renderer and ``result_of`` look
    up the key ``held_status`` wrote."""
    if conversion_kind is not None:
        return str(conversion_kind)
    if synthetic:
        return "purchase"
    from bayesian_marketing.claims import _refs as R

    return R.config_kind(client_id) or R.kind_from_runs(client_id) or "purchase"


def back_one_day(t: dt.datetime, zone: ZoneInfo) -> dt.datetime:
    """J7 (3): the same local clock time on the previous date, so a daylight-saving day still
    counts as one day."""
    local = t.astimezone(zone).replace(tzinfo=None)
    return (local - dt.timedelta(days=1)).replace(tzinfo=zone).astimezone(_UTC)


def held_status(run_id: str, *, timezone: str | None = None) -> dict[HeldKey, str]:
    """S39: the held status of every quantity present in ``run_id``, and of its decision.
    Raises when the zone can't be found, two zones are found, the run record can't be read, or a
    run file in the series can't be read (S39 (6), (7))."""
    from bayesian_marketing import pipeline

    started = _started_at()  # S39 (7): raises when the run record can't be read
    if run_id not in started:
        raise LookupError(f"run {run_id!r} is not in the run record, so it has no started_at")
    runs_dir = pipeline.data_dir() / pipeline.RUNS_DIR
    target = _read_run(runs_dir / f"{run_id}.json", run_id)
    client = target["client_id"]
    zone = ZoneInfo(_zone(run_id, target, timezone))
    me = (started[run_id], run_id)

    series: list[tuple[dt.datetime, str, dict[str, Any]]] = []
    for rid, t in sorted(started.items(), key=lambda kv: (kv[1], kv[0])):
        if (t, rid) >= me:
            break
        path = runs_dir / f"{rid}.json"
        if not path.is_file():  # S39 (7): a record entry with no file is skipped
            continue
        d = _read_run(path, rid)
        if d["client_id"] != client or d.get("synthetic"):
            continue
        series.append((t, rid, d))
    series.append((started[run_id], run_id, target))

    kinds = _Kinds(client)
    state: dict[HeldKey, int] = {}
    hist: dict[HeldKey, list[tuple[dt.datetime, dt.datetime, int]]] = {}
    seen: dict[tuple[str, str, str], set[str]] = {}  # (ad, kind, metric) -> quantity names
    out: dict[HeldKey, str] = {}
    for t, _rid, d in series:
        back = back_one_day(t, zone)
        raw = _raw(d, kinds(d), seen)
        out = {}
        for k, r in raw.items():
            h = hist.setdefault(k, [])
            h.append((t, back, r))
            held = state.get(k, 0)  # S39 (2): every series starts at below_floor
            if r < held:  # a drop shows at once
                held = r
            elif r > held:  # S39 (1): a rise waits for a streak of a day
                level = _streak(h)
                if level is not None and level > held:
                    held = level
            state[k] = held
            out[k] = ORDER[held]
    return out


def _streak(h: list[tuple[dt.datetime, dt.datetime, int]]) -> int | None:
    """S39 (1): the lowest raw over the present runs back to the latest run R that started at
    or before this run's start minus one calendar day, with no two consecutive present runs more
    than a day apart; None when there is no such R. ``h`` is (start, start less a day, raw)."""
    cutoff = h[-1][1]
    level = h[-1][2]
    for i in range(len(h) - 1, -1, -1):
        when, _back, r = h[i]
        if i < len(h) - 1 and when < h[i + 1][1]:
            return None  # a gap of more than a day: the streak restarts at the later run
        level = min(level, r)
        if when <= cutoff:
            return level
    return None


def _raw(
    d: dict[str, Any], kind: str, seen: dict[tuple[str, str, str], set[str]]
) -> dict[HeldKey, int]:
    """S39 (1), (3), (5), S41 (3): the raw status of every key present in a run, as a rank. An
    ad is present when it is among ``variants``; its names are this run's quantities for it, its
    ``not_estimable`` names, the run's metric quantity (J7 (1)) and every name its series has
    held before, and a name with no quantity is ``below_floor``. A non-ad quantity is present
    when it is in the run. The decision is present when the run has one."""
    from bayesian_marketing import pipeline

    metric = str(d["metric"])
    variants = {str(v): str(ad) for v, ad in d["variants"].items()}
    present = set(variants.values())
    out: dict[HeldKey, int] = {}
    for q in d["quantities"]:
        level = str(q["scope"]["level"])
        sid = q["scope"]["ids"].get(level)
        if level == "ad" and str(sid) not in present:
            continue
        k = quantity_key(level, sid, q["name"], kind, metric)
        r = rank(q["feasibility"]["status"])
        out[k] = min(out[k], r) if k in out else r
    for v, names in (d.get("not_estimable") or {}).items():
        ad = variants.get(str(v))
        if ad is not None:
            for name in names:
                out.setdefault(quantity_key("ad", ad, name, kind, metric), 0)
    mq = pipeline.metric_quantity(metric)
    for ad in present:
        names = seen.setdefault((ad, kind, metric), set())
        for name in [mq, *sorted(names)]:
            out.setdefault(quantity_key("ad", ad, name, kind, metric), 0)
    for level, sid, name, k_kind, k_metric in out:
        if level == "ad":
            seen.setdefault((sid, k_kind, k_metric), set()).add(name)
    dec = d.get("decision")
    if dec is not None:
        out[decision_key(kind, metric)] = rank(dec["status"])
    return out


class _Kinds:
    """``run_kind`` per run, the client's fallback read once per call."""

    def __init__(self, client: str) -> None:
        self.client = client
        self._fallback: str | None = None

    def __call__(self, d: dict[str, Any]) -> str:
        if d.get("conversion_kind") is not None or d.get("synthetic"):
            return run_kind(d.get("conversion_kind"), bool(d.get("synthetic")), self.client)
        if self._fallback is None:
            self._fallback = run_kind(None, False, self.client)
        return self._fallback


def _started_at() -> dict[str, dt.datetime]:
    """Every run-record entry's ``started_at``, read only. Raises when the record can't be read
    or an entry has no ``started_at`` (S39 (7))."""
    from pydantic import TypeAdapter

    from bayesian_marketing.decision import run_record

    path = run_record._db_path()
    if not path.is_file():
        raise FileNotFoundError(f"no run record at {path}")
    con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        rows = con.execute(
            f"SELECT payload FROM {run_record.TABLES['RunRecord']} ORDER BY seq"
        ).fetchall()
    finally:
        con.close()
    parse: Callable[[Any], dt.datetime] = TypeAdapter(dt.datetime).validate_python
    out: dict[str, dt.datetime] = {}
    for (payload,) in rows:
        rec = json.loads(payload)
        t = parse(rec["started_at"])
        if t.tzinfo is None:
            raise ValueError(f"run {rec['run_id']}: started_at {rec['started_at']!r} has no zone")
        out[str(rec["run_id"])] = t
    return out


def _read_run(path: Path, run_id: str) -> dict[str, Any]:
    """A run file as JSON. Raises when it can't be read or isn't a run snapshot."""
    d = json.loads(path.read_text())
    if not isinstance(d, dict) or not isinstance(d.get("client_id"), str):
        raise ValueError(f"run file {path.name} is not a run snapshot")
    if d.get("run_id") != run_id:
        raise ValueError(f"run file {path.name} holds run {d.get('run_id')!r}")
    for field in ("metric", "variants", "quantities"):
        if field not in d:
            raise ValueError(f"run file {path.name} has no {field}")
    return d


def _zone(run_id: str, snap: dict[str, Any], explicit: str | None) -> str:
    """S39 (6), S41 (6): the explicit zone, else the snapshot's, else the zone of the store's
    poll for the run (``refreshes`` to ``poll_outcomes``), else the one zone among the client's
    ok polls. Only that last step raises on two zones (``ValueError``, as S29). No zone raises."""
    if explicit is not None:
        return explicit
    if snap.get("timezone"):
        return str(snap["timezone"])
    from bayesian_marketing.claims import _refs as R

    path = R._live_store_path()  # S41 (4): as ``default_load_names`` finds it
    if path is None:
        raise LookupError(f"run {run_id}: no time zone in the snapshot and no live store")
    con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        row = con.execute(
            "SELECT o.timezone FROM refreshes r JOIN poll_outcomes o ON o.poll_id = r.poll_id "
            "WHERE r.run_id = ? AND o.timezone IS NOT NULL ORDER BY r.at LIMIT 1",
            (run_id,),
        ).fetchone()
        if row is not None:
            return str(row[0])
        zones = sorted(
            str(z)
            for (z,) in con.execute(
                "SELECT DISTINCT o.timezone FROM polls p JOIN poll_outcomes o "
                "ON o.poll_id = p.poll_id WHERE p.client_id = ? AND o.status = 'ok' "
                "AND o.timezone IS NOT NULL",
                (snap["client_id"],),
            ).fetchall()
        )
    finally:
        con.close()
    if len(zones) > 1:
        raise ValueError(f"expected one account time zone, found {zones}")
    if not zones:
        raise LookupError(f"run {run_id}: no time zone in the snapshot, its poll or the store")
    return zones[0]
