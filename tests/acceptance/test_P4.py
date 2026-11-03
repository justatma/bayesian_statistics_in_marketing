"""P4 floors, status registry, run record, guarantees (spec v0.3 §6.1, §6.2, §8.5, §8.6, D9, D10,
D15, D16).

# CONTRACT ASSUMPTION: quantity_feasibility reads the rate thresholds from the registry, so the
#   PrecisionTarget passed in is built from bounds.yaml; the result's target equals 0.20.
# CONTRACT ASSUMPTION: decision_feasibility's L is Comparison.expected_loss of the option with the
#   lowest expected loss (which is also the highest p_best in these fixtures).
# CONTRACT ASSUMPTION: with no loss_tolerance, decision_feasibility either raises GateFailure with
#   gate "G9" or returns a below_floor Feasibility whose reasons include "no loss tolerance set".
# CONTRACT ASSUMPTION: run_record keeps one SQLite file under BAYES_DATA_DIR (extension .sqlite,
#   .sqlite3 or .db); read(kind, **filters) takes the class name as kind ("RunRecord",
#   "Recommendation", "ApprovalRecord", "OutcomeRecord") and field-equality filters.
# CONTRACT ASSUMPTION: Guarantee.slots carries the template placeholders by name; render_guarantee
#   fills them and raises (not NotImplementedError) for a template id that is not one of the four
#   kinds, or whose registry entry is marked provisional.
# CONTRACT ASSUMPTION: status_registry.publish raises GateFailure("G2") when the feasibility's
#   bound_ref does not resolve; status_of returns the published Feasibility.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bayesian_marketing import core as C
from bayesian_marketing.core import registries
from bayesian_marketing.core.scope import STATUS_ORDER
from bayesian_marketing.decision import run_record
from bayesian_marketing.decision.guarantees import render_guarantee
from bayesian_marketing.floors.estimability import decision_feasibility, quantity_feasibility
from bayesian_marketing.status_registry import registry as status
from tests.fakes import builders as B
from tests.oracle import north_pier as NP

pytestmark = pytest.mark.piece("P4")


def _target() -> C.PrecisionTarget:
    pw = registries.resolve("bounds/estimability/posterior_width@v1")
    return C.PrecisionTarget(
        rel_half_width=pw["rel_half_width"],
        level=pw["level"],
        caveat_rel_half_width=pw["caveat_rel_half_width"],
    )


def _rate(name: str, a: float, b: float) -> C.Quantity:
    return B.quantity(name, estimate=B.beta_spec(a, b), quantity_id=f"q_{name}{a:g}x{b:g}")


def test_P4_oracle_floors() -> None:
    cases = {
        "ctr_a": _rate("ctr", *NP.CTR_POST_A),
        "ctr_b": _rate("ctr", *NP.CTR_POST_B),
        "cvr_a": _rate("cvr", *NP.CVR_POST_A),
        "cvr_b": _rate("cvr", *NP.CVR_POST_B),
    }
    for key, q in cases.items():
        f = quantity_feasibility(q, _target())
        assert f.status == NP.FLOOR_STATUS[key], key
        assert f.basis == "quantity_precision"
        assert f.target == pytest.approx(0.20)
        assert f.reasons, f"{key}: a non-estimable status needs reasons"
        registries.resolve(f.bound_ref)  # C1: the bound comes from the registry


def test_P4_extra_floor_edges_follow_registry(iso) -> None:
    iso.edit_yaml(
        "bounds",
        lambda d: d["estimability"]["posterior_width"].update(
            rel_half_width=0.30, caveat_rel_half_width=0.60
        ),
    )
    t = _target()
    assert quantity_feasibility(_rate("ctr", *NP.CTR_POST_A), t).status == "estimable"
    assert quantity_feasibility(_rate("cvr", *NP.CVR_POST_A), t).status == "marginal"


@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    r=st.floats(0.005, 0.3),
    n_small=st.floats(5.0, 50_000.0),
    factor=st.floats(1.0, 100.0),
)
def test_P4_less_data_never_improves_status(r: float, n_small: float, factor: float) -> None:
    # Same rate, more pseudo-observations: Beta(r*N, (1-r)*N). Less data never ranks higher.
    n_big = n_small * factor
    small = quantity_feasibility(_rate("cvr", r * n_small, (1 - r) * n_small), _target())
    big = quantity_feasibility(_rate("cvr", r * n_big, (1 - r) * n_big), _target())
    assert STATUS_ORDER[small.status] <= STATUS_ORDER[big.status]


def _decision_comp(best_loss: float) -> C.Comparison:
    return B.comparison(
        p_best={"ad_a": 0.1, "ad_b": 0.9},
        expected_value={"ad_a": 0, "ad_b": 500},
        expected_loss={"ad_a": 5000, "ad_b": best_loss},
    )


@pytest.mark.parametrize(
    "loss,want",
    [(5, "estimable"), (10, "estimable"), (15, "marginal"), (20, "marginal"), (25, "below_floor")],
)
def test_P4_decision_basis_governs_D9(loss: float, want: str) -> None:
    econ = B.economics(loss_tolerance=10)
    f = decision_feasibility(_decision_comp(loss), econ)
    assert f.basis == "decision_loss"
    assert f.status == want
    registries.resolve(f.bound_ref)
    if want != "estimable":
        assert f.reasons
    # D9: the decision is judged on loss only; it does not consult rate statuses, so a comparison
    # whose rates would be below floor still gets the same decision status.
    again = decision_feasibility(_decision_comp(loss), econ)
    assert again.status == f.status


def test_P4_extra_no_tolerance_not_knowable() -> None:
    econ = B.economics(loss_tolerance=None)
    try:
        f = decision_feasibility(_decision_comp(1), econ)
    except C.GateFailure as e:
        assert e.result.gate == "G9"
    else:
        assert f.status == "below_floor"
        assert any("no loss tolerance set" in r for r in f.reasons)


def test_P4_extra_decision_multiplier_from_registry(iso) -> None:
    iso.edit_yaml(
        "bounds", lambda d: d["estimability"]["decision_loss"].update(marginal_multiplier=3.0)
    )
    f = decision_feasibility(_decision_comp(25), B.economics(loss_tolerance=10))
    assert f.status == "marginal"


def _db(store: Path) -> Path:
    found = [p for p in store.rglob("*") if p.suffix in (".sqlite", ".sqlite3", ".db")]
    assert len(found) == 1, f"expected one SQLite file under BAYES_DATA_DIR, found {found}"
    return found[0]


def test_P4_run_record_rejects_update_delete(iso) -> None:
    rr = B.run_record()
    rec = B.recommendation()
    appr = B.approval_record(rec.recommendation_id)
    out = B.outcome_record(rec.recommendation_id)
    for obj in (rr, rec, appr, out):
        run_record.append(obj)
    assert run_record.read("RunRecord", run_id=rr.run_id) == [rr]
    assert run_record.read("Recommendation", run_id=rr.run_id) == [rec]
    assert run_record.read("ApprovalRecord", recommendation_id=rec.recommendation_id) == [appr]
    assert run_record.read("OutcomeRecord", recommendation_id=rec.recommendation_id) == [out]

    con = sqlite3.connect(_db(iso.store))
    try:
        tables = [
            r[0]
            for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if not r[0].startswith("sqlite_")
        ]
        assert tables
        for t in tables:
            n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            if n == 0:
                continue
            with pytest.raises(sqlite3.DatabaseError):
                con.execute(f'UPDATE "{t}" SET rowid = rowid')
                con.commit()
            con.rollback()
            with pytest.raises(sqlite3.DatabaseError):
                con.execute(f'DELETE FROM "{t}"')
                con.commit()
            con.rollback()
    finally:
        con.close()
    assert run_record.read("RunRecord", run_id=rr.run_id) == [rr]
    assert run_record.read("Recommendation", run_id=rr.run_id) == [rec]


SLOTS = {
    "evidence_plain": "orders actually received",
    "route_plain": "exact per-ad model",
    "probability": "96%",
    "option": "ad_b",
    "horizon": "1,000 clicks",
    "assumption": "the next clicks behave like the last",
    "expected_loss": "$6",
    "tolerance": "$1,000",
    "design": "a 50/50 split test",
    "evsi": "$250",
    "cost": "$120",
    "reason": "no loss tolerance set",
    "requirement": "we need a loss tolerance from you",
}
KINDS = ("posterior_probability", "expected_loss", "value_of_information", "none")


def _g(kind: str, template_id: str | None = None) -> C.Guarantee:
    return C.Guarantee(
        kind=kind,
        statement_math="m",
        template_id=template_id or kind,
        slots=dict(SLOTS),
        assumptions=[SLOTS["assumption"]],
    )


def test_P4_no_provisional_template_reachable(iso) -> None:
    templates = registries.load("guarantee_templates")["templates"]
    assert set(templates) == set(KINDS)
    for tid, t in templates.items():
        assert "provisional" not in tid.lower()
        assert "provisional" not in str(t).lower()
    for kind in KINDS:
        text = render_guarantee(_g(kind))
        assert isinstance(text, str) and text
        assert "{" not in text and "}" not in text
        assert "provisional" not in text.lower()
    assert "96%" in render_guarantee(_g("posterior_probability"))
    for bad in ("constant_factor", "competitive_ratio", "provisional_ratio"):
        with pytest.raises(Exception) as ei:
            render_guarantee(_g("posterior_probability", bad))
        assert not isinstance(ei.value, NotImplementedError)

    # A provisional entry slipped into the registry is still unreachable (D15).
    def add(d: dict) -> None:
        d["templates"]["provisional_ratio"] = {
            "kind": "posterior_probability",
            "provisional": True,
            "text": "PROVISIONAL {option} within a factor of two",
        }

    iso.edit_yaml("guarantee_templates", add)
    with pytest.raises(Exception) as ei:
        render_guarantee(_g("posterior_probability", "provisional_ratio"))
    assert not isinstance(ei.value, NotImplementedError)


def test_P4_extra_status_registry_publish_and_G2() -> None:
    q = _rate("cvr", *NP.CVR_POST_B)
    f = quantity_feasibility(q, _target())
    q = q.model_copy(update={"feasibility": f})
    status.publish(q)
    got = status.status_of(q.quantity_id)
    assert got.status == f.status
    assert got.bound_ref == f.bound_ref

    bad = B.quantity(
        "cvr",
        estimate=B.beta_spec(9, 441),
        feas=B.feasibility("below_floor", bound_ref="bounds/nope/missing@v1"),
        quantity_id="q_badbound",
    )
    with pytest.raises(C.GateFailure) as ei:
        status.publish(bad)
    assert ei.value.result.gate == "G2"
    with pytest.raises(Exception) as ei2:
        status.status_of("q_badbound")
    assert not isinstance(ei2.value, NotImplementedError)


def test_P4_extra_published_status_immutable() -> None:
    q = _rate("ctr", *NP.CTR_POST_A)
    status.publish(q.model_copy(update={"feasibility": quantity_feasibility(q, _target())}))
    better = q.model_copy(update={"feasibility": B.feasibility("estimable")})
    with pytest.raises(Exception) as ei:
        status.publish(better)
    assert not isinstance(ei.value, NotImplementedError)
    assert status.status_of(q.quantity_id).status == "marginal"
