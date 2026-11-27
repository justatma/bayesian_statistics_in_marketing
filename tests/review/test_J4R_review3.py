"""Third blind review of J4R at 43c3dc5. Every test here is a finding: it fails on 43c3dc5, with a
one line docstring saying what it shows. Severity is in the name of the group, see the comments."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from tests.acceptance import j4_fixtures as X
from tests.acceptance.conftest import iso  # noqa: F401
from tests.acceptance.j4_fixtures import CLIENT, IMG2_ID, IMG3_ID
from tests.acceptance.j4r_fixtures import J4REnv, cmp_run, fig_nb, fig_run, name_slot

pytestmark = pytest.mark.piece("J4R")

A, B = name_slot(IMG3_ID), name_slot(IMG2_ID)
ACC = {"level": "account"}


@pytest.fixture
def env(iso, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> J4REnv:  # noqa: F811
    return J4REnv(tmp_path, monkeypatch)


@pytest.fixture
def run(env: J4REnv) -> str:
    return env.lead_run_at(X.START_OLD, X.WINDOW_OLD)


def refused(res: dict[str, Any]) -> bool:
    return res["ok"] is False and res["text"] is None


def leaked(env: J4REnv, text: str) -> str:
    res = env.render(text)
    return repr(res["text"]) if res["ok"] else ""


def nb_entry(i: int, name: str, value: Any, unit: str, subject: Any = ACC, **kw: Any) -> dict:
    q = {"name": name, "value": value, "unit": unit, "subject": subject}
    return X._entry(
        f"nbe_{CLIENT}_{i:04d}",
        "figure",
        "A figure.",
        kw.pop("method", "observed"),
        "account",
        quantities=[q],
        **kw,
    )


def nb_text(env: J4REnv, entry: dict) -> str:
    rel = env.release([entry])
    q = entry["quantities"][0]["name"]
    res = env.render(f"{fig_nb(rel, entry['entry_id'], q, 'start')}")
    assert res["ok"], res["reasons"]
    return res["text"]


ZERO_MONEY = re.compile(r"\$0(?!\.\d|[\d,])")


# ------------------------------------------------------------------ blocking: wrong figure in text


def test_J4R_review3_purchase_cost_per_order_of_43_cents_renders_as_zero_dollars(
    env: J4REnv, run: str
) -> None:
    """A purchase run's cost per order of 0.43 renders "$0" (money_decimals 0): a nonzero cost
    shown as free."""
    env.rewrite(run, lambda d: d.update(conversion_kind="purchase"))
    qid = env.set_quantity(run, IMG3_ID, "cpa", status="estimable", q50=0.43, mean=0.43)
    res = env.render(f"{fig_run(run, qid, 'start')}.")
    assert res["ok"], res["reasons"]
    assert not ZERO_MONEY.search(res["text"]), res["text"]


def test_J4R_review3_lead_contribution_per_click_of_35_cents_renders_as_zero_dollars(
    env: J4REnv, run: str
) -> None:
    """A lead run's contribution per click of 0.35 renders "$0": only cpa and cpc get cents."""
    qid = env.set_quantity(run, IMG3_ID, "ctr", status="estimable", q50=0.35, mean=0.35)

    def rename(d: dict[str, Any]) -> None:
        for q in d["quantities"]:
            if q["quantity_id"] == qid:
                q["name"] = "contribution_per_click"
                q["evidence_class"] = "platform_attributed"

    env._patch(run, rename)
    res = env.render(f"{fig_run(run, qid, 'start')}.")
    assert res["ok"], res["reasons"]
    assert not ZERO_MONEY.search(res["text"]), res["text"]


def test_J4R_review3_conversion_rate_of_four_hundredths_of_a_percent_renders_as_zero(
    env: J4REnv, run: str
) -> None:
    """A cvr of 0.0004 renders "0.0%": a nonzero rate shown as zero (S25 (5) guards probabilities
    only)."""
    qid = env.set_quantity(run, IMG3_ID, "cvr", status="estimable", q50=0.0004, mean=0.0004)
    res = env.render(f"{fig_run(run, qid, 'start')}.")
    assert res["ok"], res["reasons"]
    assert not re.search(r"(?<![\d.])0\.0%", res["text"]), res["text"]


def test_J4R_review3_notebook_cost_per_thousand_impressions_of_40_cents_renders_as_zero(
    env: J4REnv, run: str
) -> None:
    """An observed notebook cpm of 0.40 USD renders "$0"."""
    text = nb_text(env, nb_entry(1, "cpm", 0.4, "USD"))
    assert not ZERO_MONEY.search(text), text


def test_J4R_review3_notebook_ratio_of_four_thousandths_of_a_percent_renders_as_zero(
    env: J4REnv, run: str
) -> None:
    """An observed notebook ctr of 0.00004 (ratio) renders "0.0%"."""
    text = nb_text(env, nb_entry(1, "ctr", 0.00004, "ratio"))
    assert not re.search(r"(?<![\d.])0\.0%", text), text


