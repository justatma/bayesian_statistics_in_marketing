"""P6 unit tests: chain diagnostics, PPC misfit, value stage, fallback edges."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from tests.fakes import builders as B
from tests.fakes.neighbours import FakeCompiler, FakeSampler, failing_report

from bayesian_marketing.core import registries
from bayesian_marketing.diagnostics.run import g3, run_diagnostics
from bayesian_marketing.funnel_state import store
from bayesian_marketing.inference import fallback, sampler_numpyro
from bayesian_marketing.inference.conjugate import fit_conjugate
from bayesian_marketing.model_spec import compile as compile_mod


@pytest.fixture(autouse=True)
def _store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BAYES_DATA_DIR", str(tmp_path / "store"))


def test_chain_column_gives_rhat_and_ess(tmp_path: Path) -> None:
    rng = np.random.default_rng(3)
    n = 500
    good = rng.normal(0.02, 0.001, 4 * n)
    shifted = np.concatenate([rng.normal(0.02 + 0.01 * c, 0.001, n) for c in range(4)])
    chain = np.repeat(np.arange(4), n)
    data = B.north_pier_day14()
    ok = B.samples_state(tmp_path / "ok.parquet", {"chain": chain, "ad_a.ctr": good})
    rep = run_diagnostics(ok, data)
    assert rep.rhat_max is not None and rep.rhat_max < 1.01
    assert rep.ess_bulk_min is not None and rep.ess_bulk_min > 400
    bad = B.samples_state(
        tmp_path / "bad.parquet", {"chain": chain, "ad_a.ctr": shifted}, state_id="fs_00000002"
    )
    rep_bad = run_diagnostics(bad, data)
    _, res = g3(rep_bad)
    assert res.passed is False
    assert any(r.startswith("rhat") for r in res.reasons)


def test_ppc_misfit_names_stage() -> None:
    data = B.north_pier_day14()
    st = fit_conjugate(data, B.default_prior_set(), seed=2)
    other = B.funnel_data(
        {
            "ad_a": {"impressions": 20000, "clicks": 1200, "spend": 500.0, "conv_obs": 8},
            "ad_b": {"impressions": 17000, "clicks": 1020, "spend": 500.0, "conv_obs": 18},
        }
    )
    rep = run_diagnostics(st, other)
    assert rep.ppc["ctr"] < 0.05
    _, res = g3(rep)
    assert res.passed is False
    assert any("ctr" in r for r in res.reasons)


@pytest.mark.parametrize("orders", [False, True])
def test_value_stage_present(orders: bool) -> None:
    ad: dict = {
        "impressions": 20000,
        "clicks": 400,
        "spend": 500.0,
        "conv_obs": 10,
        "revenue": 600.0,
    }
    data = B.funnel_data({"ad_a": ad})
    if orders:
        vals = [40.0, 55.0, 70.0, 62.0, 48.0, 90.0, 51.0, 66.0, 58.0, 60.0]
        data = data.model_copy(update={"order_values": {"ad_a": vals}})
    st = fit_conjugate(data, B.default_prior_set(), seed=4)
    rep = run_diagnostics(st, data)
    assert 0.05 < rep.ppc["value"] < 0.95
    assert rep.passed is None


def test_identical_spec_step_skipped_and_failed_states_quarantined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sampler = FakeSampler([failing_report()])
    compiler = FakeCompiler()
    monkeypatch.setattr(compile_mod, "compile_model", compiler)
    monkeypatch.setattr(
        sampler_numpyro.NumpyroSampler, "fit", lambda self, m, d, c: sampler.fit(m, d, c)
    )
    spec = B.funnel_spec(dynamics="static", hierarchy=["ad"])
    data = B.funnel_data({f"ad_{i}": {"impressions": 800, "clicks": 16, "spend": 20.0,
                                      "conv_obs": 1} for i in range(8)})  # fmt: skip
    state, reports, notices = fallback.fit_with_fallback(spec, B.default_prior_set(), data, 5)
    assert len(sampler.calls) == 1
    assert [n.step for n in notices] == ["conjugate"]
    joint_failed = registries.resolve("phrasing/notices/joint_failed@v1")
    assert joint_failed in notices[0].reason and "rhat" in notices[0].reason
    assert state.route == "conjugate"
    assert state.posterior.params[fallback.FALLBACK_FLAG] == 1.0
    assert state.diagnostics_id == reports[-1].report_id
    assert store.load("fs_00000001").quarantined is True
    assert sampler.calls[0][2].chains == registries.resolve("diagnostics/sampler/chains@v1")
