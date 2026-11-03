"""P5 unit tests beyond the frozen acceptance set."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from tests.fakes import builders as B

from bayesian_marketing import core as C
from bayesian_marketing.core import registries
from bayesian_marketing.derived_metrics.derive import derive
from bayesian_marketing.inference import sampler_numpyro as S
from bayesian_marketing.inference.router import route
from bayesian_marketing.model_spec import compile as compile_mod
from bayesian_marketing.model_spec.compile import compile_model, load_plan
from bayesian_marketing.model_spec.plan import log_cpm_moments, logit_beta_moments


@pytest.fixture(autouse=True)
def _iso(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BAYES_DATA_DIR", str(tmp_path / "store"))


def _ads(n: int, **over) -> C.FunnelData:
    row = {"impressions": 5000, "clicks": 100, "spend": 120.0, "conv_obs": 3, "conv_rep": 3.0}
    row.update(over)
    return B.funnel_data({f"ad_{i}": dict(row) for i in range(n)})


def _cfg() -> C.FitConfig:
    return C.FitConfig(chains=2, draws=60, warmup=60, target_accept=0.9, seed=5)


def test_route_reason_names_threshold() -> None:
    r = route(B.funnel_spec(), _ads(3))
    assert r.kind == "conjugate" and "8" in r.reason


def test_moments_match_monte_carlo() -> None:
    rng = np.random.default_rng(0)
    p = rng.beta(2, 98, 400_000)
    m, s = logit_beta_moments(2, 98)
    lp = np.log(p / (1 - p))
    assert abs(lp.mean() - m) < 0.01 and abs(lp.std() - s) < 0.01
    r = rng.gamma(3.0, 1 / 0.05, 400_000)
    m, s = log_cpm_moments(3.0, 0.05)
    lc = np.log(1000.0 / r)
    assert abs(lc.mean() - m) < 0.01 and abs(lc.std() - s) < 0.01


def test_unsupported_likelihood_and_missing_stage_refused() -> None:
    spec = B.funnel_spec(
        stages=[
            C.StageSpec(name="delivery", likelihood="poisson", pooled=True),
            C.StageSpec(name="ctr", likelihood="beta_binomial", pooled=True),
            C.StageSpec(name="cvr", likelihood="binomial", pooled=True),
            C.StageSpec(name="value", likelihood="lognormal", pooled=True),
        ]
    )
    with pytest.raises(ValueError, match="not implemented"):
        compile_model(spec, B.default_prior_set(), _ads(8))
    spec = B.funnel_spec(
        stages=[
            C.StageSpec(name="ctr", likelihood="binomial", pooled=True),
            C.StageSpec(name="cvr", likelihood="binomial", pooled=True),
            C.StageSpec(name="value", likelihood="lognormal", pooled=True),
        ]
    )
    with pytest.raises(ValueError, match="stages"):
        compile_model(spec, B.default_prior_set(), _ads(8))


def test_fractional_in_binomial_refused() -> None:
    data = _ads(8, conv_obs=None, conv_rep=2.5)
    with pytest.raises(ValueError, match="gamma_obs"):
        compile_model(B.funnel_spec(), B.default_prior_set(), data)


def test_unapproved_prior_in_set_blocks_client_data_only() -> None:
    priors = B.default_prior_set()
    rec = priors.records["ctr"].model_copy(update={"elicitation": B.elicitation(approved=False)})
    bad = C.PriorSet(records={**priors.records, "ctr": rec})
    with pytest.raises(C.GateFailure) as e:
        compile_model(B.funnel_spec(), bad, _ads(8))
    assert e.value.result.gate == "G8"
    syn = _ads(8).model_copy(update={"synthetic": True})
    compile_model(B.funnel_spec(), bad, syn)


def test_missing_structural_prior_g8_on_client_fallback_on_synthetic(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """D28 item 2: a path the PriorSet lacks raises G8 on client data; on synthetic data it may
    use a registry pending placeholder, counted for the unapproved-priors notice."""
    reg = tmp_path / "registries"
    shutil.copytree(registries.registry_root(), reg)
    path = reg / "priors" / "default.yaml"
    doc = yaml.safe_load(path.read_text())
    doc["pending_records"] = {"logit_scale_ctr": {"family": "halfnormal", "params": {"scale": 1}}}
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    monkeypatch.setenv("BAYES_REGISTRY_DIR", str(reg))
    registries.clear_cache()
    try:
        recs = dict(B.default_prior_set().records)
        recs.pop("logit_scale_ctr")
        priors = C.PriorSet(records=recs)
        with pytest.raises(C.GateFailure) as e:
            compile_model(B.funnel_spec(), priors, _ads(8))
        assert e.value.result.gate == "G8"
        syn = _ads(8).model_copy(update={"synthetic": True})
        plan = load_plan(compile_model(B.funnel_spec(), priors, syn))
        assert plan.unapproved == ["logit_scale_ctr"]
        assert plan.terms["logit_scale_ctr"].source == "registry_pending"
    finally:
        registries.clear_cache()


def test_fit_state_contract() -> None:
    data = _ads(8, order_values=[50.0, 70.0, 90.0])
    model = compile_model(B.funnel_spec(), B.default_prior_set(), data)
    state, report = S.NumpyroSampler().fit(model, data, _cfg())
    assert state.diagnostics_id == report.report_id and report.report_id.startswith("dg_")
    assert report.passed is None and report.seeds == [5]
    df = pd.read_parquet(state.posterior.samples_path)
    for ad in data.entities:
        for p in S.PARAMS:
            assert f"{ad}.{p}" in df.columns
    assert "rho" in df.columns
    assert sorted(df["chain"].unique().tolist()) == [0, 1]
    assert len(df) == 120
    params = state.posterior.params
    assert params["diagnostics.n_divergences"] == report.n_divergences
    assert params["ad_0.n.conversions"] == 3.0 and params["ad_0.n.orders"] == 3.0
    assert params["route.unapproved_priors"] == 0  # D32: every structural prior approved
    assert "currency.code" in params
    # not saved before G3 (P6 contract)
    assert not (Path(state.posterior.samples_path).parent / f"{state.state_id}.json").exists()
    q = derive("roas", state, B.scope("ad_0"), None)
    assert q.provenance.route == "nuts" and q.diagnostics_ref == report.report_id


def test_plan_reloads_from_disk() -> None:
    data = _ads(8)
    model = compile_model(B.funnel_spec(), B.default_prior_set(), data)
    compile_mod._PLANS.clear()
    plan = load_plan(model)
    assert plan.data_hash == C.inputs_hash(data)
    raw = json.loads((compile_mod._plan_path(plan.plan_id)).read_text())
    assert raw["spec"]["coupling"] == "lkj_bivariate"
    with pytest.raises(ValueError, match="differs"):
        S.NumpyroSampler().fit(model, _ads(9), _cfg())


def test_zero_spend_days_masked_and_campaign_level() -> None:
    import datetime as dt

    dates = [B.D_END - dt.timedelta(days=1), B.D_END]
    ads = {
        f"ad_{i}": {
            "impressions": [5000, 0],
            "clicks": [100, 0],
            "spend": [120.0, 0.0],
            "conv_obs": [3, 0],
            "conv_rep": [3.0, 0.0],
        }
        for i in range(8)
    }
    parents = {a: {"campaign": f"c{i % 2}", "account": "acc1"} for i, a in enumerate(ads)}
    data = B.funnel_data(ads, dates=dates, parents=parents)
    model = compile_model(B.funnel_spec(), B.default_prior_set(), data)
    assert model.data_shape == {"n_ads": 8, "n_days": 2, "n_campaign": 2}
    state, _ = S.NumpyroSampler().fit(model, data, _cfg())
    assert state.posterior.params["ad_0.n.impressions"] == 5000.0