# ------------------------------------------------------------------ major: wrong text from our code


@pytest.mark.parametrize("p", [0.8, 0.85], ids=["80", "85"])
def test_J4R_review3_cmp_says_a_before_a_figure_read_as_eighty_or_eleven(
    env: J4REnv, run: str, p: float
) -> None:
    """The cmp slot writes "with a 80% chance" (and 85): the article is fixed at "a"."""
    env.set_p_best(run, {IMG3_ID: p, IMG2_ID: round(1 - p, 2)})
    res = env.render(f"{cmp_run(run)}.")
    assert res["ok"], res["reasons"]
    assert not re.search(r"\ba 8\d%", res["text"]), res["text"]


def test_J4R_review3_cmp_keeps_a_trailing_full_stop_of_the_name_mid_sentence(
    env: J4REnv, run: str
) -> None:
    """The fixture's own name "IMG2_TXT1 - Updated." gives "Updated., which leads" and
    "Updated. leads" in cmp: fig slots strip the stop before "'s", cmp does not."""
    env.set_p_best(run, {IMG3_ID: 0.2, IMG2_ID: 0.8})
    for form in ("full", "start"):
        res = env.render(f"{cmp_run(run, form)}.")
        assert res["ok"], res["reasons"]
        assert "Updated.," not in res["text"] and "Updated. leads" not in res["text"], res["text"]


def test_J4R_review3_cmp_names_the_greater_id_as_leader_of_a_tie(env: J4REnv, run: str) -> None:
    """With p_best 0.5 and 0.5 the cmp slot says one ad "leads ... with a 50% chance of being
    best", picked by the greater id, and adds no caveat (the rule is p_best under 0.5)."""
    env.set_p_best(run, {IMG3_ID: 0.5, IMG2_ID: 0.5})
    res = env.render(f"{cmp_run(run)}.")
    assert refused(res) or "leads" not in res["text"] or "still a rough estimate" in res["text"], (
        res["text"]
    )


def test_J4R_review3_two_quantities_of_one_name_in_one_entry_share_one_menu_token(
    env: J4REnv, run: str
) -> None:
    """An entry with amount_spent for two ads lists the same token twice, and both render the
    first ad's figure: the second quantity cannot be addressed."""
    q = [
        {"name": "amount_spent", "value": 100, "unit": "USD", "subject": {"level": "ad", "id": i}}
        for i in (IMG3_ID, IMG2_ID)
    ]
    q[1]["value"] = 200
    e = X._entry(
        f"nbe_{CLIENT}_0001", "figure", "Spend by ad.", "observed", "account", quantities=q
    )
    env.release([e])
    toks = [i["token"] for i in env.menu()["slots"] if i["token"].startswith("{fig:nb")]
    assert len(toks) == len(set(toks)), toks


# ------------------------------------------------------------------ blocking: honest figures that pass


@pytest.mark.parametrize(
    "text",
    ["We could halve the spend.", "We're about halfway through the budget.", "Halfway there."],
    ids=["halve", "halfway_budget", "halfway"],
)
def test_J4R_review3_halve_and_halfway_pass_though_half_is_listed(
    env: J4REnv, run: str, text: str
) -> None:
    """"half", "halves" and "halved" are listed; "halve" and "halfway" are not and state half."""
    assert refused(env.render(text)), leaked(env, text)


@pytest.mark.parametrize(
    "text",
    ["Spend quadrupled.", "Clicks quadruple on weekends.", "Treble the clicks.", "Twin ads ran."],
    ids=["quadrupled", "quadruple", "treble", "twin"],
)
def test_J4R_review3_multiples_and_twin_pass_though_double_and_triple_are_listed(
    env: J4REnv, run: str, text: str
) -> None:
    """"double" and "triple" are listed; "quadrupled", "treble" and "twin" state 4, 3 and 2."""
    assert refused(env.render(text)), leaked(env, text)


@pytest.mark.parametrize(
    "text",
    ["Under a dollar per click.", "A buck per click.", "Pennies per click."],
    ids=["a_dollar", "a_buck", "pennies"],
)
def test_J4R_review3_a_money_amount_in_words_passes(env: J4REnv, run: str, text: str) -> None:
    """"a dollar" is an amount, and no list word or sign catches it ("ten dollars" fails only on
    "ten")."""
    assert refused(env.render(text)), leaked(env, text)


