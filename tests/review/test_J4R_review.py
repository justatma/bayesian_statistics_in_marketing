"""Blind review of J4R (rendered figure slots) at bf0d935. Every test here is a finding: it fails
on bf0d935, with a one line docstring saying what it shows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from bayesian_marketing.claims import slots as S
from tests.acceptance import j4_fixtures as X
from tests.acceptance.conftest import iso  # noqa: F401
from tests.acceptance.j4_fixtures import CLIENT, E_BUDGET, E_LIMIT, IMG2_ID, IMG2_NAME, IMG3_ID
from tests.acceptance.j4r_fixtures import J4REnv, cmp_run, fig_nb, fig_run, name_slot

pytestmark = pytest.mark.piece("J4R")

A, B = name_slot(IMG3_ID), name_slot(IMG2_ID)


@pytest.fixture
def env(iso, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> J4REnv:  # noqa: F811
    return J4REnv(tmp_path, monkeypatch)


@pytest.fixture
def run(env: J4REnv) -> str:
    run_id = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    env.ctr_44(run_id)
    return run_id


def refused(res: dict[str, Any]) -> bool:
    return res["ok"] is False and res["text"] is None


def leaked(env: J4REnv, text: str) -> str:
    """What the numeral rule lets through: the rendered text if the call is ok, else ''."""
    res = env.render(text)
    return repr(res["text"]) if res["ok"] else ""


# ------------------------------------------------------------------ 1. figures past the numeral rule

INVISIBLE_SPLITS = [
    ("U+034F combining grapheme joiner", "͏"),
    ("U+FE0F variation selector", "️"),
    ("U+3164 hangul filler", "ㅤ"),
    ("U+2800 braille blank", "⠀"),
    ("U+0007 control", "\x07"),
    ("U+E000 private use", ""),
]


@pytest.mark.parametrize("label,ch", INVISIBLE_SPLITS, ids=[x[0] for x in INVISIBLE_SPLITS])
def test_J4R_review_invisible_non_Cf_char_splits_a_quantity_word(
    env: J4REnv, run: str, label: str, ch: str
) -> None:
    """"ten" with an invisible non-Cf character inside is not a word break the rule can see."""
    res = env.render(f"Sign-ups rose by t{ch}en.")
    assert refused(res), f"ok text {res['text']!r}"


@pytest.mark.parametrize(
    "text",
    [
        "ᴏɴᴇ ad did well.",  # small-cap letters spelling "one"
        "оne ad did well.",  # Cyrillic o + "ne"
        "tеn ads did well.",  # Cyrillic e inside "ten"
        "οne ad did well.",  # Greek omicron + "ne"
    ],
    ids=["smallcaps", "cyrillic_o", "cyrillic_e", "greek_omicron"],
)
def test_J4R_review_homoglyph_spelling_of_a_number_passes(env: J4REnv, run: str, text: str) -> None:
    """Letters that look like "one" or "ten" but are not Latin pass the numeral rule."""
    assert refused(env.render(text)), leaked(env, text)


@pytest.mark.parametrize(
    "text",
    ["The IV ads did well.", "XII people signed up.", "We had MMXXVI visits.", "Round vii went well."],
)
def test_J4R_review_roman_numeral_in_latin_letters_passes(
    env: J4REnv, run: str, text: str
) -> None:
    """Roman numerals written with ASCII letters carry a figure and pass the numeral rule."""
    # S26 (3) sets this differently: the plain-letter Roman numeral check is dropped, and
    # Unicode numeral glyphs (Nl) are refused by the character allow list instead.
    res = env.render(text)
    assert res["ok"] is True, res["reasons"]


@pytest.mark.parametrize(
    "text",
    [
        "A trillion people saw it.",
        "Sign-ups reached a gazillion.",
        "Sign-ups rose by 5‱‱.".replace("5", "x").replace("‱‱", "‱"),
    ],
    ids=["trillion", "gazillion", "per_ten_thousand_sign"],
)
def test_J4R_review_magnitude_and_rate_forms_outside_the_lists_pass(
    env: J4REnv, run: str, text: str
) -> None:
    """Magnitude words and rate signs the lists omit (trillion, gazillion, U+2031) pass."""
    assert refused(env.render(text)), leaked(env, text)


@pytest.mark.parametrize(
    "text",
    [
        "We got nought from the first ad.",
        "It happened once.",
        "A dual test ran.",
        "A trio of ads ran.",
        "A duo of ads ran.",
        "She ran a pair.",
        "The second ad stood out.",
        "The first ad stood out.",
    ],
    ids=["nought_first", "once", "dual", "trio", "duo", "a_pair", "second", "first"],
)
def test_J4R_review_unlisted_count_words_pass(env: J4REnv, run: str, text: str) -> None:
    """Count, ordinal and multiplicity words outside QUANTITY_WORDS (nil, once, dual, trio, first)."""
    assert refused(env.render(text)), leaked(env, text)


@pytest.mark.parametrize(
    "text",
    [
        "Deux ads did well.",
        "Zwei ads did well.",
        "Dos ads did well.",
        "三 ads did well.",
        "A lakh of people saw it.",
        "A crore of people saw it.",
        "Fiftyfive ads did well.",
        "Twentyone people signed up.",
        "\U0001f51f ads did well.",
        "⚂ ads did well.",
    ],
    ids=[
        "deux", "zwei", "dos", "han_three", "lakh", "crore", "fiftyfive", "twentyone",
        "keycap_ten", "die_three",
    ],
)
def test_J4R_review_foreign_or_glued_or_emoji_number_passes(
    env: J4REnv, run: str, text: str
) -> None:
    """A number in another language, run together, or as an emoji (U+1F51F, U+2682) passes."""
    assert refused(env.render(text)), leaked(env, text)


def test_J4R_review_zero_width_space_glues_two_words_into_a_phrase_miss(
    env: J4REnv, run: str
) -> None:
    """"two" glued by a ZWSP to the next word is one token after Cf stripping and passes."""
    assert refused(env.render("two​ads did well.")), leaked(env, "two​ads did well.")




def test_J4R_review_lone_surrogate_in_text_is_returned_ok(
    env: J4REnv, run: str
) -> None:
    """A lone surrogate in the template comes back as ok True text that cannot be encoded."""
    res = env.render("Hello \ud800 there.")
    assert refused(res), repr(res["text"])


# ------------------------------------------------------------------ 2. wrong or misleading figures


def test_J4R_review_half_up_rounding_of_a_rate(env: J4REnv, run: str) -> None:
    """A ctr of exactly 1.25% renders 1.2% (half even); half up gives 1.3%."""
    qid = env.set_quantity(run, IMG3_ID, "ctr", status="estimable", q50=0.0125, mean=0.0125)
    res = env.render(f"{fig_run(run, qid, 'start')}.")
    assert res["ok"], res["reasons"]
    assert "1.3%" in res["text"], res["text"]


def test_J4R_review_half_up_rounding_of_money(env: J4REnv, run: str) -> None:
    """A cost per sign-up of exactly 0.125 renders 0.12 (half even); half up gives 0.13."""
    qid = env.set_quantity(run, IMG3_ID, "cpa", status="estimable", q50=0.125, mean=0.125)
    res = env.render(f"{fig_run(run, qid, 'start')}.")
    assert res["ok"], res["reasons"]
    assert "0.13" in res["text"], res["text"]


def test_J4R_review_p_best_near_one_is_shown_as_certainty(env: J4REnv, run: str) -> None:
    """A leader with p_best 0.9996 renders "a 100% chance of being best": a claim of certainty."""
    env.set_p_best(run, {IMG3_ID: 0.9996, IMG2_ID: 0.0004})
    res = env.render(f"{cmp_run(run)}.")
    assert res["ok"], res["reasons"]
    assert "100%" not in res["text"], res["text"]


def test_J4R_review_p_best_near_zero_is_shown_as_impossible(env: J4REnv, run: str) -> None:
    """A notebook probability of 0.0004 renders "0%", a claim of impossibility."""
    entry = X._entry(
        "nbe_lead_client_0009", "finding", f"{X.IMG3} has a tiny chance of being best.",
        "estimated", "run", context=["ad3"],
        quantities=[{"name": "p_best", "value": 0.0004, "unit": "probability",
                     "p05": 0.0, "p50": 0.0004, "p95": 0.001, "level": 0.9}],
    )
    rel = env.release([entry])
    res = env.render(f"{fig_nb(rel, 'nbe_lead_client_0009', 'p_best')}.")
    # S26 (4) (R11, R12) sets this differently: the quantity states no subject, so the slot
    # fails rather than rendering. The account is a subject that is stated, never a default.
    assert refused(res), repr(res["text"])
    assert any(S.R_NO_SUBJECT in r for r in res["reasons"]), res["reasons"]



def test_J4R_review_notebook_percent_unit_value_already_in_percent(env: J4REnv, run: str) -> None:
    """A quantity of 4.4 in unit "percent" renders as 440.0%."""
    entry = X._entry(
        "nbe_lead_client_0009", "figure", "The account click-through rate is 4.4 percent.",
        "observed", "account",
        quantities=[{"name": "ctr", "value": 4.4, "unit": "percent"}],
    )
    rel = env.release([entry])
    res = env.render(f"{fig_nb(rel, 'nbe_lead_client_0009', 'ctr')}.")
    # S26 (4) (R11, R12) sets this differently: the quantity states no subject, so the slot
    # fails rather than rendering. The account is a subject that is stated, never a default.
    assert refused(res), repr(res["text"])
    assert any(S.R_NO_SUBJECT in r for r in res["reasons"]), res["reasons"]



@pytest.mark.parametrize("unit", ["$", "dollars", ""], ids=["dollar_sign", "dollars", "no_unit"])
def test_J4R_review_notebook_money_with_a_non_iso_unit_has_no_currency(
    env: J4REnv, run: str, unit: str
) -> None:
    """An observed amount whose unit is "$" or "dollars" renders as a bare number, no currency."""
    entry = X._entry(
        "nbe_lead_client_0009", "figure", "The amount spent to date is $750.",
        "observed", "account", quantities=[{"name": "amount_spent", "value": 750, "unit": unit}],
    )
    rel = env.release([entry])
    res = env.render(f"{fig_nb(rel, 'nbe_lead_client_0009', 'amount_spent')}.")
    # S25 (6) sets this differently: a unit outside the closed set fails the slot, it is not
    # rendered as dollars. The finding (no bare number goes out) still holds.
    assert refused(res), repr(res["text"])
    assert any(S.R_UNIT in r for r in res["reasons"]), res["reasons"]


def test_J4R_review_notebook_unit_of_three_letters_is_read_as_a_currency(
    env: J4REnv, run: str
) -> None:
    """A quantity in unit "day" renders as "14 DAY": any three letters are taken as an ISO code."""
    entry = X._entry(
        "nbe_lead_client_0009", "figure", "The campaign runs for 14 days.", "observed", "account",
        quantities=[{"name": "run_length", "value": 14, "unit": "day"}],
    )
    rel = env.release([entry])
    res = env.render(f"{fig_nb(rel, 'nbe_lead_client_0009', 'run_length')}.")
    # S25 (6) sets this differently: "days" is in the closed set and "day" is not, so the slot
    # fails rather than rendering. The finding (no "14 DAY") still holds.
    assert refused(res), repr(res["text"])
    assert any(S.R_UNIT in r for r in res["reasons"]), res["reasons"]


def test_J4R_review_notebook_campaign_budget_is_called_the_accounts(env: J4REnv, run: str) -> None:
    """The lifetime budget comes from a campaign source and renders as "the account's"."""
    rel = env.release()
    res = env.render(f"We set {fig_nb(rel, E_BUDGET, 'lifetime_budget')}.")
    # S26 (4) (R11, R12) sets this differently: the quantity states no subject, so the slot
    # fails rather than rendering. The account is a subject that is stated, never a default.
    assert refused(res), repr(res["text"])
    assert any(S.R_NO_SUBJECT in r for r in res["reasons"]), res["reasons"]



def test_J4R_review_notebook_subject_is_the_first_ad_the_statement_mentions(
    env: J4REnv, run: str
) -> None:
    """A statement about the account that mentions IMG2 in passing gives IMG2's spending limit."""
    entry = X._entry(
        "nbe_lead_client_0009", "constraint",
        f"Unlike {IMG2_NAME}, the account spending limit is $1,500.", "observed", "account",
        quantities=[{"name": "account_spending_limit", "value": 1500, "unit": "USD"}],
    )
    rel = env.release([entry])
    res = env.render(f"{fig_nb(rel, 'nbe_lead_client_0009', 'account_spending_limit')}.")
    # S26 (4) (R11, R12) sets this differently: the quantity states no subject, so the slot
    # fails rather than rendering. The account is a subject that is stated, never a default.
    assert refused(res), repr(res["text"])
    assert any(S.R_NO_SUBJECT in r for r in res["reasons"]), res["reasons"]



