"""Blind review of J8 at bda884a. Each test is a probe of a limit the Principal Architect set:
the gate never loosens, a retry never hides itself, a first-try pass does not move."""

from __future__ import annotations

import itertools
import math
import subprocess
import types
from pathlib import Path

import pytest
from tests.acceptance import j8_fixtures as F
from tests.acceptance.conftest import iso  # noqa: F401
from tests.fakes import builders as B

from bayesian_marketing import core as C
from bayesian_marketing import pipeline
from bayesian_marketing.core import inputs_hash
from bayesian_marketing.diagnostics import run as diag
from bayesian_marketing.funnel_state import store
from bayesian_marketing.inference import fallback
from bayesian_marketing.live import markers

pytestmark = pytest.mark.piece("J8")

REPO = Path(__file__).resolve().parents[2]
FULL, STATIC, UNPOOLED = F.NUTS_STEPS
SEED = 1234567


def _old_diag() -> types.ModuleType:
    src = subprocess.run(
        ["git", "show", "0e6c037:src/bayesian_marketing/diagnostics/run.py"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    mod = types.ModuleType("bayesian_marketing.diagnostics._run_old")
    mod.__package__ = "bayesian_marketing.diagnostics"
    exec(compile(src, "run_old.py", "exec"), mod.__dict__)
    return mod


def _grid() -> list:
    reports = []
    nan, inf = float("nan"), float("inf")
    for div, rhat, bulk, tail in itertools.product(
        [0, 1, 7, None, nan, inf], [1.001, 1.05, None, nan, inf], [1500.0, 100.0, None, nan],
        [1200.0, 5.0, None, inf],
    ):  # fmt: skip
        r = B.diagnostics_report(divergences=0, rhat=1.001, ess_bulk=1500.0, ess_tail=1200.0)
        reports.append(r.model_copy(update={
            "n_divergences": div, "rhat_max": rhat, "ess_bulk_min": bulk, "ess_tail_min": tail,
        }))  # fmt: skip
    base = B.diagnostics_report(divergences=3)
    for ppc in (
        {"ctr": 0.5}, {"ctr": float("nan")}, {"ctr": 0.001}, {f"{diag.NON_FINITE}ad_a.ctr": 0.0},
        {"ctr": float("inf")},
    ):  # fmt: skip
        reports.append(base.model_copy(update={"ppc": ppc}))
    reports.append(base.model_copy(update={"sampler": "conjugate_exact"}))
    return reports


# ---- g3 after its refactor ---------------------------------------------------------------------


def test_g3_is_unchanged_by_the_refactor_on_a_grid_of_reports() -> None:
    old = _old_diag()
    n = 0
    for r in _grid():
        a, ga = old.g3(r)
        b, gb = diag.g3(r)
        assert (a.passed, ga.passed, ga.reasons, ga.inputs_hash, ga.blocking) == (
            b.passed, gb.passed, gb.reasons, gb.inputs_hash, gb.blocking,
        ), r  # fmt: skip
        assert repr(a.model_dump()) == repr(b.model_dump())
        n += 1
    assert n > 400


# ---- divergences_only is never fooled ----------------------------------------------------------


def test_divergences_only_is_true_only_when_zeroing_the_count_makes_g3_pass() -> None:
    """Oracle from the old g3: the report fails G3, passes once its count is 0, and the count is
    a finite number above the threshold."""
    old = _old_diag()
    seen_true = 0
    for r in _grid():
        n = r.n_divergences
        finite = n is not None and math.isfinite(float(n))
        want = False
        if finite and float(n) > 0:
            want = bool(old.g3(r.model_copy(update={"n_divergences": 0}))[1].passed)
        assert diag.divergences_only(r) is want, (n, r.rhat_max, r.ess_bulk_min, r.ess_tail_min)
        seen_true += want
    assert seen_true > 0


def test_divergences_only_never_true_when_g3_passes() -> None:
    for r in _grid():
        if diag.g3(r)[1].passed:
            assert diag.divergences_only(r) is False


# ---- retry seeds -------------------------------------------------------------------------------


def test_retry_seeds_deterministic_distinct_and_32_bit_over_many_runs() -> None:
    for seed in range(0, 3000, 7):
        taken = {seed}
        got = []
        for step in F.NUTS_STEPS:
            for n in (1, 2, 3):
                s = fallback.retry_seed(seed, step, n, taken)
                assert s == fallback.retry_seed(seed, step, n, set(taken) - {s})  # stable
                taken.add(s)
                got.append(s)
                assert 0 <= s < 2**32
        # try 1 of every step is the run's seed (pre-J8 chain); the six retries are all distinct
        retries = [s for i, s in enumerate(got) if i % 3]
        assert len(set(retries)) == 6 and seed not in retries


def test_retry_seed_salts_past_the_run_seed_and_every_taken_seed() -> None:
    seed = 99
    raw = F.retry_seed_formula(seed, FULL, 2)
    assert fallback.retry_seed(seed, FULL, 2, {seed}) == raw
    salted = fallback.retry_seed(seed, FULL, 2, {seed, raw})
    assert salted not in {seed, raw}
    assert salted == fallback.retry_seed(seed, FULL, 2, {seed, raw})
    # a hash that equals the run's seed
    alt = F.retry_seed_formula(raw, FULL, 2)  # a run whose seed is the first run's retry seed
    s2 = fallback.retry_seed(raw, FULL, 2, {raw})
    assert s2 != raw and alt != raw


def test_retry_seed_survives_a_forced_collision_with_the_run_seed(monkeypatch) -> None:
    calls = []

    def fake(key):
        calls.append(key)
        return "00000005" + "0" * 56 if "salt" not in key else "0000000a" + "0" * 56

    monkeypatch.setattr(fallback, "inputs_hash", fake)
    assert fallback.retry_seed(5, FULL, 2, {5}) == 10


def test_every_seed_in_a_nine_try_run_is_numpy_and_jax_safe() -> None:
    jax = pytest.importorskip("jax")
    taken = {SEED}
    for step in F.NUTS_STEPS:
        for n in (2, 3):
            s = fallback.retry_seed(SEED, step, n, taken)
            taken.add(s)
            jax.random.PRNGKey(s)


# ---- the chain ---------------------------------------------------------------------------------


def _run(monkeypatch, script, seed=SEED):
    spec = B.funnel_spec(dynamics="random_walk")
    sampler = F.patch_chain(monkeypatch, script, base=spec)
    out = fallback.fit_with_fallback(spec, B.default_prior_set(), F.eight_ads(), seed)
    return sampler, out


def test_a_state_with_divergences_is_never_accepted_over_random_scripts(monkeypatch) -> None:
    import random

    rng = random.Random(8)
    kinds = [F.div(1), F.div(3), {"rhat": 1.2}, {"divergences": None}, F.clean(), F.clean()]
    for i in range(40):
        cells = {(s, k): rng.choice(kinds) for s in F.NUTS_STEPS for k in (1, 2, 3)}
        sampler, (state, reports, notices, attempts) = _run(monkeypatch, cells)
        # every sampler call is an attempt, in order; the same seeds
        assert [(c.step, c.k, c.seed) for c in sampler.calls] == [
            (a["step"], a["try"], a["seed"]) for a in attempts
        ]
        n_conj = 0 if any(a['passed'] for a in attempts) else 1  # the conjugate fallback report
        assert len(reports) == len(sampler.calls) + n_conj == len(attempts) + n_conj
        passed = [a for a in attempts if a["passed"]]
        assert len(passed) <= 1
        if passed:
            assert passed[0] is attempts[-1]
            assert state.state_id == sampler.calls[-1].state_id
            assert reports[-1].n_divergences == 0 and reports[-1].passed is True
            assert state.quarantined is not True
        else:
            assert state.route == "conjugate"
        # every failed try's state is quarantined
        for c, a in zip(sampler.calls, attempts):
            if not a["passed"]:
                assert store.load(c.state_id).quarantined is True, (i, c)
        # a retry happens only after divergences alone
        for prev, cur in zip(attempts, attempts[1:]):
            if cur["step"] == prev["step"]:
                assert cur["try"] == prev["try"] + 1
                assert prev["divergences"] not in (None, 0) and not prev["passed"]
                rep = reports[attempts.index(prev)]
                assert diag.divergences_only(rep)
        seeds = [a["seed"] for a in attempts if a["try"] > 1]
        assert len(seeds) == len(set(seeds))
        monkeypatch.undo()


def test_raise_on_a_retry_is_recorded_and_moves_on(monkeypatch) -> None:
    spec = B.funnel_spec(dynamics="random_walk")
    sampler = F.patch_chain(monkeypatch, {(FULL, 1): F.div(2)}, base=spec)
    orig = sampler.fit

    def boom(model, data, cfg):
        if model.spec_version.endswith(FULL) and sum(c.step == FULL for c in sampler.calls) == 1:
            sampler.calls.append(F.Call(FULL, 2, cfg.seed, "x", "y", None))
            raise RuntimeError("boom")
        return orig(model, data, cfg)

    sampler.fit = boom
    state, reports, notices, attempts = fallback.fit_with_fallback(
        spec, B.default_prior_set(), F.eight_ads(), SEED
    )
    assert [(a["step"], a["try"], a["divergences"], a["passed"]) for a in attempts[:3]] == [
        (FULL, 1, 2, False), (FULL, 2, None, False), (STATIC, 1, 0, True),
    ]  # fmt: skip
    assert state.route == "nuts"


def test_retry_notice_text_holds_only_step_tries_seeds_counts(monkeypatch) -> None:
    sampler, (state, reports, notices, attempts) = _run(monkeypatch, F.always(F.div(2)))
    texts = [n.reason for n in notices]
    for n in notices:
        assert set(n.model_dump()) >= {"notice_id", "step", "reason", "affected"}
    retried = [t for t in texts if "retried on divergences" in t]
    assert len(retried) == 3
    for t in retried:
        assert "no try passed" in t and "Traceback" not in t and "/" not in t
        assert t.count("try ") >= 3
    # a retry notice names no ad, and nothing beyond the step
    assert all(not any(a in t for a in ("ad_0", "ad_1")) for t in retried)


def test_worst_case_is_nine_nuts_fits_and_three_compiles(monkeypatch) -> None:
    sampler, (state, *_rest) = _run(monkeypatch, F.always(F.div(1)))
    assert len(sampler.calls) == 9
    assert sampler.compiler.steps == list(F.NUTS_STEPS)
    assert state.route == "conjugate"


def test_a_failed_try_one_that_is_not_divergence_only_costs_one_fit_per_step(monkeypatch) -> None:
    sampler, (state, *_rest) = _run(monkeypatch, F.always({"divergences": 3, "rhat": float("nan")}))
    assert len(sampler.calls) == 3


# ---- pipeline ----------------------------------------------------------------------------------


def test_first_try_pass_has_no_fit_accepted_and_the_record_is_plain(iso, monkeypatch) -> None:
    env = F.pipeline_env(iso, monkeypatch)
    F.patch_chain(monkeypatch, None, derivable=True)
    ctx = env.execute()
    assert ctx.result.run.seeds == {"fit": env.seed()}
    assert [a["try"] for a in ctx.snapshot.fit_attempts] == [1]


def test_a_retry_that_passes_late_in_the_chain_keeps_every_failed_state_quarantined(
    iso, monkeypatch
) -> None:
    env = F.pipeline_env(iso, monkeypatch)
    cells = {(FULL, k): F.div(1) for k in (1, 2, 3)} | {(UNPOOLED, 1): F.div(1)}
    sampler = F.patch_chain(monkeypatch, cells, derivable=True)
    ctx = env.execute()
    rows = F.attempt_rows(ctx.snapshot.fit_attempts)
    assert [r[:2] for r in rows] == [(FULL, 1), (FULL, 2), (FULL, 3), (UNPOOLED, 1), (UNPOOLED, 2)]
    failed = [c for c, a in zip(sampler.calls, ctx.snapshot.fit_attempts) if not a["passed"]]
    assert failed
    for c in failed:
        assert store.load(c.state_id).quarantined is True
    acc = [a for a in ctx.snapshot.fit_attempts if a["passed"]]
    assert len(acc) == 1
    seeds = ctx.result.run.seeds
    assert ("fit_accepted" in seeds) == (acc[0]["try"] > 1)
    assert markers.fit_route(__import__("json").loads(ctx.snapshot.model_dump_json()))["try"] == (
        acc[0]["try"]
    )


def test_fit_route_try_for_snapshots_with_odd_attempt_lists() -> None:
    assert markers.fit_route({"route": {"kind": "nuts"}})["try"] is None
    assert markers.fit_route({"fit_attempts": None})["try"] is None
    assert markers.fit_route({"fit_attempts": [{"try": 2, "passed": False}]})["try"] is None
    assert pipeline.accepted_attempt([]) is None


# ---- repository hygiene ------------------------------------------------------------------------


def test_the_four_amended_tests_changed_only_their_unpacking() -> None:
    out = subprocess.run(
        ["git", "diff", "-U0", "0e6c037", "bda884a", "--",
         "tests/acceptance/test_P6.py", "tests/unit/p6/test_p6_units.py",
         "tests/unit/p6/test_p6_review.py"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    minus = [x[1:] for x in out.splitlines() if x.startswith("-") and not x.startswith("---")]
    plus = [x[1:] for x in out.splitlines() if x.startswith("+") and not x.startswith("+++")]
    assert len(minus) == len(plus) == 4
    for a, b in zip(minus, plus):
        assert a.replace("state, reports, notices =", "state, reports, notices, _ =") == b


def test_the_diff_touches_no_data_notebook_scripts_configs_or_registries() -> None:
    names = subprocess.run(
        ["git", "diff", "--name-only", "0e6c037", "bda884a"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.split()  # fmt: skip
    assert names and all(n.startswith(("src/", "tests/")) for n in names), names
    assert not any(n.startswith(("src/bayesian_marketing/live/templates",)) for n in names)