@pytest.mark.parametrize(
    "text",
    [
        "Nobody clicked.",
        "Neither ad converted.",
        "{A} did not get any clicks.",
        "{A} did not convert.",
    ],
    ids=["nobody_clicked", "neither_converted", "not_get_any_clicks", "did_not_convert"],
)
def test_J4R_review3_a4_misses_a_zero_stated_with_a_verb_or_a_gap(
    env: J4REnv, run: str, text: str
) -> None:
    """A4 matches the nouns ("clicks", "sign-ups") and "not any" only side by side: "clicked",
    "converted" and "did not get any clicks" state zero and pass."""
    t = text.replace("{A}", A)
    assert refused(env.render(t)), leaked(env, t)


@pytest.mark.parametrize(
    "text",
    ["{A} took the whole spend.", "The entire spend was on {A}.", "Everything went to {A}."],
    ids=["whole", "entire", "everything"],
)
def test_J4R_review3_a4_misses_the_whole_stated_as_whole_or_entire(
    env: J4REnv, run: str, text: str
) -> None:
    """A4 holds that "all" and "every" state the whole; "whole", "entire" and "everything" say
    the same beside "spend" and pass."""
    t = text.replace("{A}", A)
    assert refused(env.render(t)), leaked(env, t)


# ------------------------------------------------------------------ minor: honest text refused


def test_J4R_review3_a_best_ad_so_far_sentence_is_linted(env: J4REnv, run: str) -> None:
    """"Your best ad so far is {name:...}." fails the comparative lint on "best"."""
    res = env.render(f"Your best ad so far is {A}.")
    assert res["ok"], res["reasons"]


def test_J4R_review3_offering_help_with_an_ad_is_linted(env: J4REnv, run: str) -> None:
    """"I can help with {name:...} if you like." fails the causal lint on "help"."""
    res = env.render(f"I can help with {A} if you like.")
    assert res["ok"], res["reasons"]


@pytest.mark.parametrize(
    "text",
    [
        "Hi Sam,\r\nBoth ads ran this week.",
        "Hi Sam,\tboth ads ran.",
        "Both ads ran this week.",
        "Quick update: *both* ads are running.",
        "Both ads are running \U0001f44d",
        "Sign‑ups are being tracked.",
    ],
    ids=["crlf", "tab", "nbsp", "asterisk", "emoji", "nb_hyphen"],
)
def test_J4R_review3_ordinary_writing_with_a_pasted_character_is_refused(
    env: J4REnv, run: str, text: str
) -> None:
    """Honest sentences with a CRLF, tab, no-break space, asterisk, emoji or U+2011 are refused
    by the character allow list."""
    res = env.render(text)
    assert res["ok"], res["reasons"]


@pytest.mark.parametrize(
    "text",
    [
        "One moment while we look.",
        "Second, we should wait.",
        "Sign-ups matter most to you.",
        "A few words on what comes next.",
    ],
    ids=["one", "second", "most", "few"],
)
def test_J4R_review3_ordinary_sentences_with_a_listed_word_are_refused(
    env: J4REnv, run: str, text: str
) -> None:
    """Sentences with no figure in them fail on "one", "second", "most" and "few"."""
    res = env.render(text)
    assert res["ok"], res["reasons"]


@pytest.mark.parametrize(
    "name",
    ["Ad 2", "Spring | Video A", "[Prospecting] Spring", "Single Image Spring", "Spring \U0001f525"],
    ids=["ad_2", "pipe", "brackets", "single_image", "emoji"],
)
def test_J4R_review3_ordinary_ad_names_cannot_be_rendered(
    env: J4REnv, run: str, name: str
) -> None:
    """Meta-style names ("Ad 2", "A | B", "[x] y", "Single Image", an emoji) fail their name
    slot, and so every figure slot of that ad."""
    env.set_names(run, {IMG3_ID: name, IMG2_ID: "Other"})
    res = env.render(f"{A}.")
    assert res["ok"], res["reasons"]


# ------------------------------------------------------------------ minor: failure handling


@pytest.mark.parametrize("value", [1e30, 10**40], ids=["1e30", "10**40"])
def test_J4R_review3_a_notebook_value_beyond_decimal_precision_raises(
    env: J4REnv, run: str, value: Any
) -> None:
    """A value of 1e30 makes ``_fixed`` raise decimal.InvalidOperation out of render_client_text
    instead of failing the slot."""
    rel = env.release([nb_entry(1, "amount_spent", value, "USD")])
    res = env.render(fig_nb(rel, f"nbe_{CLIENT}_0001", "amount_spent"))
    assert refused(res), res


def test_J4R_review3_a_loaded_entry_with_a_non_list_quantities_raises(
    env: J4REnv, run: str
) -> None:
    """A release loader giving an entry whose quantities is 5 makes render_client_text raise
    TypeError instead of failing the slot."""
    rel = env.release()

    def load(rid: str) -> Any:
        return ({"client_id": CLIENT, "release_id": rid}, [{"entry_id": X.E_LIMIT, "quantities": 5}], [])

    res = env.render(fig_nb(rel, X.E_LIMIT, "account_spending_limit"), load_release=load)
    assert refused(res), res
