"""J5 unit checks beyond the frozen tests: the not-estimable reason and the CLI's not-knowable
line read the run's labels, a purchase call is unchanged, the lead purchase-word refusal names
the word for every purchase word, and the lead cost per sign-up is shown in cents while a purchase
cpa is not."""

from __future__ import annotations

import pytest
from tests.fakes import builders as B

from bayesian_marketing import cli, pipeline
from bayesian_marketing import core as C
from bayesian_marketing.claims import vocab as V
from bayesian_marketing.claims.check import check_narrative, display_value
from bayesian_marketing.core import NarrativeBlock

MISSING = {"A": {"cpa": "no conversions"}, "B": {"cpa": "no conversions"}}
VARIANTS = {"A": "ad_a", "B": "ad_b"}


def _cpa(ad: str, q50: float, name: str = "cpa") -> C.Quantity:
    q = B.quantity(name, ad, route="deterministic")
    summary = dict.fromkeys(("mean", "q05", "q50", "q95", "q025", "q975"), q50)
    return q.model_copy(update={"estimate": q.estimate.model_copy(update={"summary": summary})})


def _bundle(kind: str, q50: float = 3.35) -> C.ReportBundle:
    b = B.bundle(quantities=[_cpa("ad_a", q50)])
    return b.model_copy(update={"conversion_kind": kind})


def _g5(text: str, kind: str, q50: float = 3.35) -> C.GateResult:
    nb = NarrativeBlock(block_id="b1", text=text, author="atmaos")
    return check_narrative(nb, _bundle(kind, q50))


def test_not_estimable_reason_purchase_default_unchanged() -> None:
    default = pipeline.not_estimable_reason("cpa", VARIANTS, MISSING)
    assert default == pipeline.not_estimable_reason("cpa", VARIANTS, MISSING, "purchase")
    assert default.startswith("cost per order not estimable for ad_a, ad_b")


def test_not_estimable_reason_lead_says_sign_up() -> None:
    reason = pipeline.not_estimable_reason("cpa", VARIANTS, MISSING, "lead")
    assert reason.startswith("cost per sign-up not estimable for ad_a, ad_b")
    assert "order" not in reason


def _info(kind: str | None) -> dict:
    info: dict = {
        "compare_quantity": "cpa",
        "metric_quantity": "cvr",
        "variants": VARIANTS,
        "quantities": [],
    }
    if kind is not None:
        info["conversion_kind"] = kind
    return info


def test_cli_not_knowable_lead_labels(capsys: pytest.CaptureFixture[str]) -> None:
    cli.Narrator()._not_knowable(_info("lead"), "lead")
    out = capsys.readouterr().out
    assert "cost per sign-up for ad_a, ad_b" in out and "sign-up rate for ad_a, ad_b" in out
    assert "order" not in out


def test_cli_not_knowable_purchase_default(capsys: pytest.CaptureFixture[str]) -> None:
    cli.Narrator()._not_knowable(_info(None))
    out = capsys.readouterr().out
    assert "cost per order for ad_a, ad_b" in out and "conversion rate for ad_a, ad_b" in out


def test_display_value_purchase_is_fmt_value() -> None:
    q = _cpa("ad_a", 3.35)
    assert display_value(q, 3.35) == V.fmt_value(q, 3.35) == "3"
    assert display_value(q, 3.35, "purchase") == V.fmt_value(q, 3.35)


def test_display_value_lead_cpa_in_cents_other_money_unchanged() -> None:
    assert display_value(_cpa("ad_a", 3.35), 3.35, "lead") == "3.35"
    cpc = _cpa("ad_a", 1234.5, "cpc")
    assert display_value(cpc, 1234.5, "lead") == V.fmt_value(cpc, 1234.5)


@pytest.mark.parametrize("word", V.PURCHASE_WORDS)
def test_lead_refusal_names_each_purchase_word(word: str) -> None:
    g5 = _g5(f"Ad ad_a had a cost per sign-up of $3.35 across {word}.", "lead")
    assert g5.passed is False
    assert any(repr(word) in r and "converts on sign-ups" in r for r in g5.reasons), g5.reasons


def test_lead_cost_per_sign_up_in_cents_passes() -> None:
    g5 = _g5("Ad ad_a had a cost per sign-up of $3.35.", "lead")
    assert g5.passed is True, g5.reasons


def test_lead_purchase_word_without_a_figure_is_not_a_number_reason() -> None:
    """The refusal is for figures worded with a purchase word; a sentence with no figure is
    left to the other checks."""
    g5 = _g5("Ad ad_a took no orders.", "lead")
    assert not any("purchase word" in r for r in g5.reasons), g5.reasons


def test_purchase_run_purchase_word_is_not_refused() -> None:
    g5 = _g5("Ad ad_a had a cost per order of $3.", "purchase")
    assert g5.passed is True, g5.reasons
