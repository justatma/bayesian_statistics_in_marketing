"""P10 review fixes round 2 (D31), from the reviewer's probes v6-v11."""

from __future__ import annotations

import pytest
from tests.acceptance.test_P10 import _rate_q
from tests.fakes import builders as B

from bayesian_marketing import core as C
from bayesian_marketing.claims.check import check_narrative


def _mk(design: str = "observational") -> C.ReportBundle:
    qa = _rate_q("ctr", "ad_a", 0.0213, "estimable", design=design)
    qb = _rate_q("cvr", "ad_b", 0.0413, "estimable", design=design)
    comp = B.comparison(("ad_a", "ad_b"), p_best={"ad_a": 0.1, "ad_b": 0.9})
    return B.bundle(
        "internal",
        [qa, qb],
        recommendations=[B.recommendation("allocate", status="estimable")],
        comparisons=[comp],
    )


def _money() -> C.ReportBundle:
    q = B.quantity("cpa", "ad_a")
    summ = {"mean": 9900.0, "sd": 300.0, "q05": 9000.0, "q50": 9900.0, "q95": 11000.0,
            "q025": 8900.0, "q975": 11100.0}  # fmt: skip
    q = q.model_copy(update={"estimate": q.estimate.model_copy(update={"summary": summ})})
    comp = B.comparison(("ad_a", "ad_b"), p_best={"ad_a": 0.1, "ad_b": 0.9})
    return B.bundle(
        "internal",
        [q, _rate_q("ctr", "ad_b", 0.0990, "estimable")],
        comparisons=[comp],
        recommendations=[B.recommendation("allocate")],
    )


def _ok(text: str, b: C.ReportBundle | None = None) -> C.GateResult:
    return check_narrative(C.NarrativeBlock(block_id="nb", text=text, author="a"), b or _mk())


PASSES = [
    # D31.1 hits without an option in their clause, and generic phrases
    "Results due to arrive next week.",
    "Please lift the freeze on reporting.",
    "We need more data before we can say more.",
    "The lower bound of the interval is useful.",
    "These numbers will be more reliable once more data arrives.",
    "Thanks to the team for reading.",
    "It will lead to a decision.",
    "The conversion rate for ad_b is 4.1%, higher than we expected.",
    "ad_b is the better option.",
    # D31.2 negation frames
    "We did not find that ad_b drove orders.",
    "There is no evidence that ad_b caused orders.",
    "This is an observational result and does not show that ad_b caused orders.",
    # D31.3 direction from the clause subject
    "Compared with ad_a, ad_b has the higher conversion rate.",
    "ad_a has a lower conversion rate than ad_b.",
    "ad_a trails ad_b.",
    "ad_b leads ad_a.",
    # D31.4 allocation shares and bundle counts
    "We recommend moving 70% of spend to ad_b and 30% to ad_a.",
    "The reversible change moves 70% of the budget.",
    "Between 2026-10-19 and 2026-11-01 we looked at 2 ads over 14 days.",
    "The expected benefit over the next 1,000 clicks is $170, and the expected loss is $5.",
]


@pytest.mark.parametrize("text", PASSES)
def test_round2_passes(text: str) -> None:
    res = _ok(text)
    assert res.passed, res.reasons


FAILS = [
    # D31.1 options in scope still count; regex-like lexicon entry
    ("Thanks to ad_b, orders rose.", "Thanks to"),
    ("Orders are due to ad_b.", "due to"),
    ("ad_b made orders go up.", "made orders go up"),
    ("ad_b's effect on orders is large.", "effect on"),
    ("ad_b helped orders.", "helped"),
    # D31.2 bare negation does not negate
    ("There is no doubt that ad_b caused orders.", "caused"),
    ("We did not find any issues, and ad_b caused orders.", "caused"),
    ("Not only did ad_b cause orders, it lifted revenue.", "cause"),
    ("ad_b did not fail; it caused orders.", "caused"),
    ("Without a doubt ad_b caused orders.", "caused"),
    # D31.3 and lexicon widening
    ("ad_a leads ad_b.", "ad_a"),
    ("ad_a wins.", "ad_a"),
    ("ad_a is leading.", "ad_a"),
    ("ad_a is ahead.", "ad_a"),
    ("ad_a is superior.", "ad_a"),
    ("ad_a is the top ad.", "ad_a"),
    ("ad_a won.", "ad_a"),
    ("ad_a is better than ad_b, though not by much.", "ad_a"),
    ("Compared with ad_b, ad_a has the higher conversion rate.", "ad_a"),
    ("ad_b is ahead of ad_c.", "ad_c"),
    # D31.5 abbreviations and unreadable numbers fail closed
    ("The click-through rate for ad_a is 5 bp.", "5 bp"),
    ("The click-through rate for ad_a is 5 percentage points.", "5 percentage points"),
    ("The click-through rate for ad_a is 2.1 pp.", "2.1 pp"),
    ("We spent 1.5M on ad_a.", "1.5M"),
    ("There were 1e3 clicks for ad_a.", "1e3"),
    ("The click-through rate for ad_a is 2\uff0e1%.", "1%"),
    ("We ran 3 ads.", "3"),
]


@pytest.mark.parametrize(("text", "token"), FAILS)
def test_round2_fails(text: str, token: str) -> None:
    res = _ok(text)
    assert not res.passed, text
    assert any(token in r for r in res.reasons), res.reasons


@pytest.mark.parametrize(
    "text",
    [
        "The cost per order for ad_a is $9.9k.",
        "The cost per order for ad_a is 9.9 thousand dollars.",
        "The click-through rate for ad_b is 9.9pct.",
        "The click-through rate for ad_b is 990bps.",
    ],
)
def test_abbreviations_rejected_even_when_exact(text: str) -> None:
    assert not _ok(text, _money()).passed


def test_full_figure_passes() -> None:
    assert _ok("The cost per order for ad_a is $9,900.", _money()).passed


def test_causal_scoped_and_randomized() -> None:
    assert _ok("ad_b drove orders.", _mk("randomized")).passed
    assert not _ok("ad_b drove orders.").passed
