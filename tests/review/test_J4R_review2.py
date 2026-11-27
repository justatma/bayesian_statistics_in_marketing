"""Second blind review of J4R at 96e4ef4. Every test here is a finding: it fails on 96e4ef4, with a
one line docstring saying what it shows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.acceptance import j4_fixtures as X
from tests.acceptance.conftest import iso  # noqa: F401
from tests.acceptance.j4_fixtures import CLIENT, IMG2_ID, IMG3, IMG3_ID
from tests.acceptance.j4r_fixtures import J4REnv, cmp_run, fig_nb, fig_run, name_slot

from bayesian_marketing.notebook import release as nb_release

pytestmark = pytest.mark.piece("J4R")

A, B = name_slot(IMG3_ID), name_slot(IMG2_ID)
EID = "nbe_lead_client_0009"


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
    res = env.render(text)
    return repr(res["text"]) if res["ok"] else ""


def nb_one(
    env: J4REnv,
    q: dict[str, Any],
    statement: str = "A figure.",
    src: str = "account",
    method: str = "observed",
    **kw: Any,
) -> str:
    return env.release([X._entry(EID, "figure", statement, method, src, quantities=[q], **kw)])


def downgrade(env: J4REnv, rel: str) -> None:
    """Rewrite a release as bayes-notebook-1.0.0 (what an older writer produced), integrity kept."""
    folder = env.release_folder(rel)
    cat = json.loads((folder / "catalog.json").read_text())
    cat["schema"] = "bayes-notebook-1.0.0"
    (folder / "catalog.json").write_bytes(nb_release.canonical(cat) + b"\n")
    integ = json.loads((folder / "integrity.json").read_text())
    integ["files"]["catalog.json"] = nb_release.sha((folder / "catalog.json").read_bytes())
    integ["release_hash"] = nb_release.release_hash(integ["files"])
    (folder / "integrity.json").write_bytes(nb_release.canonical(integ) + b"\n")
    nb_release.verify(folder)


# ------------------------------------------------------------------ 1. words past the numeral rule


def _leak(env: J4REnv, text: str) -> None:
    assert refused(env.render(text)), leaked(env, text)


@pytest.mark.parametrize(
    "text",
    [
        "The Xii ads did well.",
        "Round Iv went well.",
        "We had Mmxxvi visits.",
        "Round xIi went well.",
    ],
    ids=["Xii", "Iv", "Mmxxvi", "xIi"],
)
def test_J4R_review2_roman_numeral_in_mixed_case_passes(env: J4REnv, run: str, text: str) -> None:
    """A Roman numeral in mixed case ("Xii") passes: the check needs all upper or all lower
    case, though A3 casefolds first."""
    _leak(env, text)


def test_J4R_review2_roman_numeral_split_by_full_stops_passes(env: J4REnv, run: str) -> None:
    """ "X.I.I" is read as three one-letter words, so a Roman numeral with stops passes."""
    _leak(env, "Round X.I.I went well.")


@pytest.mark.parametrize(
    "text", ["Sign-ups rose fiftypercent.", "Sign-ups rose tenpct.", "Sign-ups rose twopercent."]
)
def test_J4R_review2_number_word_glued_to_a_percent_word_passes(
    env: J4REnv, run: str, text: str
) -> None:
    """ "fiftypercent" is one token: the glue rule knows number words only, not percent words."""
    _leak(env, text)


@pytest.mark.parametrize(
    "text",
    [
        "Twodozen people came.",
        "Twothirds of people came.",
        "It was halfhalf.",
        "Threequarters came.",
    ],
)
def test_J4R_review2_listed_quantity_words_glued_together_pass(
    env: J4REnv, run: str, text: str
) -> None:
    """S25 (3) glues only the number words, so "twodozen", "twothirds" and "halfhalf" pass."""
    _leak(env, text)


@pytest.mark.parametrize(
    "text", ["Sign-ups rose by t.e.n.", "Sign-ups rose by f i v e.", "Sign-ups rose by o-n-e."]
)
def test_J4R_review2_number_spelled_letter_by_letter_passes(
    env: J4REnv, run: str, text: str
) -> None:
    """A number spelled one letter at a time with stops, spaces or hyphens passes."""
    _leak(env, text)


@pytest.mark.parametrize(
    "text",
    [
        "Sign-ups rose by séven.",
        "Sign-ups rose by twö.",
        "Sign-ups rose by tèn.",
        "Sign-ups rose by thrée.",
        "Sign-ups rose by nıne.",
    ],
)
def test_J4R_review2_number_word_with_an_accent_passes(env: J4REnv, run: str, text: str) -> None:
    """A number word with one Latin-1 accented letter ("séven") is not folded and passes."""
    _leak(env, text)


def test_J4R_review2_letters_standing_for_digits_pass(env: J4REnv, run: str) -> None:
    """ "lOO" (l, O, O in ASCII letters) reads as 100 and passes."""
    _leak(env, "Sign-ups rose by lOO.")


@pytest.mark.parametrize(
    "text",
    [
        "Sign-ups rose by fiftyish.",
        "We got zeroes.",
        "Twentysomething people came.",
        "The twentyfirst ad did well.",
        "It cost a tenner.",
        "It cost a fiver.",
    ],
)
def test_J4R_review2_suffixed_number_words_outside_the_lists_pass(
    env: J4REnv, run: str, text: str
) -> None:
    """Number words with a suffix the lists lack ("zeroes", "fiftyish", "fiver") pass."""
    _leak(env, text)


# ------------------------------------------------------------------ 2. names (S25 (9))


@pytest.mark.parametrize(
    "name",
    ["Save 50 dollars", "Top 10 ads", "Save50", "Ten2", "FiftyPercentOff", "Spring Xii", "IMG3 x2"],
    ids=[
        "save_50_dollars",
        "top_10",
        "save50",
        "ten2",
        "fifty_percent_off",
        "spring_Xii",
        "img3_x2",
    ],
)
def test_J4R_review2_name_that_states_a_figure_renders(env: J4REnv, run: str, name: str) -> None:
    """A display name that states a figure ("Save 50 dollars", "FiftyPercentOff", "Spring Xii")
    renders into the text: S25 (9) lets digits through and checks no glued or mixed-case form."""
    env.set_names(run, {IMG3_ID: name, IMG2_ID: "IMG2_TXT1"})
    res = env.render(f"{A} ran.")
    assert refused(res), repr(res["text"])


def test_J4R_review2_name_of_only_punctuation_renders_as_a_bare_possessive(
    env: J4REnv, run: str
) -> None:
    """An ad named "..." renders "'s click-through rate": a subject that is no subject."""
    env.set_names(run, {IMG3_ID: "...", IMG2_ID: "IMG2_TXT1"})
    qid = env.qid(run, IMG3_ID, "ctr")
    res = env.render(f"{fig_run(run, qid, 'start')}.")
    assert refused(res), repr(res["text"])


def test_J4R_review2_name_with_a_line_feed_renders_a_line_break_in_a_sentence(
    env: J4REnv, run: str
) -> None:
    """A name holding a line feed breaks the client's sentence in two lines, where the lint's
    splitter and the renderer disagree."""
    env.set_names(run, {IMG3_ID: "Spring\nSale", IMG2_ID: "IMG2_TXT1"})
    qid = env.qid(run, IMG3_ID, "ctr")
    res = env.render(f"{fig_run(run, qid, 'start')}.")
    assert refused(res) or "\n" not in res["text"], repr(res["text"])


def test_J4R_review2_unnamed_ad_puts_its_numeric_id_into_the_client_text(
    env: J4REnv, run: str
) -> None:
    """An ad with no display name renders as "ad 120253899504590526's ...": an 18-digit
    number, which the numeral rule would refuse in free text, reaches the client."""
    env.set_names(run, {IMG2_ID: "IMG2_TXT1"})
    qid = env.qid(run, IMG3_ID, "ctr")
    res = env.render(f"{fig_run(run, qid, 'start')}.")
    assert refused(res) or not any(c.isdigit() for c in res["text"].replace("4.4", "")), repr(
        res["text"]
    )


# ------------------------------------------------------------------ 3. rendering errors


def test_J4R_review2_p_best_as_a_ratio_unit_shows_certainty(env: J4REnv, run: str) -> None:
    """A notebook p_best of 0.9996 with unit "ratio" renders "100.0%", the certainty S25 (5)
    forbids for a probability."""
    rel = nb_one(env, {"name": "p_best", "value": 0.9996, "unit": "ratio"})
    res = env.render(f"{fig_nb(rel, EID, 'p_best')}.")
    assert res["ok"], res["reasons"]
    assert "100" not in res["text"], res["text"]


def test_J4R_review2_p_best_in_percent_unit_shows_certainty(env: J4REnv, run: str) -> None:
    """A notebook p_best of 99.96 with unit "percent" renders "100.0%"."""
    rel = nb_one(env, {"name": "p_best", "value": 99.96, "unit": "percent"})
    res = env.render(f"{fig_nb(rel, EID, 'p_best')}.")
    assert res["ok"], res["reasons"]
    assert "100" not in res["text"], res["text"]


def test_J4R_review2_negative_amount_that_rounds_to_zero_shows_minus_zero(
    env: J4REnv, run: str
) -> None:
    """An amount of -0.001 USD renders "-$0"."""
    rel = nb_one(env, {"name": "amount_spent", "value": -0.001, "unit": "USD"})
    res = env.render(f"{fig_nb(rel, EID, 'amount_spent')}.")
    assert res["ok"], res["reasons"]
    assert "-$0" not in res["text"], res["text"]


def test_J4R_review2_negative_ratio_that_rounds_to_zero_shows_minus_zero(
    env: J4REnv, run: str
) -> None:
    """A lift of -0.0004 (unit "ratio") renders "-0.0%"."""
    rel = nb_one(env, {"name": "lift", "value": -0.0004, "unit": "ratio"})
    res = env.render(f"{fig_nb(rel, EID, 'lift')}.")
    assert res["ok"], res["reasons"]
    assert "-0.0%" not in res["text"], res["text"]


@pytest.mark.parametrize("value", [0.4, 1.4, 1.5])
def test_J4R_review2_fractional_days_are_shown_as_a_different_whole_number(
    env: J4REnv, run: str, value: float
) -> None:
    """1.5 days renders "2 days", 1.4 "1 day" and 0.4 "0 days": the value is not the figure."""
    rel = nb_one(env, {"name": "run_length", "value": value, "unit": "days"})
    res = env.render(f"{fig_nb(rel, EID, 'run_length')}.")
    assert refused(res) or str(value) in res["text"], res["text"]


def test_J4R_review2_notebook_subject_at_campaign_level_is_named_by_an_ad_s_name(
    env: J4REnv, run: str
) -> None:
    """A subject {"level": "campaign", "id": <an ad's id>} renders the ad's name as if it were
    the campaign: the level is ignored when the id is in the names."""
    rel = nb_one(
        env,
        {
            "name": "lifetime_budget",
            "value": 1500,
            "unit": "USD",
            "subject": {"level": "campaign", "id": IMG3_ID},
        },
    )
    res = env.render(f"{fig_nb(rel, EID, 'lifetime_budget')}.")
    assert refused(res) or IMG3 not in res["text"], res["text"]


def test_J4R_review2_notebook_subject_id_not_in_names_renders_the_raw_id(
    env: J4REnv, run: str
) -> None:
    """A subject whose id has no name renders "ad 999888777's ...": a numeric id as the subject."""
    rel = nb_one(
        env,
        {
            "name": "cpa",
            "value": 12.0,
            "unit": "USD",
            "subject": {"level": "ad", "id": "999888777"},
        },
    )
    res = env.render(f"{fig_nb(rel, EID, 'cpa')}.")
    assert refused(res) or "999888777" not in res["text"], res["text"]


def test_J4R_review2_release_1_0_0_quantity_about_an_ad_renders_with_no_subject(
    env: J4REnv, run: str
) -> None:
    """A bayes-notebook-1.0.0 release cannot carry a subject; its p_best, cited to the ad, is
    rendered "The chance of being best is 62%." with no object, read as the account's."""
    entry = X._entry(
        EID,
        "finding",
        f"{IMG3} has a 0.621 chance of being the best ad.",
        "estimated",
        "run",
        context=["ad3"],
        quantities=[
            {
                "name": "p_best",
                "value": 0.621,
                "unit": "probability",
                "p05": 0.48,
                "p50": 0.621,
                "p95": 0.75,
                "level": 0.9,
            }
        ],
    )
    rel = env.release([entry])
    downgrade(env, rel)
    res = env.render(f"{fig_nb(rel, EID, 'p_best', 'start')}")
    assert refused(res) or IMG3 in res["text"], res["text"]


def test_J4R_review2_release_1_0_0_ad_cost_per_lead_renders_as_the_account_s(
    env: J4REnv, run: str
) -> None:
    """A 1.0.0 release's cost per lead, cited to one ad, renders "The cost per lead is $12.00."
    (no subject), where the same entry in 1.1.0 with a subject names the ad."""
    entry = X._entry(
        EID,
        "figure",
        f"{IMG3} cost per lead is 12.",
        "observed",
        "ad3",
        quantities=[{"name": "cpa", "value": 12.0, "unit": "USD"}],
    )
    rel = env.release([entry])
    downgrade(env, rel)
    res = env.render(f"{fig_nb(rel, EID, 'cpa', 'start')}")
    assert refused(res) or IMG3 in res["text"], res["text"]


# ------------------------------------------------------------------ 4. kind, clients, menu


def test_J4R_review2_run_probability_quantity_p_exceeds_shows_certainty(
    env: J4REnv, run: str
) -> None:
    """A run's p_exceeds (a probability, in RATE_NAMES) of 0.9996 renders "100.0%": S25 (5)'s
    guard is on the notebook probability unit only."""
    qid = env.set_quantity(run, IMG3_ID, "ctr", status="estimable", q50=0.9996, mean=0.9996)

    def rename(d: dict[str, Any]) -> None:
        for q in d["quantities"]:
            if q["quantity_id"] == qid:
                q["name"] = "p_exceeds"
                q["evidence_class"] = "platform_attributed"

    env._patch(run, rename)
    res = env.render(f"{fig_run(run, qid, 'start')}.")
    assert res["ok"], res["reasons"]
    assert "100" not in res["text"], res["text"]


def test_J4R_review2_kind_fallback_ignores_runs_that_say_lead_when_newest_run_has_no_kind(
    env: J4REnv,
) -> None:
    """S25 (8): newest run, then config, then "lead" if any run says lead. A newest run without
    a saved kind and a config that cannot be read give "purchase" (conversion_kind_of's silent
    default) and the notebook cpa reads "cost per order" although an older run says lead."""
    old = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    new = env.lead_run_at(X.START_NEW, X.WINDOW_NEW, started_at=X.STARTED_NEW)
    env.rewrite(new, lambda d: d.update(conversion_kind=None))
    assert env.snapshot(old).conversion_kind == "lead"
    entry = X._entry(
        EID,
        "figure",
        "Cost per lead is 12.",
        "observed",
        "account",
        quantities=[{"name": "cpa", "value": 12.0, "unit": "USD"}],
    )
    rel = env.release([entry])
    (env.config_root / f"{CLIENT}.yaml").write_text("not: [valid")
    res = env.render(f"{fig_nb(rel, EID, 'cpa')}.")
    low = (res["text"] or "").lower()
    assert refused(res) or ("order" not in low and "purchase" not in low), res["text"]


def test_J4R_review2_a_release_whose_catalog_names_another_client_than_its_id_renders(
    env: J4REnv, run: str
) -> None:
    """Another client's release (its id and folder say other_client), with its catalog edited
    to say lead_client and the integrity file recomputed, renders in the lead client's text:
    A1 and S25 (10) are not applied to the release id."""
    rel = env.other_release()
    folder = env.release_folder(rel, X.OTHER)
    cat = json.loads((folder / "catalog.json").read_text())
    cat["client_id"] = CLIENT
    (folder / "catalog.json").write_bytes(nb_release.canonical(cat) + b"\n")
    integ = json.loads((folder / "integrity.json").read_text())
    integ["files"]["catalog.json"] = nb_release.sha((folder / "catalog.json").read_bytes())
    integ["release_hash"] = nb_release.release_hash(integ["files"])
    (folder / "integrity.json").write_bytes(nb_release.canonical(integ) + b"\n")
    res = env.render(f"{fig_nb(rel, X.E_OTHER, 'account_spending_limit')}.")
    assert refused(res), repr(res["text"])


def test_J4R_review2_menu_and_render_differ_when_another_ads_name_collides_in_the_store(
    env: J4REnv, run: str
) -> None:
    """The menu reads the store (an ad of the run is unnamed), where the name of a second ad
    equals IMG3's, and drops both names; a render of the same slot alone does not read the
    store and keeps IMG3's. Same slot, two renderings."""
    env.set_names(run, {IMG3_ID: IMG3})
    env.store_names = {IMG2_ID: IMG3.lower()}
    qid = env.qid(run, IMG3_ID, "ctr")
    items = {i["token"]: i for i in env.menu()["slots"]}
    item = items["{fig:run/%s/%s}" % (run, qid)]
    res = env.render(fig_run(run, qid, "start"))
    assert res["ok"], res["reasons"]
    assert res["text"] == item["forms"]["start"], (res["text"], item["forms"]["start"])


def test_J4R_review2_same_slot_renders_differently_with_another_slot_beside_it(
    env: J4REnv, run: str
) -> None:
    """The ctr slot of IMG3 renders "IMG3_TXT1's ..." alone and "Ad 1202...'s ..." when a name
    slot of the other ad is in the text, because the names layers depend on what else is
    needed."""
    env.set_names(run, {IMG3_ID: IMG3})
    env.store_names = {IMG2_ID: IMG3.lower()}
    qid = env.qid(run, IMG3_ID, "ctr")
    alone = env.render(fig_run(run, qid, "start"))
    both = env.render(f"{fig_run(run, qid, 'start')} {B}")
    assert alone["ok"], alone["reasons"]
    assert IMG3 in alone["text"]
    assert both["slots"][0]["rendered"] == alone["slots"][0]["rendered"], both["slots"][0]


@pytest.mark.parametrize(
    "text",
    ["Sign-ups rose by nİne.", "Sign-ups rose by sİx.", "Sign-ups rose by fİve.", "FİFTY came."],
)
def test_J4R_review2_capital_dotted_i_splits_a_number_word(
    env: J4REnv, run: str, text: str
) -> None:
    """U+0130 is allowed, and casefolds to "i" plus U+0307; the combining mark is not a word
    character, so "nİne" is read as "ni" and "ne" and passes."""
    _leak(env, text)


# ------------------------------------------------------------------ 5. lint and A4 (not the guarantee)


@pytest.mark.parametrize(
    "text",
    [
        "{A} outshines {B}.",
        "{A} pulls away from {B}.",
        "{A} versus {B}.",
        "{A} brought the sign-ups.",
    ],
    ids=["outshines", "pulls_away", "versus", "brought"],
)
def test_J4R_review2_lint_misses_a_comparative_or_causal_phrase(
    env: J4REnv, run: str, text: str
) -> None:
    """A sentence naming two ads with "outshines", "pulls away from" or "versus", or crediting
    one ad with sign-ups ("brought"), is not linted."""
    _leak(env, text.replace("{A}", A).replace("{B}", B))


def test_J4R_review2_lint_misses_a_comparative_split_from_the_name_by_a_line_feed(
    env: J4REnv, run: str
) -> None:
    """The splitter breaks at a line feed, so "IMG3 did\\nbetter" is two sentences."""
    _leak(env, f"{A} did\nbetter than the others.")


def test_J4R_review2_lint_misses_a_comparative_beside_a_cmp_slot(env: J4REnv, run: str) -> None:
    """A cmp slot names the leader, but only name and fig slots count as naming an ad, so
    "far better than the others" beside it is not linted."""
    env.set_p_best(run, {IMG3_ID: 0.621, IMG2_ID: 0.379})
    text = f"{cmp_run(run)}, and it is far better than the others."
    _leak(env, text)


@pytest.mark.parametrize(
    "text",
    ["Nobody signed up.", "Neither ad got clicks.", "Not a click came from the ads."],
    ids=["nobody", "neither", "not_a"],
)
def test_J4R_review2_a4_misses_a_zero_stated_without_the_four_words(
    env: J4REnv, run: str, text: str
) -> None:
    """A4's list is no, none, all, every: "nobody", "neither" and "not a" state zero beside a
    measure and pass."""
    _leak(env, text)
