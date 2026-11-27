"""J8: the joint model's retry, recorded (Brain join spec v0.4, J8 items 10 to 13 and checks (a) to
(e), as S40 settles them; S40 governs where it differs from J8's text).

The sampler is never run. ``j8_fixtures.patch_chain`` replaces ``compile_model`` and
``NumpyroSampler.fit`` through their modules, as test_P6 does, with a scripted sampler whose report
for each (step, try) the test chooses. Call k of a step is its try k. Its state and report ids hash
(step, seed), so a try run at the wrong seed shows up as the wrong id.

Readings the spec leaves to the test writer, and how they are read here:

* An attempt is a dict with exactly the keys of ``fallback.ATTEMPT_FIELDS``: ``step`` (the §7.5
  step name), ``try`` (1, 2 or 3, counted within the step), ``seed`` (the seed the sampler was
  given), ``divergences`` (the report's ``n_divergences``, None when the report has none) and
  ``passed`` (G3's verdict on that try).
* Every NUTS try is an attempt, a try that isn't retried included (J8 (11), "every try"). Try 1 of
  every step, not only the first step, uses the run's seed: that is the chain before J8, and S40 (2)
  draws a retry's seed from (seed, step, try) only for tries 2 and 3.
* A retry's report stays in the reports ``fit_with_fallback`` returns, in try order, as every NUTS
  report does before J8 ("nothing about a retry is dropped").
* "One notice per retried step" is a notice added to the notices of the chain before J8 (one per
  step entered after the first). So a run has (steps entered after nuts_full, the conjugate step
  included) + (retried steps) notices. Its wording is free and isn't asserted.
* ``fit_route.try`` is the ``try`` of the attempt that passed. A run with no passing attempt (the
  D11 conjugate route, with no attempts, and the §7.5 conjugate fallback, whose nine tries all
  failed) has no accepted try, so ``try`` is null there.
* ``retry_seed(seed, step, 1, taken)`` is ``seed``, as its docstring says. The salt's form is free:
  a salted seed is only required to be deterministic and clear of the run's seed and ``taken``.
* "Byte-identical in its quantities" (J8 (12), check (d), S40 (2)) is pinned on the values the
  pipeline at the skeleton (5b13c40, before J8) gives for the same inputs at the same clock: run
  id, seed, config hash, state id, report ids, quantity ids, and a digest of the saved quantities
  less their check and compute times and their draws file's tmp path. The config hash is pinned
  too, because J8 adds the attempts to the snapshot and nowhere in ``configuration``. That test
  passes at the skeleton by design: it guards against a change, so it can't fail before one.
* Old snapshots loading with ``fit_attempts == []`` is the skeleton's default, so that test passes
  now as well.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from bayesian_marketing import core as C
from bayesian_marketing import pipeline
from bayesian_marketing.atmaos import socket as sock
from bayesian_marketing.core import registries
from bayesian_marketing.decision import run_record
from bayesian_marketing.diagnostics import run as diag
from bayesian_marketing.funnel_state import store
from bayesian_marketing.inference import fallback
from bayesian_marketing.live import markers
from tests.acceptance import j8_fixtures as F
from tests.fakes import builders as B

pytestmark = pytest.mark.piece("J8")

SEED = 7
FULL, STATIC, UNPOOLED = F.NUTS_STEPS

# test_J8_d pins these from the skeleton's pipeline (before J8) on PipelineEnv at F.T_RUN.
RUN_ID_BEFORE_J8 = "run_122248b8"
SEED_BEFORE_J8 = 950234362
CONFIG_HASH_BEFORE_J8 = "659bf8d46dd98b67703b0acce7f4b081e3fd46a0cffb4e8da73a87c2896afa91"
STATE_ID_BEFORE_J8 = "fs_a9d1f630"
REPORT_IDS_BEFORE_J8 = ["dg_a9d1f630"]
QUANTITY_IDS_BEFORE_J8 = [
    "q_47505601",
    "q_55bb565e",
    "q_5be86e9b",
    "q_765af69d",
    "q_7c49b859",
    "q_ab972303",
    "q_b7fb5ff2",
    "q_bf894c49",
    "q_c8a8d272",
    "q_d62857d5",
    "q_dc595f4f",
    "q_e1f121b9",
]
QUANTITIES_DIGEST_BEFORE_J8 = "16a5fbd684176a71ff99509cb61e469a33c94f1229bd531d2d19f72ce5bb5087"


def _spec() -> C.FunnelSpec:
    """Three distinct steps: random-walk dynamics and a campaign level above the ad."""
    spec = B.funnel_spec(dynamics="random_walk")
    assert [n for n, _ in F.chain_steps(spec)] == list(F.NUTS_STEPS)
    return spec


def _chain(monkeypatch: pytest.MonkeyPatch, script, seed: int = SEED):
    """Run ``fit_with_fallback`` on three steps. Returns (sampler, state, reports, notices,
    attempts)."""
    spec = _spec()
    sampler = F.patch_chain(monkeypatch, script, base=spec)
    out = fallback.fit_with_fallback(spec, B.default_prior_set(), F.eight_ads(), seed)
    assert isinstance(out, tuple) and len(out) == 4, "S40 (3): the attempts are a fourth value"
    state, reports, notices, attempts = out
    for a in attempts:
        assert set(a) == set(fallback.ATTEMPT_FIELDS), a
    return sampler, state, reports, notices, attempts


def _seed(step: str, n: int, seed: int = SEED) -> int:
    s = F.retry_seed_formula(seed, step, n)
    assert s != seed  # the inputs here never collide, so no salt is in play
    return s


def _quarantined(state_id: str) -> bool:
    return store.load(state_id).quarantined is True


# ------------------------------------------------------------------ S40 (1): divergences alone


def test_J8_S40_1_divergences_only_on_a_divergence_count_with_every_other_check_passing() -> None:
    assert diag.divergences_only(B.diagnostics_report(divergences=1)) is True
    assert diag.divergences_only(B.diagnostics_report(divergences=40)) is True


@pytest.mark.parametrize(
    "kw",
    [
        {"divergences": 0},  # G3 passes: nothing failed
        {"divergences": None},  # S40 (1): a null count is never retried
        {"divergences": 2, "rhat": 1.05},
        {"divergences": 2, "rhat": None},  # R-hat not computed fails G3 on a NUTS report
        {"divergences": 2, "ess_bulk": 399.0},
        {"divergences": 2, "ess_tail": 120.0},
        {"divergences": 2, "ppc": {"delivery": 0.5, "ctr": 0.5, "cvr": 0.01, "value": 0.5}},
        {"divergences": 2, "ppc": {f"{diag.NON_FINITE}ad_a.ctr": 0.0}},
        {"divergences": None, "rhat": 1.05},
    ],
    ids=[
        "zero",
        "null",
        "rhat",
        "rhat_not_computed",
        "ess_bulk",
        "ess_tail",
        "ppc",
        "non_finite_draws",
        "null_and_rhat",
    ],
)
def test_J8_S40_1_divergences_only_is_false_otherwise(kw: dict[str, Any]) -> None:
    assert diag.divergences_only(B.diagnostics_report(**kw)) is False


def test_J8_S40_1_divergences_only_reads_divergences_max_from_the_registry(iso) -> None:
    iso.edit_yaml("diagnostics", lambda d: d["thresholds"].update(divergences_max=3))
    assert diag.divergences_only(B.diagnostics_report(divergences=3)) is False  # G3 passes
    assert diag.divergences_only(B.diagnostics_report(divergences=4)) is True


# ------------------------------------------------------------------ S40 (2), check (e): seeds


def test_J8_S40_2_try_1_is_the_run_seed() -> None:
    for step in F.NUTS_STEPS:
        assert fallback.retry_seed(SEED, step, 1, set()) == SEED
        assert fallback.retry_seed(950234362, step, 1, set()) == 950234362


@pytest.mark.parametrize("seed", [SEED, 950234362, 0, 2**32 - 1])
def test_J8_S40_2_retry_seeds_are_the_formula_distinct_and_deterministic(seed: int) -> None:
    got = []
    for step in F.NUTS_STEPS:
        taken = {seed}
        for n in (2, 3):
            s = fallback.retry_seed(seed, step, n, set(taken))
            want = F.retry_seed_formula(seed, step, n)
            if want != seed and want not in taken:
                assert s == want, (step, n)
            assert s != seed and s not in taken
            assert fallback.retry_seed(seed, step, n, set(taken)) == s  # check (e)
            taken.add(s)
            got.append(s)
    assert len(set(got)) == len(got)


def test_J8_S40_2_a_seed_colliding_with_an_earlier_try_is_salted() -> None:
    f2 = F.retry_seed_formula(SEED, FULL, 2)
    first = fallback.retry_seed(SEED, FULL, 2, {SEED, f2})
    assert first not in {SEED, f2}
    assert fallback.retry_seed(SEED, FULL, 2, {SEED, f2}) == first  # deterministic
    second = fallback.retry_seed(SEED, FULL, 2, {SEED, f2, first})  # "until it doesn't"
    assert second not in {SEED, f2, first}


def test_J8_S40_2_a_seed_colliding_with_the_run_seed_is_salted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The unsalted hash is forced to give the run's seed for (seed, nuts_full, 2)."""
    real = fallback.inputs_hash
    forced = {"seed": SEED, "step": FULL, "try": 2}

    def rigged(obj: Any) -> str:
        if obj == forced:
            return f"{SEED:08x}" + "0" * 56
        return real(obj)

    monkeypatch.setattr(fallback, "inputs_hash", rigged)
    monkeypatch.setattr(C, "inputs_hash", rigged)
    s = fallback.retry_seed(SEED, FULL, 2, set())
    assert s != SEED
    assert fallback.retry_seed(SEED, FULL, 2, set()) == s
    s3 = fallback.retry_seed(SEED, FULL, 3, {SEED, s})
    assert s3 not in {SEED, s}


