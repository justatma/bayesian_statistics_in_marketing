"""P10 round-2 verification fix: allocation shares and probabilities bound to their option;
lexicon additions at 97c6ccb."""

from __future__ import annotations

import pytest
from tests.acceptance.test_P10 import _rate_q
from tests.fakes import builders as B

from bayesian_marketing import core as C
from bayesian_marketing.claims.check import check_narrative


def _mk() -> C.ReportBundle:
    # allocation in the fake recommendation: ad_b 0.7, ad_a 0.3
    qa = _rate_q("ctr", "ad_a", 0.0213, "estimable")
    qb = _rate_q("cvr", "ad_b", 0.0413, "estimable")
    comp = B.comparison(("ad_a", "ad_b"), p_best={"ad_a": 0.1, "ad_b": 0.9})
    return B.bundle(
        "internal",
        [qa, qb],
        recommendations=[B.recommendation("allocate", status="estimable")],
        comparisons=[comp],
    )


def _ok(text: str) -> C.GateResult:
    return check_narrative(C.NarrativeBlock(block_id="nb", text=text, author="a"), _mk())


@pytest.mark.parametrize(
    "text",
    [
        "ad_b gets 70% of the budget.",
        "ad_a gets 30% of the budget.",
        "Allocation: ad_b 70%, ad_a 30%.",
        "Put 70% on ad_b.",
        "We recommend moving 70% of spend to ad_b and 30% to ad_a.",
        "The reversible change moves 70% of the budget.",
        "ad_b has a 90% chance of being best.",
        "There is a 90% chance ad_b is best.",
        "ad_b has a 0.90 chance of being best.",
        "ad_b came out on top.",
    ],
)
def test_bound_passes(text: str) -> None:
    res = _ok(text)
    assert res.passed, res.reasons


@pytest.mark.parametrize(
    ("text", "token"),
    [
        ("ad_a gets 70% of the budget.", "70%"),
        ("Allocation: ad_b 30%, ad_a 70%.", "30%"),
        ("Put 30% on ad_b.", "30%"),
        ("ad_a has a 90% chance of being best.", "90%"),
        ("ad_a has a 0.90 chance of being best.", "0.90"),
        ("ad_b pushed orders up.", "pushed orders up"),
        ("ad_b gets us orders.", "gets us"),
        ("ad_b brings in orders.", "brings in"),
        ("ad_a came out on top.", "ad_a"),
        ("ad_a is number one.", "ad_a"),
        ("ad_a came out ahead.", "ad_a"),
    ],
)
def test_bound_fails(text: str, token: str) -> None:
    res = _ok(text)
    assert not res.passed, text
    assert any(token in r for r in res.reasons), res.reasons
