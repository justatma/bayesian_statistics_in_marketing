"""L6 unit checks beyond the frozen tests: the kind is validated, a lead kind falls back to the
purchase table and ceiling for paths the lead tables lack, and purchase defaults keep their ids."""

from __future__ import annotations

import datetime as dt

import pytest
from tests.fakes import builders as B

from bayesian_marketing import core as C
from bayesian_marketing.core import registries
from bayesian_marketing.prior_registry import registry as prior_registry

AS_OF = dt.datetime(2026, 11, 10, 12, 0, tzinfo=dt.UTC)


def _ceilings(name: str) -> dict[str, float]:
    return {k: float(v) for k, v in registries.load("bounds")["plausibility"][name].items()}


@pytest.mark.parametrize("call", ["resolve", "predictive_check", "approve", "default"])
def test_unknown_conversion_kind_is_refused(call: str) -> None:
    rec = B.prior_record("cvr", "beta", {"a": 2.0, "b": 60.0}, client_id="c1")
    with pytest.raises(ValueError, match="conversion_kind"):
        if call == "resolve":
            prior_registry.resolve("cvr", "c1", AS_OF, conversion_kind="sale")
        elif call == "predictive_check":
            prior_registry.predictive_check(rec, conversion_kind="sale")
        elif call == "approve":
            pid = prior_registry.propose(rec)
            prior_registry.approve(pid, "owner", conversion_kind="sale")
        else:
            prior_registry._default_prior("cvr", conversion_kind="sale")


def test_every_purchase_default_id_is_the_base_formula_under_either_kind() -> None:
    reg = registries.load("priors/default")
    lead_paths = set(reg.get("lead_records") or {})
    for path, spec in reg["records"].items():
        params = {k: float(v) for k, v in spec["params"].items()}
        base = C.make_id("pr_", {"default": path, "params": params})
        assert prior_registry._default_prior(path).prior_id == base
        lead = prior_registry._default_prior(path, conversion_kind="lead")
        if path in lead_paths:
            assert lead.prior_id != base
            assert lead.resolution_path == [f"default:priors/default/lead_records/{path}@v1"]
        else:
            assert lead.prior_id == base


def test_lead_ctr_check_keeps_the_purchase_ceiling() -> None:
    assert "ctr" not in _ceilings("ceiling_q99_lead")
    rec = B.prior_record("ctr", "beta", {"a": 2.0, "b": 98.0}, client_id=None)
    out = prior_registry.predictive_check(rec, conversion_kind="lead")
    assert out["ceiling"] == _ceilings("ceiling_q99")["ctr"]


def test_lead_ceiling_still_refuses_above_it() -> None:
    lead_ceiling = _ceilings("ceiling_q99_lead")["cvr"]
    rec = B.prior_record("cvr", "beta", {"a": 20.0, "b": 2.0}, client_id="c1")
    with pytest.raises(prior_registry.PriorRefused, match=str(lead_ceiling)):
        prior_registry.predictive_check(rec, conversion_kind="lead")


def test_lead_default_is_approved_by_its_own_elicitation() -> None:
    entry = registries.load("priors/default")["lead_records"]["cvr"]
    rec = prior_registry._default_prior("cvr", conversion_kind="lead")
    assert rec is not None and rec.approved
    assert rec.elicitation.source == entry["elicitation"]["source"]
    assert rec.elicitation.evidence_refs == ["priors/default/lead_records/cvr@v1"]


def test_lead_path_missing_from_every_table_still_raises() -> None:
    with pytest.raises(registries.RegistryError):
        prior_registry.resolve("no_such_path", "c1", AS_OF, conversion_kind="lead")
