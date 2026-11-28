"""J7: held status, the route on each figure, and the account's time zone (Brain join spec v0.4,
J7 checks (a) to (k), as S39 settles them; S39 governs where it differs from J7's text).

Series are built by ``j7_fixtures.J7Env.put_run``: copies of one template run's snapshot with
chosen ``started_at``, raw statuses and variants, written as run files plus run-record entries in
the test's data dir. Nothing is sampled per run. The held statuses are read from
``claims.held.held_status`` by the keys of S39 (4) and (5) as the skeleton's ``HeldKey`` writes
them: ``("ad", ad id, quantity name, conversion kind, metric)``, ``("ad_set", ad set id, ...)``
and ``("decision", "", "", conversion kind, metric)``.

Times are UTC. Unless a case says otherwise the account's zone is America/New_York and the series
sit in mid-November, away from any daylight-saving change. "A marginal day" is marginal runs every
six hours for 36 hours, after which a quantity seen first at marginal is held marginal (S39 (2)).

Readings the spec leaves to the test writer, and how they are read here:

* Held carries across runs where the quantity is absent (J7 (3), "held carries over"): S39 (3)
  removes only the absent run's own entry, and S39 (1) only stops a rise across a gap.
* Two consecutive present runs exactly one calendar day apart don't break the streak; only "more
  than one calendar day" does.
* The two-zone raise of S39 (6) belongs to its last step (the one zone among the client's ok
  polls), as S29 does. A zone found at an earlier step ends the search, so a run whose poll names
  a zone is answered by it even when the client's ok polls hold two.
* The zone in S39 (6) is the run's own snapshot's ``timezone``.
* A non-ad quantity is present when it is in the run.
* The two-zone case raises ``ValueError``, as S29 does. Every other raise is any exception.
* ``held_status_reason`` is absent or null when ``held_status`` is not null.
* A posterior entry's keys are the skeleton's plus ``held_status`` and ``fit_route`` (and
  ``held_status_reason`` when held is null); nothing else is added or dropped (S39 (8), (9)).
* An engine_run marker's fields are J3's plus ``timezone`` and ``fit_route``. ``test_J3`` asserts
  J3's set exactly, so it has to be amended on the record when J7 lands.

Check (j) copies the live run record, run files and live store into ``tmp_path`` read-only, and is
skipped when ``data/live/engine/run_record.sqlite`` is absent. No other case reads ``data/live``.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import random
import shutil
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from bayesian_marketing import pipeline
from bayesian_marketing.claims import held as H
from bayesian_marketing.decision import run_record
from bayesian_marketing.live import markers as Mk
from bayesian_marketing.prior_registry import registry as prior_registry
from tests.acceptance import j2_fixtures as J2
from tests.acceptance import j4_fixtures as X
from tests.acceptance.j4_fixtures import IMG2_ID, IMG3_ID, IMG4_ID
from tests.acceptance.j4r_fixtures import cmp_run, fig_run, name_slot
from tests.acceptance.j7_fixtures import (
    ADSET,
    BELOW_FLOOR_ENTRY_KEYS,
    CTR_FULL,
    LONDON,
    NEW_ENTRY_KEYS,
    NY,
    QUANTITY_ENTRY_KEYS,
    RANK,
    ROUGH,
    B,
    E,
    J7Env,
    M,
    adset_key,
    at,
    decision_key,
    hours,
    key,
    oracle_held,
    raw_of,
    write_garbage,
)
from tests.acceptance.test_J2 import RUN_ID_BEFORE_J2, SEED_BEFORE_J2, T_APPROVE, T_RUN

pytestmark = pytest.mark.piece("J7")

REPO = Path(__file__).resolve().parents[2]
CONFIG_HASH_BEFORE_J7 = "afd651575f3414a0b320f0399ee8b54e9ba576c2b5c89bf875ea6bcac1be7055"
# L12.3 (D55): live.yaml's version is bumped to 2026-11-27, so every new run's config hash
# changes once. With the version at 2026-11-07 this run still gives CONFIG_HASH_BEFORE_J7.
CONFIG_HASH_AFTER_L12 = "6015e37dd5d25ddfc0604c0b2c2d6b6ff02080fee201b6fe2d0d4adb20352c7c"
BASE = at("2026-11-10T12:00")
H1 = dt.timedelta(hours=1)
D1 = dt.timedelta(days=1)
CMP_FULL = f"{X.IMG3}, which leads on clicks with a 62% chance of being best"


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[J7Env]:
    e = J7Env(tmp_path, monkeypatch)
    yield e
    e.close()


@pytest.fixture
def j2env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[J2.J2Env]:
    yield from J2.make_env(tmp_path, monkeypatch)


# ------------------------------------------------------------------ helpers


def marginal_day(env: J7Env, start: dt.datetime = BASE, **kw: Any) -> dt.datetime:
    """Marginal runs every six hours for 36 hours from ``start``; returns the last run's time.
    After it every ctr of the three ads, and the decision when ``decision`` is marginal, is held
    marginal."""
    times = hours(start, 7, 6)
    kw.setdefault("decision", M)
    for t in times:
        env.put_run(t, M, **kw)
    return times[-1]


def estimable_day(env: J7Env, start: dt.datetime, n: int = 27, **kw: Any) -> list[str]:
    """Estimable ctr runs hourly from ``start``; after the 25th every ctr is held estimable."""
    return [env.put_run(t, E, **kw) for t in hours(start, n)]


def held_of(env: J7Env, run_id: str, k: Any = None, **kw: Any) -> str | None:
    return env.held(run_id, **kw).get(key() if k is None else k)


def why(res: dict[str, Any]) -> str:
    parts = list(res.get("reasons") or []) + list(res.get("lint") or [])
    for s in res.get("slots") or []:
        parts += s.get("reasons") or []
    return repr({"ok": res.get("ok"), "text": res.get("text"), "reasons": parts})


def menu_item(menu: dict[str, Any], token: str) -> dict[str, Any]:
    hits = [s for s in menu["slots"] if s["token"] == token]
    assert len(hits) == 1, [s["token"] for s in menu["slots"]]
    return hits[0]


def run_items(menu: dict[str, Any], run_id: str) -> list[dict[str, Any]]:
    return [s for s in menu["slots"] if s["kind"] in ("fig", "cmp") and s["run_id"] == run_id]


def rec_line(held: str, raw: str) -> str:
    return H.HELD_REASON.format(held=held, raw=raw)


def test_J7_skeleton_constants() -> None:
    assert H.ORDER == ("below_floor", "marginal", "estimable")  # J7 (1)
    assert rec_line(M, E) == "held at marginal until estimable has held for a day"  # S39 (8)


# ------------------------------------------------------------------ (a) the day rule


def test_J7_a_23_hours_of_estimable_is_never_held_estimable(env: J7Env) -> None:
    last = marginal_day(env)
    e0 = last + H1
    est = [env.put_run(t, E) for t in hours(e0, 24)]  # e0 .. e0 + 23h
    back = env.put_run(e0 + 24 * H1, M)
    for rid in [*est, back]:
        assert held_of(env, rid) == M, rid


def test_J7_a_25_hours_of_estimable_is_held_estimable_from_the_run_that_completes_the_day(
    env: J7Env,
) -> None:
    last = marginal_day(env)
    e0 = last + H1
    est = [env.put_run(t, E) for t in hours(e0, 26)]  # e0 .. e0 + 25h
    got = [held_of(env, rid) for rid in est]
    assert got[:24] == [M] * 24  # e0 .. e0 + 23h
    assert got[24:] == [E, E]  # e0 + 24h completes the day


def test_J7_S39_2_first_appearance_starts_at_below_floor(env: J7Env) -> None:
    """A first status above below_floor waits a day like every other rise, straight up to it."""
    est = [env.put_run(t, E) for t in hours(BASE, 25)]  # BASE .. BASE + 24h
    got = [held_of(env, rid) for rid in est]
    assert got[:24] == [B] * 24
    assert got[24] == E
    # marginal first: below_floor until the day is done
    other = [env.put_run(t, M, client=X.OTHER) for t in hours(BASE, 5, 6)]  # 0 .. 24h
    got2 = [env.held(rid)[key()] for rid in other]
    assert got2 == [B, B, B, B, M]


def test_J7_S39_1_a_streak_mixing_estimable_and_marginal_gives_marginal(env: J7Env) -> None:
    rids = [env.put_run(t, E if i % 2 == 0 else M) for i, t in enumerate(hours(BASE, 31))]
    got = [held_of(env, rid) for rid in rids]
    assert E not in got
    assert got[30] == M and got[24] == M  # raw estimable at both


# ------------------------------------------------------------------ (b) a drop


def test_J7_b_a_drop_shows_at_once(env: J7Env) -> None:
    last = marginal_day(env)
    est = estimable_day(env, last + H1)
    assert held_of(env, est[-1]) == E
    t = last + H1 + 27 * H1
    down = env.put_run(t, M)
    assert held_of(env, down) == M
    floor = env.put_run(t + H1, B)
    assert held_of(env, floor) == B


def test_J7_b_estimable_straight_to_below_floor(env: J7Env) -> None:
    last = marginal_day(env)
    est = estimable_day(env, last + H1)
    assert held_of(env, est[-1]) == E
    floor = env.put_run(last + 28 * H1, B)
    assert held_of(env, floor) == B
    again = env.put_run(last + 29 * H1, E)  # a rise after a drop waits a day again
    assert held_of(env, again) == B


# ------------------------------------------------------------------ (c) later runs


def test_J7_c_a_run_gets_the_same_held_status_whether_or_not_later_runs_exist(
    env: J7Env,
) -> None:
    last = marginal_day(env)
    est = estimable_day(env, last + H1, n=24)
    probe = est[-1]
    before = {rid: env.held(rid) for rid in est}
    t_probe = last + 24 * H1
    # later runs: lower statuses, a run at the same started_at with a greater run id, and a run
    # recorded later whose started_at is later still
    env.put_run(t_probe, B, run_id="run_ffffffff")
    assert probe < "run_ffffffff"
    for t in hours(t_probe + H1, 30):
        env.put_run(t, B)
    after = {rid: env.held(rid) for rid in est}
    assert after == before
    assert before[probe][key()] == M


def test_J7_S39_12_no_cache_held_status_writes_nothing(env: J7Env) -> None:
    last = marginal_day(env)
    rids = estimable_day(env, last + H1, n=3)
    files = env.files_under_data_dir()
    env.held(rids[-1])
    env.result(rids[-1])
    assert env.files_under_data_dir() == files


# ------------------------------------------------------------------ (d) daylight saving


def fall_back_series(env: J7Env, **kw: Any) -> tuple[str, str]:
    """America/New_York falls back at 2026-11-01 02:00 local. Marginal to 15:30 UTC on 31 Oct
    (11:30 EDT), estimable hourly from 16:30 UTC (12:30 EDT). The run at 17:00 UTC on 1 Nov is
    12:00 EST: a local day back is 12:00 EDT, 16:00 UTC, so the streak's last run at or before it
    is the marginal one, though 24.5 real hours of estimable lie behind it. The run at 17:30 UTC
    (12:30 EST) reaches back to 16:30 UTC and is held estimable. In Europe/London (GMT on both
    days) the 17:00 run already reaches back to 16:30 UTC."""
    for t in hours(at("2026-10-29T12:00"), 9, 6):
        env.put_run(t, M, **kw)
    env.put_run(at("2026-10-31T15:30"), M, **kw)
    for t in hours(at("2026-10-31T16:30"), 25):
        env.put_run(t, E, **kw)
    return env.put_run(at("2026-11-01T17:00"), E, **kw), env.put_run(
        at("2026-11-01T17:30"), E, **kw
    )


def test_J7_d_fall_back_counts_by_local_clock_time(env: J7Env) -> None:
    not_yet, held_e = fall_back_series(env)
    assert held_of(env, not_yet) == M
    assert held_of(env, held_e) == E


def test_J7_d_spring_forward_counts_by_local_clock_time(env: J7Env) -> None:
    """America/New_York springs forward at 2027-03-14 02:00 local. Estimable from 17:00 UTC on
    13 Mar (12:00 EST). The run at 16:00 UTC on 14 Mar is 12:00 EDT: a local day back is 12:00
    EST, 17:00 UTC, so 23 real hours of estimable complete the day. The run an hour earlier
    reaches back to 16:00 UTC, where the last run is marginal."""
    for t in hours(at("2027-03-11T12:00"), 9, 6):
        env.put_run(t, M)
    env.put_run(at("2027-03-13T16:30"), M)
    est = [env.put_run(t, E) for t in hours(at("2027-03-13T17:00"), 23)]  # to 15:00 on 14 Mar
    target = env.put_run(at("2027-03-14T16:00"), E)
    assert held_of(env, est[-1]) == M
    assert held_of(env, target) == E


# ------------------------------------------------------------------ S39 (1) the streak


def test_J7_S39_1_a_gap_of_more_than_a_day_breaks_the_streak(env: J7Env) -> None:
    last = marginal_day(env)
    e0 = last + H1
    env.put_run(e0, E)
    after = [env.put_run(t, E) for t in hours(e0 + D1 + H1, 3)]
    assert [held_of(env, r) for r in after] == [M, M, M]


def test_J7_S39_1_runs_exactly_a_day_apart_keep_the_streak(env: J7Env) -> None:
    last = marginal_day(env)
    e0 = last + H1
    env.put_run(e0, E)
    one_day = env.put_run(e0 + D1, E)
    assert held_of(env, one_day) == E


def test_J7_S39_1_a_lower_run_24_hours_and_1_minute_back(env: J7Env) -> None:
    """The run at or before a day back must itself have the level. Every run in the last 24
    hours is estimable, but the last run at or before T minus a day is marginal."""
    t = BASE + 3 * D1
    marginal_day(env, t - 3 * D1)
    env.put_run(t - D1 - dt.timedelta(minutes=1), M)
    est = [env.put_run(x, E) for x in hours(t - 23 * H1, 23)]  # T - 23h .. T - 1h
    target = env.put_run(t, E)
    assert [held_of(env, r) for r in [*est, target]] == [M] * 24
    nxt = env.put_run(t + H1, E)  # reaches back to T - 23h, estimable
    assert held_of(env, nxt) == E


# ------------------------------------------------------------------ S39 (3) presence


def test_J7_S39_3_an_ad_in_variants_without_the_quantity_is_below_floor(env: J7Env) -> None:
    last = marginal_day(env)
    est = estimable_day(env, last + H1)
    assert held_of(env, est[-1]) == E
    rid = env.put_run(last + 28 * H1, E, not_estimable=[(IMG3_ID, "ctr")])
    got = env.held(rid)
    assert got[key()] == B  # present, raw below_floor: a drop
    assert got[key(IMG2_ID)] == E
    nxt = env.put_run(last + 29 * H1, E)
    assert held_of(env, nxt) == B  # and the rise waits a day


def test_J7_S39_3_an_ad_not_in_variants_has_no_entry_and_held_carries_over(env: J7Env) -> None:
    last = marginal_day(env)
    est = estimable_day(env, last + H1)
    assert held_of(env, est[-1]) == E
    rid = env.put_run(last + 28 * H1, E, absent=[IMG3_ID])
    got = env.held(rid)
    assert not [k for k in got if IMG3_ID in k[:2]], got  # nothing of the ad in that run
    assert got[key(IMG2_ID)] == E
    nxt = env.put_run(last + 29 * H1, E)
    assert held_of(env, nxt) == E  # not a drop: held carried over


def test_J7_S39_3_every_quantity_name_of_a_present_subject(env: J7Env) -> None:
    """Not only the metric: a name in ``not_estimable`` and a name with no quantity are both
    below_floor while the ad is present."""
    last = marginal_day(env)
    rid = env.put_run(last + H1, M, gone=[(IMG3_ID, "cpa")])
    got = env.held(rid)
    assert got[key(IMG3_ID, "cpa")] == B  # held marginal before, raw below_floor now
    assert got[key(IMG2_ID, "cpa")] == M
    assert got[key(IMG3_ID, "aov")] == B  # listed in the template's not_estimable (D33)
    assert got[key(IMG3_ID, "cvr")] == M


def test_J7_S39_3_a_quantity_absent_for_days(env: J7Env) -> None:
    last = marginal_day(env)
    est = estimable_day(env, last + H1)
    t = last + 28 * H1
    gap = [env.put_run(x, E, absent=[IMG3_ID]) for x in hours(t, 7, 12)]  # three days
    for rid in gap:
        assert key() not in env.held(rid)
    back = env.put_run(t + 4 * D1, E)
    assert held_of(env, est[-1]) == E
    assert held_of(env, back) == E  # carried over the absence


def test_J7_S39_3_a_rise_across_days_of_absence_waits_a_fresh_day(env: J7Env) -> None:
    last = marginal_day(env)
    e0 = last + H1
    for x in hours(e0, 2):
        env.put_run(x, E)
    for x in hours(e0 + 2 * H1, 7, 12):
        env.put_run(x, E, absent=[IMG3_ID])
    back = [env.put_run(x, E) for x in hours(e0 + 4 * D1, 3)]
    assert [held_of(env, r) for r in back] == [M, M, M]
    # the ads that stayed present rose as usual
    assert held_of(env, back[-1], key(IMG2_ID)) == E


# ------------------------------------------------------------------ S39 (4) identity


def test_J7_S39_4_a_change_of_conversion_kind_starts_a_new_series(env: J7Env) -> None:
    last = marginal_day(env)
    est = estimable_day(env, last + H1)
    assert held_of(env, est[-1]) == E
    rid = env.put_run(last + 28 * H1, E, kind="purchase")
    got = env.held(rid)
    assert got[key(kind="purchase")] == B  # first appearance of the new identity
    assert key() not in got
    assert got[decision_key(kind="purchase")] == B
    assert decision_key() not in got


def test_J7_S39_4_a_change_of_metric_starts_a_new_series(env: J7Env) -> None:
    last = marginal_day(env)
    estimable_day(env, last + H1)
    rid = env.put_run(last + 28 * H1, E, metric="cvr")
    got = env.held(rid)
    assert got[key(metric="cvr")] == B
    assert key() not in got


def test_J7_S39_4_a_change_of_window_or_segments_keeps_the_series(env: J7Env) -> None:
    last = marginal_day(env)
    estimable_day(env, last + H1)
    rid = env.put_run(last + 28 * H1, E, window=(dt.date(2026, 11, 1), dt.date(2026, 11, 14)))
    assert held_of(env, rid) == E


# ------------------------------------------------------------------ S39 (5) decision, non-ad


def test_J7_S39_5_the_decision_status_is_held_by_the_same_rule(env: J7Env) -> None:
    last = marginal_day(env, decision=M)
    assert env.held(env.runs[-1].run_id)[decision_key()] == M
    est = [env.put_run(t, M, decision=E) for t in hours(last + H1, 26)]
    got = [env.held(r)[decision_key()] for r in est]
    assert got[:24] == [M] * 24 and got[24:] == [E, E]
    down = env.put_run(last + 27 * H1, M, decision=B)
    assert env.held(down)[decision_key()] == B


def test_J7_S39_5_a_non_ad_quantity_uses_its_own_level_and_id(env: J7Env) -> None:
    last = marginal_day(env)
    two = [env.put_run(t, M, status={(ADSET, "cvr"): E}) for t in hours(last + H1, 2)]
    got = env.held(two[-1])
    assert got[adset_key()] == M
    day = [env.put_run(t, M, status={(ADSET, "cvr"): E}) for t in hours(last + 3 * H1, 24)]
    assert env.held(day[-1])[adset_key()] == E


# ------------------------------------------------------------------ S39 (6) the zone, (e)


def test_J7_S39_6_the_argument_comes_before_the_snapshot(env: J7Env) -> None:
    not_yet, _ = fall_back_series(env, tz=LONDON)
    assert held_of(env, not_yet) == E  # the snapshot's zone
    assert held_of(env, not_yet, timezone=NY) == M  # the argument's


def test_J7_S39_6_the_snapshot_comes_before_the_store(env: J7Env) -> None:
    not_yet, _ = fall_back_series(env, tz=LONDON)
    poll = env.store_poll(at("2026-11-01T16:50"), NY)
    env.store_refresh(poll, not_yet)
    assert held_of(env, not_yet) == E


@pytest.mark.parametrize(("zone", "other", "want"), [(NY, LONDON, M), (LONDON, NY, E)])
def test_J7_e_a_pre_J7_snapshot_takes_its_zone_from_its_poll(
    env: J7Env, zone: str, other: str, want: str
) -> None:
    """The refreshes row names the run's poll, and that poll's outcome names the zone. The
    client's ok polls hold two zones, which would raise at the last step: the poll comes first."""
    not_yet, _ = fall_back_series(env, tz=None)
    poll = env.store_poll(at("2026-11-01T16:50"), zone)
    env.store_poll(at("2026-11-01T15:50"), other)
    env.store_refresh(poll, not_yet)
    assert env.snap_json(not_yet)["timezone"] is None
    assert pipeline.RunSnapshot.model_validate(env.snap_json(not_yet)).timezone is None
    assert held_of(env, not_yet) == want


