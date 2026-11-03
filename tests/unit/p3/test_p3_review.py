"""P3 blind-review fixes, one block per finding."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from scipy import stats
from tests.fakes import builders as B

from bayesian_marketing import core as C
from bayesian_marketing.core import registries
from bayesian_marketing.decision import compare as compare_mod
from bayesian_marketing.decision.compare import LOSS_SE_PREFIX, compare
from bayesian_marketing.derived_metrics import derive as derive_mod
from bayesian_marketing.derived_metrics.derive import NotEstimable, derive
from bayesian_marketing.derived_metrics.dist import (
    QuadratureError,
    decode_currency,
    encode_currency,
    exact_max_moments,
)
from bayesian_marketing.funnel_state import store
from bayesian_marketing.inference.conjugate import fit_conjugate
from bayesian_marketing.test_design import voi

TOL = 1e-10


@pytest.fixture(autouse=True)
def _iso(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BAYES_DATA_DIR", str(tmp_path / "store"))
    registries.clear_cache()


def _q(a: float, b: float, ad: str) -> C.Quantity:
    return B.quantity("cvr", ad, estimate=B.beta_spec(a, b))


def _truth(d1, d2):  # brute-force trapezoid on a fine grid over both supports
    lo = min(d1.ppf(1e-14), d2.ppf(1e-14))
    hi = max(d1.isf(1e-14), d2.isf(1e-14))
    x = np.linspace(lo, hi, 2_000_001)
    p2 = np.trapezoid(d2.pdf(x) * d1.cdf(x), x)
    em = np.trapezoid(x * d1.pdf(x) * d2.cdf(x), x) + np.trapezoid(x * d2.pdf(x) * d1.cdf(x), x)
    return p2, em - d1.mean(), em - d2.mean()


# --- 1 quadrature at realistic and extreme counts --------------------------------------------
@pytest.mark.parametrize("n", [1e4, 1e6, 1e8, 1e10])
def test_quadrature_large_counts(n: float) -> None:
    d1, d2 = stats.beta(0.05 * n, 0.95 * n), stats.beta(0.0501 * n, 0.9499 * n)
    (p1, p2), (l1, l2) = exact_max_moments([d1, d2], TOL)
    assert abs(p1 + p2 - 1) <= TOL
    assert l1 >= 0 and l2 >= 0
    if n <= 1e8:  # beyond, the brute-force grid is coarser than the posterior
        t2, tl1, tl2 = _truth(d1, d2)
        assert p2 == pytest.approx(t2, abs=1e-7)
        assert l1 == pytest.approx(tl1, abs=1e-9)
        assert l2 == pytest.approx(tl2, abs=1e-9)
    else:
        sd = np.hypot(d1.std(), d2.std())
        assert p2 == pytest.approx(stats.norm.cdf((d2.mean() - d1.mean()) / sd), abs=1e-6)


def test_quadrature_reviewer_cases() -> None:
    c = compare(
        [_q(5e4, 9.5e5, "a"), _q(5.01e4, 9.499e5, "b")], B.objective("orders"), B.economics()
    )
    assert c.method == "exact_integration"
    assert c.p_best["a"] == pytest.approx(0.37286, abs=1e-5)
    assert c.p_best["b"] == pytest.approx(0.62714, abs=1e-5)
    assert all(float(v.amount) >= 0 for v in c.expected_loss.values())
    c = compare([_q(5e5, 9.5e6, "a"), _q(6e5, 9.4e6, "b")], B.objective("orders"), B.economics())
    assert abs(sum(c.p_best.values()) - 1) <= TOL
    assert float(c.expected_loss["a"].amount) == pytest.approx(1000 * 0.01, abs=1e-9)


def test_quadrature_ties_and_three_arms_match_monte_carlo() -> None:
    p, loss = exact_max_moments([stats.beta(10, 90)] * 3, TOL)
    assert p == pytest.approx([1 / 3] * 3, abs=TOL)
    assert loss[0] == loss[1] == loss[2] > 0
    ds = [stats.beta(10, 90), stats.beta(12, 88), stats.beta(8, 92)]
    p, loss = exact_max_moments(ds, TOL)
    x = np.column_stack([d.rvs(1_000_000, random_state=i) for i, d in enumerate(ds)])
    assert p == pytest.approx(np.bincount(x.argmax(1)) / len(x), abs=2e-3)
    assert loss == pytest.approx(list(x.max(1).mean() - x.mean(0)), abs=2e-4)


def test_quadrature_failure_falls_back_to_joint_draws(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a, **k):
        raise QuadratureError("forced")

    monkeypatch.setattr(compare_mod, "exact_max_moments", boom)
    c = compare([_q(9, 441, "a"), _q(19, 371, "b")], B.objective("orders"), B.economics())
    assert c.method == "joint_draws"
    assert c.mc_standard_error is not None
    assert c.p_best["b"] == pytest.approx(0.9907, abs=0.01)


def test_quadrature_refuses_infinite_mean() -> None:
    with pytest.raises(QuadratureError):
        exact_max_moments([stats.invgamma(0.5), stats.invgamma(3)], TOL)


def test_many_options_use_joint_draws() -> None:
    k = registries.resolve("bounds/coupling/min_ads_for_coupling@v1")
    qs = [_q(10 + i, 100 - i, f"x{i}") for i in range(k)]
    c = compare(qs, B.objective("orders"), B.economics())
    assert c.method == "joint_draws"
    assert sum(c.p_best.values()) == pytest.approx(1)


# --- 2 CPA lag disclosure ------------------------------------------------------------------------
def test_cpa_lag_notice_names_spend_exposure() -> None:
    data = B.funnel_data(
        {"a": {"impressions": [1000, 1000], "clicks": [50, 50], "spend": [100.0, 100.0],
               "conv_obs": [10, 4], "mature": [1.0, 0.5]}},
        dates=[B.D_START, B.D_END],
    )  # fmt: skip
    st = fit_conjugate(data, B.default_prior_set(), seed=1)
    q = derive("cpa", st, B.scope("a"), None)
    assert q.estimate.params == {"a": 15.0, "scale": 151.0}
    assert derive_mod.NOTICE_CPA_LAG_SPEND in q.notices
    assert derive_mod.NOTICE_CPA_LAG_SPEND not in derive("cvr", st, B.scope("a"), None).notices


# --- 3 currency ------------------------------------------------------------------------------
def test_currency_codec_round_trips() -> None:
    for code in ("USD", "EUR", "AAA", "ZZZ", "XXX"):
        assert decode_currency(encode_currency(code)) == code


def test_currency_mismatch_refused(tmp_path: Path) -> None:
    data = B.north_pier_day14().model_copy(update={"currency": "EUR"})
    st = fit_conjugate(data, B.default_prior_set(), seed=1)
    with pytest.raises(C.GateFailure) as ei:
        derive("contribution_per_click", st, B.scope("ad_a"), B.economics(currency="USD"))
    assert ei.value.result.gate == "G9"
    assert "currency" in ei.value.result.reasons[0]
    q = derive("contribution_per_click", st, B.scope("ad_a"), B.economics(currency="EUR"))
    assert q.name == "contribution_per_click"
    p = C.DecisionProblem(
        options=["ad_a"], payoffs={"ad_a": B.beta_spec(2, 3)}, objective=B.objective()
    )
    d = C.TestDesign(arms=["ad_a"], allocation={"ad_a": 1.0}, volume=B.horizon(),
                     randomized=False, holdout=False, sensitivity=0.7,
                     false_positive_rate=0.2)  # fmt: skip
    with pytest.raises(C.GateFailure):
        voi.assess(p, d, B.economics(currency="USD"), st)


# --- 4 impossible data -----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("ad", "match"),
    [
        ({"impressions": 10, "clicks": 50, "spend": 10.0}, "clicks 50 exceed impressions"),
        ({"impressions": 1000, "clicks": 5, "spend": 10.0, "conv_obs": 9}, "exceed clicks"),
        ({"impressions": 1000, "clicks": 5, "spend": 10.0, "conv_rep": 5.5}, "exceed clicks"),
        ({"impressions": 1000, "clicks": 5, "spend": 10.0, "order_values": [80.0, 0.0]},
         "order value #1"),
        ({"impressions": 1000, "clicks": 5, "spend": -1.0}, "negative"),
        ({"impressions": 1000, "clicks": 5, "spend": 1.0, "mature": 1.5}, "mature fraction"),
    ],
)  # fmt: skip
def test_impossible_data_refused(ad: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match) as ei:
        fit_conjugate(B.funnel_data({"ad_z": ad}), B.default_prior_set(), seed=1)
    assert "ad_z" in str(ei.value)


def test_lagged_day_trials_never_below_conversions() -> None:
    data = B.funnel_data({"a": {"impressions": 1000, "clicks": 10, "spend": 10.0, "conv_obs": 8,
                                "mature": 0.5}})  # fmt: skip
    st = fit_conjugate(data, B.default_prior_set(), seed=1)
    assert derive("cvr", st, B.scope("a"), None).estimate.params == {"a": 9.0, "b": 49.0}


# --- 5 deterministic state id ----------------------------------------------------------------
def test_state_id_deterministic_and_resave_ok() -> None:
    a = fit_conjugate(B.north_pier_day14(), B.default_prior_set(), seed=7)
    b = fit_conjugate(B.north_pier_day14(), B.default_prior_set(), seed=7)
    c = fit_conjugate(B.north_pier_day14(), B.default_prior_set(), seed=8)
    assert a.state_id == b.state_id != c.state_id
    store.save(a)
    store.save(b)  # same state, later created_at
    assert store.load(a.state_id) == a


# --- 6 unapproved priors: synthetic only -----------------------------------------------------
def test_unapproved_prior_allowed_on_synthetic_with_notice() -> None:
    ps = B.default_prior_set()
    recs = {**ps.records, "ctr": B.prior_record("ctr", params={"a": 2.0, "b": 98.0})}
    data = B.north_pier_day14().model_copy(update={"synthetic": True})
    st = fit_conjugate(data, C.PriorSet(records=recs), seed=1)
    assert derive_mod.NOTICE_UNAPPROVED_PRIORS in derive("ctr", st, B.scope("ad_a"), None).notices
    with pytest.raises(C.GateFailure) as ei:
        fit_conjugate(B.north_pier_day14(), C.PriorSet(records=recs), seed=1)
    assert ei.value.result.gate == "G8"


# --- 7 reference-prior disclosures -----------------------------------------------------------
def test_reference_prior_notices() -> None:
    values = list(np.random.default_rng(0).lognormal(np.log(80), 0.3, 30))
    data = B.funnel_data({"a": {"impressions": 20000, "clicks": 400, "spend": 500.0,
                                "conv_obs": 30, "order_values": values}})  # fmt: skip
    # D32 approved CPM and order-value priors; drop them to exercise the reference-prior route.
    base = B.default_prior_set()
    no_struct = C.PriorSet(records={k: v for k, v in base.records.items()
                                    if k not in ("cpm_impressions_per_dollar",
                                                 "order_value_log_mean", "order_value_log_sd")})  # fmt: skip
    st = fit_conjugate(data, no_struct, seed=1)
    n = {name: derive(name, st, B.scope("a"), None).notices for name in
         ("cpm", "cpc", "roas", "aov", "ctr", "cvr")}  # fmt: skip
    for name in ("cpm", "cpc", "roas"):
        assert derive_mod.NOTICE_CPM_REFERENCE in n[name], name
    for name in ("aov", "roas"):
        assert derive_mod.NOTICE_AOV_REFERENCE in n[name], name
    for name in ("ctr", "cvr"):
        assert derive_mod.NOTICE_CPM_REFERENCE not in n[name]
        assert derive_mod.NOTICE_AOV_REFERENCE not in n[name]
    cg = B.funnel_data({"a": {"impressions": 2000, "clicks": 40, "spend": 50.0, "conv_obs": 2,
                              "revenue": 160.0}})  # fmt: skip
    st = fit_conjugate(cg, no_struct, seed=1)
    assert derive_mod.NOTICE_COMPOUND_GAMMA in derive("aov", st, B.scope("a"), None).notices


# --- 8 zero-data cases -----------------------------------------------------------------------
def test_zero_data_is_typed_not_estimable() -> None:
    d = B.funnel_data({"a": {"impressions": 1000, "clicks": 0, "spend": 10.0}})
    st = fit_conjugate(d, B.default_prior_set(), seed=1)
    for name in ("cvr", "cpa", "aov", "roas"):
        with pytest.raises(NotEstimable) as ei:
            derive(name, st, B.scope("a"), None)
        assert ei.value.feasibility.status == "below_floor"
        assert ei.value.feasibility.reasons == [ei.value.reason]
    q = derive("ctr", st, B.scope("a"), None)
    assert derive_mod.PRIOR_ONLY in q.feasibility.reasons


# --- 9 MC SE for expected loss; EVSI arm cap -------------------------------------------------
def test_joint_draws_report_expected_loss_se(tmp_path: Path) -> None:
    rng = np.random.default_rng(1)
    qs = [
        B.quantity("cvr", ad, route="nuts",
                   estimate=B.samples_spec(tmp_path / f"{ad}.parquet",
                                           {ad: stats.beta(a, b).rvs(20000, random_state=rng)}))
        for ad, (a, b) in (("a", (9, 441)), ("b", (19, 371)))
    ]  # fmt: skip
    c = compare(qs, B.objective("orders"), B.economics())
    se = c.mc_standard_error
    assert se is not None
    for ad in ("a", "b"):
        assert se[f"{LOSS_SE_PREFIX}{ad}"] > 0
    assert se[f"{LOSS_SE_PREFIX}a"] < 0.05 * float(c.expected_loss["a"].amount)


def test_evsi_refuses_too_many_arms() -> None:
    opts = [f"o{i}" for i in range(voi.MAX_SIGNAL_ARMS + 1)]
    p = C.DecisionProblem(options=opts, payoffs={o: B.beta_spec(10, 90) for o in opts},
                          objective=B.objective())  # fmt: skip
    d = C.TestDesign(arms=opts, allocation={o: 1 / len(opts) for o in opts}, volume=B.horizon(),
                     randomized=True, holdout=False, sensitivity=0.8,
                     false_positive_rate=0.2)  # fmt: skip
    with pytest.raises(ValueError, match="arms exceed"):
        voi.evsi(p, d)


# --- 10 assess at net zero -------------------------------------------------------------------
def test_assess_net_zero_does_not_buy(tmp_path: Path) -> None:
    st = fit_conjugate(B.north_pier_day14(), B.default_prior_set(), seed=1)
    path = tmp_path / "pay.parquet"
    B.write_samples(path, {"ad_b": [2000.0] * 4 + [-1000.0] * 6, "ad_a": [0.0] * 10})
    spec = {k: C.DistributionSpec(kind="samples", samples_path=str(path), n_samples=10,
                                  summary=B.summary_from_draws([0.0, 1.0]))
            for k in ("ad_b", "ad_a")}  # fmt: skip
    p = C.DecisionProblem(options=["ad_b", "ad_a"], payoffs=spec, objective=B.objective())
    d = C.TestDesign(arms=["ad_b"], allocation={"ad_b": 1.0}, volume=B.horizon("spend", 250),
                     randomized=True, holdout=False, sensitivity=0.75,
                     false_positive_rate=0.25)  # fmt: skip
    res = voi.assess(p, d, B.economics(), st)
    assert float(res.net_value.amount) == pytest.approx(0.0)
    assert res.verdict == "do_not_buy"
    assert res.design_label == "randomized"
