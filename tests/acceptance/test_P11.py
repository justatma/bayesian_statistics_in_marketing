"""P11 pipeline, socket, smoke (spec v0.3 §9.4, §11, §13.2, G6, G8).

# CONTRACT ASSUMPTION: test datasets come from the simulator (P2): generate(...) into a tmp dir,
#   and dataset_uri is "file://" + the path of the DatasetManifest JSON it wrote. The manifest's
#   economics_id resolves to approved ClientEconomics with a loss tolerance by a mechanism P11
#   owns (see manifest open question); the window passed is the min and max export date.
# CONTRACT ASSUMPTION: priors={} means "framework defaults" and passes G8; a prior id that is
#   unknown or unapproved makes compare raise core.GateFailure with gate "G8".
# CONTRACT ASSUMPTION: BayesianResult.posterior is keyed by variant and each entry has
#   "quantity_id"; uncertainty has at least "currency", "run_id" and "recommendation_ids".
# CONTRACT ASSUMPTION: observation_evidence keys are the snake_case G3.4 names in
#   tests/fakes/atmaos_base.G3_4_KEYS; evidence["result"] equals the result passed in.
# CONTRACT ASSUMPTION: recommendations(run_id) returns dicts with "recommendation_id",
#   "requires_human_approval" and the rendered guarantee under "guarantee_text"; every run
#   produces at least one recommendation (not_knowable counts).
# CONTRACT ASSUMPTION: record_approval raises core.GateFailure("G6") for an empty decided_by, an
#   unknown recommendation id or a decision other than approved/rejected; an accepted approval is
#   readable with run_record.read("ApprovalRecord", recommendation_id=...).
# CONTRACT ASSUMPTION: replay writes OutcomeRecord(source="ground_truth") rows readable with
#   run_record.read("OutcomeRecord", source="ground_truth") and returns an AuditReport with
#   by_source["ground_truth"], regret and coverage_90 filled.
"""

from __future__ import annotations

import datetime as dt
import importlib.metadata
from pathlib import Path
from typing import Any

import pytest

from bayesian_marketing import __version__
from bayesian_marketing import core as C
from bayesian_marketing.atmaos import socket as sock
from bayesian_marketing.decision import run_record
from bayesian_marketing.simulate.generate import generate
from bayesian_marketing.simulate.replay import replay
from tests.fakes.atmaos_base import G3_4_KEYS, BayesianResult
from tests.fakes.exports import read_table

pytestmark = pytest.mark.piece("P11")

REPO = Path(__file__).resolve().parents[2]
SCEN = REPO / "data" / "scenarios"
SCENARIOS = [
    "north_pier_day2",
    "north_pier_day14",
    "tiny_campaign",
    "negative_dependence",
    "delivery_mix_shift",
    "attribution_window_change",
    "lag_heavy",
    "fractional_conversions",
    "switching_cost_hold",
    "many_accounts",
]


def _dataset(name: str, out: Path, seed: int = 1) -> tuple[str, C.DatasetManifest, tuple]:
    generate(SCEN / f"{name}.yaml", seed, out)
    found = []
    for p in out.glob("*.json"):
        if p.name == "ground_truth.json":
            continue
        try:
            found.append((p, C.DatasetManifest.model_validate_json(p.read_text())))
        except ValueError:
            continue
    assert len(found) == 1
    path, m = found[0]
    dates = []
    for f in m.files:
        if f.platform in ("meta", "google_ads", "linkedin", "ga4"):
            rows = read_table(out / f.path, f.platform)
            dates += [dt.date.fromisoformat(r["date"][:10]) for r in rows]
    return f"file://{path}", m, (min(dates), max(dates))


def _compare(uri: str, m: C.DatasetManifest, window: tuple, metric: str = "contribution",
             priors: dict | None = None) -> dict[str, Any]:  # fmt: skip
    return sock.compare(
        uri,
        metric=metric,
        variants=sorted(m.entity_map),
        priors=priors or {},
        window={
            "start": window[0].isoformat(),
            "end": window[1].isoformat(),
            "horizon": {"unit": "clicks", "amount": 1000},
        },
        segments={},
    )