@pytest.mark.parametrize(("zone", "want"), [(NY, M), (LONDON, E)])
def test_J7_S39_6_a_run_with_no_refresh_takes_the_one_zone_of_the_ok_polls(
    env: J7Env, zone: str, want: str
) -> None:
    """Error polls and other clients' polls don't count (S29)."""
    not_yet, _ = fall_back_series(env, tz=None)
    other = LONDON if zone == NY else NY
    env.store_poll(at("2026-11-01T12:00"), zone)
    env.store_poll(at("2026-11-01T13:00"), zone)
    env.store_poll(at("2026-11-01T14:00"), other, status="error")
    env.store_poll(at("2026-11-01T14:30"), other, client=X.OTHER)
    assert held_of(env, not_yet) == want


def test_J7_S39_6_two_zones_raise(env: J7Env) -> None:
    not_yet, _ = fall_back_series(env, tz=None)
    env.store_poll(at("2026-11-01T12:00"), NY)
    env.store_poll(at("2026-11-01T13:00"), LONDON)
    with pytest.raises(ValueError):
        env.held(not_yet)
    assert held_of(env, not_yet, timezone=NY) == M  # an explicit zone still answers


def test_J7_e_no_zone_anywhere_raises_and_result_of_gives_null_with_a_reason(
    env: J7Env,
) -> None:
    not_yet, _ = fall_back_series(env, tz=None)
    assert not env.store_path.exists()
    assert held_of(env, not_yet, timezone=NY) == M  # with a zone, it answers
    with pytest.raises(Exception):  # noqa: B017
        env.held(not_yet)
    _assert_null_held(env.result(not_yet))
    env.store_poll(at("2026-11-01T12:00"), NY, client=X.OTHER)  # a store, none of this client's
    with pytest.raises(Exception):  # noqa: B017
        env.held(not_yet)
    _assert_null_held(env.result(not_yet))