def test_J4R_review_notebook_label_is_purchase_wording_when_config_is_unreadable(
    env: J4REnv, run: str
) -> None:
    """With the client's config unreadable, a notebook cpa on a lead account says "per purchase"."""
    entry = X._entry(
        "nbe_lead_client_0009", "figure", f"{X.IMG3} cost per lead is 12.", "observed", "ad3",
        quantities=[{"name": "cpa", "value": 12.0, "unit": "USD"}],
    )
    rel = env.release([entry])
    (env.config_root / f"{CLIENT}.yaml").write_text("not: [valid")
    res = env.render(f"{fig_nb(rel, 'nbe_lead_client_0009', 'cpa')}.")
    # S26 (4) (R11, R12) sets this differently: the quantity states no subject, so the slot
    # fails rather than rendering. The account is a subject that is stated, never a default.
    assert refused(res), repr(res["text"])
    assert any(S.R_NO_SUBJECT in r for r in res["reasons"]), res["reasons"]



def test_J4R_review_name_slot_with_braces_in_the_display_name_reaches_the_text(
    env: J4REnv, run: str
) -> None:
    """An ad named "x {date:2026-01-01}" renders braces into the text AtmaOS renders next."""
    env.set_names(run, {IMG3_ID: "Promo {date:2026-01-01}", IMG2_ID: IMG2_NAME})
    res = env.render(f"{A} ran.")
    assert refused(res), repr(res["text"])


