"""P6 diagnostics and fallback (spec v0.3 §5.4, §7.4, §7.5, G3).

# CONTRACT ASSUMPTION: g3(report) returns (report with passed set, GateResult) and does not raise;
#   GateResult.gate == "G3", blocking True, and a failing result lists one reason per breached
#   threshold naming the metric ("rhat", "ess_bulk", "ess_tail", "divergences") or, for PPC, the
#   stage name.
# CONTRACT ASSUMPTION: fit_with_fallback looks up compile_model and NumpyroSampler through their
#   modules at call time (bayesian_marketing.model_spec.compile.compile_model and
#   bayesian_marketing.inference.sampler_numpyro.NumpyroSampler), so the tests can substitute the
#   fakes in tests/fakes/neighbours.py; step 4 uses the real conjugate route (P3).
# CONTRACT ASSUMPTION: derive refuses a quarantined state by raising (any exception other than
#   NotImplementedError); funnel_state.load still returns it.
"""

from __future__ import annotations

import datetime as dt

import pytest

from bayesian_marketing import core as C
from bayesian_marketing.core import registries
from bayesian_marketing.derived_metrics.derive import derive
from bayesian_marketing.diagnostics.run import g3, run_diagnostics
from bayesian_marketing.funnel_state import store
from bayesian_marketing.inference import fallback, sampler_numpyro
from bayesian_marketing.inference.conjugate import fit_conjugate
from bayesian_marketing.model_spec import compile as compile_mod
from tests.fakes import builders as B
from tests.fakes.neighbours import FakeCompiler, FakeSampler, failing_report, passing_report

pytestmark = pytest.mark.piece("P6")


@pytest.mark.parametrize(
    "kw,needle",
    [
        ({"rhat": 1.05}, "rhat"),
        ({"ess_bulk": 399.0}, "ess_bulk"),
        ({"ess_tail": 120.0}, "ess_tail"),
        ({"divergences": 1}, "divergences"),
        ({"ppc": {"delivery": 0.5, "ctr": 0.5, "cvr": 0.01, "value": 0.5}}, "cvr"),
        ({"ppc": {"delivery": 0.5, "ctr": 0.99, "cvr": 0.5, "value": 0.5}}, "ctr"),
    ],
)
def test_P6_rhat_fixture_fails_G3(kw: dict, needle: str) -> None:
    report = B.diagnostics_report(**kw)
    out, res = g3(report)
    assert res.gate == "G3"
    assert res.passed is False and out.passed is False
    assert res.blocking is True
    assert any(needle in r.lower() for r in res.reasons), res.reasons

    clean, ok = g3(B.diagnostics_report())
    assert ok.passed is True and clean.passed is True
    assert ok.reasons == [] or all(isinstance(r, str) for r in ok.reasons)


def test_P6_extra_G3_thresholds_from_registry(iso) -> None:
    iso.edit_yaml("diagnostics", lambda d: d["thresholds"].update(rhat_max=1.1))
    out, res = g3(B.diagnostics_report(rhat=1.05))
    assert res.passed is True and out.passed is True
    assert registries.resolve("diagnostics/thresholds/rhat_max@v1") == 1.1


def _data(n_ads: int = 8, n_days: int = 21) -> C.FunnelData:
    dates = [B.D_END - dt.timedelta(days=n_days - 1 - i) for i in range(n_days)]
    return B.funnel_data(
        {
            f"ad_{i}": {
                "impressions": [800] * n_days,
                "clicks": [16 + i] * n_days,
                "spend": [20.0] * n_days,
                "conv_obs": [1] * n_days,
                "conv_rep": [1.0] * n_days,
                "mature": [1.0] * n_days,
            }
            for i in range(n_ads)
        },
        dates=dates,
    )


def _patch(monkeypatch: pytest.MonkeyPatch, sampler: FakeSampler) -> FakeCompiler:
    compiler = FakeCompiler()
    monkeypatch.setattr(compile_mod, "compile_model", compiler)
    monkeypatch.setattr(fallback, "compile_model", compiler, raising=False)
    monkeypatch.setattr(
        sampler_numpyro.NumpyroSampler, "fit", lambda self, m, d, c: sampler.fit(m, d, c)
    )
    return compiler


def test_P6_each_fallback_step_emits_notice(monkeypatch: pytest.MonkeyPatch) -> None:
    joint_failed = registries.resolve("phrasing/notices/joint_failed@v1")
    sampler = FakeSampler([failing_report()])
    compiler = _patch(monkeypatch, sampler)
    spec = B.funnel_spec(dynamics="random_walk")
    state, reports, notices = fallback.fit_with_fallback(spec, B.default_prior_set(), _data(), 7)

    assert len(sampler.calls) == 3, "three NUTS attempts before the conjugate step"
    assert len(compiler.specs) == 3
    assert compiler.specs[0].dynamics == "random_walk"
    assert compiler.specs[1].dynamics == "static"
    assert compiler.specs[2].dynamics == "static"
    assert compiler.specs[2] != compiler.specs[1], "step 3 drops pooling above the ad level"
    assert state.route == "conjugate"
    assert len(reports) >= 3 and all(r.passed is False for r in reports[:3])
    assert len(notices) >= 3
    assert len({n.step for n in notices}) == len(notices), "one notice per step"
    assert all(isinstance(n, C.DegradationNotice) and n.reason for n in notices)
    assert any(joint_failed in n.reason for n in notices)


def test_P6_extra_fallback_stops_at_first_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    sampler = FakeSampler([failing_report(), passing_report()])
    _patch(monkeypatch, sampler)
    spec = B.funnel_spec(dynamics="random_walk")
    state, reports, notices = fallback.fit_with_fallback(spec, B.default_prior_set(), _data(), 7)
    assert len(sampler.calls) == 2
    assert state.route == "nuts"
    assert [r.passed for r in reports] == [False, True]
    assert len(notices) == 1


def test_P6_quarantined_state_refused_by_derive() -> None:
    st = fit_conjugate(B.north_pier_day14(), B.default_prior_set(), seed=1)
    assert derive("cvr", st, B.scope("ad_a"), None).name == "cvr"
    bad = st.model_copy(update={"quarantined": True, "state_id": "fs_quarant1"})
    store.save(bad)
    with pytest.raises(Exception) as ei:
        derive("cvr", bad, B.scope("ad_a"), None)
    assert not isinstance(ei.value, NotImplementedError)
    loaded = store.load("fs_quarant1")
    assert loaded.quarantined is True


def test_P6_extra_run_diagnostics_leaves_passed_unset() -> None:
    data = B.north_pier_day14()
    st = fit_conjugate(data, B.default_prior_set(), seed=1)
    rep = run_diagnostics(st, data)
    assert isinstance(rep, C.DiagnosticsReport)
    assert rep.passed is None
    assert rep.ppc, "PPC p-values per stage"