def _assert_null_held(res: dict[str, Any]) -> None:
    assert res["posterior"]
    for v, entry in res["posterior"].items():
        assert "held_status" in entry and entry["held_status"] is None, v
        assert isinstance(entry.get("held_status_reason"), str), v
        assert entry["held_status_reason"].strip(), v
        assert not any(str(r).startswith("held at ") for r in entry["status_reasons"]), v
        assert entry["fit_route"]["kind"] == "conjugate", v  # the route doesn't need the zone


# ------------------------------------------------------------------ S39 (7) the runs counted


@pytest.mark.parametrize("which", ["other_client", "synthetic", "no_record"])
def test_J7_S39_7_runs_not_counted(env: J7Env, which: str) -> None:
    """Estimable runs a day and more back that are not the client's saved, real runs. Counted,
    they would lift the target's held status; not counted, the target is a first appearance."""
    t = BASE + 3 * D1
    kw: dict[str, Any] = {
        "other_client": {"client": X.OTHER},
        "synthetic": {"synthetic": True},
        "no_record": {"record": False},
    }[which]
    for x in (t - 25 * H1, t - 12 * H1, t - H1):
        env.put_run(x, E, **kw)
    target = env.put_run(t, E)
    assert held_of(env, target) == B


def test_J7_S39_7_a_record_entry_with_no_file_is_skipped(env: J7Env) -> None:
    last = marginal_day(env)
    est = estimable_day(env, last + H1)
    env.put_run(last + 27 * H1 + dt.timedelta(minutes=30), B, file=False)
    target = env.put_run(last + 28 * H1, E)
    assert held_of(env, est[-1]) == E
    assert held_of(env, target) == E


