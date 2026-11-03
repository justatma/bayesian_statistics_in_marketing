"""P10 unit tests: G5 edge cases, prior intake, render details."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.fakes import builders as B

from bayesian_marketing import core as C
from bayesian_marketing.claims.check import check_narrative, intake_prior_proposal
from bayesian_marketing.reporting.render import render


def _nb(text: str) -> C.NarrativeBlock:
    return C.NarrativeBlock(block_id="nb", text=text, author="atmaos")


def _bundle(**kw) -> C.ReportBundle:
    qa = B.quantity("cvr", "ad_a", estimate=B.beta_spec(8, 392), quantity_id="q_a")
    qb = B.quantity("cvr", "ad_b", estimate=B.beta_spec(18, 322), quantity_id="q_b")
    qc = B.quantity(
        "cvr",
        "ad_c",
        estimate=B.beta_spec(2, 50),
        feas=B.feasibility("below_floor", available=2, required=50),
        quantity_id="q_c",
    )
    comp = B.comparison(
        ("ad_a", "ad_b"),
        p_best={"ad_a": 0.04, "ad_b": 0.96},
        expected_loss={"ad_a": 120, "ad_b": 5},
    )
    base = dict(
        recommendations=[B.recommendation("allocate")],
        comparisons=[comp],
        know=B.knowability(not_knowable=["q_c"]),
    )
    base.update(kw)
    return B.bundle("internal", [qa, qb, qc], **base)


@pytest.mark.parametrize(
    "text",
    [
        "The conversion rate for ad_b is 5.3%.",
        "There is a 96.0% chance ad_b is best.",
        "Choosing ad_a risks an expected loss of $120.",
        "ad_a is worse than ad_b.",
        "The conversion rate for ad_c is not knowable yet. We have 2; we need about 50.",
        "ad_b had a higher conversion rate than ad_a.",
    ],
)
def test_clean_sentences_pass(text: str) -> None:
    res = check_narrative(_nb(text), _bundle())
    assert res.passed, res.reasons


@pytest.mark.parametrize(
    ("text", "token"),
    [
        ("The conversion rate for ad_a is 5.3%.", "5.3%"),  # ad_b's number on ad_a
        ("The conversion rate is 96.0%.", "96.0%"),  # a probability quoted as a rate
        ("Choosing ad_a risks an expected loss of $121.", "$121"),
        ("ad_b is worse than ad_a.", "ad_b"),
        ("ad_z is better than ad_a.", "ad_z"),
        ("ad_c's conversion rate looks weak.", "ad_c"),
        ("ad_b lifted orders.", "lifted"),
    ],
)
def test_bad_sentences_name_token(text: str, token: str) -> None:
    res = check_narrative(_nb(text), _bundle())
    assert not res.passed
    assert any(token in r for r in res.reasons), res.reasons


def test_comparative_needs_decision_basis() -> None:
    weak = _bundle(recommendations=[B.recommendation("hold", status="below_floor")])
    res = check_narrative(_nb("ad_b is better than ad_a."), weak)
    assert not res.passed and any("decision basis" in r for r in res.reasons)


def test_intake_prior_proposal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAYES_DATA_DIR", str(tmp_path))
    prop = {
        "client_id": "client_x",
        "parameter_path": "cvr",
        "family": "beta",
        "params": {"a": 2, "b": 60},
        "rationale": "similar stores convert near 3%",
        "author": "imani",
    }
    pid = intake_prior_proposal(prop)
    assert pid.startswith("pr_")
    rec = json.loads((tmp_path / "priors" / "records" / f"{pid}.json").read_text())
    assert rec["elicitation"]["source"] == "ai_proposal"
    assert rec["elicitation"]["approved_by"] is None
    with pytest.raises(ValueError):
        intake_prior_proposal({**prop, "approved_by": "imani"})
    with pytest.raises(ValueError):
        intake_prior_proposal({k: v for k, v in prop.items() if k != "client_id"})
    with pytest.raises(ValueError):
        intake_prior_proposal({**prop, "params": {"a": float("nan"), "b": 1}})


def test_render_escapes_and_hides_below_floor(tmp_path: Path) -> None:
    good = check_narrative(_nb("ad_b is better than ad_a."), _bundle())
    block = C.NarrativeBlock(block_id="nb", text="ad_b is better than ad_a.", author="x", gate=good)
    html = Path(render(_bundle(narrative=[block]), tmp_path).html_path).read_text()
    assert "ad_b is better than ad_a." in html
    assert "<script" not in html and "http" not in html.split("</head>")[1]
    assert "3.8%" not in html  # ad_c's mean, 2/52
    assert "We have 2; we need about 50." in html


def test_forged_g5_pass_is_not_rendered(tmp_path: Path) -> None:
    forged = C.NarrativeBlock(
        block_id="nb", text="ad_b caused 97.7% more orders.", author="x",
        gate=B.gate_result("G5", True),
    )  # fmt: skip
    html = Path(render(_bundle(narrative=[forged]), tmp_path).html_path).read_text()
    assert "97.7%" not in html


def test_g7_lists_missing_basis(tmp_path: Path) -> None:
    b = _bundle(recommendations=[B.recommendation("allocate", basis=["q_missing"])])
    with pytest.raises(C.GateFailure) as ei:
        render(b, tmp_path)
    assert ei.value.result.gate == "G7"
    assert any("q_missing" in r for r in ei.value.result.reasons)
