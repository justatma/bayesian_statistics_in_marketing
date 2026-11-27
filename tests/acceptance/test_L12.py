"""L12: re-read 28 days, analyse 7 (live view spec v0.2, L12 items 1 to 7; L12.1 to L12.6, which
govern where they differ; D55). Pointer rules from the Brain join spec v0.4, J1, J2, S28 to S37.

How the checks are driven:

* The refresh runs against ``FakeStore`` (where the export is not involved) or a real
  ``SqliteStore`` laid out as the export expects (``l12_fixtures.L12Env``), with real economics
  and an approved client CTR prior, as test_L4 and the J2 fixtures do. ``pipeline.execute`` is
  wrapped, never replaced, to keep what the refresh passed.
* The export is ``scripts/export_history.py`` loaded from its file, ``versioned`` then ``runs()``
  as its ``main`` calls them, with the module's ``LIVE`` patched to the test's ``tmp_path``.
* The analysis width is read from the registry the iso fixture copies (``BAYES_REGISTRY_DIR``),
  which after the build holds ``lookback_days: 28`` and ``analysis_days: 7``.
* (j) is a replay: a 28-day pull paged 25 rows a page is recorded through ``pull()`` against an
  httpx mock (``BAYES_RECORD_DIR``), then served back with sockets blocked (``BAYES_REPLAY_DIR``).
  The replay machinery expresses pages (each page is its own exchange, keyed by its redacted
  ``after`` URL), so the poll itself is tested on it, and the connector too.

Checks that hold today and must keep holding are marked "guard" in their docstrings: (d), (i), the
7-day and 3-day widths of L12.4, and the connector half of (j).
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from bayesian_marketing import core as C
from bayesian_marketing import pipeline
from bayesian_marketing.core import inputs_hash, registries
from bayesian_marketing.data_contract.connectors import http as H
from bayesian_marketing.data_contract.connectors.pull import pull
from bayesian_marketing.live import horizon as live_horizon
from bayesian_marketing.live import refresh as refresh_mod
from bayesian_marketing.live import rows as live_rows
from bayesian_marketing.live import view
from bayesian_marketing.live.poll import poll
from bayesian_marketing.live.refresh import ONE_AD
from bayesian_marketing.live.registry import LiveRegistry, load_live_registry
from bayesian_marketing.live.store import SqliteStore
from bayesian_marketing.prior_registry import registry as prior_registry
from tests.acceptance import j2_fixtures as j2
from tests.acceptance import j2_oracle
from tests.acceptance.l12_fixtures import (
    CLIENT,
    DAYS7,
    DAYS28,
    END,
    META_ADS,
    OLD,
    OLD_LABEL,
    PREFIX,
    REPO,
    T0,
    TZ,
    W7,
    W28,
    WIN_LABEL,
    L12Env,
    add_poll,
    days_of,
    live_row,
    make_env,
    meta_rows_28,
    old_rows,
    paging_handler,
    posteriors,
    window,
    window_rows,
)
from tests.fakes.live import FakeStore, FixedClock
from tests.fakes.meta_api import META_TOKEN

pytestmark = pytest.mark.piece("L12")

UTC = dt.UTC
REAL_CLIENT = httpx.Client
KEY = re.compile(r"^meta:([^:]+):(\d{4}-\d{2}-\d{2}):v(\d+)$")


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[L12Env]:
    yield from make_env(tmp_path, monkeypatch)


def iso(w: tuple[Any, Any]) -> tuple[str, str]:
    """A window as ISO text, whether given as dates or as text."""
    return str(w[0]), str(w[1])


def key_date(key: str) -> dt.date:
    m = KEY.match(key)
    assert m, key
    return dt.date.fromisoformat(m.group(2))


def keys_for(ads: tuple[str, ...], days: list[dt.date], v: int = 1) -> list[str]:
    return sorted(f"meta:{ad}:{d.isoformat()}:v{v}" for ad in ads for d in days)


def request_key(request: Any) -> Any:
    """The request as pipeline hashes it for the seed and run id (S13; J2's copy)."""
    if request.conversion_kind == "purchase":
        return request.model_dump(mode="json", exclude={"conversion_kind", "horizon_basis"})
    return request.model_dump(mode="json", exclude={"horizon_basis"})


def canon(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


# ------------------------------------------------------------------ item 1, (c): the registry


def test_L12_item1_real_registry_reads_28_and_analyses_7() -> None:
    """The amended ``tests/unit/l0/test_l0.py`` expectation (L12.1, last point), on the real
    ``registries/live.yaml``: lookback 28, a new ``analysis_days: 7``, version and
    freshness_date bumped to 2026-11-27 (L12.3); everything else as the 7 November rulings."""
    root = REPO / "registries"
    registries.clear_cache()
    try:
        raw = yaml.safe_load((root / "live.yaml").read_text())
        r = load_live_registry(root)
    finally:
        registries.clear_cache()
    assert raw.get("analysis_days") == 7  # item 1: written in the file, not left to the default
    assert (r.lookback_days, r.analysis_days) == (28, 7)  # item 1, D55
    assert (str(r.version), r.freshness_date) == ("2026-11-27", "2026-11-27")  # L12.3
    assert (r.interval_seconds, r.stale_after_seconds) == (3600, 7200)
    assert (r.bind, r.port, r.recordings_keep_days, r.page_refresh_seconds) == (
        "127.0.0.1",
        8765,
        7,
        300,
    )
    assert r.account_status["1"] == "active" and "4" not in r.account_status


def _set_widths(iso: Any, lookback: int, analysis: int) -> None:
    def edit(d: dict[str, Any]) -> None:
        d["lookback_days"] = lookback
        d["analysis_days"] = analysis

    iso.edit_yaml("live", edit)


@pytest.mark.parametrize(("lookback", "analysis"), [(7, 8), (28, 29), (1, 2), (28, 100)])
def test_L12_c_analysis_days_above_lookback_days_fails_to_load(
    iso: Any, lookback: int, analysis: int
) -> None:
    _set_widths(iso, lookback, analysis)
    with pytest.raises(Exception) as got:  # item 1, (c): the registry fails to load
        load_live_registry(iso.registry)
    assert not isinstance(got.value, (KeyError, FileNotFoundError)), got.value


@pytest.mark.parametrize(("lookback", "analysis"), [(28, 7), (28, 28), (7, 7), (1, 1), (28, 1)])
def test_L12_c_analysis_days_within_lookback_days_loads(
    iso: Any, lookback: int, analysis: int
) -> None:
    _set_widths(iso, lookback, analysis)
    r = load_live_registry(iso.registry)
    assert (r.lookback_days, r.analysis_days) == (lookback, analysis)


def test_L12_c_the_model_itself_holds_the_rule(iso: Any) -> None:
    """Item 1: ``LiveRegistry`` has ``1 <= analysis_days <= lookback_days``."""
    data = load_live_registry(iso.registry).model_dump()
    with pytest.raises(ValueError):
        LiveRegistry.model_validate({**data, "lookback_days": 7, "analysis_days": 8})
    with pytest.raises(ValueError):
        LiveRegistry.model_validate({**data, "lookback_days": 28, "analysis_days": 0})
    ok = LiveRegistry.model_validate({**data, "lookback_days": 28, "analysis_days": 28})
    assert ok.analysis_days == 28


# ------------------------------------------------------------------ L12.4 the window


@pytest.mark.parametrize(
    ("width", "want"),
    [(28, W7), (7, window(7)), (3, window(3))],
    ids=["28-day poll: its last 7", "7-day poll: its own 7 (guard)", "3-day poll: its 3 (guard)"],
)
def test_L12_4_the_analysis_window_follows_the_poll(
    env: L12Env, width: int, want: tuple[dt.date, dt.date]
) -> None:
    """L12.4: ``(max(poll.window[0], window_end - analysis_days + 1), window_end)``."""
    env.client()
    calls = env.capture_execute()
    w = window(width)
    store = FakeStore()
    rows = [live_row("p", ad, d) for d in days_of(w) for ad in ("ad_a", "ad_b")]
    p = add_poll(store, T0, w, rows)
    rec = env.refresh(p, store)
    assert rec.status == "ran", rec.reason
    request = calls[0]["request"]
    assert tuple(request.window) == want  # item 3: CompareRequest.window
    assert env.snapshot(str(rec.run_id)).window == want
    assert p.window == w  # the stored poll keeps its full read


def test_L12_4_the_width_is_the_registry_analysis_days(env: L12Env, iso: Any) -> None:
    """Item 3: the refresh analyses the last ``analysis_days`` of the poll, as the registry
    (``BAYES_REGISTRY_DIR``, as every registry read) sets it."""
    _set_widths(iso, 28, 3)
    env.client()
    calls = env.capture_execute()
    store = FakeStore()
    p = add_poll(store, T0, W28, [*window_rows(), *old_rows()])
    rec = env.refresh(p, store)
    assert rec.status == "ran", rec.reason
    assert tuple(calls[0]["request"].window) == window(3)
    assert {r.date for r in calls[0]["kwargs"]["pulls"][0].rows} == set(days_of(window(3)))


# ------------------------------------------------------------------ L12.1 the refresh's readers


def test_L12_1_every_input_the_refresh_builds_comes_from_the_window_rows(env: L12Env) -> None:
    """L12.1, first point: ``ads``, ``_manifest`` (entity_map, attribution_window, currency),
    ``_pull`` (rows, window, partial_truth), ``_entity_names`` and ``_entity_parents`` all come
    from the rows with ``date`` in the analysis window. The old rows carry an extra ad in its own
    ad set, another attribution label, another currency and no observed conversions."""
    env.client()
    calls = env.capture_execute()
    store = FakeStore()
    rows = [*window_rows(observed=2), *old_rows(observed=None, currency="EUR")]
    p = add_poll(store, T0, W28, rows)
    rec = env.refresh(p, store)
    assert rec.status == "ran", rec.reason
    call = calls[0]
    manifest, request, kw = call["manifest"], call["request"], call["kwargs"]
    assert sorted(request.variants) == ["ad_a", "ad_b"]  # ads
    assert sorted(manifest.entity_map) == ["ad_a", "ad_b"]  # _manifest entity_map
    assert manifest.attribution_window == {"meta": WIN_LABEL}  # _manifest attribution_window
    assert manifest.currency == "USD"  # _manifest currency
    (pulled,) = kw["pulls"]
    assert tuple(pulled.window) == W7  # _pull window set to the analysis window
    assert sorted({r.date for r in pulled.rows}) == DAYS7  # _pull rows
    assert len(pulled.rows) == 14
    assert pulled.partial_truth is False  # _pull partial_truth, over the window rows
    names = kw.get("entity_names") or {}
    assert "ad_x" not in names and "s9" not in names  # _entity_names
    assert {"ad_a", "ad_b"} <= set(names)
    assert kw.get("entity_parents") == {"ad_a": "s1", "ad_b": "s1"}  # _entity_parents


def test_L12_1_fewer_than_two_ads_in_the_window_is_one_ad(env: L12Env) -> None:
    """Item 3, L12.1: a 28-day poll with two ads, only one of them in the analysis window."""
    env.client()
    calls = env.capture_execute()
    store = FakeStore()
    rows = [*window_rows(ads=("ad_a",)), *old_rows(ads=("ad_a", "ad_b"))]
    p = add_poll(store, T0, W28, rows)
    rec = env.refresh(p, store)
    assert rec.status == "skipped"
    assert rec.reason == ONE_AD
    assert rec.run_id is None and calls == []


# ------------------------------------------------------------------ (a), (a2) as 7 days


BUDGET = 5000


def _stores_for_a() -> tuple[FakeStore, FakeStore, FakeStore, Any, Any, Any]:
    """Store A: one 28-day poll, its old days carrying the extra ad ``ad_x`` and ``OLD_LABEL``.
    Store B: a 7-day poll of the same last seven days with the same poll id and start, after an
    earlier poll holding exactly A's old rows, so the stored spend (S12) is the same. Store C: the
    7-day poll alone. Returns the three stores and the three run polls."""
    pid = j2.poll_id(CLIENT, T0)
    a, b, c = FakeStore(), FakeStore(), FakeStore()
    pa = add_poll(a, T0, W28, [*window_rows(), *old_rows()], pid=pid)
    add_poll(b, T0 - dt.timedelta(days=1), (OLD[0], OLD[-1]), old_rows())
    pb = add_poll(b, T0, W7, window_rows(), pid=pid)
    pc = add_poll(c, T0, W7, window_rows(), pid=pid)
    return a, b, c, pa, pb, pc


def test_L12_a_a_28_day_poll_runs_as_a_7_day_poll_of_its_last_week(env: L12Env) -> None:
    """L12.6 (a): with the horizon pinned (the same stored spend), the same manifest, request
    key, seed, posterior summaries and config hash (registry version fixed) as a 7-day poll of
    the same last 7 days."""
    env.client(test_budget=BUDGET)
    calls = env.capture_execute()
    a, b, _, pa, pb, _ = _stores_for_a()
    spent_a = live_horizon.spend_to_date(a, CLIENT, "meta", pa.started_at)
    assert spent_a == live_horizon.spend_to_date(b, CLIENT, "meta", pb.started_at)  # pinned
    ra, rb = env.refresh(pa, a), env.refresh(pb, b)
    assert ra.status == "ran" and rb.status == "ran", (ra.reason, rb.reason)
    ca, cb = calls
    assert tuple(ca["request"].window) == W7
    assert ca["manifest"].model_dump(mode="json") == cb["manifest"].model_dump(mode="json")
    assert request_key(ca["request"]) == request_key(cb["request"])
    assert ca["request"].horizon == cb["request"].horizon
    sa, sb = env.snapshot(str(ra.run_id)), env.snapshot(str(rb.run_id))
    reca, recb = env.record(str(ra.run_id)), env.record(str(rb.run_id))
    assert sa.manifest_id == sb.manifest_id
    assert reca.seeds == recb.seeds and sa.configuration["seed"] == sb.configuration["seed"]
    assert posteriors(sa) == posteriors(sb)
    assert posteriors(sa)  # the run estimated something
    assert reca.config_hash == recb.config_hash
    assert sa.window == sb.window == W7


def test_L12_a2_unpinned_the_run_differs_only_through_spend_to_date(env: L12Env) -> None:
    """L12.6 (a2): against the 7-day poll alone, the 28-day run's horizon is the budget left
    after ``spend_to_date`` over every stored row, priced over the window rows only (L12.1); with
    that horizon put in, the 7-day run's request, configuration and posteriors are the 28-day
    run's."""
    econ = env.client(test_budget=BUDGET)
    calls = env.capture_execute()
    a, _, c, pa, _, pc = _stores_for_a()
    spent_a, since_a = live_horizon.spend_to_date(a, CLIENT, "meta", pa.started_at)
    spent_c, since_c = live_horizon.spend_to_date(c, CLIENT, "meta", pc.started_at)
    assert spent_a != spent_c  # the wider re-read stores more spend
    ra, rc = env.refresh(pa, a), env.refresh(pc, c)
    assert ra.status == "ran" and rc.status == "ran", (ra.reason, rc.reason)
    ca, cc = calls
    in_window = [r for r in a.rows(pa.poll_id) if W7[0] <= r.date <= W7[1]]
    unit = pipeline.horizon_unit("ctr")
    want_a = live_horizon.budget_horizon(econ.test_budget, spent_a, since_a, in_window, unit)
    want_c = live_horizon.budget_horizon(econ.test_budget, spent_c, since_c, in_window, unit)
    assert (ca["request"].horizon, ca["request"].horizon_basis) == want_a  # L12.1 horizon
    assert (cc["request"].horizon, cc["request"].horizon_basis) == want_c
    assert want_a[0] != want_c[0]  # so the horizon does move
    swapped = ca["request"].model_copy(
        update={"horizon": cc["request"].horizon, "horizon_basis": cc["request"].horizon_basis}
    )
    assert swapped == cc["request"]  # nothing else in the request differs
    assert ca["manifest"].model_dump(mode="json") == cc["manifest"].model_dump(mode="json")
    sa, sc = env.snapshot(str(ra.run_id)), env.snapshot(str(rc.run_id))
    drop = {"horizon", "seed"}  # the horizon, and the seed it feeds (L12.3)
    assert {k: v for k, v in sa.configuration.items() if k not in drop} == {
        k: v for k, v in sc.configuration.items() if k not in drop
    }
    assert posteriors(sa) == posteriors(sc)


# ------------------------------------------------------------------ (b), (h) the pointer


def test_L12_b_row_keys_hold_only_window_dates_and_equal_a_fresh_export(env: L12Env) -> None:
    """L12.6 (b) and item 4: the run's ``row_keys`` are the versions its poll read for dates in
    its window, ``rows_sha256`` is over those rows (J1, by the test writer's own hash), and a
    fresh export's ``runs.jsonl`` names the same keys and hash."""
    env.client()
    p = add_poll(env.store, T0, W28, [*window_rows(), *old_rows()])
    rec = env.refresh(p)
    assert rec.status == "ran", rec.reason
    run_id = str(rec.run_id)
    snap = env.snapshot(run_id)
    want = keys_for(("ad_a", "ad_b"), DAYS7)
    assert snap.row_keys == want
    assert all(W7[0] <= key_date(k) <= W7[1] for k in snap.row_keys)
    mod = env.export_module()
    exported = env.export_runs(mod)[run_id]
    assert exported["describes"] == {"start": W7[0].isoformat(), "end": W7[1].isoformat()}
    assert exported["row_keys"] == snap.row_keys  # (b): equal to a fresh export's
    ro = SqliteStore.open(env.store_path, read_only=True)
    try:
        rows, _, _ = mod.versioned(ro, CLIENT)
    finally:
        ro.close()
    by_key = {r["key"]: r for r in rows}
    sha = j2.j1_hash([by_key[k] for k in want])
    assert exported["rows_sha256"] == sha
    assert snap.dataset_hashes == [PREFIX + sha]  # J2: the run record names the same digest
    assert env.record(run_id).dataset_hashes == [PREFIX + sha]


def _spy_pointer(monkeypatch: pytest.MonkeyPatch, *mods: Any) -> list[dict[str, Any]]:
    """Wrap ``live.rows.pointer`` (the real one still runs), also where a module bound it by
    name, and record each call's poll id, window and result."""
    calls: list[dict[str, Any]] = []
    real = live_rows.pointer

    def spy(rows: Any, seen: Any, poll_id: Any, window: Any = None) -> Any:
        out = real(rows, seen, poll_id, window)
        calls.append({"poll_id": poll_id, "window": window, "out": out})
        return out

    monkeypatch.setattr(live_rows, "pointer", spy)
    for m in mods:
        if hasattr(m, "pointer"):
            monkeypatch.setattr(m, "pointer", spy)
    return calls


def test_L12_h_the_refresh_computes_the_pointer_through_rows_pointer(env: L12Env) -> None:
    """L12.6 (h), L12.2: the refresh passes the run's window to ``rows.pointer``."""
    env.client()
    calls = _spy_pointer(env.monkeypatch, refresh_mod)
    p = add_poll(env.store, T0, W28, [*window_rows(), *old_rows()])
    rec = env.refresh(p)
    assert rec.status == "ran", rec.reason
    snap = env.snapshot(str(rec.run_id))
    mine = [c for c in calls if c["poll_id"] == p.poll_id]
    assert len(mine) == 1, calls
    assert mine[0]["window"] is not None and iso(mine[0]["window"]) == iso(W7)
    keys, sha = mine[0]["out"]
    assert sorted(keys) == snap.row_keys and snap.dataset_hashes == [PREFIX + sha]


def test_L12_h_the_export_computes_the_pointer_through_rows_pointer(env: L12Env) -> None:
    """L12.6 (h), L12.2: ``runs()`` calls ``rows.pointer`` with ``tuple(d["window"])`` from the
    run file, once per run."""
    env.client()
    p1 = add_poll(env.store, T0, W28, [*window_rows(), *old_rows()])
    p2 = add_poll(env.store, T0 + dt.timedelta(hours=1), W7, window_rows(clicks=25))
    r1, r2 = env.refresh(p1), env.refresh(p2)
    assert r1.status == "ran" and r2.status == "ran", (r1.reason, r2.reason)
    calls = _spy_pointer(env.monkeypatch)  # before the script binds its imports
    mod = env.export_module()
    if hasattr(mod, "pointer"):
        env.monkeypatch.setattr(mod, "pointer", live_rows.pointer)
    exported = env.export_runs(mod)
    assert len(calls) == 2, calls
    for rec in (r1, r2):
        d = json.loads(env.snapshot_file(str(rec.run_id)).read_text())
        mine = [c for c in calls if c["poll_id"] == rec.poll_id]
        assert len(mine) == 1
        assert mine[0]["window"] == tuple(d["window"])  # L12.2: tuple(d["window"])
        keys, sha = mine[0]["out"]
        assert exported[str(rec.run_id)]["row_keys"] == list(keys)
        assert exported[str(rec.run_id)]["rows_sha256"] == sha


# ------------------------------------------------------------------ (d) pre-L12 runs


def test_L12_d_pre_L12_runs_export_the_same_row_keys_and_hash(env: L12Env) -> None:
    """L12.6 (d), item 4, L12.2 (guard): 7-day polls (a restated day, a rename with figures
    unchanged, a non-ASCII name) refreshed into runs whose window is their poll's. The export's
    ``row_keys`` and ``rows_sha256`` for each run are byte for byte what ``runs()`` wrote before
    L12: every key the poll read (the export's ``polls()`` at e983942, ``j2_oracle``), hashed
    under J1."""
    env.client()
    fig = j2.base_figures()
    w = j2.WINDOW
    polls = []
    for i, figures in enumerate(
        [
            fig,
            {**j2.base_figures(j2.NAMES_A2), ("ad_b", j2.LAST): (40, j2.NAMES_B)},
            {**j2.base_figures(j2.NAMES_A2), ("ad_a", j2.LAST): (22, j2.NAMES_A2)},
        ]
    ):
        started = T0 + dt.timedelta(hours=i)
        rows = [
            j2.live_row("p", ad, day, clicks, names).model_copy(update={"client_id": CLIENT})
            for (ad, day), (clicks, names) in figures.items()
        ]
        polls.append(add_poll(env.store, started, w, rows))
    runs = []
    for p in polls:
        rec = env.refresh(p)
        assert rec.status == "ran", rec.reason
        runs.append(rec)
    conn = j2_oracle_conn(env)
    try:
        oracle_rows, oracle_seen = j2_oracle.polls(conn, CLIENT, TZ)
    finally:
        conn.close()
    by_key = {r["key"]: r for r in oracle_rows}
    exported = env.export_runs()
    for rec in runs:
        keys = oracle_seen.get(rec.poll_id, [])
        before = canon({"row_keys": keys, "rows_sha256": j2.j1_hash([by_key[k] for k in keys])})
        got = exported[str(rec.run_id)]
        after = canon({"row_keys": got["row_keys"], "rows_sha256": got["rows_sha256"]})
        assert after == before
        assert len(keys) == 14  # every key the poll read: the window is the poll's


def j2_oracle_conn(env: L12Env) -> Any:
    import sqlite3

    conn = sqlite3.connect(f"{env.store_path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ------------------------------------------------------------------ (e) restated days


def test_L12_e_a_restated_old_day_is_stored_but_not_cited(env: L12Env) -> None:
    """L12.6 (e): a day restated 20 days back makes a new ``v(n+1)`` in ``polls.jsonl`` and
    ``reads.jsonl``; the run made in that poll doesn't cite it. A day restated inside the window
    is cited. Earlier runs' pointers are byte-identical."""
    env.client()
    ads = ("ad_a", "ad_b")
    base = [*window_rows(), *old_rows(ads=ads)]
    back20 = END - dt.timedelta(days=20)
    inside = END - dt.timedelta(days=2)
    assert back20 in OLD and inside in DAYS7

    def figures(changed: dict[tuple[str, dt.date], int]) -> list:
        out = []
        for r in base:
            k = (r.entity_ids["ad"], r.date)
            out.append(r.model_copy(update={"clicks": changed[k]}) if k in changed else r)
        return out

    p1 = add_poll(env.store, T0, W28, base)
    r1 = env.refresh(p1)
    assert r1.status == "ran", r1.reason
    file1 = env.snapshot_file(str(r1.run_id)).read_bytes()
    export1 = env.export_runs()[str(r1.run_id)]

    p2 = add_poll(env.store, T0 + dt.timedelta(hours=1), W28, figures({("ad_a", back20): 9}))
    r2 = env.refresh(p2)
    assert r2.status == "ran", r2.reason
    mod = env.export_module()
    ro = SqliteStore.open(env.store_path, read_only=True)
    try:
        rows, _, reads = mod.versioned(ro, CLIENT)
    finally:
        ro.close()
    restated = f"meta:ad_a:{back20.isoformat()}:v2"
    v2 = [r for r in rows if r["key"] == restated]
    assert len(v2) == 1 and v2[0]["poll_id"] == p2.poll_id  # polls.jsonl
    assert v2[0]["restates"] == f"meta:ad_a:{back20.isoformat()}:v1"
    read = [r for r in reads if r["key"] == f"read:{p2.poll_id}:ad_a:{back20.isoformat()}"]
    assert len(read) == 1 and read[0]["version_key"] == restated  # reads.jsonl
    snap2 = env.snapshot(str(r2.run_id))
    assert not [k for k in snap2.row_keys if key_date(k) == back20]  # not cited
    assert snap2.row_keys == keys_for(ads, DAYS7)
    exported = env.export_runs(mod)
    assert exported[str(r2.run_id)]["row_keys"] == snap2.row_keys
    assert env.snapshot_file(str(r1.run_id)).read_bytes() == file1
    assert canon(exported[str(r1.run_id)]) == canon(export1)  # the earlier run's pointer
    export2 = exported[str(r2.run_id)]

    p3 = add_poll(
        env.store,
        T0 + dt.timedelta(hours=2),
        W28,
        figures({("ad_a", back20): 9, ("ad_b", inside): 41}),
    )
    r3 = env.refresh(p3)
    assert r3.status == "ran", r3.reason
    snap3 = env.snapshot(str(r3.run_id))
    cited = f"meta:ad_b:{inside.isoformat()}:v2"
    assert cited in snap3.row_keys  # restated inside the window: cited
    assert f"meta:ad_b:{inside.isoformat()}:v1" not in snap3.row_keys
    assert not [k for k in snap3.row_keys if key_date(k) == back20]
    exported = env.export_runs()
    assert exported[str(r3.run_id)]["row_keys"] == snap3.row_keys
    assert env.snapshot_file(str(r1.run_id)).read_bytes() == file1
    assert canon(exported[str(r1.run_id)]) == canon(export1)
    assert canon(exported[str(r2.run_id)]) == canon(export2)


# ------------------------------------------------------------------ (g) the view


H2 = re.compile(r"<h2[^>]*>(.*?)</h2>", re.S | re.I)
TABLES = ("h_account", "h_delivery", "h_conversions", "h_budget")


def _text(fragment: str) -> str:
    import html

    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _section(page: str, key: str) -> str:
    title = registries.load("phrasing")["live"][key]
    ms = list(H2.finditer(page))
    for i, m in enumerate(ms):
        if _text(m.group(1)) == title:
            end = ms[i + 1].start() if i + 1 < len(ms) else len(page)
            return page[m.end() : end]
    raise AssertionError(f"no h2 {title!r}")


def _render(store: FakeStore, data_dir: Path) -> str:
    cfg = C.ClientConfig(client_id=CLIENT, timezone=TZ, currency="USD", accounts={"meta": "act_1"})
    return view.render(
        store,
        CLIENT,
        FixedClock(dt.datetime(2026, 11, 7, 18, 0, tzinfo=UTC)),  # 13:00 on END in New York
        registry=load_live_registry(),
        phrasing=registries.load("phrasing"),
        data_dir=data_dir,
        config=cfg,
    )


@pytest.mark.parametrize("analysis", [7, 3], ids=["analysis 7", "analysis 3: view stays at 7"])
def test_L12_g_the_view_tables_on_28_days_equal_the_7_day_store(
    env: L12Env, iso: Any, analysis: int
) -> None:
    """L12.6 (g), L12.1: the view's tables on a 28-day store equal its tables on the 7-day store
    of the same last week; the view's own window is pinned at 7 days."""
    _set_widths(iso, 28, analysis)
    pid = j2.poll_id(CLIENT, T0)
    s28, s7 = FakeStore(), FakeStore()
    add_poll(s28, T0, W28, [*window_rows(), *old_rows()], pid=pid)
    add_poll(s7, T0, W7, window_rows(), pid=pid)
    page28, page7 = _render(s28, env.data_dir), _render(s7, env.data_dir)
    assert "ad_a" in _section(page7, "h_delivery")
    for key in TABLES:
        assert _section(page28, key) == _section(page7, key), key
    assert "ad_x" not in page28 and OLD_LABEL not in page28


# ------------------------------------------------------------------ (i) a pre-L12 7-day poll


# Taken at a87e978 (before L12) on the J2 fixture's P1 with the prior registry's and the
# pipeline's clocks pinned as J2 (c) pins them; the run id and seed are J2 (c)'s own constants.
T_APPROVE = dt.datetime(2026, 11, 7, 12, 0, 0, tzinfo=UTC)
T_RUN = dt.datetime(2026, 11, 7, 17, 40, 0, tzinfo=UTC)
RUN_ID_I = "run_81c61671"
SEED_I = 1820359372
DATASET_HASH_I = "bayes-rows-c1:a69a14356197c6ee6321822cc1345135d12e1758f4c1e205b3b8a79dbbe556f3"
CONFIG_SANS_REGISTRIES_I = "693061c57022bd573c1e034d532df156de8c6eb9307083427dfe719c69921e9f"
CTR_PARAMS_I = {"ad_a": {"a": 142.0, "b": 6958.0}, "ad_b": {"a": 247.0, "b": 6853.0}}


@pytest.fixture
def j2env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[j2.J2Env]:
    yield from j2.make_env(tmp_path, monkeypatch)


def test_L12_i_a_pre_L12_7_day_poll_refreshes_exactly_as_before(
    j2env: j2.J2Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L12.6 (i) (guard): the same run id, seed, window, pointer, configuration (but for the
    registry versions, which L12.3 bumps once) and posteriors as at a87e978."""
    monkeypatch.setattr(prior_registry, "utcnow", lambda: T_APPROVE)
    j2env.client()
    monkeypatch.setattr(pipeline, "utcnow", lambda: T_RUN)
    polls = j2env.history(upto="P1")
    rec = j2env.refresh(polls["P1"])
    assert rec.status == "ran", rec.reason
    run_id = str(rec.run_id)
    snap, record = j2env.snapshot(run_id), j2env.record(run_id)
    assert run_id == RUN_ID_I
    assert record.seeds["fit"] == SEED_I == snap.configuration["seed"]
    assert snap.window == polls["P1"].window == j2.WINDOW
    keys, sha = j2env.oracle_pointer(polls["P1"].poll_id)
    assert snap.row_keys == keys and len(keys) == 14
    assert snap.dataset_hashes == [DATASET_HASH_I] == [PREFIX + sha]
    conf = {k: v for k, v in snap.configuration.items() if k != "registry_versions"}
    assert inputs_hash(conf) == CONFIG_SANS_REGISTRIES_I
    ctr = {k[1]: v["params"] for k, v in posteriors(snap).items() if k[0] == "ctr"}
    assert ctr == CTR_PARAMS_I


# ------------------------------------------------------------------ (j) a multi-page 28-day pull


NOON = dt.datetime(2026, 11, 7, 18, 0, 0, 123456, tzinfo=UTC)  # 10:00 on END in Los Angeles


def _meta_config() -> C.ClientConfig:
    return C.ClientConfig(
        client_id="unit_client",
        timezone="America/Los_Angeles",
        currency="USD",
        accounts={"meta": "act_111"},
    )


def _record_28(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, list[dict]]:
    """Record a 28-day pull paged 25 rows a page into ``tmp_path / "rec28"`` through ``pull()``
    in record mode against an httpx mock; then leave the environment ready to replay it."""
    for k in (H.REPLAY_ENV, H.RECORD_ENV):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("META_ACCESS_TOKEN", META_TOKEN)
    monkeypatch.setattr(H, "BACKOFF_BASE_S", 0.0)
    rows = meta_rows_28(DAYS28)
    handler = paging_handler(rows)
    monkeypatch.setattr(
        H.httpx, "Client", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw)
    )
    target = tmp_path / "rec28"
    monkeypatch.setenv(H.RECORD_ENV, str(target))
    got = pull("meta", _meta_config(), W28)
    assert len(got.rows) == len(rows) == 112
    monkeypatch.delenv(H.RECORD_ENV)
    monkeypatch.delenv("META_ACCESS_TOKEN")

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access during replay")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    return target, rows


def _insight_exchanges(d: Path) -> list[Path]:
    out = []
    for p in sorted(d.glob(H.EXCHANGE_GLOB)):
        if "/insights" in json.loads(p.read_text())["request"]["url"]:
            out.append(p)
    return out


def test_L12_j_the_connector_replays_a_multi_page_28_day_pull(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """L12.5, (j), connector level (guard): every page of the replay is read."""
    rec, _ = _record_28(monkeypatch, tmp_path)
    assert len(_insight_exchanges(rec)) == 5  # 112 rows at 25 a page
    monkeypatch.setenv(H.REPLAY_ENV, str(rec))
    got = pull("meta", _meta_config(), W28)
    assert len(got.rows) == 112 and not got.quarantined
    assert sorted({r.date for r in got.rows}) == DAYS28
    assert {r.entity_ids["ad"] for r in got.rows} == set(META_ADS)


def test_L12_j_the_poll_reads_and_stores_all_28_days_from_the_replay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """L12.6 (j), items 2 and L12.1: a poll on the deployed registry reads the 28-day window
    across every page, stores every row it read, and ``n_rows`` counts all 28 days."""
    rec_dir, _ = _record_28(monkeypatch, tmp_path)
    monkeypatch.setenv(H.REPLAY_ENV, str(rec_dir))
    store = SqliteStore.open(tmp_path / "live.sqlite")
    try:
        rec = poll(
            _meta_config(),
            store,
            FixedClock(NOON),
            platform="meta",
            registry=load_live_registry(),
            record_root=None,
        )
        assert rec.status == "ok", rec.error
        assert rec.window == W28  # item 2: the poll reads 28 days
        assert rec.n_rows == 112  # L12.1: PollRecord.n_rows counts all 28 days
        stored = store.rows(rec.poll_id)
        assert len(stored) == 112  # item 2: every row it reads goes into the store
        assert sorted({r.date for r in stored}) == DAYS28
    finally:
        store.close()


def test_L12_j_too_much_data_on_a_later_page_makes_the_poll_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """L12.5, (j): the "too much data" answer on a later page of the 28-day pull, which today
    makes the poll an error, is seen: the poll is an error naming code 100 subcode 1487534 and
    nothing is stored."""
    rec_dir, _ = _record_28(monkeypatch, tmp_path)
    bad = tmp_path / "rec28_too_much"
    shutil.copytree(rec_dir, bad)
    third = _insight_exchanges(bad)[2]
    ex = json.loads(third.read_text())
    ex["response"] = {
        "status": 400,
        "headers": {},
        "body": {
            "error": {
                "message": "Please reduce the amount of data you're asking for, then retry",
                "code": 100,
                "error_subcode": 1487534,
            }
        },
    }
    third.write_text(json.dumps(ex, indent=1, sort_keys=True) + "\n")
    monkeypatch.setenv(H.REPLAY_ENV, str(bad))
    store = SqliteStore.open(tmp_path / "live.sqlite")
    try:
        rec = poll(
            _meta_config(),
            store,
            FixedClock(NOON),
            platform="meta",
            registry=load_live_registry(),
            record_root=None,
        )
        assert rec.window == W28
        assert rec.status == "error"
        assert rec.error and "1487534" in rec.error, rec.error
        assert store.rows(rec.poll_id) == []
    finally:
        store.close()
