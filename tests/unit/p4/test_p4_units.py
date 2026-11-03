"""P4 unit checks beyond the frozen set."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.fakes import builders as B

from bayesian_marketing import core as C
from bayesian_marketing.core import registries
from bayesian_marketing.decision import run_record
from bayesian_marketing.decision.guarantees import render_guarantee
from bayesian_marketing.floors.estimability import decision_feasibility, quantity_feasibility
from bayesian_marketing.status_registry import registry as status


@pytest.fixture(autouse=True)
def _store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("BAYES_DATA_DIR", str(tmp_path))
    return tmp_path


def _target() -> C.PrecisionTarget:
    pw = registries.resolve("bounds/estimability/posterior_width@v1")
    return C.PrecisionTarget(
        rel_half_width=pw["rel_half_width"],
        level=pw["level"],
        caveat_rel_half_width=pw["caveat_rel_half_width"],
    )


def test_regime_notice_downgrades_one_level() -> None:
    est = B.beta_spec(400, 19600)  # w well under 0.20
    clean = B.quantity("ctr", estimate=est)
    assert quantity_feasibility(clean, _target()).status == "estimable"
    lag = registries.resolve("phrasing/notices/lag_approx@v1")
    few = registries.resolve("phrasing/notices/too_few_ads@v1")
    one = B.quantity("ctr", estimate=est, notices=[lag])
    f1 = quantity_feasibility(one, _target())
    assert f1.status == "marginal" and any(lag in r for r in f1.reasons)
    two = B.quantity("ctr", estimate=est, notices=[lag, few])
    assert quantity_feasibility(two, _target()).status == "below_floor"


def test_required_projection_uses_n_events() -> None:
    q = B.quantity("cvr", estimate=B.beta_spec(9, 441)).model_copy(update={"n_events": 8.0})
    f = quantity_feasibility(q, _target())
    w = (q.estimate.summary["q95"] - q.estimate.summary["q05"]) / (2 * q.estimate.summary["q50"])
    assert f.available == 8.0
    assert f.required == pytest.approx(8.0 * (w / 0.20) ** 2)
    assert any("approximate" in r for r in f.reasons)


def test_signed_quantity_inherits() -> None:
    q = B.quantity("contribution", feas=B.feasibility("marginal"))
    f = quantity_feasibility(q, _target())
    assert f.basis == "inherited" and f.status == "marginal"


def test_decision_currency_and_economics_mismatch() -> None:
    comp = B.comparison(expected_loss={"ad_a": 5, "ad_b": 1})
    with pytest.raises(ValueError):
        decision_feasibility(comp, B.economics(economics_id="econ_other"))
    with pytest.raises(ValueError):
        decision_feasibility(comp, B.economics(currency="EUR"))


def test_publish_supersedes_unknown_fails_g2() -> None:
    q = B.quantity("ctr", feas=B.feasibility("estimable", supersedes="q_never"))
    with pytest.raises(C.GateFailure) as ei:
        status.publish(q)
    assert ei.value.result.gate == "G2"


def test_publish_identical_is_idempotent_and_new_data_supersedes() -> None:
    old = B.quantity("ctr", feas=B.feasibility("marginal"), quantity_id="q_old00001")
    status.publish(old)
    status.publish(old)
    same_pulls = B.quantity(
        "ctr",
        estimate=B.beta_spec(400, 19600),
        feas=B.feasibility("estimable", supersedes="q_old00001"),
        quantity_id="q_same0001",
    )
    with pytest.raises(C.GateFailure) as ei:
        status.publish(same_pulls)
    assert ei.value.result.gate == "G2"
    assert any("strict superset" in r for r in ei.value.result.reasons)
    new = B.quantity(
        "ctr",
        estimate=B.beta_spec(400, 19600),
        feas=B.feasibility("estimable", supersedes="q_old00001"),
        quantity_id="q_new00001",
        pulls=[B.META_PULL, "pull_meta_00000002"],
    )
    status.publish(new)
    assert status.status_of("q_new00001").supersedes == "q_old00001"
    assert status.status_of("q_old00001").status == "marginal"


def test_publish_rejects_claim_that_disagrees_with_floor() -> None:
    q = B.quantity("cvr", estimate=B.beta_spec(9, 441), feas=B.feasibility("marginal"))
    with pytest.raises(C.GateFailure) as ei:
        status.publish(q)  # the floor says below_floor
    assert ei.value.result.gate == "G2"


def test_regime_limited_status_does_not_project_required() -> None:
    lag = registries.resolve("phrasing/notices/lag_approx@v1")
    q = B.quantity("ctr", estimate=B.beta_spec(400, 19600), notices=[lag])
    f = quantity_feasibility(q.model_copy(update={"n_events": 400.0}), _target())
    assert f.status == "marginal"
    assert f.required is None
    assert any("regime mismatch" in r for r in f.reasons)


def test_unknown_event_count_keeps_available_an_event_count() -> None:
    f = quantity_feasibility(B.quantity("cvr", estimate=B.beta_spec(9, 441)), _target())
    assert f.available == 0.0 and f.required is None
    assert any("event count unknown" in r for r in f.reasons)


def test_target_differing_from_registry_is_refused() -> None:
    t = C.PrecisionTarget(rel_half_width=0.5, level=0.9, caveat_rel_half_width=0.9)
    with pytest.raises(ValueError):
        quantity_feasibility(B.quantity("ctr"), t)


def test_platform_modeled_is_not_a_regime_downgrade() -> None:
    pm = registries.resolve("phrasing/notices/platform_modeled@v1")
    q = B.quantity("ctr", estimate=B.beta_spec(400, 19600), notices=[pm])
    assert quantity_feasibility(q, _target()).status == "estimable"


def test_run_record_rejects_duplicates_and_replace(_store: Path) -> None:
    import sqlite3

    rr = B.run_record()
    run_record.append(rr)
    with pytest.raises(run_record.DuplicateRecordError):
        run_record.append(rr)
    rec = B.recommendation()
    run_record.append(rec)
    with pytest.raises(run_record.DuplicateRecordError):
        run_record.append(rec)
    con = sqlite3.connect(_store / run_record.DB_NAME)
    try:
        for sql in (
            "INSERT OR REPLACE INTO run_records (seq, uid, payload) VALUES (1, 'x', '{}')",
            "INSERT OR REPLACE INTO run_records (uid, payload) VALUES ('run_00000001', '{}')",
        ):
            with pytest.raises(sqlite3.DatabaseError):
                con.execute(sql)
                con.commit()
            con.rollback()
    finally:
        con.close()
    assert run_record.read("RunRecord") == [rr]
    # Outcomes may repeat per recommendation.
    run_record.append(B.outcome_record())
    run_record.append(B.outcome_record())
    assert len(run_record.read("OutcomeRecord")) == 2


def test_run_record_filters_and_kinds() -> None:
    run_record.append(B.outcome_record("rec_1", "atmaos"))
    run_record.append(B.outcome_record("rec_1", "ground_truth"))
    assert len(run_record.read("OutcomeRecord")) == 2
    assert [o.source for o in run_record.read("OutcomeRecord", source="ground_truth")] == [
        "ground_truth"
    ]
    with pytest.raises(ValueError):
        run_record.read("Quantity")
    with pytest.raises(ValueError):
        run_record.read("OutcomeRecord", nope=1)
    with pytest.raises(TypeError):
        run_record.append(B.quantity())  # type: ignore[arg-type]


def test_guarantee_refusals() -> None:
    g = B.guarantee("posterior_probability")
    with pytest.raises(LookupError):
        render_guarantee(g)  # slots missing evidence_plain etc.
    full = g.model_copy(
        update={
            "slots": {
                "evidence_plain": "e",
                "route_plain": "r",
                "probability": "96%",
                "option": "ad_b",
                "horizon": "1,000 clicks",
                "assumption": "a",
            }
        }
    )
    assert "96%" in render_guarantee(full)
    for blank in ("", "   "):
        empty = full.model_copy(update={"slots": {**full.slots, "option": blank}})
        with pytest.raises(LookupError):
            render_guarantee(empty)
    with pytest.raises(LookupError):
        render_guarantee(full, locale="fr")
    wrong_kind = full.model_copy(update={"template_id": "expected_loss"})
    with pytest.raises(LookupError):
        render_guarantee(wrong_kind)
