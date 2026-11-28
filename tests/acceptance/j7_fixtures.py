"""Fixtures for the J7 acceptance set (Brain join spec v0.4, J7 and S39).

A held-status series is many runs of one client with chosen ``started_at``, raw statuses and
variants. Running the sampler for each would be slow and would not let a case choose a status, so
the series is built from one template run: a lead run of three ads (j4_fixtures' IMG3 and IMG2,
plus IMG4) made once by ``refresh`` against ``FakeStore`` in its own data dir, and cached for the
session. Each series run is a copy of the template's snapshot JSON with the case's edits, written
as ``<data_dir>/runs/<run_id>.json``, plus a ``RunRecord`` (the template's, with the run id,
``started_at`` and quantity ids changed) appended to the run record in the same data dir.
Quantity ids are made unique per run, so nothing can key a series on a quantity id.

The template is edited once: names for the three ads and the ad set (S16), IMG3's ctr at 4.4%
(q05 4.0%, q95 4.7%), a comparison record with IMG3 leading at 0.621 (so a cmp slot names a
leader and its caveat follows the status only), the account's ``timezone`` America/New_York, and
one ad-set-level quantity (``cvr`` of ad set ``s1``) for the non-ad cases of S39 (5).

The data dir is ``J4REnv.data_dir`` (``tmp_path / "engine_data"``), entered with ``env.in_data``.
The live store, when a case needs one, is a real ``SqliteStore`` at ``tmp_path / "live" /
"live.sqlite"``, and ``BAYES_LIVE_DIR`` names ``tmp_path / "live"`` in every case, so the two ways
the engine finds a live store (``BAYES_LIVE_DIR``, and ``data_dir().parent / "live"``) both name
it, and no case can reach ``data/live/``.

``oracle_held`` is S39's rule written from the text alone, used by the property test.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from bayesian_marketing import core as C
from bayesian_marketing import pipeline
from bayesian_marketing.atmaos import socket as sock
from bayesian_marketing.decision import run_record
from bayesian_marketing.live.contracts import PollRecord, RefreshRecord
from bayesian_marketing.live.refresh import data_dir_env, refresh
from bayesian_marketing.live.store import SqliteStore
from tests.acceptance import j2_fixtures as J2
from tests.acceptance import j4_fixtures as X
from tests.acceptance.j4_fixtures import CLIENT, IMG2_ID, IMG3_ID, IMG4_ID
from tests.acceptance.j4r_fixtures import J4REnv
from tests.acceptance.test_J5 import LEAD
from tests.acceptance.test_L5 import config
from tests.fakes.live import FakeStore, FixedClock

UTC = dt.UTC
NY = "America/New_York"
LONDON = "Europe/London"
ORDER = ("below_floor", "marginal", "estimable")
RANK = {s: i for i, s in enumerate(ORDER)}
B, M, E = ORDER  # below_floor, marginal, estimable

ADS = (IMG3_ID, IMG2_ID, IMG4_ID)
ADSET = "s1"
ADSET_NAME = "Set One"
NAMES = {IMG3_ID: X.IMG3, IMG2_ID: "IMG2_TXT1", IMG4_ID: X.IMG4, ADSET: ADSET_NAME}
P_BEST = {IMG3_ID: 0.621, IMG2_ID: 0.300, IMG4_ID: 0.079}
KIND = "lead"
METRIC = "ctr"
ROUGH = "still a rough estimate"
NOT_KNOWABLE = "not knowable yet"

#: The fig forms of IMG3's ctr (4.4%) on the newest run, from J4R's Forms table.
CTR_FULL = {
    E: "IMG3_TXT1's click-through rate of 4.4%",
    M: "IMG3_TXT1's click-through rate of about 4.4%, still a rough estimate",
    B: "IMG3_TXT1's click-through rate, which is not knowable yet",
}

#: Posterior entry keys as ``socket._posterior_entry`` gives them at the J7 skeleton (98886cb).
#: J7 adds ``held_status`` and ``fit_route`` to both, and ``held_status_reason`` when held is null.
QUANTITY_ENTRY_KEYS = frozenset(
    {
        "entity",
        "metric",
        "synthetic",
        "rows_form",
        "rows_sha256",
        "row_keys",
        "quantity_id",
        "summary",
        "status",
        "status_basis",
        "status_reasons",
        "evidence_class",
        "inventory_class",
        "design",
        "route",
        "funnel_state_id",
        "notices",
        "published",
    }
)
BELOW_FLOOR_ENTRY_KEYS = frozenset(
    {
        "entity",
        "metric",
        "synthetic",
        "rows_form",
        "rows_sha256",
        "row_keys",
        "quantity_id",
        "status",
        "status_reasons",
        "summary",
        "evidence_class",
        "inventory_class",
        "design",
        "notices",
        "published",
    }
)
NEW_ENTRY_KEYS = frozenset({"held_status", "held_status_reason", "fit_route"})

HeldKey = tuple[str, str, str, str, str]


def key(ad: str = IMG3_ID, name: str = "ctr", kind: str = KIND, metric: str = METRIC) -> HeldKey:
    """S39 (4): (level, subject id, quantity name, conversion kind, metric)."""
    return ("ad", ad, name, kind, metric)


def decision_key(kind: str = KIND, metric: str = METRIC) -> HeldKey:
    """S39 (5), as the skeleton's ``HeldKey`` docstring writes it."""
    return ("decision", "", "", kind, metric)


