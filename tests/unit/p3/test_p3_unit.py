"""P3 unit tests beyond the frozen acceptance set."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from tests.fakes import builders as B

from bayesian_marketing import core as C
from bayesian_marketing.core import registries
from bayesian_marketing.decision.compare import compare
from bayesian_marketing.derived_metrics.derive import QuarantinedStateError, derive
from bayesian_marketing.funnel_state import store
from bayesian_marketing.inference.conjugate import fit_conjugate
from bayesian_marketing.test_design import voi


@pytest.fixture(autouse=True)
def _iso(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BAYES_DATA_DIR", str(tmp_path / "store"))
    registries.clear_cache()


def _notice(key: str) -> str:
    return registries.resolve(f"phrasing/notices/{key}@v1")


def test_lag_adjusted_trials_and_notice() -> None:
    data = B.funnel_data(
        {"ad_a": {"impressions": [1000, 1000], "clicks": [100, 100], "spend": [50.0, 50.0],
                  "conv_obs": [4, 1], "mature": [1.0, 0.5]}},
        dates=[B.D_START, B.D_END],
    )  # fmt: skip
    st = fit_conjugate(data, B.default_prior_set(), seed=3)
    q = derive("cvr", st, B.scope("ad_a"), None)
    assert q.estimate.params == {"a": 1 + 5, "b": 49 + (100 + 50 - 5)}
    assert _notice("lag_approx") in q.notices
    assert _notice("too_few_ads") in q.notices
    assert _notice("lag_approx") not in derive("ctr", st, B.scope("ad_a"), None).notices


def test_platform_modeled_conversions() -> None:
    data = B.funnel_data(
        {"ad_a": {"impressions": 5000, "clicks": 100, "spend": 80.0, "conv_rep": 2.5,
                  "revenue": 200.0}}
    )  # fmt: skip
    st = fit_conjugate(data, B.default_prior_set(), seed=3)
    q = derive("cvr", st, B.scope("ad_a"), None)
    assert q.estimate.params["a"] == pytest.approx(3.5)
    assert _notice("platform_modeled") in q.notices
    assert q.evidence_class == "platform_attributed"
    aov = derive("aov", st, B.scope("ad_a"), None)
    k = registries.resolve("bounds/value/compound_gamma_k@v1")
    assert aov.estimate.family == "invgamma"
    assert aov.estimate.params == {"a": k * 2.5, "scale": k * 200.0}


def test_zero_spend_days_carry_no_likelihood() -> None:
    data = B.funnel_data(
        {"ad_a": {"impressions": [1000, 500], "clicks": [20, 10], "spend": [10.0, 0.0],
                  "conv_obs": [1, 1]}},
        dates=[B.D_START, B.D_END],
    )  # fmt: skip
    st = fit_conjugate(data, B.default_prior_set(), seed=3)
    assert derive("ctr", st, B.scope("ad_a"), None).estimate.params == {"a": 22, "b": 98 + 980}


def test_orders_file_gives_lognormal_aov_and_roas() -> None:
    rng = np.random.default_rng(0)
    values = list(rng.lognormal(np.log(80), 0.3, 40))
    data = B.funnel_data(
        {"ad_a": {"impressions": 20000, "clicks": 400, "spend": 500.0, "conv_obs": 40,
                  "order_values": values}}
    )  # fmt: skip
    st = fit_conjugate(data, B.default_prior_set(), seed=3)
    aov = derive("aov", st, B.scope("ad_a"), None)
    assert aov.estimate.kind == "samples"
    assert aov.evidence_class == "commercially_realized"
    assert 70 < aov.estimate.summary["mean"] < 95
    roas = derive("roas", st, B.scope("ad_a"), None)
    assert roas.estimate.kind == "samples"
    assert pd.read_parquet(roas.estimate.samples_path).shape[1] == 1
    # observed ROAS: 40 orders x ~$83 / $500 ~ 6.6
    assert 4 < roas.estimate.summary["q50"] < 10


def test_seeded_draws_reproduce() -> None:
    a = fit_conjugate(B.north_pier_day14(), B.default_prior_set(), seed=7)
    b = fit_conjugate(B.north_pier_day14(), B.default_prior_set(), seed=7)
    da = pd.read_parquet(a.posterior.samples_path)
    db = pd.read_parquet(b.posterior.samples_path)
    pd.testing.assert_frame_equal(da, db)
    assert a.data_pull_ids == B.north_pier_day14().pull_ids


def test_unapproved_prior_blocks_with_g8() -> None:
    ps = B.default_prior_set()
    recs = dict(ps.records)
    recs["cvr"] = B.prior_record("cvr", approved=False)
    with pytest.raises(C.GateFailure) as ei:
        fit_conjugate(B.north_pier_day14(), C.PriorSet(records=recs), seed=1)
    assert ei.value.result.gate == "G8"


def test_quarantined_refused_but_loadable() -> None:
    st = fit_conjugate(B.north_pier_day14(), B.default_prior_set(), seed=1)
    bad = st.model_copy(update={"quarantined": True})
    store.save(bad)
    with pytest.raises(QuarantinedStateError):
        derive("cvr", bad, B.scope("ad_a"), None)
    assert store.load(bad.state_id).quarantined


def test_save_same_state_twice_is_noop() -> None:
    st = fit_conjugate(B.north_pier_day2(), B.default_prior_set(), seed=1)
    store.save(st)
    store.save(st)
    assert store.load(st.state_id) == st


def test_modeled_aov_contribution_uses_joint_draws() -> None:
    data = B.funnel_data(
        {
            "ad_a": {"impressions": 20000, "clicks": 400, "spend": 500.0, "conv_obs": 8,
                     "revenue": 640.0},
            "ad_b": {"impressions": 17000, "clicks": 340, "spend": 500.0, "conv_obs": 18,
                     "revenue": 1440.0},
        }
    )  # fmt: skip
    st = fit_conjugate(data, B.default_prior_set(), seed=1)
    econ = B.economics(fixed_price=None)
    qs = [derive("contribution_per_click", st, B.scope(a), econ) for a in ("ad_a", "ad_b")]
    assert all(q.estimate.kind == "samples" for q in qs)
    c = compare(qs, B.objective("contribution", "clicks", 1000), econ)
    assert c.method == "joint_draws"
    assert c.mc_standard_error is not None
    assert 0.7 < c.p_best["ad_b"] < 0.962  # wider than at a fixed $80 price
    assert set(c.p_exceeds_break_even) == {"ad_a", "ad_b"}
    assert c.value_q05 is not None
    assert float(c.value_q05["ad_a"].amount) < float(c.expected_value["ad_a"].amount)


def test_compare_refuses_mismatched_objective() -> None:
    opts = [B.quantity("cvr", "ad_a"), B.quantity("cvr", "ad_b", estimate=B.beta_spec(19, 371))]
    with pytest.raises(ValueError):
        compare(opts, B.objective("clicks", "impressions", 1000), B.economics())


def test_evpi_analytic_matches_draws(tmp_path: Path) -> None:
    from scipy import stats

    a, b = B.beta_spec(9, 441), B.beta_spec(19, 371)
    p = C.DecisionProblem(options=["a", "b"], payoffs={"a": a, "b": b}, objective=B.objective())
    exact = float(voi.evpi(p).amount)
    rng = np.random.default_rng(1)
    x = np.column_stack([stats.beta(9, 441).rvs(200_000, random_state=rng),
                         stats.beta(19, 371).rvs(200_000, random_state=rng)])  # fmt: skip
    mc = x.max(axis=1).mean() - x.mean(axis=0).max()
    assert exact == pytest.approx(mc, abs=2e-5)
    assert voi.evpi(p).currency == "XXX"


def test_assess_prices_test_from_cpc(tmp_path: Path) -> None:
    st = fit_conjugate(B.north_pier_day14(), B.default_prior_set(), seed=1)
    path = tmp_path / "payoffs.parquet"
    B.write_samples(path, {"ad_b": [2000.0] * 4 + [-1000.0] * 6, "ad_a": [0.0] * 10})
    spec = {
        k: C.DistributionSpec(kind="samples", samples_path=str(path), n_samples=10,
                              summary=B.summary_from_draws([0.0, 1.0]))
        for k in ("ad_b", "ad_a")
    }  # fmt: skip
    p = C.DecisionProblem(options=["ad_b", "ad_a"], payoffs=spec, objective=B.objective())
    d = C.TestDesign(arms=["ad_b"], allocation={"ad_b": 1.0}, volume=B.horizon("clicks", 100),
                     randomized=False, holdout=False, sensitivity=0.75,
                     false_positive_rate=0.25)  # fmt: skip
    res = voi.assess(p, d, B.economics(), st)
    assert res.design_label == "observational"
    assert float(res.evsi.amount) == pytest.approx(250.0)
    # 100 clicks at about $500/340 per click
    assert 120 < float(res.cost.mid.amount) < 175
    assert res.verdict == "buy"
    assert res.evsi.currency == "USD"
