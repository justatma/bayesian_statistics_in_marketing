"""P6 blind review fixes: items 1, 2, 4, 5, 7."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from tests.fakes import builders as B

from bayesian_marketing.diagnostics.run import g3, run_diagnostics
from bayesian_marketing.inference import fallback
from bayesian_marketing.model_spec import compile as compile_mod


@pytest.fixture(autouse=True)
def _store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BAYES_DATA_DIR", str(tmp_path / "store"))


DIV = "diagnostics.n_divergences"


def _nuts_state(tmp_path: Path, name: str, cols: dict, params: dict | None = None):
    st = B.samples_state(tmp_path / f"{name}.parquet", cols, state_id=name)
    if params:
        merged = {**(st.posterior.params or {}), **params}
        st = st.model_copy(update={"posterior": st.posterior.model_copy(update={"params": merged})})
    return st


def _iid(n: int, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).normal(0.02, 0.001, n)


def test_nuts_single_chain_gets_ess_but_fails_rhat(tmp_path: Path) -> None:
    cols = {"chain": np.zeros(2000, int), "ad_a.ctr": _iid(2000)}
    st = _nuts_state(tmp_path, "fs_r0000001", cols, {DIV: 0.0})
    rep = run_diagnostics(st, B.north_pier_day14())
    assert rep.rhat_max is None
    assert rep.ess_bulk_min is not None and rep.ess_bulk_min > 400
    _, res = g3(rep)
    assert res.passed is False
    assert len(res.reasons) == 1 and res.reasons[0].startswith("rhat not computed")


def test_nuts_no_chain_column_and_no_divergences_fail(tmp_path: Path) -> None:
    st = _nuts_state(tmp_path, "fs_r0000002", {"ad_a.ctr": _iid(2000)})
    _, res = g3(run_diagnostics(st, B.north_pier_day14()))
    assert res.passed is False
    for metric in ("rhat", "ess_bulk", "ess_tail", "divergences"):
        assert any(r.startswith(f"{metric} not computed") for r in res.reasons), res.reasons


def test_conjugate_none_metrics_still_skipped() -> None:
    rep = B.diagnostics_report(
        rhat=None, ess_bulk=None, ess_tail=None, divergences=None, sampler="conjugate"
    )
    assert g3(rep)[1].passed is True


def test_unequal_chains_not_truncated(tmp_path: Path) -> None:
    chain = np.concatenate([np.zeros(600, int), np.ones(400, int)])
    cols = {"chain": chain, "ad_a.ctr": _iid(1000)}
    st = _nuts_state(tmp_path, "fs_r0000003", cols, {DIV: 0.0})
    rep = run_diagnostics(st, B.north_pier_day14())
    assert rep.rhat_max is None and rep.ess_bulk_min is None
    _, res = g3(rep)
    assert any(r.startswith("rhat not computed") for r in res.reasons)


def test_constant_and_non_parameter_columns_excluded(tmp_path: Path) -> None:
    cols = {
        "chain": np.repeat(np.arange(4), 500),
        "draw": np.tile(np.arange(500), 4),
        "ad_a.ctr": _iid(2000),
        "ad_b.ctr": np.full(2000, 0.02),
    }
    st = _nuts_state(tmp_path, "fs_r0000004", cols, {DIV: 0.0})
    rep = run_diagnostics(st, B.north_pier_day14())
    assert rep.rhat_max is not None and np.isfinite(rep.rhat_max) and rep.rhat_max < 1.01
    assert g3(rep)[1].passed is True


def test_nan_metric_is_not_finite_breach() -> None:
    _, res = g3(B.diagnostics_report(rhat=float("nan")))
    assert res.passed is False and res.reasons == ["rhat nan is not finite"]


def test_nan_divergences_fail_not_crash(tmp_path: Path) -> None:
    cols = {"chain": np.repeat(np.arange(4), 500), "ad_a.ctr": _iid(2000)}
    st = _nuts_state(tmp_path, "fs_r0000005", cols, {DIV: float("nan")})
    rep = run_diagnostics(st, B.north_pier_day14())
    assert rep.n_divergences is None
    _, res = g3(rep)
    assert any(r.startswith("divergences not computed") for r in res.reasons)


def test_raising_step_is_a_recorded_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def boom(spec, priors, data):
        calls.append(1)
        raise ValueError("model would not compile")

    monkeypatch.setattr(compile_mod, "compile_model", boom)
    spec = B.funnel_spec(dynamics="random_walk")
    ad = {"impressions": 800, "clicks": 16, "spend": 20.0, "conv_obs": 1}
    data = B.funnel_data({f"ad_{i}": dict(ad) for i in range(8)})
    state, reports, notices = fallback.fit_with_fallback(spec, B.default_prior_set(), data, 5)
    assert len(calls) == 3
    assert state.route == "conjugate"
    assert [n.step for n in notices] == ["nuts_static", "nuts_unpooled", "conjugate"]
    assert all("raised ValueError: model would not compile" in n.reason for n in notices)
    assert notices[0].reason.startswith("nuts_full raised")
    assert len(reports) == 1 and reports[0].sampler == "conjugate"