# ------------------------------------------------------------------ (a) a pass on the second try


def test_J8_a_divergent_first_try_then_a_pass_is_accepted_with_both_tries_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s2 = _seed(FULL, 2)
    sampler, state, reports, notices, attempts = _chain(monkeypatch, {(FULL, 1): F.div(1)})

    assert [(c.step, c.k, c.seed) for c in sampler.calls] == [(FULL, 1, SEED), (FULL, 2, s2)]
    assert F.attempt_rows(attempts) == [(FULL, 1, SEED, 1, False), (FULL, 2, s2, 0, True)]
    accepted = sampler.calls[1]
    assert state.state_id == accepted.state_id and state.route == "nuts"
    assert state.diagnostics_id == accepted.report_id
    assert not state.quarantined
    assert [r.report_id for r in reports] == [sampler.calls[0].report_id, accepted.report_id]
    assert [r.passed for r in reports] == [False, True]
    assert reports[-1].n_divergences == 0  # accepted at zero divergences
    assert _quarantined(sampler.calls[0].state_id)  # J8 (11): the failed try is still quarantined
    assert len(notices) == 1, "one notice for the retried step, none for a step entered"


def test_J8_a_divergences_max_is_never_loosened(monkeypatch: pytest.MonkeyPatch) -> None:
    """Three, then one, then zero divergences: the try with one isn't accepted."""
    script = {(FULL, 1): F.div(3), (FULL, 2): F.div(1)}
    sampler, state, reports, _, attempts = _chain(monkeypatch, script)
    s2, s3 = _seed(FULL, 2), _seed(FULL, 3)
    assert F.attempt_rows(attempts) == [
        (FULL, 1, SEED, 3, False),
        (FULL, 2, s2, 1, False),
        (FULL, 3, s3, 0, True),
    ]
    assert state.state_id == sampler.calls[2].state_id
    assert reports[-1].n_divergences == 0 and reports[-1].passed is True
    assert registries.resolve("diagnostics/thresholds/divergences_max@v1") == 0
    assert all(_quarantined(c.state_id) for c in sampler.calls[:2])


