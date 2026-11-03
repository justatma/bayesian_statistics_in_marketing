"""P9 unit checks beyond the frozen set."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from tests.fakes import builders as B

from bayesian_marketing import core as C
from bayesian_marketing.audit.report import guarantee_report
from bayesian_marketing.core import registries
from bayesian_marketing.decision import run_record
from bayesian_marketing.decision.allocation import allocate, bounded_shares
from bayesian_marketing.decision.reallocation import reallocate
from bayesian_marketing.decision.stopping import stop_or_continue

REPO = Path(__file__).resolve().parents[3]
RUN = "run_p9unit001"


@pytest.fixture(autouse=True)
def _iso(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    reg = tmp_path / "registries"
    shutil.copytree(REPO / "registries", reg)
    monkeypatch.setenv("BAYES_REGISTRY_DIR", str(reg))
    monkeypatch.setenv("BAYES_DATA_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("BAYES_CONFIG_DIR", str(tmp_path / "configs"))
    registries.clear_cache()
    yield reg
    registries.clear_cache()


def _set_cost(reg: Path, platform: str, amount: str | None) -> None:
    path = reg / "channels.yaml"
    d = yaml.safe_load(path.read_text())
    d["channels"][platform]["learning_phase_switching_cost"] = (
        None if amount is None else {"amount": amount, "currency": "USD"}
    )
    path.write_text(yaml.safe_dump(d, sort_keys=False))
    registries.clear_cache()


def _cmp() -> C.Comparison:
    return B.comparison(
        ("keep", "switch"),
        p_best={"keep": 0.3, "switch": 0.7},
        expected_value={"keep": 1000, "switch": 1170},
        expected_loss={"keep": 350, "switch": 180},
    )


def _est() -> C.Feasibility:
    return B.feasibility("estimable", "decision_loss")


def _data(ads: tuple[str, ...], mature: float = 1.0) -> C.FunnelData:
    return B.funnel_data(
        {a: {"impressions": 5000, "clicks": 100, "spend": 120.0, "mature": mature} for a in ads}
    )


def test_scope_platform_picks_its_switching_cost(_iso: Path) -> None:
    _set_cost(_iso, "meta", "250")
    _set_cost(_iso, "google_ads", "0")
    meta = reallocate(_cmp(), _est(), B.economics(), RUN, scope=B.scope(platform="meta"))
    assert meta.action == "hold"
    assert meta.scope.platform == "meta"
    g = reallocate(_cmp(), _est(), B.economics(), RUN, scope=B.scope(platform="google_ads"))
    assert g.action == "reallocate"
    assert g.reversibility == "reversible"
    assert float(g.expected_benefit.amount) == pytest.approx(170)


def test_no_scope_uses_largest_known_cost(_iso: Path) -> None:
    for p, a in (("meta", "50"), ("google_ads", "250"), ("linkedin", "10")):
        _set_cost(_iso, p, a)
    assert reallocate(_cmp(), _est(), B.economics(), RUN).action == "hold"


def test_no_tolerance_or_unapproved_is_not_knowable() -> None:
    c = B.comparison(expected_loss={"ad_a": 700, "ad_b": 5})
    for econ in (B.economics(loss_tolerance=None), B.economics(approved=False)):
        assert reallocate(_cmp(), _est(), econ, RUN).action == "not_knowable"
        s = stop_or_continue(c, _est(), _data(("ad_a", "ad_b")), econ, RUN)
        assert s.action == "not_knowable"


def test_rate_basis_refused() -> None:
    with pytest.raises(ValueError, match="decision_loss"):
        reallocate(_cmp(), B.feasibility("estimable"), B.economics(), RUN)


def test_floor_without_q05_blocks_switch() -> None:
    rec = reallocate(_cmp(), _est(), B.economics(survival_floor=0), RUN)
    assert rec.action == "hold"
    assert "survival floor" in rec.model_dump_json()


def test_stop_without_budget_or_required_is_not_knowable() -> None:
    c = B.comparison(expected_loss={"ad_a": 700, "ad_b": 5})
    data = _data(("ad_a", "ad_b"))
    below = B.feasibility("below_floor", "decision_loss", required=5000.0)
    assert stop_or_continue(c, below, data, B.economics(), RUN).action == "not_knowable"
    unprojected = B.feasibility("below_floor", "decision_loss")
    econ = B.economics(test_budget=10**9)
    assert stop_or_continue(c, unprojected, data, econ, RUN).action == "not_knowable"
    marginal = B.feasibility("marginal", "decision_loss", required=10.0)
    assert stop_or_continue(c, marginal, data, econ, RUN).action == "continue_test"


def test_stop_ignores_cells_without_clicks() -> None:
    spec = {
        "impressions": [5000, 0],
        "clicks": [100, 0],
        "spend": [120.0, 0.0],
        "mature": [1.0, 0.1],
    }
    data = B.funnel_data({"ad_a": spec, "ad_b": spec}, dates=[B.D_START, B.D_END])
    c = B.comparison(expected_loss={"ad_a": 700, "ad_b": 5})
    assert stop_or_continue(c, _est(), data, B.economics(), RUN).action == "stop_test"


def test_bounded_shares() -> None:
    s = bounded_shares({"a": 0.98, "b": 0.01, "c": 0.01}, 0.1, 0.9)
    assert sum(s.values()) == pytest.approx(1.0)
    assert s["b"] == pytest.approx(0.1)
    assert s["a"] == pytest.approx(0.8)
    s = bounded_shares({"a": 0.5, "b": 0.5, "c": 0.0}, 0.1, 0.4)
    assert sum(s.values()) == pytest.approx(1.0)
    assert max(s.values()) <= 0.4 + 1e-12
    with pytest.raises(ValueError):
        bounded_shares({"a": 1.0}, 0.1, 0.9)


def test_allocation_reads_economics_and_relaxes_cap(tmp_path: Path) -> None:
    econ = B.economics(survival_floor=0)
    (tmp_path / "configs" / "economics").mkdir(parents=True)
    (tmp_path / "configs" / "economics" / f"{econ.economics_id}.json").write_text(
        econ.model_dump_json()
    )
    c = B.comparison(p_best={"ad_a": 0.5, "ad_b": 0.5}, expected_loss={"ad_a": 5, "ad_b": 5})
    c = c.model_copy(update={"value_q05": {"ad_a": B.money(-1), "ad_b": B.money(10)}})
    rec = allocate(c, RUN)
    assert rec.action == "allocate"
    assert rec.params["allocation"] == {"ad_a": 0.0, "ad_b": pytest.approx(1.0)}
    assert rec.decision_feasibility.status == "estimable"
    assert any("relaxed" in n for n in rec.params["notices"])
    none = c.model_copy(update={"value_q05": {"ad_a": B.money(-1), "ad_b": B.money(-1)}})
    assert allocate(none, RUN).action == "not_knowable"


def test_audit_keeps_evidence_and_sources_apart() -> None:
    rec = B.recommendation(run_id=RUN, recommendation_id="rec_p9unit01")
    run_record.append(rec)
    cases = (
        ("atmaos", "platform_attributed", 300.0),
        ("atmaos", "observed", 120.0),
        ("ground_truth", None, 150.0),
    )
    for src, ev, benefit in cases:
        realized = {"benefit": benefit, "regret": 10.0, "interval_90": [100, 200], "truth": 150}
        if ev:
            realized["evidence"] = ev
        run_record.append(
            C.OutcomeRecord(
                recommendation_id=rec.recommendation_id,
                source=src,
                realized=realized,
                recorded_at=B.T0,
            )
        )
    report = guarantee_report(B.D_START)
    assert set(report.by_source) == {
        "atmaos.platform_attributed",
        "atmaos.observed",
        "ground_truth",
    }
    assert report.by_source["atmaos.observed"]["mean_benefit_error"] == pytest.approx(-50.0)
    assert report.coverage_90["ground_truth"] == 1.0
    assert report.regret["ground_truth"] == 10.0
    assert guarantee_report(B.D_END.replace(year=2027)).n_recommendations == 0