def test_J4R_review_name_slot_with_a_figure_in_the_display_name_reaches_the_text(
    env: J4REnv, run: str
) -> None:
    """An ad named "Save 50% today, one day only" puts a percent and a word into the text."""
    env.set_names(run, {IMG3_ID: "Save 50% today, one day only", IMG2_ID: IMG2_NAME})
    res = env.render(f"{A} ran.")
    assert refused(res), repr(res["text"])


# ------------------------------------------------------------------ 3 and 4. clients, failures






# ------------------------------------------------------------------ 5. grammar and lint


def test_J4R_review_comparative_after_an_abbreviation_is_not_linted(env: J4REnv, run: str) -> None:
    """A comparative split from its ad's name by "e.g." is in another "sentence" and passes."""
    res = env.render(f"{A} (e.g. on clicks) is better.")
    assert refused(res), repr(res["text"])


def test_J4R_review_forged_newest_run_head_marks_the_clients_real_newest_run_stale(
    env: J4REnv,
) -> None:
    """A newer run file with head client lead_client and body client other_client makes the
    client's real newest run render "as of 7 November" as if it were stale."""
    import json

    old = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    new = env.lead_run_at(X.START_NEW, X.WINDOW_NEW, started_at=X.STARTED_NEW)
    path = env.snapshot_file(new)
    body = json.loads(path.read_text())
    body["client_id"] = X.OTHER
    path.write_text('{"client_id": "' + CLIENT + '", ' + json.dumps(body)[1:])
    qid = env.qid(old, IMG3_ID, "ctr")
    res = env.render(f"{fig_run(old, qid)}.")
    assert res["ok"], res["reasons"]
    assert "as of" not in res["text"], res["text"]  # old is the client's own newest run