def test_J7_S39_7_a_tie_in_started_at_goes_to_the_greater_run_id(env: J7Env) -> None:
    """Held marginal; at T two runs, one dropping to below_floor. The smaller run id is the
    earlier, whatever the order they were recorded in, so the other run sees the drop."""
    last = marginal_day(env)
    t = last + 6 * H1
    later = env.put_run(t, M, run_id="run_00000bbb")  # recorded first
    earlier = env.put_run(t, B, run_id="run_00000aaa")
    assert held_of(env, earlier) == B
    assert held_of(env, later) == B  # after the drop; a rise would wait a day


def test_J7_S39_7_an_unreadable_run_record_raises(env: J7Env) -> None:
    last = marginal_day(env)
    rid = env.put_run(last + H1, E)
    assert held_of(env, rid) == M  # readable, it answers
    write_garbage(env.data_dir / run_record.DB_NAME)
    with pytest.raises(Exception):  # noqa: B017
        env.held(rid)
    _assert_null_held(env.result(rid))


def test_J7_S39_7_an_unreadable_run_file_in_the_series_raises(env: J7Env) -> None:
    last = marginal_day(env)
    rid = env.put_run(last + H1, E)
    assert held_of(env, rid) == M  # readable, it answers
    write_garbage(env.data_dir / "runs" / f"{env.runs[2].run_id}.json")
    with pytest.raises(Exception):  # noqa: B017
        env.held(rid)


