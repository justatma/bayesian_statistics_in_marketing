"""P5 joint model and router (spec v0.3 §5.2, §7.1, §7.3, D11, I9).

# CONTRACT ASSUMPTION: compile_model raises core.UncoupledFunnelError for a spec without
#   coupling even when the spec object was built without validation (model_construct).
# CONTRACT ASSUMPTION: compile_model raises ValueError for dynamics="random_walk" on a window
#   shorter than min_days_for_dynamics.
# CONTRACT ASSUMPTION: the PriorSet built from registries/priors/default.yaml (every record there)
#   is what the joint model is fitted with; paths it needs beyond those must be added to that
#   registry file by the integrator (see manifest open questions).
# CONTRACT ASSUMPTION: a NUTS FunnelState's samples parquet has one column per
#   "<entity>.<parameter>" (ctr, cvr, cpm, aov) and a column "rho" holding the draws of the
#   CTR/CVR correlation; derive (P3) reads it.
# CONTRACT ASSUMPTION: the negative-dependence and A1 data come from tests/fakes/synth.py, which
#   follows the §9.1 description of `negative_dependence` (12 ads, true correlation -0.6), so the
#   test does not wait for P2.
# CONTRACT ASSUMPTION (SBC): bayesian_marketing.inference.sampler_numpyro exposes
#   sbc_ranks(spec, priors, n_ads, n_fits, n_draws, seed) -> dict[str, list[int]]: for each model
#   parameter, the rank (0..n_draws) of the prior-simulated true value among n_draws thinned
#   posterior draws, one rank per fit.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from bayesian_marketing import core as C
from bayesian_marketing.core import registries
from bayesian_marketing.derived_metrics.derive import derive
from bayesian_marketing.floors.estimability import quantity_feasibility
from bayesian_marketing.inference import sampler_numpyro
from bayesian_marketing.inference.router import route
from bayesian_marketing.model_spec.compile import compile_model
from tests.fakes import builders as B
from tests.fakes import synth
from tests.oracle import a1_reference as A1

pytestmark = pytest.mark.piece("P5")


def _config(seed: int = 1, draws: int = 500) -> C.FitConfig:
    return C.FitConfig(chains=2, draws=draws, warmup=draws, target_accept=0.9, seed=seed)


def _fit(spec: C.FunnelSpec, data: C.FunnelData, seed: int = 1):
    priors = B.default_prior_set()
    model = compile_model(spec, priors, data)
    assert isinstance(model, C.CompiledModel)
    state, report = sampler_numpyro.NumpyroSampler().fit(model, data, _config(seed))
    assert state.route == "nuts"
    assert report.sampler == "numpyro_nuts"
    assert report.passed is None, "only G3 sets passed"
    assert report.seeds
    return state, report


def _ads(n: int) -> C.FunnelData:
    return B.funnel_data(
        {
            f"ad_{i}": {"impressions": 5000, "clicks": 100, "spend": 120.0, "conv_obs": 3,
                        "conv_rep": 3.0}
            for i in range(n)
        }
    )  # fmt: skip


def test_P5_uncoupled_spec_rejected() -> None:
    good = B.funnel_spec()
    bad = C.FunnelSpec.model_construct(
        version="funnel@uncoupled",
        stages=good.stages,
        hierarchy=good.hierarchy,
        coupling=None,
        dynamics="static",
    )
    with pytest.raises(C.UncoupledFunnelError):
        compile_model(bad, B.default_prior_set(), _ads(12))
    model = compile_model(good, B.default_prior_set(), _ads(12))
    assert model.spec_version == good.version


def test_P5_small_account_routes_conjugate(iso) -> None:
    notice = registries.resolve("phrasing/notices/too_few_ads@v1")
    threshold = registries.resolve("bounds/coupling/min_ads_for_coupling@v1")
    assert threshold == 8
    for n, kind in ((2, "conjugate"), (7, "conjugate"), (8, "nuts"), (12, "nuts")):
        r = route(B.funnel_spec(), _ads(n))
        assert r.kind == kind, n
        assert r.reason
        if kind == "conjugate":
            assert notice in r.notices
        else:
            assert notice not in r.notices
    iso.edit_yaml("bounds", lambda d: d["coupling"].update(min_ads_for_coupling=3))
    assert route(B.funnel_spec(), _ads(4)).kind == "nuts"
    assert route(B.funnel_spec(), _ads(2)).kind == "conjugate"


def test_P5_extra_dynamics_needs_min_days() -> None:
    def days(n: int) -> C.FunnelData:
        d = [B.D_END - dt.timedelta(days=n - 1 - i) for i in range(n)]
        return B.funnel_data(
            {
                f"ad_{i}": {
                    "impressions": [500] * n,
                    "clicks": [10] * n,
                    "spend": [12.0] * n,
                    "conv_obs": [1] * n,
                    "conv_rep": [1.0] * n,
                    "mature": [1.0] * n,
                }
                for i in range(8)
            },
            dates=d,
        )

    rw = B.funnel_spec(dynamics="random_walk")
    with pytest.raises(ValueError):
        compile_model(rw, B.default_prior_set(), days(10))
    assert isinstance(compile_model(rw, B.default_prior_set(), days(21)), C.CompiledModel)


def _width(q: C.Quantity) -> float:
    return q.estimate.summary["q95"] - q.estimate.summary["q05"]


def test_P5_A1_roas_wider_with_modeled_value() -> None:
    data = synth.a1_data()
    assert {a: len(data.order_values[a]) for a in data.entities} == A1.CONVERSIONS
    state, _ = _fit(B.funnel_spec(), data, seed=2)
    for ad, aov in A1.FIXED_REVENUE_PER_CONVERSION.items():
        roas = derive("roas", state, B.scope(ad), None)
        cvr = derive("cvr", state, B.scope(ad), None)
        assert roas.provenance.route == "nuts" and roas.diagnostics_ref
        fixed_width = _width(cvr) * aov * A1.CLICKS / A1.SPEND
        assert _width(roas) > A1.MIN_WIDTH_RATIO * fixed_width, (
            f"{ad}: ROAS width {_width(roas):.4f} is not wider than the fixed-value "
            f"reference {fixed_width:.4f}"
        )


def test_P5_recovers_negative_dependence() -> None:
    data, realized = synth.negative_dependence()
    assert realized < -0.6
    state, _ = _fit(B.funnel_spec(), data, seed=3)
    assert state.posterior.kind == "samples"
    draws = pd.read_parquet(state.posterior.samples_path)
    rho = draws["rho"].to_numpy()
    assert np.all((rho >= -1) & (rho <= 1))
    assert float(np.mean(rho < 0)) > 0.9


def test_P5_fractional_uses_gamma_obs() -> None:
    data = synth.fractional_data()
    assert all(v is None for row in data.conversions_observed for v in row)
    spec = B.funnel_spec(
        stages=[
            C.StageSpec(name="delivery", likelihood="poisson", pooled=True),
            C.StageSpec(name="ctr", likelihood="binomial", pooled=True),
            C.StageSpec(name="cvr", likelihood="gamma_obs", pooled=True),
            C.StageSpec(name="value", likelihood="compound_gamma", pooled=True),
        ]
    )
    state, _ = _fit(spec, data, seed=4)
    notice = registries.resolve("phrasing/notices/platform_modeled@v1")
    pw = registries.resolve("bounds/estimability/posterior_width@v1")
    target = C.PrecisionTarget(
        rel_half_width=pw["rel_half_width"], caveat_rel_half_width=pw["caveat_rel_half_width"]
    )
    for ad in data.entities:
        for name in ("cvr", "roas"):
            q = derive(name, state, B.scope(ad), None)
            assert notice in q.notices, f"{ad}.{name} lacks the platform-modeled notice"
            assert q.evidence_class == "platform_attributed"
            assert quantity_feasibility(q, target).status != "estimable"


@pytest.mark.slow
def test_P5_sbc() -> None:
    sbc_ranks = sampler_numpyro.sbc_ranks
    spec = B.funnel_spec(hierarchy=["ad"])
    ranks = sbc_ranks(spec, B.default_prior_set(), n_ads=6, n_fits=100, n_draws=199, seed=2026)
    assert ranks, "no parameters ranked"
    alpha = 0.01 / len(ranks)  # Bonferroni
    failures = {}
    for param, r in ranks.items():
        r = np.asarray(r)
        assert r.size == 100, param
        assert r.min() >= 0 and r.max() <= 199, param
        counts = np.bincount(r // 10, minlength=20)  # 200 rank values into 20 bins of 10
        p = stats.chisquare(counts).pvalue
        if p <= alpha:
            failures[param] = p
    assert not failures, f"SBC rank histograms not uniform: {failures}"
