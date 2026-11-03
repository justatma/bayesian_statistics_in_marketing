"""P10 review fixes (D29): number tokens, causal stems and negation, comparative lexicon,
no fallback, allowed bundle facts, case-insensitive ids, probability rounding, report labels.

Bundles follow the reviewer's probes (scratchpad p10/probe*.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.acceptance.test_P10 import _rate_q
from tests.fakes import builders as B

from bayesian_marketing import core as C
from bayesian_marketing.claims.check import check_narrative
from bayesian_marketing.reporting.render import render


def _mk(design: str = "observational") -> C.ReportBundle:
    qa = _rate_q("ctr", "ad_a", 0.0213, "estimable", design=design)
    qb = _rate_q("cvr", "ad_b", 0.0413, "estimable", design=design)
    qm = _rate_q("cvr", "ad_m", 0.0317, "marginal", design=design)
    qc = _rate_q("cvr", "ad_c", 0.0777, "below_floor", design=design)
    comp = B.comparison(("ad_a", "ad_b"), p_best={"ad_a": 0.1, "ad_b": 0.9})
    return B.bundle(
        "internal",
        [qa, qb, qm, qc],
        recommendations=[B.recommendation("allocate", status="estimable")],
        comparisons=[comp],
        know=B.knowability(not_knowable=[qc.quantity_id]),
    )


def _money_bundle() -> C.ReportBundle:
    q = B.quantity("cpa", "ad_a")
    summ = {"mean": 1234.4, "sd": 50.0, "q05": 1100.0, "q50": 1230.0, "q95": 1400.0,
            "q025": 1090.0, "q975": 1410.0}  # fmt: skip
    q = q.model_copy(update={"estimate": q.estimate.model_copy(update={"summary": summ})})
    qa = _rate_q("ctr", "ad_b", 0.0213, "estimable")
    comp = B.comparison(("ad_a", "ad_b"), p_best={"ad_a": 0.1, "ad_b": 0.9})
    return B.bundle(
        "internal", [q, qa], comparisons=[comp], recommendations=[B.recommendation("allocate")]
    )


def _check(text: str, bundle: C.ReportBundle) -> C.GateResult:
    return check_narrative(C.NarrativeBlock(block_id="nb", text=text, author="atmaos"), bundle)


PASSES = [
    "The click-through rate for ad_a is 2.1%.",
    "The click-through rate for ad_a is 2.1 %.",
    "The click-through rate for ad_a is 2.1 percent.",
    "The click-through rate for ad_a is 2.1 per cent.",
    "The click-through rate for ad_a is 2.1%, with a 90% range of 2.0% to 2.3%.",
    "Ad_B is better than ad_a.",
    "AD_B is better than AD_A.",
    "ad_b is the winner.",
    "ad_b has a 90% chance of being best.",
    "ad_b has a 0.90 chance of being best.",
    "We did not find that ad_b drove orders.",
    "Nothing here shows that ad_b caused anything.",
    "The data cover 2026-10-19 to 2026-11-01, run run_00000001, 14 days and 4 ads.",
    "The conversion rate for ad_m is 3.2%, but this estimate is still rough.",
    "The conversion rate for ad_c is not knowable yet.",
]


@pytest.mark.parametrize("text", PASSES)
def test_passes(text: str) -> None:
    res = _check(text, _mk())
    assert res.passed, res.reasons


FAILS = [
    # D29.1 suffixed and spelled-out numbers
    ("The click-through rate for ad_a is two percent.", "two percent"),
    ("The click-through rate for ad_a is 2%.", "2%"),
    ("The click-through rate for ad_a is 9.9pct.", "9.9pct"),
    ("The click-through rate for ad_a is 99bps.", "99bps"),
    ("The conversion rate for ad_c is seven point eight percent.", "seven point eight percent"),
    ("The click-through rate for ad_a is nine point nine percent.", "nine point nine percent"),
    # D29.2 causal stems, phrases, case
    ("ad_b causes orders.", "causes"),
    ("ad_b is causing orders.", "causing"),
    ("ad_b drives orders.", "drives"),
    ("ad_b generates orders.", "generates"),
    ("ad_b lifts orders.", "lifts"),
    ("ad_b CAUSES orders.", "CAUSES"),
    ("ad_b led to more orders.", "led to"),
    ("ad_b resulted in more orders.", "resulted in"),
    ("ad_a might have lifted orders.", "lifted"),
    # D29.3 comparatives and superlatives
    ("ad_a is the winner.", "ad_a"),
    ("ad_c is the winner.", "ad_c"),
    ("ad_a has the higher click-through rate.", "ad_a"),
    ("ad_a is ahead of ad_b.", "ad_a"),
    ("ad_a is the winner over ad_b.", "ad_a"),
    ("The ads are better than expected.", "better"),
    # D29.4 no fallback
    ("The click-through rate is 4.1%.", "4.1%"),
    ("ad_a is 4.1%.", "4.1%"),
    ("ad_a cvr is 4.1%.", "4.1%"),
    ("Overall performance rose 2.1%.", "2.1%"),
    # D29.5 facts that are not the bundle's
    ("The campaign ran on 2026-11-03.", "2026-11-03"),
    ("We tested 50 variants.", "50"),
    ("Run run_00000002 is done.", "run_00000002"),
    ("The click-through rate for ad_a is 2.1% (95% interval).", "95%"),
    # item 8: probability rounding
    ("ad_b has a 91% chance of being best.", "91%"),
    # marginal caveat in another sentence
    ("The conversion rate for ad_m is 3.2%. This estimate is still rough.", "3.2%"),
]


@pytest.mark.parametrize(("text", "token"), FAILS)
def test_fails_naming_token(text: str, token: str) -> None:
    res = _check(text, _mk())
    assert not res.passed, text
    assert any(token in r for r in res.reasons), res.reasons


@pytest.mark.parametrize(
    "text",
    ["ad_b drove orders.", "ad_b caused more orders than ad_a.", "ad_b boosted orders."],
)
def test_causal_passes_when_randomized(text: str) -> None:
    res = _check(text, _mk("randomized"))
    assert res.passed, res.reasons


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("The cost per order for ad_a is $1,234.", True),
        ("The cost per order for ad_a is 1,234 USD.", True),
        ("The cost per order for ad_a is $9.9k.", False),
        ("The cost per order for ad_a is $1.2k.", False),
        ("The cost per order for ad_a is 5K.", False),
        ("The cost per order for ad_a is $1,234.40.", False),
    ],
)
def test_money_tokens(text: str, ok: bool) -> None:
    res = _check(text, _money_bundle())
    assert res.passed is ok, res.reasons
    if not ok:
        token = text.split(" is ")[1].rstrip(".")
        assert any(token in r for r in res.reasons), res.reasons


def test_report_labels_evidence_on_comparisons_and_recommendations(tmp_path: Path) -> None:
    b = _mk()
    html = Path(render(b, tmp_path).html_path).read_text()
    plain = "what the ad platform counted as delivered"
    caption = html.split('<h2 id="h-comp">')[1].split("</caption>")[0]
    assert plain in caption
    rec = html.split('<article class="rec">')[1].split("</article>")[0]
    assert "What this counts" in rec and plain in rec
    assert "90% range" in html
