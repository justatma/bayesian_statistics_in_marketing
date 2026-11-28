"""Blind review L8 probes, ported (ruling B24): F1 the U7 notice on the no-cost reallocate path,
F2 a count recommendation's money shown in cents; plus the review's claims probe."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any

import pytest
from tests.acceptance.test_L8 import NOT_APPLIED_TEXT, TOL, count_comparison
from tests.fakes import builders as B

from bayesian_marketing import core as C
from bayesian_marketing.claims.check import check_narrative
from bayesian_marketing.cli import main as cli_main
from bayesian_marketing.decision import reallocation
from bayesian_marketing.decision.reallocation import fmt_money
from bayesian_marketing.reporting.render import render

WINDOW = (dt.date(2026, 11, 1), dt.date(2026, 11, 7))


def _realloc(cost: Any, el: dict[str, str] | None = None) -> C.Recommendation:
    c = count_comparison(
        "clicks",
        cost=cost,
        options=("inc", "cand"),
        ev={"inc": "10", "cand": "30"},
        el=el or {"inc": "20", "cand": "0.5"},
    )
    econ = B.economics(loss_tolerance=TOL, survival_floor=1500)
    decision = B.feasibility("estimable", "decision_loss", available=1.0, target=TOL)
    scope = C.Scope(level="ad", ids={"options": "inc,cand"}, window=WINDOW, platform="meta")
    return reallocation.reallocate(c, decision, econ, "run_00000001", scope=scope)


def test_f1_u7_notice_once_per_recommendation_when_floor_set_even_without_a_cost() -> None:
    notice = NOT_APPLIED_TEXT.format(unit="clicks")
    priced = _realloc("2")
    assert priced.params["notices"].count(notice) == 1
    unpriced = _realloc(None)
    assert unpriced.action == "not_knowable"
    assert unpriced.params["notices"].count(notice) == 1
    assert unpriced.guarantee.assumptions.count(notice) == 1


def test_f2_fmt_money_itself_is_unchanged_for_contribution() -> None:
    """The review's probe asked fmt_money not to show 0.31 as "0 USD"; B24 keeps fmt_money (and
    every contribution text) as it is and shows cents only for count recommendations."""
    assert fmt_money(B.money("0.31")) == "0 USD"


def test_f2_cli_ctr_demo_shows_the_loss_and_tolerance_in_cents(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli_main(["demo", "--metric", "ctr", "--out", str(tmp_path / "demo")])
    text = capsys.readouterr().out
    assert code == 0, text
    loss = next(line for line in text.splitlines() if line.startswith("Expected loss:"))
    assert re.search(r"Expected loss:\s+[\d,]+\.\d\d USD over", loss), loss
    assert re.search(r"the [\d,]+\.\d\d USD tolerance", loss), loss
    assert not re.search(r"\s0 USD", loss), loss


def test_f2_render_count_recommendation_in_cents(tmp_path: Path) -> None:
    rec = _realloc("0.62", el={"inc": "20", "cand": "0.5"})  # loss 0.5 x 0.62 = 0.31 USD
    assert rec.action == "reallocate"
    comp = count_comparison(
        "clicks",
        cost="0.62",
        options=("inc", "cand"),
        ev={"inc": "10", "cand": "30"},
        el={"inc": "20", "cand": "0.5"},
    )
    b = B.bundle("internal", recommendations=[rec], comparisons=[comp])
    html = Path(render(b, tmp_path).html_path).read_text()
    article = html.split('<article class="rec">')[1].split("</article>")[0]
    assert "0.31 USD" in article and "150.00 USD" in article
    assert not re.search(r"[^\d.,]0 USD", article), article


def test_f2_contribution_recommendation_keeps_whole_units(tmp_path: Path) -> None:
    rec = B.recommendation("allocate")  # expected_benefit 170 USD, expected_loss 5 USD
    b = B.bundle("internal", recommendations=[rec], comparisons=[B.comparison()])
    html = Path(render(b, tmp_path).html_path).read_text()
    article = html.split('<article class="rec">')[1].split("</article>")[0]
    assert "5 USD" in article and "5.00 USD" not in article


@pytest.mark.parametrize(
    ("cost", "said"),
    [("1234.5678", "$1,234.57"), ("0.6189", "$0.62"), ("12.345", "$12.35"), ("0.004", "$0.00")],
)
def test_claims_accept_the_cost_as_shown(cost: str, said: str) -> None:
    comp = count_comparison(
        "orders", cost=cost, ev={"ad_a": "12.5", "ad_b": "14.25"}, el={"ad_a": "2", "ad_b": "0"}
    )
    b = B.bundle("internal", comparisons=[comp])
    blk = C.NarrativeBlock(block_id="nb", text=f"We priced each order at {said}.", author="x")
    r = check_narrative(blk, b)
    assert r.passed, r.reasons
