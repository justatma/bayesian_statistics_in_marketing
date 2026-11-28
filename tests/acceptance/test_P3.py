"""P3 conjugate path and decision math (spec v0.3 §5.4, §5.5, §6.3, §7.2, §8.1, §9.2).

# CONTRACT ASSUMPTION: fit_conjugate(data, priors, seed) takes the PriorSet keyed by the parameter
#   paths of registries/priors/default.yaml ("ctr", "cvr", "conversions_per_dollar"), and that set
#   is sufficient for the conjugate route.
# CONTRACT ASSUMPTION: derive(name, state, scope, econ) picks the ad by scope.ids["ad"], which is
#   the FunnelData entity id.
# CONTRACT ASSUMPTION: Comparison.options[i] names options[i] (same order) and every per-option
#   dict in the Comparison is keyed by those names.
# CONTRACT ASSUMPTION: the CTR comparison uses Objective(target="clicks", horizon in impressions);
#   the CVR comparison uses Objective(target="orders", horizon in clicks); the money rows compare
#   derive("contribution_per_click") quantities under Objective(target="contribution",
#   horizon=1,000 clicks), and p_exceeds_break_even is P(contribution per click > 0), i.e.
#   P(cvr > CPC / contribution per order).
# CONTRACT ASSUMPTION: compare raises core.GateFailure with result.gate == "G9" when economics are
#   unapproved or have no loss_tolerance.
# CONTRACT ASSUMPTION: a samples DistributionSpec for one Quantity is a parquet whose single column
#   holds that quantity's draws; rows are aligned across quantities (joint draws).
# CONTRACT ASSUMPTION: a sampled FunnelState's parquet has one column per "<entity>.<parameter>"
#   with parameters ctr, cvr, cpm (dollars per 1,000 impressions) and aov; derive("roas") uses the
#   draws row by row.
# CONTRACT ASSUMPTION: DecisionProblem payoffs given as samples read the column named after the
#   option; a signal-type TestDesign (sensitivity, false_positive_rate) on an arm signals positive
#   with probability `sensitivity` on draws where that arm's payoff is > 0 and
#   `false_positive_rate` otherwise.
# CONTRACT ASSUMPTION: funnel_state.save/load persist under BAYES_DATA_DIR; saving a different
#   state under an existing state_id raises.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from scipy import stats

from bayesian_marketing import core as C
from bayesian_marketing.decision.compare import compare
from bayesian_marketing.derived_metrics.derive import derive
from bayesian_marketing.funnel_state import store
from bayesian_marketing.inference.conjugate import fit_conjugate
from bayesian_marketing.test_design import voi
from tests.fakes import builders as B
from tests.oracle import north_pier as NP

pytestmark = pytest.mark.piece("P3")


def _state(data: C.FunnelData) -> C.FunnelState:
    st = fit_conjugate(data, B.default_prior_set(), seed=1)
    assert st.route == "conjugate"
    return st


def _derive(name: str, st: C.FunnelState, ad: str, econ=None) -> C.Quantity:
    q = derive(name, st, B.scope(ad), econ)
    assert isinstance(q, C.Quantity)
    assert q.name == name
    assert q.provenance.route == "conjugate"
    assert q.provenance.funnel_state_id == st.state_id
    return q


def _check_rate(q: C.Quantity, mean: float, ci: tuple[float, float]) -> None:
    s = q.estimate.summary
    assert NP.close4(s["mean"], mean)
    assert NP.close4(s["q025"], ci[0])
    assert NP.close4(s["q975"], ci[1])


def test_P3_oracle_ctr_day_two() -> None:
    st = _state(B.north_pier_day2())
    qa, qb = _derive("ctr", st, "ad_a"), _derive("ctr", st, "ad_b")
    _check_rate(qa, NP.CTR_MEAN_A, NP.CTR_CI95_A)
    _check_rate(qb, NP.CTR_MEAN_B, NP.CTR_CI95_B)
    c = compare([qa, qb], B.objective("clicks", "impressions", 2000), B.economics())
    a, _ = c.options
    assert c.method == "exact_integration"
    assert NP.close4(c.p_best[a], NP.CTR_P_A_GT_B)


def test_P3_oracle_cvr_day_fourteen() -> None:
    st = _state(B.north_pier_day14())
    qa, qb = _derive("cvr", st, "ad_a"), _derive("cvr", st, "ad_b")
    _check_rate(qa, NP.CVR_MEAN_A, NP.CVR_CI95_A)
    _check_rate(qb, NP.CVR_MEAN_B, NP.CVR_CI95_B)
    c = compare([qa, qb], B.objective("orders", "clicks", 1000), B.economics())
    _, b = c.options
    assert c.method == "exact_integration"
    assert NP.close4(c.p_best[b], NP.CVR_P_B_GT_A)


def _money_comparison(variable_cost: float = NP.VARIABLE_COST) -> C.Comparison:
    econ = B.economics(fixed_price=NP.PRICE, variable_cost=variable_cost)
    st = _state(B.north_pier_day14())
    qa = _derive("contribution_per_click", st, "ad_a", econ)
    qb = _derive("contribution_per_click", st, "ad_b", econ)
    c = compare([qa, qb], B.objective("contribution", "clicks", NP.HORIZON_CLICKS), econ)
    assert c.method == "exact_integration"
    assert c.economics_id == econ.economics_id
    return c


def test_P3_oracle_expected_contribution() -> None:
    c = _money_comparison()
    a, b = c.options
    assert NP.close4(float(c.expected_value[a].amount), NP.EV_A)
    assert NP.close4(float(c.expected_value[b].amount), NP.EV_B)
    assert c.expected_value[a].currency == "USD"
    assert NP.close4(c.p_best[b], NP.P_B_HIGHER)


def test_P3_oracle_expected_opportunity_loss() -> None:
    c = _money_comparison()
    a, b = c.options
    assert abs(float(c.expected_loss[a].amount) - NP.LOSS_A) <= NP.LOSS_TOL
    assert abs(float(c.expected_loss[b].amount) - NP.LOSS_B) <= NP.LOSS_TOL


def test_P3_oracle_break_even() -> None:
    c = _money_comparison()
    a, b = c.options
    assert NP.close4(c.p_exceeds_break_even[a], NP.P_A_CLEARS)
    assert NP.close4(c.p_exceeds_break_even[b], NP.P_B_CLEARS)


def test_P3_oracle_economics() -> None:
    assert NP.PRICE - NP.VARIABLE_COST == NP.BREAK_EVEN_CPA
    assert NP.PRICE / NP.BREAK_EVEN_CPA == NP.BREAK_EVEN_ROAS
    c = _money_comparison(NP.VARIABLE_COST_HIGH)
    a, b = c.options
    assert NP.close4(c.p_exceeds_break_even[a], NP.P_A_CLEARS_HIGH)
    assert NP.close4(c.p_exceeds_break_even[b], NP.P_B_CLEARS_HIGH)
    # contribution $24 per order: A's expected contribution at 1,000 clicks is 1000*(24*0.02-1.25)
    assert NP.close4(float(c.expected_value[a].amount), 1000 * (24 * 0.02 - 1.25))


def _decision_problem(tmp_path: Path) -> C.DecisionProblem:
    path = tmp_path / "payoffs.parquet"
    launch = [2000.0] * 4 + [-1000.0] * 6
    hold = [0.0] * 10
    B.write_samples(path, {"launch": launch, "hold": hold})
    spec = {
        k: C.DistributionSpec(
            kind="samples",
            samples_path=str(path),
            n_samples=10,
            summary=B.summary_from_draws(v),
        )
        for k, v in (("launch", launch), ("hold", hold))
    }
    return C.DecisionProblem(options=["launch", "hold"], payoffs=spec, objective=B.objective())


def test_P3_oracle_evpi_evsi(tmp_path: Path) -> None:
    p = _decision_problem(tmp_path)
    assert NP.close4(p.payoffs["launch"].summary["mean"], NP.EV_NOW)
    assert NP.close4(float(voi.evpi(p).amount), NP.EVPI)
    design = C.TestDesign(
        arms=["launch"],
        allocation={"launch": 1.0},
        volume=B.horizon(),
        randomized=False,
        holdout=False,
        sensitivity=0.75,
        false_positive_rate=0.25,
    )
    assert NP.close4(float(voi.evsi(p, design).amount), NP.EVSI)


def test_P3_oracle_sample_size() -> None:
    n = voi.sample_size_two_proportions(0.03, 0.04, 0.05, 0.8)
    assert abs(n - NP.SAMPLE_SIZE_PER_ARM) <= NP.SAMPLE_SIZE_TOL


def test_P3_oracle_dependence(tmp_path: Path) -> None:
    (c1, v1), (c2, v2) = NP.DEP_PAIRS
    cpm = NP.DEP_SPEND / NP.DEP_IMPRESSIONS * 1000  # $20 per 1,000 impressions
    st = B.samples_state(
        tmp_path / "state.parquet",
        {
            "ad_x.ctr": [c1, c2],
            "ad_x.cvr": [v1, v2],
            "ad_x.cpm": [cpm, cpm],
            "ad_x.aov": [NP.DEP_AOV, NP.DEP_AOV],
        },
    )
    q = derive("roas", st, B.scope("ad_x"), None)
    assert q.name == "roas"
    assert NP.close4(q.estimate.summary["mean"], NP.DEP_PAIRED_MEAN)
    assert not NP.close4(q.estimate.summary["mean"], NP.DEP_INDEPENDENT_MEAN)


def test_P3_exact_and_sampled_agree(tmp_path: Path) -> None:
    rng = np.random.default_rng(5)
    n = 40_000
    exact, sampled = [], []
    for ad, (a, b) in (("ad_a", NP.CVR_POST_A), ("ad_b", NP.CVR_POST_B)):
        exact.append(B.quantity("cvr", ad, estimate=B.beta_spec(a, b)))
        draws = stats.beta(a, b).rvs(n, random_state=rng)
        spec = B.samples_spec(tmp_path / f"{ad}.parquet", {ad: draws})
        sampled.append(B.quantity("cvr", ad, estimate=spec, route="nuts"))
    obj = B.objective("orders", "clicks", 1000)
    ce = compare(exact, obj, B.economics())
    cs = compare(sampled, obj, B.economics())
    assert ce.method == "exact_integration"
    assert cs.method == "joint_draws"
    assert cs.mc_standard_error is not None
    for oe, os_ in zip(ce.options, cs.options, strict=True):
        se = cs.mc_standard_error[os_]
        assert 0 < se < 0.01
        assert abs(cs.p_best[os_] - ce.p_best[oe]) <= 4 * se + 1e-9
    assert NP.close4(ce.p_best[ce.options[1]], NP.CVR_P_B_GT_A)


@pytest.mark.parametrize("econ_kw", [{"approved": False}, {"loss_tolerance": None}],
                         ids=["unapproved", "no_loss_tolerance"])  # fmt: skip
def test_P3_G9_without_economics(econ_kw: dict) -> None:
    opts = [
        B.quantity("cvr", "ad_a", estimate=B.beta_spec(*NP.CVR_POST_A)),
        B.quantity("cvr", "ad_b", estimate=B.beta_spec(*NP.CVR_POST_B)),
    ]
    with pytest.raises(C.GateFailure) as ei:
        compare(opts, B.objective("orders"), B.economics(**econ_kw))
    assert ei.value.result.gate == "G9"
    assert ei.value.result.passed is False
    assert ei.value.result.reasons


def test_P3_extra_funnel_state_store_immutable() -> None:
    st = _state(B.north_pier_day14())
    store.save(st)
    assert store.load(st.state_id) == st
    changed = st.model_copy(update={"synthetic": not st.synthetic})
    with pytest.raises(Exception) as ei:
        store.save(changed)
    assert not isinstance(ei.value, NotImplementedError)
    assert store.load(st.state_id) == st


def test_P3_extra_conjugate_quantities_valid() -> None:
    st = _state(B.north_pier_day14())
    econ = B.economics()
    for name in ("ctr", "cvr", "cpc", "cpm", "contribution_per_click"):
        q = _derive(name, st, "ad_a", econ)
        assert q.diagnostics_ref is None or q.provenance.route != "conjugate"
        assert q.scope.ids["ad"] == "ad_a"
        assert C.g10_reasons(q) == []


# CONTRACT ASSUMPTION: mix_weighted_rate(rates, clicks) is sum(rate_i * clicks_i) / sum(clicks_i),
#   keyed by ad id, so times 1,000 clicks it gives orders per 1,000 clicks (D22).
def test_P3_oracle_delivery_mix() -> None:
    from bayesian_marketing.derived_metrics.derive import mix_weighted_rate

    rates = {"a": 0.05, "b": 0.01}
    before = mix_weighted_rate(rates, {"a": 800, "b": 200}) * 1000
    after = mix_weighted_rate(rates, {"a": 300, "b": 700}) * 1000
    assert before == pytest.approx(NP.MIX_BEFORE, abs=1e-9) == pytest.approx(42, abs=1e-9)
    assert after == pytest.approx(NP.MIX_AFTER, abs=1e-9) == pytest.approx(22, abs=1e-9)