def adset_key(name: str = "cvr", kind: str = KIND, metric: str = METRIC) -> HeldKey:
    return ("ad_set", ADSET, name, kind, metric)


def at(s: str) -> dt.datetime:
    """``"2026-11-10T12:00"`` as UTC."""
    return dt.datetime.fromisoformat(s).replace(tzinfo=UTC)


def hours(start: dt.datetime, n: int, step: float = 1.0) -> list[dt.datetime]:
    return [start + dt.timedelta(hours=step * i) for i in range(n)]


# ------------------------------------------------------------------ the template (cached)

_TEMPLATE: dict[str, Any] = {}


def _template(env: J4REnv) -> tuple[dict[str, Any], dict[str, Any]]:
    """The template snapshot JSON and run-record JSON, built once per session."""
    if not _TEMPLATE:
        tdir = env.tmp / "template_data"
        store = FakeStore()
        clock = FixedClock(X.START_OLD + dt.timedelta(minutes=30))
        ads = {IMG3_ID: (1000, 40), IMG2_ID: (1000, 60), IMG4_ID: (1000, 50)}
        rec = refresh(
            config(**LEAD),
            X.seed_poll(store, X.START_OLD, X.WINDOW_OLD, ads, 70),
            store,
            clock,
            data_dir=tdir,
            config_root=env.config_root,
        )
        assert rec.status == "ran", rec.reason
        snap = json.loads((tdir / "runs" / f"{rec.run_id}.json").read_text())
        with data_dir_env(tdir):
            (record,) = run_record.read("RunRecord", run_id=rec.run_id)
        _shape_template(snap)
        pipeline.RunSnapshot.model_validate(snap)
        _TEMPLATE["snap"] = snap
        _TEMPLATE["record"] = json.loads(record.model_dump_json())
    return copy.deepcopy(_TEMPLATE["snap"]), copy.deepcopy(_TEMPLATE["record"])


def _shape_template(d: dict[str, Any]) -> None:
    assert d["conversion_kind"] == KIND and d["metric"] == METRIC
    assert sorted(d["variants"].values()) == sorted(ADS)
    d["entity_names"] = dict(NAMES)
    d["entity_parents"] = {ad: ADSET for ad in ADS}
    d["timezone"] = NY
    for q in d["quantities"]:
        if q["name"] == "ctr" and q["scope"]["ids"] == {"ad": IMG3_ID}:
            q["estimate"]["summary"].update(q50=0.044, mean=0.044, q05=0.040, q95=0.047)
    cvr = next(q for q in d["quantities"] if q["name"] == "cvr")
    adset_q = copy.deepcopy(cvr)
    adset_q["quantity_id"] = "q_adset000"
    adset_q["scope"]["level"] = "ad_set"
    adset_q["scope"]["ids"] = {"ad_set": ADSET}
    d["quantities"].append(adset_q)
    d["published"]["q_adset000"] = True
    d["comparison"]["p_best"] = dict(P_BEST)


# ------------------------------------------------------------------ a series run

_KEEP = object()


@dataclass
class Run:
    """What a series run was built with, for the oracle and the raw-status reads."""

    run_id: str
    at: dt.datetime
    client: str
    raw: dict[HeldKey, str] = field(default_factory=dict)


def _set_status(f: dict[str, Any], status: str) -> None:
    f["status"] = status
    if status == E:
        f["reasons"] = []
    elif not f["reasons"]:
        f["reasons"] = [f"set {status} for the case"]
    if status == B:
        f["required"] = 4000.0