def test_J7_S39_7_a_run_with_no_started_at_raises(env: J7Env) -> None:
    last = marginal_day(env)
    rid = env.put_run(last + H1, E, record=False)
    assert held_of(env, env.runs[-2].run_id) == M  # the recorded run before it answers
    with pytest.raises(Exception):  # noqa: B017
        env.held(rid)
    _assert_null_held(env.result(rid))  # S39 (8): not in the run record


# ------------------------------------------------------------------ (f) result_of, S39 (8), (9)


def _result_series(env: J7Env) -> str:
    """The newest run: IMG3's ctr raw estimable two hours into a rise (held marginal), IMG2's
    ctr not estimable (a below-floor entry), IMG4's marginal (held equal to raw)."""
    last = marginal_day(env)
    env.put_run(last + H1, {IMG3_ID: E})
    return env.put_run(last + 2 * H1, {IMG3_ID: E}, not_estimable=[(IMG2_ID, "ctr")])


def test_J7_f_result_of_carries_held_status_and_fit_route_on_every_posterior_entry(
    env: J7Env,
) -> None:
    rid = _result_series(env)
    res = env.result(rid)
    post = res["posterior"]
    assert set(post) == {IMG3_ID, IMG2_ID, IMG4_ID}  # variants are the ad ids here
    snap = env.snap_json(rid)
    fit_route = {"kind": "conjugate", "step": "conjugate", "try": None}
    assert snap["route"]["kind"] == "conjugate" and snap["configuration"]["fit_step"] == "conjugate"
    held = env.held(rid)
    for v, entry in post.items():
        assert entry["fit_route"] == fit_route, v  # S39 (9), below floor too
        assert entry["held_status"] == held[key(v)], v
        assert entry.get("held_status_reason") is None, v

    img3 = post[IMG3_ID]
    assert img3["status"] == E and img3["held_status"] == M
    assert img3["route"] == "conjugate"  # the existing string, as it is
    assert set(img3) - NEW_ENTRY_KEYS == QUANTITY_ENTRY_KEYS
    assert rec_line(M, E) in img3["status_reasons"]
    assert [r for r in img3["status_reasons"] if r != rec_line(M, E)] == []

    img2 = post[IMG2_ID]
    assert img2["status"] == B and img2["held_status"] == B
    assert img2["quantity_id"] is None
    assert set(img2) - NEW_ENTRY_KEYS == BELOW_FLOOR_ENTRY_KEYS
    assert "route" not in img2
    assert img2["status_reasons"] == ["not estimable for the case"]

    img4 = post[IMG4_ID]
    assert img4["status"] == M and img4["held_status"] == M
    q4 = next(
        q for q in snap["quantities"] if q["name"] == "ctr" and q["scope"]["ids"] == {"ad": IMG4_ID}
    )
    assert img4["status_reasons"] == q4["feasibility"]["reasons"]  # nothing added at held = raw


