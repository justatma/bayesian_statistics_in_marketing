"""P7 priors and lag (spec v0.3 §5.3, §5.6, G8).

# CONTRACT ASSUMPTION: a proposed PriorRecord names its client in resolution_path[0] as
#   "client:<client_id>" (PriorRecord has no client field). Proposals and approvals persist under
#   BAYES_DATA_DIR.
# CONTRACT ASSUMPTION: resolve(path, client, as_of) raises core.GateFailure with gate "G8" when the
#   client's prior for that path exists but is unapproved; with no client or vertical prior it
#   returns the framework default (registries/priors/default.yaml) with every hop recorded in
#   resolution_path, the last hop naming "default".
# CONTRACT ASSUMPTION: approve refuses an implausible prior by raising (any exception other than
#   NotImplementedError); the parameter path ("ctr" or "cvr") selects the plausibility ceiling.
#   An approved record has elicitation.approved_by == approver and a predictive_check dict.
# CONTRACT ASSUMPTION: prior_from_cohorts(rates, discount) returns the discounted (a, b) =
#   discount * (m*kappa, (1-m)*kappa); discount 1.0 means no discount.
# CONTRACT ASSUMPTION: import_promoted takes a PriorRecord JSON dump; an empty or None promotion
#   id raises ValueError.
# CONTRACT ASSUMPTION: lag_model(platform, window_code, history, None) with at least
#   min_lagged_conversions orders that carry first_click_at estimates the lag from
#   (ordered_at - first_click_at) in whole days. mature_fraction(click_date, as_of, lag) is
#   lag.cdf[a] for a = (as_of - click_date).days, and lag.cdf[-1] beyond the curve.
# CONTRACT ASSUMPTION: the lag_heavy data come from tests/fakes/synth.py (geometric lag, median 4
#   days, true CVR 4%), so the test does not wait for P2; the conjugate route (P3) applies the
#   effective-trials approximation from FunnelData.mature_fraction.
"""

from __future__ import annotations

import datetime as dt

import pytest

from bayesian_marketing import core as C
from bayesian_marketing.core import registries
from bayesian_marketing.derived_metrics.derive import derive
from bayesian_marketing.inference.conjugate import fit_conjugate
from bayesian_marketing.lag.model import lag_model, mature_fraction
from bayesian_marketing.prior_registry import registry as priors
from tests.fakes import builders as B
from tests.fakes import synth
from tests.oracle import north_pier as NP

pytestmark = pytest.mark.piece("P7")

AS_OF = dt.datetime(2026, 11, 2, tzinfo=dt.UTC)


def test_P7_unapproved_prior_blocks_fit() -> None:
    rec = B.prior_record("cvr", params={"a": 2.0, "b": 60.0}, client_id="client_x")
    pid = priors.propose(rec)
    assert pid.startswith("pr_") and len(pid) == len("pr_") + 8
    with pytest.raises(C.GateFailure) as ei:
        priors.resolve("cvr", "client_x", AS_OF)
    assert ei.value.result.gate == "G8"
    assert ei.value.result.passed is False

    approved = priors.approve(pid, "owner")
    assert approved.elicitation.approved_by == "owner"
    assert approved.predictive_check is not None
    got = priors.resolve("cvr", "client_x", AS_OF)
    assert got.params == {"a": 2.0, "b": 60.0}
    assert any("client" in hop for hop in got.resolution_path)

    other = priors.resolve("cvr", "client_y", AS_OF)
    assert other.params == {"a": 1.0, "b": 49.0}
    assert other.approved
    assert "default" in other.resolution_path[-1]
    assert len(other.resolution_path) >= 1