def _replace_client(x: Any, client: str) -> None:
    if isinstance(x, dict):
        for k, v in x.items():
            if k == "client_id" and isinstance(v, str):
                x[k] = client
            else:
                _replace_client(v, client)
    elif isinstance(x, list):
        for v in x:
            _replace_client(v, client)


def raw_of(d: Mapping[str, Any], k: HeldKey) -> str | None:
    """The raw status of a held key in a snapshot's JSON, by S39 (1), (3) and (5): the stored
    ``feasibility.status``; ``below_floor`` when the subject is present and the quantity isn't;
    the decision's status for the decision key."""
    level, sid, name, _kind, _metric = k
    if level == "decision":
        dec = d.get("decision")
        return None if dec is None else str(dec["status"])
    for q in d["quantities"]:
        if (
            q["name"] == name
            and q["scope"]["level"] == level
            and q["scope"]["ids"].get(level) == sid
        ):
            return str(q["feasibility"]["status"])
    return B


class J7Env(J4REnv):
    """J4REnv with a series builder, a SQLite live store in ``tmp_path / "live"`` and the held
    and result calls run inside the data dir."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        super().__init__(tmp_path, monkeypatch)
        self.tmp = tmp_path
        self.live_dir = tmp_path / "live"
        self.live_dir.mkdir()
        monkeypatch.setenv("BAYES_LIVE_DIR", str(self.live_dir))
        self._store: SqliteStore | None = None
        self._n = 0
        self.runs: list[Run] = []

    def close(self) -> None:
        if self._store is not None:
            self._store.close()
            self._store = None

    # the series

    def put_run(
        self,
        when: dt.datetime,
        ctr: str | Mapping[str, str] = M,
        *,
        status: Mapping[tuple[str, str], str] | None = None,
        absent: Iterable[str] = (),
        not_estimable: Iterable[tuple[str, str]] = (),
        gone: Iterable[tuple[str, str]] = (),
        decision: str | None = E,
        kind: str = KIND,
        metric: str | None = None,
        tz: Any = _KEEP,
        client: str = CLIENT,
        synthetic: bool = False,
        run_id: str | None = None,
        record: bool = True,
        file: bool = True,
        window: tuple[dt.date, dt.date] | None = None,
        fit_step: Any = _KEEP,
        route_kind: str | None = None,
    ) -> str:
        """Write one series run and return its id.

        ``ctr`` is the raw status of every present ad's ctr (a string), or per ad (a mapping;
        ads left out keep marginal). ``status`` sets other quantities, keyed (subject id, name),
        the subject an ad id or ``ADSET``. ``absent`` ads are taken out of ``variants`` with all
        their quantities. ``not_estimable`` removes a quantity and lists its name in
        ``not_estimable``; ``gone`` removes it without listing it. ``tz`` is the snapshot's
        ``timezone`` (default America/New_York; ``None`` for a pre-J7 snapshot). ``record`` and
        ``file`` choose whether the run-record entry and the run file are written.
        """
        d, rec = _template(self)
        self._n += 1
        rid = run_id or (
            "run_"
            + hashlib.sha256(f"j7|{client}|{when.isoformat()}|{self._n}".encode()).hexdigest()[:8]
        )
        d["run_id"] = rid
        d["client_id"] = client
        if client != CLIENT:
            _replace_client(d, client)
        d["synthetic"] = synthetic
        d["conversion_kind"] = kind
        if metric is not None:
            d["metric"] = metric
            d["compare_quantity"] = pipeline.metric_quantity(metric)
        if tz is not _KEEP:
            d["timezone"] = tz
        if window is not None:
            d["window"] = [window[0].isoformat(), window[1].isoformat()]
        if fit_step is not _KEEP:
            if fit_step is None:
                d["configuration"].pop("fit_step", None)
            else:
                d["configuration"]["fit_step"] = fit_step
        if route_kind is not None:
            d["route"]["kind"] = route_kind

        per_ad = (
            {ad: ctr for ad in ADS} if isinstance(ctr, str) else {ad: M for ad in ADS} | dict(ctr)
        )
        sets: dict[tuple[str, str], str] = {(ad, "ctr"): s for ad, s in per_ad.items()}
        sets.update(status or {})
        for q in d["quantities"]:
            level = q["scope"]["level"]
            sid = q["scope"]["ids"].get(level)
            if (sid, q["name"]) in sets:
                _set_status(q["feasibility"], sets[(sid, q["name"])])
        if decision is None:
            d["decision"] = None
        else:
            _set_status(d["decision"], decision)

        absent = set(absent)
        drop = set(not_estimable) | set(gone)
        if absent:
            for v, ad in list(d["variants"].items()):
                if ad in absent:
                    del d["variants"][v]
                    d["not_estimable"].pop(v, None)
            comp = d["comparison"]
            comp["options"] = [o for o in comp["options"] if o not in absent]
            for f in (
                "p_best",
                "expected_value",
                "expected_loss",
                "value_q05",
                "p_exceeds_break_even",
            ):
                comp[f] = {o: x for o, x in comp[f].items() if o not in absent}
            d["recommendations"] = []
        kept = []
        for q in d["quantities"]:
            ad = q["scope"]["ids"].get("ad")
            if ad in absent or (ad, q["name"]) in drop:
                d["published"].pop(q["quantity_id"], None)
                continue
            kept.append(q)
        d["quantities"] = kept
        ad_to_variant = {ad: v for v, ad in d["variants"].items()}
        for ad, name in not_estimable:
            d["not_estimable"].setdefault(ad_to_variant[ad], {})[name] = (
                "not estimable for the case"
            )

        # quantity ids unique per run
        new_ids = {
            q["quantity_id"]: "q_"
            + hashlib.sha256(f"{rid}|{q['quantity_id']}".encode()).hexdigest()[:8]
            for q in d["quantities"]
        }
        for q in d["quantities"]:
            q["quantity_id"] = new_ids[q["quantity_id"]]
        d["published"] = {new_ids.get(k, k): v for k, v in d["published"].items() if k in new_ids}
        for r in d["recommendations"]:
            r["basis"] = [new_ids.get(b, b) for b in r["basis"]]

        pipeline.RunSnapshot.model_validate(d)  # the run file loads
        if file:
            path = self.data_dir / "runs" / f"{rid}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            assert not path.exists(), rid
            path.write_text(json.dumps(d))
        if record:
            rec.update(
                run_id=rid,
                started_at=when.isoformat(),
                quantity_ids=[new_ids[q] for q in rec["quantity_ids"] if q in new_ids],
                recommendation_ids=[r["recommendation_id"] for r in d["recommendations"]],
            )
            obj = C.RunRecord.model_validate(rec)
            self.in_data(run_record.append, obj)

        k_metric = d["metric"]
        raw: dict[HeldKey, str] = {}
        for ad in d["variants"].values():
            raw[key(ad, "ctr", kind, k_metric)] = raw_of(d, key(ad, "ctr", kind, k_metric))  # type: ignore[assignment]
        if d["decision"] is not None:
            raw[decision_key(kind, k_metric)] = str(d["decision"]["status"])
        self.runs.append(Run(rid, when, client, raw))
        return rid

    def series(self, steps: Iterable[tuple[dt.datetime, Any]], **kw: Any) -> list[str]:
        """``put_run(when, ctr, **kw)`` for each (when, ctr)."""
        return [self.put_run(w, c, **kw) for w, c in steps]

    def snap_json(self, run_id: str) -> dict[str, Any]:
        return json.loads((self.data_dir / "runs" / f"{run_id}.json").read_text())

    # the calls

    def held(self, run_id: str, **kw: Any) -> dict[Any, str]:
        from bayesian_marketing.claims.held import held_status

        return self.in_data(lambda: held_status(run_id, **kw))

    def result(self, run_id: str) -> dict[str, Any]:
        return self.in_data(lambda: sock.result_of(pipeline.load_snapshot(run_id)))

    def result_of_snapshot(self, snap: pipeline.RunSnapshot) -> dict[str, Any]:
        return self.in_data(lambda: sock.result_of(snap))

    def menu7(self, **kw: Any) -> dict[str, Any]:
        kw.setdefault("load_parents", lambda c: {})
        kw.setdefault("load_display_names", lambda c: {})
        return self.menu(**kw)

    def render7(self, text: str, **kw: Any) -> dict[str, Any]:
        kw.setdefault("load_parents", lambda c: {})
        kw.setdefault("load_display_names", lambda c: {})
        return self.render(text, **kw)

    def qid(self, run_id: str, ad: str, name: str) -> str:  # type: ignore[override]
        hits = [
            q["quantity_id"]
            for q in self.snap_json(run_id)["quantities"]
            if q["name"] == name and q["scope"]["ids"].get(q["scope"]["level"]) == ad
        ]
        assert len(hits) == 1, hits
        return hits[0]

    def raw_held_map(
        self, run_id: str, overrides: Mapping[HeldKey, str] | None = None
    ) -> dict[HeldKey, str]:
        """A fake ``load_held`` answer for ``run_id``: every key at its raw status, then the
        overrides."""
        d = self.snap_json(run_id)
        kind, metric = d["conversion_kind"], d["metric"]
        out: dict[HeldKey, str] = {}
        for q in d["quantities"]:
            level = q["scope"]["level"]
            out[(level, q["scope"]["ids"][level], q["name"], kind, metric)] = q["feasibility"][
                "status"
            ]
        if d["decision"] is not None:
            out[decision_key(kind, metric)] = d["decision"]["status"]
        out.update(overrides or {})
        return out

    # the live store

    @property
    def store_path(self) -> Path:
        return self.live_dir / "live.sqlite"

    def sqlite(self) -> SqliteStore:
        if self._store is None:
            self._store = SqliteStore.open(self.store_path)
        return self._store

    def store_poll(
        self, when: dt.datetime, tz: str | None, *, client: str = CLIENT, status: str = "ok"
    ) -> PollRecord:
        rec = J2.poll_record(client, when, status=status, timezone=tz)
        store = self.sqlite()
        store.begin_poll(rec)
        store.finish_poll(rec, [])
        return rec

    def store_refresh(self, poll: PollRecord, run_id: str) -> RefreshRecord:
        when = poll.started_at + dt.timedelta(minutes=10)
        rr = RefreshRecord(
            refresh_id="lv_"
            + hashlib.sha256(f"{poll.poll_id}|{when.isoformat()}".encode()).hexdigest()[:8],
            poll_id=poll.poll_id,
            client_id=poll.client_id,
            at=when,
            status="ran",
            reason=None,
            run_id=run_id,
        )
        self.sqlite().add_refresh(rr)
        return rr

    def files_under_data_dir(self) -> dict[str, bytes]:
        """Every file under the data dir with its bytes, the run record's SQLite file by name
        only (its bytes may be rewritten by a read that changes nothing)."""
        out: dict[str, bytes] = {}
        for p in sorted(self.data_dir.rglob("*")):
            if p.is_file():
                rel = str(p.relative_to(self.data_dir))
                out[rel] = b"" if rel.startswith(run_record.DB_NAME) else p.read_bytes()
        return out


# ------------------------------------------------------------------ S39 from its text (the oracle)


def back_one_day(t: dt.datetime, zone: ZoneInfo) -> dt.datetime:
    """J7 (3): the same local clock time on the previous date."""
    local = t.astimezone(zone)
    prev = (local.replace(tzinfo=None) - dt.timedelta(days=1)).replace(tzinfo=zone)
    return prev.astimezone(UTC)


def _streak_level(hist: list[tuple[dt.datetime, str]], zone: ZoneInfo) -> str | None:
    """S39 (1): the level every present run back to a run R at or before this start minus one
    calendar day has had, with no two consecutive present runs more than a day apart; None when
    there is no such R."""
    now = hist[-1][0]
    cutoff = back_one_day(now, zone)
    level = hist[-1][1]
    for i in range(len(hist) - 1, -1, -1):
        when, raw = hist[i]
        if i < len(hist) - 1 and when < back_one_day(hist[i + 1][0], zone):
            return None  # the streak restarts at the later run, which is after the cutoff
        level = min(level, raw, key=RANK.__getitem__)
        if when <= cutoff:
            return level
    return None


def oracle_held(runs: Iterable[Run], tz: str) -> dict[str, dict[HeldKey, str]]:
    """S39 (1) to (3) per key, in (started_at, run_id) order, over the client's runs given."""
    zone = ZoneInfo(tz)
    order = sorted(runs, key=lambda r: (r.at, r.run_id))
    hist: dict[HeldKey, list[tuple[dt.datetime, str]]] = {}
    state: dict[HeldKey, str] = {}
    out: dict[str, dict[HeldKey, str]] = {}
    for r in order:
        res: dict[HeldKey, str] = {}
        for k, raw in r.raw.items():
            h = hist.setdefault(k, [])
            h.append((r.at, raw))
            held = state.get(k, B)  # S39 (2): starts at below_floor
            if RANK[raw] < RANK[held]:
                held = raw
            elif RANK[raw] > RANK[held]:
                lvl = _streak_level(h, zone)
                if lvl is not None and RANK[lvl] > RANK[held]:
                    held = lvl
            state[k] = held
            res[k] = held
        out[r.run_id] = res
    return out


def write_garbage(path: Path) -> None:
    os.chmod(path, 0o644)
    path.write_bytes(b"this is not a readable file\x00\xff")