def test_J7_S39_9_fit_route_reads_the_snapshot(env: J7Env) -> None:
    last = marginal_day(env)
    nuts = env.put_run(last + H1, M, route_kind="nuts", fit_step="fallback_conjugate")
    for entry in env.result(nuts)["posterior"].values():
        assert entry["fit_route"] == {"kind": "nuts", "step": "fallback_conjugate", "try": None}
    old = env.put_run(last + 2 * H1, M, fit_step=None)
    assert "fit_step" not in env.snap_json(old)["configuration"]
    for entry in env.result(old)["posterior"].values():
        assert entry["fit_route"] == {"kind": "conjugate", "step": None, "try": None}


def test_J7_S39_8_an_unsaved_snapshot_gives_null_held_with_a_reason(env: J7Env) -> None:
    rid = _result_series(env)
    d = env.snap_json(rid)
    d["run_id"] = "run_0badf00d"
    snap = pipeline.RunSnapshot.model_validate(d)
    _assert_null_held(env.result_of_snapshot(snap))


def test_J7_f_the_run_file_and_record_keep_the_raw_status(env: J7Env) -> None:
    rid = _result_series(env)
    before = (env.data_dir / "runs" / f"{rid}.json").read_bytes()
    entry = env.result(rid)["posterior"][IMG3_ID]
    assert (entry["status"], entry["held_status"]) == (E, M)  # J7 (5): beside, not instead
    assert (env.data_dir / "runs" / f"{rid}.json").read_bytes() == before
    assert raw_of(env.snap_json(rid), key()) == E


# ------------------------------------------------------------------ (g) the renderer, S39 (10)


def _two_runs(env: J7Env, **kw: Any) -> str:
    """A newest run with IMG3's ctr raw estimable (and whatever ``kw`` sets)."""
    last = marginal_day(env)
    return env.put_run(last + H1, {IMG3_ID: E}, **kw)


@pytest.mark.parametrize(("raw", "held"), [(E, M), (M, B), (E, B), (E, E)])
def test_J7_g_fig_forms_and_menu_status_follow_held_and_status_raw_the_raw(
    env: J7Env, raw: str, held: str
) -> None:
    last = marginal_day(env)
    rid = env.put_run(last + H1, {IMG3_ID: raw})
    calls: list[str] = []

    def load_held(run_id: str) -> dict:
        calls.append(run_id)
        return env.raw_held_map(run_id, {key(): held})

    qid = env.qid(rid, IMG3_ID, "ctr")
    res = env.render7(f"Here: {fig_run(rid, qid)}.", load_held=load_held)
    assert res["ok"] is True, why(res)
    assert res["text"] == f"Here: {CTR_FULL[held]}."
    assert res["slots"][0]["quantity"]["status"] == held
    assert rid in calls
    menu = env.menu7(load_held=load_held)
    item = menu_item(menu, fig_run(rid, qid))
    assert item["status"] == held
    assert item["status_raw"] == raw
    assert item["forms"]["full"] == CTR_FULL[held]


def test_J7_g_the_default_loader_is_held_status(env: J7Env) -> None:
    rid = _two_runs(env)
    qid = env.qid(rid, IMG3_ID, "ctr")
    menu = env.menu7()
    item = menu_item(menu, fig_run(rid, qid))
    assert (item["status"], item["status_raw"]) == (M, E)
    assert item["forms"]["full"] == CTR_FULL[M]
    res = env.render7(f"Here: {fig_run(rid, qid)}.")
    assert res["ok"] is True, why(res)
    assert res["text"] == f"Here: {CTR_FULL[M]}."


def test_J7_g_cmp_follows_the_held_decision_status(env: J7Env) -> None:
    last = marginal_day(env, decision=M)
    rid = env.put_run(last + H1, M, decision=E)
    menu = env.menu7()  # the default loader: the decision is two hours into a rise
    item = menu_item(menu, cmp_run(rid))
    assert (item["status"], item["status_raw"]) == (M, E)
    assert item["forms"]["full"] == f"{CMP_FULL}, {ROUGH}"
    res = env.render7(f"So: {cmp_run(rid)}.")
    assert res["ok"] is True, why(res)
    assert res["text"] == f"So: {CMP_FULL}, {ROUGH}."
    # held equal to raw: no caveat
    res = env.render7(
        f"So: {cmp_run(rid)}.", load_held=lambda r: env.raw_held_map(r, {decision_key(): E})
    )
    assert res["text"] == f"So: {CMP_FULL}.", why(res)
    # held below floor
    floor = env.render7(
        f"So: {cmp_run(rid)}.", load_held=lambda r: env.raw_held_map(r, {decision_key(): B})
    )
    assert floor["text"] == "So: which ad is best, not knowable yet.", why(floor)


def test_J7_g_a_non_ad_slot_follows_its_held_status(env: J7Env) -> None:
    rid = _two_runs(env, status={(ADSET, "cvr"): E})
    qid = env.qid(rid, ADSET, "cvr")
    menu = env.menu7()
    item = menu_item(menu, fig_run(rid, qid))
    assert item["subject"] == ADSET
    assert (item["status"], item["status_raw"]) == (M, E)
    assert "about" in item["forms"]["full"] and ROUGH in item["forms"]["full"]
    est = env.menu7(load_held=lambda r: env.raw_held_map(r, {adset_key(): E}))
    full = menu_item(est, fig_run(rid, qid))["forms"]["full"]
    assert "about" not in full and ROUGH not in full


