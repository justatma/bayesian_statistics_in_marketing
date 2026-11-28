"""D32: the seven structural priors are approved records with their own elicitation."""

from __future__ import annotations

from bayesian_marketing.core import registries
from bayesian_marketing.prior_registry import registry as R

STRUCTURAL = [
    "cpm_impressions_per_dollar",
    "order_value_log_mean",
    "order_value_log_sd",
    "logit_scale_ctr",
    "logit_scale_cvr",
    "lkj_concentration",
    "gamma_obs_shape",
]


def test_structural_priors_approved_by_owner() -> None:
    registries.clear_cache()
    reg = registries.load("priors/default")
    assert not reg.get("pending_records")
    for path in STRUCTURAL:
        rec = R._default_prior(path)
        assert rec is not None
        assert rec.elicitation.approved_by == "owner"
        assert rec.elicitation.author == "claude"


def test_manuscript_priors_keep_their_approval() -> None:
    rec = R._default_prior("cvr")
    assert rec is not None and rec.elicitation.author == "owner"