@pytest.mark.parametrize(
    "path,params,ok",
    [
        ("cvr", {"a": 50.0, "b": 10.0}, False),
        ("ctr", {"a": 30.0, "b": 70.0}, False),
        ("cvr", {"a": 1.0, "b": 49.0}, True),
        ("ctr", {"a": 2.0, "b": 98.0}, True),
    ],
)
def test_P7_predictive_check_refuses_implausible(path: str, params: dict, ok: bool) -> None:
    ceiling = registries.resolve(f"bounds/plausibility/ceiling_q99/{path}@v1")
    assert ceiling in (0.2, 0.5)
    pid = priors.propose(B.prior_record(path, params=params, client_id="client_z"))
    if ok:
        rec = priors.approve(pid, "owner")
        assert rec.elicitation.approved_by == "owner"
        assert rec.predictive_check is not None
    else:
        with pytest.raises(Exception) as ei:
            priors.approve(pid, "owner")
        assert not isinstance(ei.value, NotImplementedError)
        with pytest.raises(C.GateFailure):
            priors.resolve(path, "client_z", AS_OF)


def test_P7_cohort_prior_oracle() -> None:
    a, b = priors.prior_from_cohorts(NP.COHORT_RATES, 1.0)
    assert NP.close4(a, NP.COHORT_AB[0]) and NP.close4(b, NP.COHORT_AB[1])
    assert NP.close4(a + b, NP.COHORT_KAPPA)
    ad, bd = priors.prior_from_cohorts(NP.COHORT_RATES, NP.COHORT_DISCOUNT)
    assert NP.close4(ad, NP.COHORT_AB_DISCOUNTED[0])
    assert NP.close4(bd, NP.COHORT_AB_DISCOUNTED[1])
    k, n = NP.COHORT_UPDATE
    assert NP.close4((ad + k) / (ad + bd + n), NP.COHORT_POST_MEAN)


def test_P7_import_promoted_requires_id() -> None:
    rec = B.prior_record(
        "cvr", params={"a": 3.0, "b": 97.0}, approved=True, client_id=None, source="promoted",
        promotion_id="promo_1",
    )  # fmt: skip
    payload = rec.model_dump(mode="json")
    for bad in ("", None):
        with pytest.raises(ValueError):
            priors.import_promoted(payload, bad)  # type: ignore[arg-type]
    pid = priors.import_promoted(payload, "promo_1")
    assert isinstance(pid, str) and pid.startswith("pr_")


def test_P7_lag_thinned_likelihood_recovers_cvr() -> None:
    lh = synth.lag_heavy()
    lag = lag_model("meta", "7d_click_1d_view", lh.history, None)
    assert lag.source == "orders_history"
    assert lag.n_lagged_conversions == len(lh.history)
    mature = [mature_fraction(d, lh.as_of, lag) for d in lh.dates]
    assert mature == sorted(mature, reverse=True)
    assert mature[-1] < registries.resolve("bounds/lag/min_maturity@v1")
    data = B.funnel_data(
        {
            "ad_a": {
                "impressions": [c * 50 for c in lh.clicks],
                "clicks": lh.clicks,
                "spend": [c * 1.0 for c in lh.clicks],
                "conv_obs": lh.conv_observed,
                "conv_rep": [float(v) for v in lh.conv_observed],
                "mature": mature,
            }
        },
        dates=lh.dates,
    )
    st = fit_conjugate(data, B.default_prior_set(), seed=1)
    q = derive("cvr", st, B.scope("ad_a"), None)
    s = q.estimate.summary
    assert s["q05"] <= lh.true_cvr <= s["q95"], s
    approx = registries.resolve("phrasing/notices/lag_approx@v1")
    assert approx in q.notices


def test_P7_extra_lag_default_below_min() -> None:
    few = synth.lag_heavy().history[:10]
    lag = lag_model("meta", "7d_click_1d_view", few, None)
    assert lag.source == "registry_default"
    d = dt.date(2026, 11, 1)
    assert mature_fraction(d, d, lag) == pytest.approx(lag.cdf[0])
    assert mature_fraction(d, d + dt.timedelta(days=1), lag) == pytest.approx(lag.cdf[1])
    far = d + dt.timedelta(days=len(lag.cdf) + 30)
    assert mature_fraction(d, far, lag) == pytest.approx(lag.cdf[-1])
    none = lag_model("meta", "7d_click_1d_view", None, None)
    assert none.source == "registry_default"