@pytest.mark.parametrize("how", ["none", "raises", "default"])
def test_J7_g_S39_10_the_renderer_refuses_every_fig_and_cmp_slot_when_held_is_null(
    env: J7Env, how: str
) -> None:
    if how == "default":  # no zone anywhere: held_status raises inside the default loader
        last = marginal_day(env, tz=None)
        rid = env.put_run(last + H1, {IMG3_ID: E}, tz=None)
        kw: dict[str, Any] = {}
    else:
        rid = _two_runs(env)

        def load_held(run_id: str) -> dict:
            if how == "raises":
                raise RuntimeError("held store unreadable for the case")
            return None  # type: ignore[return-value]

        kw = {"load_held": load_held}
    qid = env.qid(rid, IMG3_ID, "ctr")
    for slot in (fig_run(rid, qid), cmp_run(rid), fig_run(rid, env.qid(rid, ADSET, "cvr"))):
        res = env.render7(f"Here: {slot}.", **kw)
        assert res["ok"] is False, (slot, why(res))
        assert res["text"] is None
        assert res["slots"][0]["ok"] is False
        if how == "raises":
            assert "held store unreadable for the case" in why(res)
    menu = env.menu7(**kw)
    assert run_items(menu, rid) == []  # never a fall back to raw
    names = env.render7(f"The ad {name_slot(IMG3_ID)} is live.", **kw)
    assert names["ok"] is True, why(names)  # a name slot doesn't read a status


# ------------------------------------------------------------------ (h) no allocation, S39 (13)


def test_J7_h_the_menu_lists_no_recommendation_allocation_or_share(env: J7Env) -> None:
    rid = _two_runs(env)
    snap = env.snap_json(rid)
    rec_ids = [r["recommendation_id"] for r in snap["recommendations"]]
    assert rec_ids  # the run has a recommendation to refuse
    qids = {q["quantity_id"] for q in snap["quantities"]}
    menu = env.menu7(load_held=lambda r: env.raw_held_map(r))
    assert run_items(menu, rid)
    for item in menu["slots"]:
        assert item["kind"] in ("fig", "cmp", "name", "na"), item  # S52: J9.2's na kind
        assert not any(r in item["token"] for r in rec_ids), item
        for word in ("alloc", "share", "budget", "recommend"):
            assert word not in str(item["measure"] or "").lower(), item
        if item["kind"] == "fig" and item["run_id"] == rid:
            assert item["token"].removeprefix(f"{{fig:run/{rid}/").removesuffix("}") in qids


def test_J7_h_S39_13_a_made_up_ref_is_refused(env: J7Env) -> None:
    rid = _two_runs(env)
    load_held = lambda r: env.raw_held_map(r)  # noqa: E731
    rec_id = env.snap_json(rid)["recommendations"][0]["recommendation_id"]
    good = env.render7(f"Here: {fig_run(rid, env.qid(rid, IMG3_ID, 'ctr'))}.", load_held=load_held)
    assert good["ok"] is True, why(good)
    for qid in (rec_id, "q_00000000", "allocation", "budget_share"):
        res = env.render7(f"Here: {fig_run(rid, qid)}.", load_held=load_held)
        assert res["ok"] is False, (qid, why(res))
        assert res["text"] is None


# ------------------------------------------------------------------ (i) markers, S39 (11)


def test_J7_i_a_new_marker_carries_the_pull_s_timezone_and_fit_route(j2env: J2.J2Env) -> None:
    j2env.client()  # the client's config says America/New_York; the pull says Chicago
    poll = J2.add_poll(j2env.store, J2.T0, J2.base_figures(), timezone="America/Chicago")
    rec = j2env.refresh(poll)
    assert rec.status == "ran", rec.reason
    snap = j2env.snapshot(str(rec.run_id))
    assert snap.timezone == "America/Chicago"  # J7 (8), filled from the pull
    m = json.loads(j2env.run_marker(str(rec.run_id)).read_text())
    assert set(m) == J2.ENGINE_RUN_FIELDS | {"timezone", "fit_route"}
    assert m["timezone"] == "America/Chicago"
    assert m["fit_route"] == {
        "kind": snap.route.kind,
        "step": snap.configuration["fit_step"],
        "try": None,
    }
    assert J2.canonical_marker(j2env.run_marker(str(rec.run_id)).read_bytes())


def test_J7_i_a_backfilled_marker_for_a_pre_J7_run(j2env: J2.J2Env) -> None:
    j2env.client()
    polls = j2env.history(upto="P1")
    rec = j2env.refresh(polls["P1"])
    assert rec.status == "ran", rec.reason
    d = json.loads(j2env.snapshot_file(str(rec.run_id)).read_text())
    for rid, edit in (
        ("run_0000aaaa", lambda x: x.pop("timezone", None)),
        ("run_0000bbbb", lambda x: (x.pop("timezone", None), x["configuration"].pop("fit_step"))),
        ("run_0000cccc", lambda x: x.update(timezone="America/Denver")),
    ):
        old = json.loads(json.dumps(d))
        edit(old)
        old["run_id"] = rid
        j2env.snapshot_file(rid).write_text(json.dumps(old))
    assert pipeline.load_snapshot("run_0000aaaa").timezone is None
    assert Mk.backfill()["engine_run"] == 3
    a = json.loads(j2env.run_marker("run_0000aaaa").read_text())
    assert a["timezone"] is None
    assert a["fit_route"] == {"kind": d["route"]["kind"], "step": "conjugate", "try": None}
    b = json.loads(j2env.run_marker("run_0000bbbb").read_text())
    assert b["timezone"] is None and b["fit_route"]["step"] is None
    c = json.loads(j2env.run_marker("run_0000cccc").read_text())
    assert c["timezone"] == "America/Denver"  # a post-J7 snapshot's own zone
    for m in (a, b, c):
        assert set(m) == J2.ENGINE_RUN_FIELDS | {"timezone", "fit_route"}


# ------------------------------------------------------------------ (k) nothing moves