def test_P11_result_fits_BayesianResult(tmp_path: Path) -> None:
    uri, m, window = _dataset("north_pier_day14", tmp_path)
    for metric in ("cvr", "contribution"):
        res = _compare(uri, m, window, metric)
        br = BayesianResult.model_validate(res)
        variants = sorted(m.entity_map)
        assert sorted(br.posterior) == variants
        for v in variants:
            assert br.posterior[v]["quantity_id"].startswith("q_")
        assert sorted(br.probability_best) == variants
        assert sum(br.probability_best.values()) == pytest.approx(1.0, abs=1e-6)
        assert sorted(br.expected_loss) == variants
        assert all(isinstance(x, float) for x in br.expected_loss.values())
        assert br.uncertainty["run_id"].startswith("run_")
        assert isinstance(br.uncertainty["recommendation_ids"], list)
        assert br.uncertainty["currency"] == "USD" or len(br.uncertainty["currency"]) == 3
        assert __version__ in br.tool_version
        assert br.config_hash
        rr = run_record.read("RunRecord", run_id=br.uncertainty["run_id"])
        assert len(rr) == 1 and rr[0].config_hash == br.config_hash


def test_P11_evidence_matches_G3_4(tmp_path: Path) -> None:
    uri, m, window = _dataset("north_pier_day14", tmp_path)
    res = _compare(uri, m, window, "cvr")
    ev = sock.observation_evidence(res, "tr_0001")
    assert set(ev) == G3_4_KEYS
    assert ev["tool_result_id"] == "tr_0001"
    assert ev["result"] == res
    assert ev["metric"] == "cvr"
    assert ev["uncertainty"] == res["uncertainty"]
    assert ev["dataset_snapshot_hash"]
    assert ev["tool_version"] == res["tool_version"]


def test_P11_record_approval_G6(tmp_path: Path) -> None:
    uri, m, window = _dataset("north_pier_day14", tmp_path)
    res = _compare(uri, m, window)
    recs = sock.recommendations(res["uncertainty"]["run_id"])
    assert recs, "every run proposes at least one recommendation"
    for r in recs:
        assert r["requires_human_approval"] is True
        assert r["guarantee_text"] and "{" not in r["guarantee_text"]
    rid = recs[0]["recommendation_id"]
    when = "2026-11-03T10:00:00+00:00"
    for bad in (
        dict(recommendation_id=rid, approval_ref="apr_1", decision="approved", decided_by="",
             decided_at=when),
        dict(recommendation_id="rec_nothere", approval_ref="apr_1", decision="approved",
             decided_by="Atma", decided_at=when),
        dict(recommendation_id=rid, approval_ref="apr_1", decision="maybe", decided_by="Atma",
             decided_at=when),
    ):  # fmt: skip
        with pytest.raises(C.GateFailure) as ei:
            sock.record_approval(**bad)
        assert ei.value.result.gate == "G6"
    assert run_record.read("ApprovalRecord", recommendation_id=rid) == []
    sock.record_approval(rid, "apr_1", "approved", "Atma", when)
    got = run_record.read("ApprovalRecord", recommendation_id=rid)
    assert len(got) == 1 and got[0].decided_by == "Atma" and got[0].decision == "approved"


def test_P11_extra_unapproved_prior_fails_G8(tmp_path: Path) -> None:
    uri, m, window = _dataset("north_pier_day14", tmp_path)
    with pytest.raises(C.GateFailure) as ei:
        _compare(uri, m, window, "cvr", priors={"cvr": "pr_deadbeef"})
    assert ei.value.result.gate == "G8"


@pytest.mark.parametrize("name", SCENARIOS)
def test_P11_smoke_every_scenario(name: str, tmp_path: Path) -> None:
    uri, m, window = _dataset(name, tmp_path)
    res = _compare(uri, m, window)
    br = BayesianResult.model_validate(res)
    assert sorted(br.posterior) == sorted(m.entity_map)
    for v in br.posterior.values():
        assert v.get("synthetic", True) is not False or m.synthetic is False


def test_P11_shadow_replay_writes_scores(tmp_path: Path) -> None:
    _, _, (start, end) = _dataset("north_pier_day14", tmp_path / "probe")
    report = replay(SCEN / "north_pier_day14.yaml", 1, start, end)
    assert isinstance(report, C.AuditReport)
    assert "ground_truth" in report.by_source
    assert report.regret and report.coverage_90
    outcomes = run_record.read("OutcomeRecord", source="ground_truth")
    assert outcomes and all(o.source == "ground_truth" for o in outcomes)
    assert importlib.metadata.version("bayesian-marketing")
