"""L6 blind review fixes (spec/reviews/L6_blind.md, ported from tests/review/l6/test_probes.py).

F1: an approved client prior is checked again against the ceiling of the run's kind at resolve,
whatever kind approved it. F3: resolve refuses an unknown kind before any hop."""

from __future__ import annotations

import datetime as dt

import pytest
from scipy import stats
from tests.fakes import builders as B

from bayesian_marketing import core as C
from bayesian_marketing import pipeline
from bayesian_marketing.core import registries
from bayesian_marketing.prior_registry import registry as pr

AS_OF = dt.datetime(2026, 11, 10, 12, 0, tzinfo=dt.UTC)
CX = "cx"
BETWEEN = {"a": 8.0, "b": 12.0}  # q99 0.655: above the purchase ceiling, below the lead one


def _ceiling(name: str) -> float:
    return float(registries.load("bounds")["plausibility"][name]["cvr"])


def _approved_as_lead() -> str:
    q99 = float(stats.beta(BETWEEN["a"], BETWEEN["b"]).ppf(0.99))
    assert _ceiling("ceiling_q99") < q99 < _ceiling("ceiling_q99_lead"), q99
    pid = pr.propose(B.prior_record("cvr", "beta", BETWEEN, approved=False, client_id=CX))
    with pytest.raises(pr.PriorRefused):
        pr.approve(pid, "owner")
    pr.approve(pid, "owner", conversion_kind="lead")
    return pid


@pytest.mark.parametrize("kw", [{}, {"conversion_kind": "purchase"}])
def test_prior_approved_as_lead_fails_g8_on_a_purchase_resolve(kw: dict[str, str]) -> None:
    pid = _approved_as_lead()
    with pytest.raises(C.GateFailure) as exc:
        pr.resolve("cvr", CX, AS_OF, **kw)
    assert exc.value.result.gate == "G8"
    text = " ".join(exc.value.result.reasons)
    q99 = float(stats.beta(BETWEEN["a"], BETWEEN["b"]).ppf(0.99))
    assert pid in text and "'cvr'" in text
    assert f"{q99:.4f}" in text and str(_ceiling("ceiling_q99")) in text


def test_prior_approved_as_lead_fails_g8_on_a_purchase_run() -> None:
    pid = _approved_as_lead()
    with pytest.raises(C.GateFailure) as exc:
        pipeline.resolve_priors({}, CX, False, AS_OF)
    assert exc.value.result.gate == "G8"
    assert pid in " ".join(exc.value.result.reasons)


def test_prior_approved_as_lead_resolves_on_a_lead_run() -> None:
    pid = _approved_as_lead()
    assert pr.resolve("cvr", CX, AS_OF, conversion_kind="lead").prior_id == pid
    priors, g8 = pipeline.resolve_priors({}, CX, False, AS_OF, conversion_kind="lead")
    assert g8.passed and priors.records["cvr"].prior_id == pid


@pytest.mark.parametrize("kind", ["purchase", "lead"])
def test_prior_approved_as_purchase_resolves_under_either_kind(kind: str) -> None:
    pid = pr.propose(B.prior_record("cvr", "beta", {"a": 6.0, "b": 24.0}, client_id=CX))
    pr.approve(pid, "owner")
    got = pr.resolve("cvr", CX, AS_OF, conversion_kind=kind)
    assert got.prior_id == pid and got.resolution_path == [f"client:{CX}:{pid}"]


def test_unknown_kind_is_refused_even_when_a_client_prior_exists() -> None:
    pid = pr.propose(B.prior_record("cvr", "beta", {"a": 6.0, "b": 24.0}, client_id=CX))
    pr.approve(pid, "owner")
    with pytest.raises(ValueError, match="conversion_kind"):
        pr.resolve("cvr", CX, AS_OF, conversion_kind="sale")


def test_unknown_kind_is_refused_by_resolve_priors() -> None:
    with pytest.raises(ValueError, match="conversion_kind"):
        pipeline.resolve_priors({}, CX, False, AS_OF, conversion_kind="sale")