def test_J7_k_run_id_seed_and_config_hash_are_unchanged(
    j2env: J2.J2Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(prior_registry, "utcnow", lambda: T_APPROVE)
    j2env.client()
    monkeypatch.setattr(pipeline, "utcnow", lambda: T_RUN)
    polls = j2env.history(upto="P1")
    rec = j2env.refresh(polls["P1"])
    assert rec.status == "ran", rec.reason
    run_id = str(rec.run_id)
    snap, record = j2env.snapshot(run_id), j2env.record(run_id)
    assert snap.timezone == J2.TZ  # the J7 field is filled
    assert run_id == RUN_ID_BEFORE_J2
    assert record.seeds["fit"] == SEED_BEFORE_J2 == snap.configuration["seed"]
    assert snap.config_hash == record.config_hash == CONFIG_HASH_AFTER_L12  # L12.3


# ------------------------------------------------------------------ property: held <= raw


def test_J7_property_held_never_exceeds_raw_and_matches_S39(env: J7Env, tmp_path: Path) -> None:
    """Random series: steps from a tie to more than a day, random ctr and decision statuses,
    ads dropping out of variants. For every run and key, held is at most raw; the ctr and
    decision keys equal S39's rule written from the text (``oracle_held``); a drop equals raw;
    and each run's answer is the same before and after the later runs are written (check c)."""
    rng = random.Random(20261127)
    steps = [0, 20, 60, 60, 60, 300, 720, 1380, 1440, 1441, 1500, 1800]  # minutes
    for n in range(8):
        env.data_dir = tmp_path / f"prop_{n}"
        env.data_dir.mkdir()
        env.runs = []
        t = at("2026-11-05T12:00")
        first: dict[str, dict[Any, str]] = {}
        for i in range(16):
            t += dt.timedelta(minutes=rng.choice(steps))
            absent = [a for a in (IMG3_ID, IMG2_ID, IMG4_ID) if rng.random() < 0.2][:1]
            ctr = {a: rng.choice((B, M, E, E)) for a in (IMG3_ID, IMG2_ID, IMG4_ID)}
            rid = env.put_run(
                t,
                ctr,
                absent=absent,
                decision=rng.choice((B, M, E, E)),
                run_id=f"run_{n:02x}{i:06x}",  # a tie written later is later (the tie test
            )  # covers ties against the write order)
            first[rid] = env.held(rid)
        want = oracle_held(env.runs, NY)
        for run in env.runs:
            got = env.held(run.run_id)
            assert got == first[run.run_id], run.run_id  # (c)
            d = env.snap_json(run.run_id)
            for k, h in got.items():
                raw = raw_of(d, k)
                assert raw is not None and RANK[h] <= RANK[raw], (run.run_id, k, h, raw)
            for k, w in want[run.run_id].items():
                assert got.get(k) == w, (n, run.run_id, run.at, k, got.get(k), w)
            for ad in set((IMG3_ID, IMG2_ID, IMG4_ID)) - set(d["variants"].values()):
                assert not [k for k in got if k[1] == ad], (run.run_id, ad)


# ------------------------------------------------------------------ (j) the live store copy

LIVE = REPO / "data" / "live"
LIVE_RECORD = LIVE / "engine" / run_record.DB_NAME


@pytest.mark.skipif(not LIVE_RECORD.is_file(), reason="no live run record on this machine")
def test_J7_j_live_copy_is_fast_and_changes_less_often_than_raw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "live_copy"
    engine = base / "engine"
    engine.mkdir(parents=True)
    shutil.copy2(LIVE_RECORD, engine / run_record.DB_NAME)
    shutil.copytree(LIVE / "engine" / "runs", engine / "runs")
    for name in ("live.sqlite", "live.sqlite-wal"):
        if (LIVE / name).is_file() and (LIVE / name).stat().st_size:
            shutil.copy2(LIVE / name, base / name)
    for p in base.rglob("*"):
        if p.is_file():
            os.chmod(p, 0o444)
    monkeypatch.setenv("BAYES_DATA_DIR", str(engine))
    monkeypatch.setenv("BAYES_LIVE_DIR", str(base))

    records = run_record.read("RunRecord")
    snaps: dict[str, dict[str, Any]] = {}
    started: dict[str, dt.datetime] = {}
    for r in records:
        path = engine / "runs" / f"{r.run_id}.json"
        if path.is_file():
            d = json.loads(path.read_text())
            if not d.get("synthetic"):
                snaps[r.run_id] = d
                started[r.run_id] = r.started_at
    newest = max(snaps, key=lambda rid: (started[rid], rid))
    client = snaps[newest]["client_id"]
    series = sorted(
        (rid for rid, d in snaps.items() if d["client_id"] == client),
        key=lambda rid: (started[rid], rid),
    )

    t0 = time.perf_counter()
    H.held_status(newest)
    elapsed = time.perf_counter() - t0

    last: dict[Any, tuple[str, str]] = {}
    raw_changes = held_changes = 0
    metric_raw = metric_held = 0
    for rid in series:
        got = H.held_status(rid)
        for k, h in got.items():
            raw = raw_of(snaps[rid], k)
            assert raw is not None and RANK[h] <= RANK[raw], (rid, k, h, raw)
            if k in last:
                dr, dh = last[k][0] != raw, last[k][1] != h
                raw_changes += dr
                held_changes += dh
                if k[0] == "ad" and k[2] == pipeline.metric_quantity(k[4]):
                    metric_raw += dr
                    metric_held += dh
            last[k] = (raw, h)
    print(
        f"\nJ7 (j): {len(series)} runs of {client}; held_status on the newest in "
        f"{elapsed:.3f}s; status changes between consecutive appearances: raw {raw_changes}, "
        f"held {held_changes}; the metric alone: raw {metric_raw}, held {metric_held}"
    )
    assert elapsed < 2.0
    assert held_changes <= raw_changes