def test_J8_a_a_retry_is_not_accepted_under_a_loosened_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One divergence on every try of nuts_full; the next step passes. No try with a divergence
    is accepted."""
    script = {(FULL, k): F.div(1) for k in (1, 2, 3)}
    sampler, state, _, _, attempts = _chain(monkeypatch, script)
    assert [a["passed"] for a in attempts] == [False, False, False, True]
    assert attempts[-1]["step"] == STATIC and attempts[-1]["divergences"] == 0
    assert state.state_id == sampler.calls[-1].state_id


# ------------------------------------------------------------------ (b) three divergent tries


def test_J8_b_three_divergent_tries_move_to_the_next_step_with_all_three_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = {(FULL, k): F.div(k) for k in (1, 2, 3)}
    sampler, state, reports, notices, attempts = _chain(monkeypatch, script)
    s2, s3 = _seed(FULL, 2), _seed(FULL, 3)

    assert [(c.step, c.k, c.seed) for c in sampler.calls] == [
        (FULL, 1, SEED),
        (FULL, 2, s2),
        (FULL, 3, s3),
        (STATIC, 1, SEED),
    ]
    assert F.attempt_rows(attempts) == [
        (FULL, 1, SEED, 1, False),
        (FULL, 2, s2, 2, False),
        (FULL, 3, s3, 3, False),
        (STATIC, 1, SEED, 0, True),
    ]
    assert state.state_id == sampler.calls[3].state_id
    assert [r.passed for r in reports] == [False, False, False, True]
    assert all(_quarantined(c.state_id) for c in sampler.calls[:3])
    assert len(notices) == 2, "the step entered (nuts_static) and the retried step (nuts_full)"
    assert any(n.step == STATIC for n in notices)


# ------------------------------------------------------------------ S40 (6): every try diverges


def test_J8_S40_6_divergences_on_every_try_reach_the_conjugate_fallback_with_nine_tries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    joint_failed = registries.resolve("phrasing/notices/joint_failed@v1")
    sampler, state, reports, notices, attempts = _chain(monkeypatch, F.always(F.div(2)))

    want = [(step, k) for step in F.NUTS_STEPS for k in (1, 2, 3)]
    assert [(c.step, c.k) for c in sampler.calls] == want
    assert [(a["step"], a["try"]) for a in attempts] == want
    assert all(a["passed"] is False and a["divergences"] == 2 for a in attempts)
    for step in F.NUTS_STEPS:
        seeds = [a["seed"] for a in attempts if a["step"] == step]
        assert seeds == [SEED, _seed(step, 2), _seed(step, 3)], step
    assert [a["seed"] for a in attempts] == [c.seed for c in sampler.calls]
    retry_seeds = [a["seed"] for a in attempts if a["try"] > 1]
    assert len(set(retry_seeds)) == 6 and SEED not in retry_seeds

    assert all(_quarantined(c.state_id) for c in sampler.calls), "all nine tries quarantined"
    assert len({c.state_id for c in sampler.calls}) == 9
    assert state.route == "conjugate"
    assert (state.posterior.params or {}).get(fallback.FALLBACK_FLAG) == 1.0
    assert [r.passed for r in reports[:9]] == [False] * 9 and len(reports) == 10
    # entered: nuts_static, nuts_unpooled, conjugate; retried: all three NUTS steps
    assert len(notices) == 6
    assert any(joint_failed in n.reason for n in notices)


# ------------------------------------------------------------------ (c), S40 (6): no retry


@pytest.mark.parametrize(
    "bad",
    [
        {"rhat": 1.05},
        {"ess_bulk": 399.0},
        {"ess_tail": 120.0},
        {"rhat": 1.05, "divergences": 2},
        {"ess_bulk": 399.0, "divergences": 2},
        {"ess_tail": 120.0, "divergences": 2},
        {"ppc": {"delivery": 0.5, "ctr": 0.5, "cvr": 0.01, "value": 0.5}, "divergences": 2},
        {"divergences": None},
    ],
    ids=[
        "rhat",
        "ess_bulk",
        "ess_tail",
        "divergence_with_rhat",
        "divergence_with_ess_bulk",
        "divergence_with_ess_tail",
        "divergence_with_ppc",
        "null_divergences",
    ],
)
def test_J8_c_a_G3_failure_not_on_divergences_alone_is_not_retried(
    monkeypatch: pytest.MonkeyPatch, bad: dict[str, Any]
) -> None:
    sampler, state, reports, notices, attempts = _chain(monkeypatch, {(FULL, 1): bad})
    div = bad.get("divergences", 0)
    assert [(c.step, c.k, c.seed) for c in sampler.calls] == [(FULL, 1, SEED), (STATIC, 1, SEED)]
    assert F.attempt_rows(attempts) == [(FULL, 1, SEED, div, False), (STATIC, 1, SEED, 0, True)]
    assert state.state_id == sampler.calls[1].state_id
    assert _quarantined(sampler.calls[0].state_id)
    assert len(notices) == 1, "only the step entered; nothing was retried"
    assert [r.passed for r in reports] == [False, True]


# ------------------------------------------------------------------ S40 (2), (3): a first-try pass


def test_J8_S40_3_a_first_try_pass_records_one_attempt_and_changes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sampler, state, reports, notices, attempts = _chain(monkeypatch, None)
    [call] = sampler.calls
    assert call.seed == SEED
    assert F.attempt_rows(attempts) == [(FULL, 1, SEED, 0, True)]
    assert state.state_id == call.state_id and state.diagnostics_id == call.report_id
    assert [r.report_id for r in reports] == [call.report_id]
    assert notices == []


def test_J8_e_the_retry_seeds_are_the_same_on_every_run_of_the_same_inputs(
    iso, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _chain(monkeypatch, F.always(F.div(1)))
    F.fresh_store(monkeypatch, iso.root, "again")
    again = _chain(monkeypatch, F.always(F.div(1)))
    assert F.attempt_rows(first[4]) == F.attempt_rows(again[4])
    assert [c.seed for c in first[0].calls] == [c.seed for c in again[0].calls]
    F.fresh_store(monkeypatch, iso.root, "other")
    other = _chain(monkeypatch, F.always(F.div(1)), seed=SEED + 1)
    assert [a["seed"] for a in other[4]] != [a["seed"] for a in first[4]]


# ------------------------------------------------------------------ S40 (3): pipeline.fit


def test_J8_S40_3_fit_takes_the_step_and_attempts_from_the_accepted_try(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = F.eight_ads()
    steps = [n for n, _ in F.chain_steps(pipeline.funnel_spec(data))]
    assert steps[:2] == [FULL, UNPOOLED]
    script = {
        (FULL, 1): F.div(1),
        (FULL, 2): F.div(1),
        (FULL, 3): F.div(1),
        (UNPOOLED, 1): F.div(1),
    }
    sampler = F.patch_chain(monkeypatch, script, derivable=True)
    fitted = pipeline.fit(data, B.default_prior_set(), SEED)
    assert fitted.step == UNPOOLED
    assert F.attempt_rows(fitted.attempts) == [
        (FULL, 1, SEED, 1, False),
        (FULL, 2, _seed(FULL, 2), 1, False),
        (FULL, 3, _seed(FULL, 3), 1, False),
        (UNPOOLED, 1, SEED, 1, False),
        (UNPOOLED, 2, _seed(UNPOOLED, 2), 0, True),
    ]
    assert fitted.state.state_id == sampler.calls[-1].state_id


def test_J8_S40_3_fit_on_a_retry_of_the_first_step_keeps_that_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    F.patch_chain(monkeypatch, {(FULL, 1): F.div(2)}, derivable=True)
    fitted = pipeline.fit(F.eight_ads(), B.default_prior_set(), SEED)
    assert fitted.step == FULL
    assert [(a["step"], a["try"], a["passed"]) for a in fitted.attempts] == [
        (FULL, 1, False),
        (FULL, 2, True),
    ]


def test_J8_S40_3_fit_on_the_conjugate_fallback_records_every_try(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = F.eight_ads()
    n_steps = len(F.chain_steps(pipeline.funnel_spec(data)))
    F.patch_chain(monkeypatch, F.always(F.div(1)), derivable=True)
    fitted = pipeline.fit(data, B.default_prior_set(), SEED)
    assert fitted.step == "fallback_conjugate"
    assert len(fitted.attempts) == F.TRIES * n_steps
    assert not any(a["passed"] for a in fitted.attempts)


def test_J8_S40_3_fit_on_the_conjugate_route_records_no_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sampler = F.patch_chain(monkeypatch, None, derivable=True)
    fitted = pipeline.fit(F.eight_ads(n_ads=3), B.default_prior_set(), SEED)
    assert fitted.step == "conjugate" and fitted.attempts == []
    assert sampler.calls == []


# ------------------------------------------------------------------ (d), S40 (2), (5): pinned


def test_J8_d_a_first_try_pass_is_unchanged_from_before_J8(iso, monkeypatch) -> None:
    env = F.pipeline_env(iso, monkeypatch)
    sampler = F.patch_chain(monkeypatch, None, derivable=True)
    ctx = env.execute()
    snap, record = ctx.snapshot, ctx.result.run
    [call] = sampler.calls
    assert call.seed == SEED_BEFORE_J8 == env.seed()
    assert snap.run_id == record.run_id == RUN_ID_BEFORE_J8
    assert record.seeds == {"fit": SEED_BEFORE_J8}  # S40 (4): no fit_accepted on a first try
    assert snap.configuration["seed"] == SEED_BEFORE_J8
    assert snap.config_hash == record.config_hash == CONFIG_HASH_BEFORE_J8
    assert record.route_log[-1] == f"state {STATE_ID_BEFORE_J8}"
    assert [r.report_id for r in snap.diagnostics] == REPORT_IDS_BEFORE_J8
    assert sorted(q.quantity_id for q in snap.quantities) == QUANTITY_IDS_BEFORE_J8
    assert F.quantities_digest(snap.quantities) == QUANTITIES_DIGEST_BEFORE_J8
    assert snap.configuration["fit_step"] == FULL


def test_J8_d_a_first_try_pass_records_one_attempt_on_the_snapshot(iso, monkeypatch) -> None:
    env = F.pipeline_env(iso, monkeypatch)
    F.patch_chain(monkeypatch, None, derivable=True)
    snap = env.execute().snapshot
    assert F.attempt_rows(snap.fit_attempts) == [(FULL, 1, env.seed(), 0, True)]
    saved = pipeline.load_snapshot(snap.run_id)
    assert saved.fit_attempts == snap.fit_attempts


# ------------------------------------------------------------------ the run: snapshot and record


def _retry_run(iso, monkeypatch, script=None):
    env = F.pipeline_env(iso, monkeypatch)
    sampler = F.patch_chain(monkeypatch, script or {(FULL, 1): F.div(1)}, derivable=True)
    return env, sampler, env.execute()


def test_J8_S40_3_a_retried_run_records_both_tries_on_the_snapshot(iso, monkeypatch) -> None:
    env, sampler, ctx = _retry_run(iso, monkeypatch)
    snap = ctx.snapshot
    seed = env.seed()
    s2 = F.retry_seed_formula(seed, FULL, 2)
    want = [(FULL, 1, seed, 1, False), (FULL, 2, s2, 0, True)]
    assert F.attempt_rows(snap.fit_attempts) == want
    saved = json.loads((iso.store / "runs" / f"{snap.run_id}.json").read_text())
    assert F.attempt_rows(saved["fit_attempts"]) == want
    assert snap.configuration["fit_step"] == FULL
    accepted = sampler.calls[1]
    assert ctx.result.run.route_log[-1] == f"state {accepted.state_id}"
    assert {q.provenance.funnel_state_id for q in snap.quantities} == {accepted.state_id}
    assert F.quantities_digest(snap.quantities) != QUANTITIES_DIGEST_BEFORE_J8  # try 2's draws


def test_J8_S40_4_seeds_gain_fit_accepted_only_when_a_retry_is_accepted(iso, monkeypatch) -> None:
    env, _, ctx = _retry_run(iso, monkeypatch)
    seed = env.seed()
    s2 = F.retry_seed_formula(seed, FULL, 2)
    assert ctx.result.run.seeds == {"fit": seed, "fit_accepted": s2}
    [stored] = [r for r in run_record.read("RunRecord") if r.run_id == ctx.result.run.run_id]
    assert stored.seeds == {"fit": seed, "fit_accepted": s2}
    assert ctx.snapshot.configuration["seed"] == seed


def test_J8_S40_4_a_fallback_run_has_no_fit_accepted(iso, monkeypatch) -> None:
    env, _, ctx = _retry_run(iso, monkeypatch, F.always(F.div(1)))
    snap = ctx.snapshot
    assert ctx.result.run.seeds == {"fit": env.seed()}
    assert snap.configuration["fit_step"] == "fallback_conjugate"
    n_steps = len({a["step"] for a in snap.fit_attempts})
    assert n_steps >= 1 and len(snap.fit_attempts) == F.TRIES * n_steps
    assert not any(a["passed"] for a in snap.fit_attempts)


def test_J8_S40_3_the_conjugate_route_records_an_empty_list(iso, monkeypatch) -> None:
    env = F.pipeline_env(iso, monkeypatch, nuts=False)
    sampler = F.patch_chain(monkeypatch, None, derivable=True)
    ctx = env.execute()
    assert ctx.snapshot.route.kind == "conjugate"
    assert ctx.snapshot.configuration["fit_step"] == "conjugate"
    assert ctx.snapshot.fit_attempts == [] and sampler.calls == []
    assert ctx.result.run.seeds == {"fit": env.seed()}


def test_J8_S40_3_an_old_snapshot_loads_with_no_attempts(iso, monkeypatch) -> None:
    env = F.pipeline_env(iso, monkeypatch, nuts=False)
    d = env.execute().snapshot.model_dump(mode="json")
    d.pop("fit_attempts", None)
    assert pipeline.RunSnapshot.model_validate(d).fit_attempts == []


def test_J8_11_one_notice_per_retried_step_on_the_run(iso, monkeypatch) -> None:
    env = F.pipeline_env(iso, monkeypatch)
    F.patch_chain(monkeypatch, None, derivable=True)
    plain = env.execute().snapshot.notices
    F.fresh_store(monkeypatch, iso.root, "retried")
    F.patch_chain(monkeypatch, {(FULL, 1): F.div(1)}, derivable=True)
    snap = env.execute(F.T_RUN.replace(hour=16)).snapshot
    assert snap.configuration["fit_step"] == FULL, "the retry is accepted: no step was entered"
    retried = snap.notices
    assert len(retried) == len(plain) + 1
    assert set(plain) <= set(retried)


def test_J8_e_the_run_s_retry_seeds_are_the_same_on_every_run(iso, monkeypatch) -> None:
    env = F.pipeline_env(iso, monkeypatch)
    F.patch_chain(monkeypatch, F.always(F.div(1)), derivable=True)
    a = env.execute().snapshot
    F.fresh_store(monkeypatch, iso.root, "again")
    F.patch_chain(monkeypatch, F.always(F.div(1)), derivable=True)
    b = env.execute(F.T_RUN.replace(hour=18)).snapshot
    assert a.run_id != b.run_id  # another clock, another run
    assert [x["seed"] for x in a.fit_attempts] == [x["seed"] for x in b.fit_attempts]
    assert len(a.fit_attempts) >= F.TRIES


# ------------------------------------------------------------------ S39 (9), S40 (7): fit_route


def _routes(snap: pipeline.RunSnapshot) -> list[dict[str, Any]]:
    entries = sock.result_of(snap)["posterior"].values()
    out = [e["fit_route"] for e in entries]
    out.append(markers.fit_route(json.loads(snap.model_dump_json())))
    assert out
    return out


def test_J8_S40_7_fit_route_try_is_the_accepted_try(iso, monkeypatch) -> None:
    _, _, ctx = _retry_run(iso, monkeypatch)
    for route in _routes(ctx.snapshot):
        assert route == {"kind": "nuts", "step": FULL, "try": 2}


def test_J8_S40_7_fit_route_after_a_step_moved_on(iso, monkeypatch) -> None:
    env = F.pipeline_env(iso, monkeypatch)
    sampler = F.patch_chain(monkeypatch, {(FULL, k): F.div(1) for k in (1, 2, 3)}, derivable=True)
    ctx = env.execute()
    second = ctx.snapshot.configuration["fit_step"]
    assert second == sampler.calls[-1].step == UNPOOLED
    for route in _routes(ctx.snapshot):
        assert route == {"kind": "nuts", "step": second, "try": 1}


def test_J8_S39_9_fit_route_try_on_a_first_try_pass(iso, monkeypatch) -> None:
    env = F.pipeline_env(iso, monkeypatch)
    F.patch_chain(monkeypatch, None, derivable=True)
    for route in _routes(env.execute().snapshot):
        assert route == {"kind": "nuts", "step": FULL, "try": 1}


def test_J8_S39_9_fit_route_try_is_null_with_no_accepted_try(iso, monkeypatch) -> None:
    _, _, ctx = _retry_run(iso, monkeypatch, F.always(F.div(1)))
    for route in _routes(ctx.snapshot):
        assert route == {"kind": "conjugate", "step": "fallback_conjugate", "try": None}


def test_J8_S39_9_fit_route_try_is_null_on_the_conjugate_route(iso, monkeypatch) -> None:
    env = F.pipeline_env(iso, monkeypatch, nuts=False)
    F.patch_chain(monkeypatch, None, derivable=True)
    for route in _routes(env.execute().snapshot):
        assert route == {"kind": "conjugate", "step": "conjugate", "try": None}
