"""Blind review of J7 at 45dca37. Every test here is a finding or a recorded pass."""

from __future__ import annotations

import datetime as dt
import json
import random
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tests.acceptance import j4_fixtures as X
from tests.acceptance.conftest import iso  # noqa: F401
from tests.acceptance.j7_fixtures import ADS, E, J7Env, M, at, key
from tests.acceptance.j4r_fixtures import fig_run

from bayesian_marketing.claims import _refs as R
from bayesian_marketing.claims import held as H

pytestmark = pytest.mark.piece("J7")

BASE = at("2026-11-10T12:00")
H1 = dt.timedelta(hours=1)


@pytest.fixture
def env(iso, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[J7Env]:
    e = J7Env(tmp_path, monkeypatch)
    yield e
    e.close()


def _old_kind(env: J7Env, run_id: str) -> None:
    """Make the run's file look like one saved before J5: no conversion_kind."""
    p = env.data_dir / "runs" / f"{run_id}.json"
    d = json.loads(p.read_text())
    d["conversion_kind"] = None
    p.write_text(json.dumps(d))


def _no_config(env: J7Env) -> None:
    for f in env.config_root.glob("*.yaml"):
        f.unlink()  # the client's config can't be read, so R9 falls to the client's runs
    assert env.in_data(R.config_kind, X.CLIENT) is None, "the case needs a client with no config"


# ---- (2) reading 1: the old snapshot's kind comes from the client's later runs ----------------


def test_F1_held_keys_of_an_old_run_do_not_move_when_a_later_lead_run_arrives(env: J7Env) -> None:
    """S39 (4), J7 (2): the same run always gets the same answer. An old run (no conversion_kind,
    client with no readable config) takes its kind from R9's last step, which reads the client's
    later runs; a later lead run changes the kind, so the keys of the answer change."""
    _no_config(env)
    old = [env.put_run(BASE + n * H1, E, kind=None) for n in range(30)]  # type: ignore[arg-type]
    for r in old:
        _old_kind(env, r)
    before = env.held(old[-1])
    env.put_run(BASE + 40 * H1, E, kind="lead")
    after = env.held(old[-1])
    assert after == before


def test_F2_held_value_of_a_run_does_not_change_when_a_later_run_of_another_kind_arrives(
    env: J7Env,
) -> None:
    """The same cause moves a value: old runs plus one explicit purchase run P form one series
    while no run says lead (kind_from_runs gives purchase). A later lead run turns the old runs
    into lead, P starts a new series, and P's held status drops to below_floor."""
    _no_config(env)
    old = [env.put_run(BASE + n * H1, E, kind=None) for n in range(30)]  # type: ignore[arg-type]
    for r in old:
        _old_kind(env, r)
    p = env.put_run(BASE + 35 * H1, E, kind="purchase")
    before = {k[1:]: v for k, v in env.held(p).items()}
    env.put_run(BASE + 40 * H1, E, kind="lead")
    after = {k[1:]: v for k, v in env.held(p).items()}
    assert after == before


def test_P_old_run_menu_and_result_of_use_the_same_key(env: J7Env) -> None:
    """Recorded pass: with no later run to disturb it, an old run's result_of and menu read the key
    held_status wrote."""
    _no_config(env)
    old = [env.put_run(BASE + n * H1, E, kind=None) for n in range(30)]  # type: ignore[arg-type]
    for r in old:
        _old_kind(env, r)
    res = env.result(old[-1])
    for v, ent in res["posterior"].items():
        assert ent["held_status"] == E, (v, ent.get("held_status_reason"))
    qid = env.qid(old[-1], X.IMG3_ID, "ctr")
    menu = env.menu7()
    item = [s for s in menu["slots"] if s["token"] == fig_run(old[-1], qid)]
    assert item and item[0]["status"] == E and item[0]["status_raw"] == E


# ---- the guarantee, at random ----------------------------------------------------------------


def _random_steps(rng: random.Random, n: int) -> list[tuple[dt.datetime, dict[str, str], bool]]:
    t = BASE
    out = []
    for _ in range(n):
        t = t + dt.timedelta(minutes=rng.choice([30, 60, 180, 600, 1440, 1441, 2000]))
        ctr = {ad: rng.choice(["below_floor", M, E, E, E]) for ad in ADS}
        out.append((t, ctr, rng.random() < 0.2))
    return out


@pytest.mark.parametrize("seed", range(4))
def test_P_held_never_above_raw_and_independent_of_later_runs(
    iso, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, seed: int
) -> None:
    """Recorded pass: with absences, not_estimable and decisions, held is at most raw in
    result_of, and the answer for each run is the same in a store that stops at that run."""
    rng = random.Random(seed)
    steps = _random_steps(rng, 14)
    (tmp_path / "full").mkdir()
    full = J7Env(tmp_path / "full", monkeypatch)
    try:
        ids = []
        for i, (t, ctr, drop) in enumerate(steps):
            kw: dict[str, Any] = {"run_id": f"run_r{seed}x{i:02d}"}
            if drop:
                kw["not_estimable"] = [(X.IMG2_ID, "ctr")]
            ids.append(full.put_run(t, ctr, **kw))
        full_held = {r: full.held(r) for r in ids}
        for r in ids:
            res = full.result(r)
            for v, ent in res["posterior"].items():
                if ent["held_status"] is not None:
                    assert H.rank(ent["held_status"]) <= H.rank(ent["status"]), (r, v)
    finally:
        full.close()
    for cut in (3, 8, 13):
        sub = tmp_path / f"cut{cut}"
        sub.mkdir()
        part = J7Env(sub, monkeypatch)
        try:
            for i, (t, ctr, drop) in enumerate(steps[: cut + 1]):
                kw = {"run_id": f"run_r{seed}x{i:02d}"}
                if drop:
                    kw["not_estimable"] = [(X.IMG2_ID, "ctr")]
                part.put_run(t, ctr, **kw)
            assert part.held(ids[cut]) == full_held[ids[cut]], (seed, cut)
        finally:
            part.close()
