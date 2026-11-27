# ruff: noqa: RUF001  (the S25 cases are about exactly these characters)
"""J4R unit checks beyond the frozen set: the word forms past the floor, ISO codes in upper case
only, the slot grammar's parts, strict dates, release ids with underscores in the client, the
names precedence and the two-id rule (S16), the refresh's entity names, a slot of another client
rendering nothing, and the lint naming the word it refused."""

from __future__ import annotations

import datetime as dt
import inspect
from pathlib import Path

import pytest
from tests.acceptance import j4_fixtures as X
from tests.acceptance import j4r_fixtures as _j4r
from tests.acceptance.conftest import iso  # noqa: F401  (the isolated store, autouse)
from tests.acceptance.j4_fixtures import CLIENT, IMG2_ID, IMG2_NAME, IMG3, IMG3_ID
from tests.acceptance.j4r_fixtures import J4REnv, fig_run, name_slot

from bayesian_marketing import core as C
from bayesian_marketing import pipeline
from bayesian_marketing.claims import _refs as R
from bayesian_marketing.claims import slots as S
from bayesian_marketing.live import refresh as live_refresh
from bayesian_marketing.live.contracts import LiveRow

# ------------------------------------------------------------------ pure


def test_word_forms_reach_past_the_floor_and_spare_the_allowed_words() -> None:
    forms = S.quantity_word_forms()
    assert {"fifths", "twentieths", "halved", "doubling", "hundredfold"} <= forms
    assert not set(S.ALLOWED_WORDS) & forms
    assert not {"none", "no", "both", "each"} & forms


@pytest.mark.parametrize(
    ("text", "hit"),
    [
        ("ALL ads are live.", "ALL"),
        ("Paid in USD.", "USD"),
        ("A few basis points.", "basis point"),
        ("Up some percentages.", "percentages"),
        ("The second fifths.", "fifths"),
    ],
)
def test_word_hits(text: str, hit: str) -> None:
    assert hit in S._word_hits(text)


@pytest.mark.parametrize("text", ["all ads try the top cup.", "Usd is not a code here.", "I did"])
def test_no_hits(text: str) -> None:
    assert S._numeral_reasons(text) == []


# ------------------------------------------------------------------ S25 (1) to (12), pure


@pytest.mark.parametrize(
    "ch",
    ["\u00d7", "\u00f7", "\u0180", "\u0430", "#", "+", "=", "{", "@", "\u2028", "\x07",
     "\U0001f44d", "|", "[", "\u00a8"],
)  # fmt: skip
def test_S25_1_characters_outside_the_set_fail_by_code_point(ch: str) -> None:
    reasons = S._numeral_reasons(f"a{ch}b")
    assert any(S.R_CHARACTER in r and f"U+{ord(ch):04X}" in r for r in reasons), reasons


def test_S25_1_the_allowed_set() -> None:
    text = "AbÀſ .,;:!?'\"()-/& ’‘“”–—…\n"
    assert all(c in S.ALLOWED_CHARACTERS for c in text)
    assert S._numeral_reasons("Café — “good”, isn’t it…") == []


@pytest.mark.parametrize(
    "word", ["I", "ID", "DM", "CC", "mix", "did", "civil", "vivid", "IV", "Xii", "X.I.I"]
)
def test_S26_3_plain_letter_roman_numerals_pass(word: str) -> None:
    """S26 (3): the plain-letter Roman numeral check is dropped."""
    assert S._numeral_reasons(f"See {word} here.") == []


@pytest.mark.parametrize("glyph", ["Ⅳ", "Ⅻ", "ⅰ", "ⅻ"])
def test_S26_3_roman_numeral_glyphs_still_fail(glyph: str) -> None:
    assert any(S.R_CHARACTER in r for r in S._numeral_reasons(f"See {glyph} here."))


@pytest.mark.parametrize("token", ["fiftyfive", "twentyone", "onehundred", "tenten"])
def test_S25_3_glued_number_words_fail(token: str) -> None:
    assert token in S._word_hits(f"We saw {token}.")


@pytest.mark.parametrize("word", ["someone", "often", "tone", "nonetheless", "fourteen"])
def test_S25_3_words_holding_number_words_are_not_glued(word: str) -> None:
    assert not S._glued(word)


@pytest.mark.parametrize(
    "word",
    [
        "nil",
        "once",
        "dual",
        "pairs",
        "first",
        "second",
        "millionth",
        "umpteen",
        "lakh",
        "crore",
        "trillions",
        "dos",
        "zwei",
        "fünf",
        "quattro",
        "dezoito",
        "vingt",
        "cent",
    ],
)
def test_S25_4_the_list_gains(word: str) -> None:
    assert word in S.quantity_word_forms()
    assert S._word_hits(f"We saw {word}.")


@pytest.mark.parametrize("word", ["due", "seize", "elf", "un", "une", "una", "sept"])
def test_S25_4_collisions_stay_out(word: str) -> None:
    assert word not in S.quantity_word_forms()


@pytest.mark.parametrize(
    ("fn", "x", "want"),
    [
        (S._fmt_percent, 0.0125, "1.3%"),
        (S._fmt_percent, 0.0005, "0.1%"),
        (S._fmt_count, 2.5, "3"),
        (S._fmt_probability, 0.625, "63%"),
        (S._fmt_probability, 0.9951, "more than 99%"),
        (S._fmt_probability, 1.0, "more than 99%"),
        (S._fmt_probability, 0.0049, "less than 1%"),
        (S._fmt_probability, 0.0, "less than 1%"),
        (S._fmt_probability, 0.005, "1%"),
    ],
)
def test_S25_5_half_up(fn: object, x: float, want: str) -> None:
    assert fn(x) == want  # type: ignore[operator]


def test_S25_5_money_half_up() -> None:
    assert S._fixed(0.125, 2) == "0.13"
    assert S._fixed(1500.5, 0) == "1,501"


@pytest.mark.parametrize(
    ("unit", "value", "want"),
    [
        ("USD", 1500, "$1,500"),
        ("usd", 1500, "$1,500"),
        ("EUR", 20, "\u20ac20.00"),
        ("CHF", 20, "20.00 CHF"),
        ("EUR", 2000, "\u20ac2,000"),
        ("count", 12.5, "13"),
        ("ratio", 0.044, "4.4%"),
        ("probability", 0.62, "62%"),
        ("percent", 4.4, "4.4%"),
        ("days", 14, "14 days"),
        ("days", 1, "1 day"),
    ],
)
def test_S25_6_closed_units_render(unit: str, value: float, want: str) -> None:
    assert S._nb_value({"name": "x", "value": value, "unit": unit}, "purchase") == want


@pytest.mark.parametrize("unit", ["day", "$", "dollars", "", "pct", "share", "DAY", "Percent"])
def test_S25_6_other_units_fail(unit: str) -> None:
    with pytest.raises(S._Fail, match=S.R_UNIT):
        S._nb_value({"name": "x", "value": 1, "unit": unit}, "purchase")


def test_S25_6_lead_cost_per_in_cents() -> None:
    assert S._nb_value({"name": "cpa", "value": 12, "unit": "USD"}, "lead") == "$12.00"
    assert S._nb_value({"name": "cpa", "value": 12, "unit": "USD"}, "purchase") == "$12.00"


@pytest.mark.parametrize(
    ("subject", "want"),
    [
        ({"level": "account"}, ("account", None)),
        ({"level": "campaign", "id": "c1"}, ("campaign", "c1")),
        ({"level": "ad", "id": "a1"}, ("ad", "a1")),
    ],
)
def test_S25_7_subject_from_the_quantity(subject: object, want: object) -> None:
    assert S._nb_subject({"name": "x", "value": 1, "unit": "count", "subject": subject}) == want


def test_S26_4_no_subject_fails() -> None:
    """S26 (4), R11, R12: the account default is withdrawn."""
    with pytest.raises(S._Fail, match=S.R_NO_SUBJECT):
        S._nb_subject({"name": "x", "value": 1, "unit": "count"})


@pytest.mark.parametrize(
    "subject", [{"level": "country", "id": "x"}, {"level": "ad"}, "ad", {"level": "ad", "id": 5}]
)
def test_S25_7_malformed_subject_fails(subject: object) -> None:
    with pytest.raises(S._Fail):
        S._nb_subject({"name": "x", "value": 1, "unit": "count", "subject": subject})


@pytest.mark.parametrize(
    "name",
    ["Promo {date:2026-01-01}", "Save 50% today", "Price $5", "Ad\u200bTwo", "USD promo"],
)
def test_S25_9_name_stating_a_figure(name: str) -> None:
    assert S.R_NAME_FIGURE in (S._name_states_a_figure(name) or "")


@pytest.mark.parametrize("name", ["IMG3_TXT1", "IMG2_TXT1 – Updated.", "Café promo"])
def test_S25_9_plain_names_pass(name: str) -> None:
    assert S._name_states_a_figure(name) is None


def test_S25_10_head_and_body_naming_two_clients(tmp_path: Path) -> None:
    good = tmp_path / "run_a.json"
    good.write_text('{"client_id": "c1", "run_id": "run_a"}')
    forged = tmp_path / "run_b.json"
    forged.write_text('{"client_id": "c1", "client_id": "c2", "run_id": "run_b"}')
    assert R.client_of_run_file(good) == "c1"
    assert R.client_of_run_file(forged) is None
    assert R.client_of_run_file(tmp_path / "missing.json") is None


@pytest.mark.parametrize(
    ("text", "n"),
    [
        ("A e.g. b. C.", 2),
        ("A i.e. b vs. c etc. d. E.", 2),
        ("A. B.", 2),
    ],
)
def test_S25_11_no_split_after_abbreviations(text: str, n: int) -> None:
    assert len([x for x in S._sentences(text) if x.strip()]) == n


def test_R28_a_line_feed_keeps_the_sentence_and_adds_its_lines() -> None:
    got = S._sentences("A did\nbetter. C.")
    assert "A did\nbetter." in got and "A did" in got and "better." in got


@pytest.mark.parametrize("cf", ["​", "‍", "­", "⁠", "﻿"])
def test_S25_12_cf_is_refused_and_cannot_glue(cf: str) -> None:
    reasons = S._numeral_reasons(f"two{cf}ads")
    assert any(S.R_CHARACTER in r for r in reasons), reasons
    assert "two" in S._word_hits(f"two{cf}ads")


def test_parse_slot_parts() -> None:
    s = S._parse_slot("{fig:run/run_ab/q_cd#clm_1|start}", 0, 0)
    assert (s.kind, s.run_id, s.quantity_id, s.claim_id, s.form) == (
        "fig",
        "run_ab",
        "q_cd",
        "clm_1",
        "start",
    )
    assert s.ref == "run/run_ab/q_cd"
    nb = S._parse_slot("{fig:nb/nb_a_b_20261120_2/nbe_a_b_0001/lifetime_budget}", 0, 0)
    assert (nb.release_id, nb.entry_id, nb.quantity_name, nb.form) == (
        "nb_a_b_20261120_2",
        "nbe_a_b_0001",
        "lifetime_budget",
        "full",
    )
    assert S._parse_slot("{cmp:run/run_ab/q_cd}", 0, 0).kind is None
    assert S._parse_slot("{date:2026-11-26|full}", 0, 0).reasons


@pytest.mark.parametrize(
    ("value", "ok"),
    [
        ("2026-11-26", True),
        ("2026-11-26T15:00", True),
        ("2026-11-26T15:00:00.5Z", True),
        ("2026-11-26T15:00:00+05:30", True),
        ("2026-11-26 15:00", False),
        ("20261126", False),
        ("2026-11-26T15", False),
        ("2026-02-29", False),
    ],
)
def test_strict_iso(value: str, ok: bool) -> None:
    assert S._strict_iso(value) is ok


def test_release_id_client_with_underscores() -> None:
    assert R.client_of_release_id("nb_lead_client_20261120_12") == "lead_client"
    assert R.release_key("nb_lead_client_20261120_12") == (20261120, 12)
    assert R.client_of_release_id("not_a_release") is None


def test_merge_names_precedence_and_two_ids() -> None:
    merged = R.merge_names([{"1": "Alpha"}, {"1": "Beta", "2": "Gamma"}, {"3": "gamma"}])
    assert merged == {"1": "Alpha", "2": "Gamma"}  # the lower layer's "gamma" is dropped
    same_layer = R.merge_names([{"1": "Alpha", "2": "alpha"}, {"1": "Alpha"}])
    assert same_layer == {}  # a layer giving one name to two ids names neither


def test_refresh_entity_names_latest_day_wins() -> None:
    def row(day: int, name: str) -> LiveRow:
        return LiveRow(
            poll_id="poll_1",
            client_id=CLIENT,
            platform="meta",
            entity_ids={"account": "555", "campaign": "c1", "ad_set": "s1", "ad": "a1"},
            entity_names={"campaign": "Camp", "ad": name},
            objective="OUTCOME_LEADS",
            date=dt.date(2026, 11, day),
            impressions=10,
            clicks=1,
            spend=C.Money(amount="1.00", currency="USD"),
            conversions_reported=0.0,
            conversions_observed=None,
            revenue_reported=None,
            attribution_window="7d_click_1d_view",
        )

    got = live_refresh._entity_names([row(3, "New"), row(1, "Old")])
    assert got == {"c1": "Camp", "a1": "New"}


def test_execute_takes_entity_names() -> None:
    param = inspect.signature(pipeline.execute).parameters["entity_names"]
    assert param.default is None


# ------------------------------------------------------------------ against fixture runs


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> J4REnv:
    _j4r.hold_raw(monkeypatch)  # J7: these cases render raw statuses (see j4r_fixtures.raw_held)
    return J4REnv(tmp_path, monkeypatch)


def test_other_clients_slot_renders_nothing(env: J4REnv) -> None:
    run = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    qid = env.qid(run, IMG3_ID, "ctr")
    res = env.render(f"We looked at {fig_run(run, qid)}.", X.OTHER)
    (row,) = res["slots"]
    assert row["ok"] is False and row["rendered"] is None
    assert any(S.R_OTHER_CLIENT in r for r in row["reasons"])


def test_a_name_on_two_ids_is_no_name(env: J4REnv) -> None:
    run = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    env.set_names(run, {IMG3_ID: IMG3, IMG2_ID: IMG3.lower()})
    res = env.render(f"The ad {name_slot(IMG3_ID)} is live.")
    assert res["ok"] is False
    assert all(i["kind"] != "name" for i in env.menu()["slots"])


def test_snapshot_names_come_before_the_store(env: J4REnv) -> None:
    run = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    env.store_names = {IMG3_ID: "Store name"}
    res = env.render(f"The ad {name_slot(IMG3_ID)} is live.")
    assert res["text"] == f"The ad {IMG3} is live.", res
    assert env.names_calls == [CLIENT]  # R13: the store is always read, and ranks last
    assert run


def test_possessive_strips_trailing_punctuation_and_name_slot_keeps_it(env: J4REnv) -> None:
    """Integrator's ruling on open question 3."""
    run = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    qid = env.ctr_44(run, status="estimable", ad=IMG2_ID)
    res = env.render(f"We looked at {fig_run(run, qid)}. The ad {name_slot(IMG2_ID)} is live.")
    assert res["ok"] is True, res["reasons"]
    assert res["text"] == (
        "We looked at IMG2_TXT1 \u2013 Updated's click-through rate of 4.4%. "
        f"The ad {IMG2_NAME} is live."
    )
    assert S._possessive("Ad name ?! ") == "Ad name's"


def test_zero_or_all_reason_names_its_word(env: J4REnv) -> None:
    res = env.render("Every click came from phones.")
    assert res["ok"] is False
    assert any(S.R_ZERO_OR_ALL in r and "'every'" in r and "'click'" in r for r in res["lint"])


# ------------------------------------------------------------------ S25 against fixture releases


def _nb_entry(quantity: dict) -> dict:
    return X._entry(
        "nbe_lead_client_0009", "figure", "A figure.", "observed", "account", quantities=[quantity]
    )


def _nb(rel: str, name: str) -> str:
    return "{fig:nb/" + rel + "/nbe_lead_client_0009/" + name + "}"


def test_S25_7_notebook_subject_names_the_ad_or_campaign(env: J4REnv) -> None:
    env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    ad = {"name": "amount_spent", "value": 750, "unit": "USD",
          "subject": {"level": "ad", "id": IMG3_ID}}  # fmt: skip
    rel = env.release([_nb_entry(ad)])
    res = env.render(f"{_nb(rel, 'amount_spent')}.")
    assert res["text"] == f"{IMG3}'s amount spent of $750.", res
    assert res["slots"][0]["quantity"]["subject"] == IMG3_ID
    camp = {"name": "lifetime_budget", "value": 1500, "unit": "USD",
            "subject": {"level": "campaign", "id": "c1"}}  # fmt: skip
    rel = env.release([_nb_entry(camp)], day="20261121")
    res = env.render(f"{_nb(rel, 'lifetime_budget')}.")
    assert res["ok"] is False  # R15: campaign c1 has no name, and no raw id reaches the text
    assert any(S.R_NO_NAME in r for r in res["reasons"]), res["reasons"]


def test_S25_7_release_format_accepts_and_checks_the_subject(env: J4REnv) -> None:
    from bayesian_marketing.notebook import release as nb_release

    assert nb_release.SCHEMA == "bayes-notebook-1.2.0"
    bad = {"name": "x", "value": 1, "unit": "count", "subject": {"level": "country", "id": "x"}}
    with pytest.raises(ValueError, match="subject"):
        env.release([_nb_entry(bad)])
    good = {"name": "x", "value": 1, "unit": "count", "subject": {"level": "ad", "id": IMG3_ID}}
    rel = env.release([_nb_entry(good)], day="20261122")
    assert nb_release.verify(env.release_folder(rel))


def test_S25_7_a_1_0_0_release_still_verifies(env: J4REnv, monkeypatch: pytest.MonkeyPatch) -> None:
    from bayesian_marketing.notebook import release as nb_release

    monkeypatch.setattr(nb_release, "SCHEMA", "bayes-notebook-1.0.0")
    rel = env.release([_nb_entry({"name": "x", "value": 1, "unit": "count"})])  # no subject
    folder = env.release_folder(rel)
    assert '"schema":"bayes-notebook-1.0.0"' in (folder / "catalog.json").read_text()
    assert nb_release.verify(folder)
    with_subject = {"name": "x", "value": 1, "unit": "count", "subject": {"level": "account"}}
    with pytest.raises(ValueError, match=r"1\.1\.0"):
        env.release([_nb_entry(with_subject)], day="20261123")


def test_S25_8_kind_unreadable_everywhere_fails_the_slot(env: J4REnv) -> None:
    rel = env.release()
    (env.config_root / f"{CLIENT}.yaml").write_text("not: [valid")
    res = env.render("{fig:nb/" + rel + f"/{X.E_LIMIT}/account_spending_limit}}.")
    assert res["ok"] is False
    assert any(S.R_KIND_UNKNOWN in r for r in res["slots"][0]["reasons"]), res


def test_S25_8_kind_from_the_runs_when_newest_and_config_fail(env: J4REnv) -> None:
    env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    (env.config_root / f"{CLIENT}.yaml").write_text("not: [valid")

    def load_run(run_id: str) -> object:
        raise ValueError("unreadable")

    cpa = {"name": "cpa", "value": 12, "unit": "USD", "subject": {"level": "account"}}
    rel = env.release([_nb_entry(cpa)])
    res = env.render(f"{_nb(rel, 'cpa')}.", load_run=load_run)
    assert res["text"] == "the cost per sign-up of $12.00.", res


def test_S25_10_forged_run_file_is_unreadable_as_a_ref(env: J4REnv) -> None:
    import json

    run = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    qid = env.qid(run, IMG3_ID, "ctr")
    path = env.snapshot_file(run)
    body = json.loads(path.read_text())
    body["client_id"] = X.OTHER
    path.write_text('{"client_id": "' + CLIENT + '", ' + json.dumps(body)[1:])
    res = env.render(f"{fig_run(run, qid)}.")
    assert res["ok"] is False
    assert any(run in r and "cannot be read" in r for r in res["reasons"]), res["reasons"]


def test_S25_9_name_stating_a_figure_fails_every_slot_it_is_in(env: J4REnv) -> None:
    run = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    env.set_names(run, {IMG3_ID: "Save 50% now", IMG2_ID: IMG2_NAME})
    qid = env.ctr_44(run)
    for text in (name_slot(IMG3_ID), fig_run(run, qid)):
        res = env.render(f"{text}.")
        assert res["ok"] is False and res["text"] is None
        assert any(S.R_NAME_FIGURE in r for r in res["reasons"]), res["reasons"]
    assert all(IMG3_ID not in i["token"] for i in env.menu()["slots"] if i["kind"] == "name")


def test_S25_11_lint_after_e_g(env: J4REnv) -> None:
    env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    res = env.render(f"{name_slot(IMG3_ID)} (e.g. on clicks) is better.")
    assert any(S.R_COMPARATIVE in r for r in res["lint"]), res


# ------------------------------------------------------------------ S26 and the second review

ACCOUNT = {"level": "account"}


@pytest.mark.parametrize(
    "text",
    ["t.e.n", "f i v e", "o-n-e", "o'n'e", "s\u00e9ven", "tw\u00f6", "n\u0131ne", "n\u0130ne",
     "F\u0130FTY", "fiftypercent", "tenpct", "twodozen", "halfhalf", "threequarters", "fiftyish",
     "twentysomething", "twentyfirst", "sixfold", "FiftyPercentOff"],
)  # fmt: skip
def test_S26_2_folds_catch(text: str) -> None:
    assert S._word_hits(f"We saw {text} today."), text


@pytest.mark.parametrize(
    "text",
    ["lOO", "zeroes", "tenner", "fiver", "someone", "often", "content", "attention", "polish",
     "finish", "scaffold", "foremost", "despair", "tremendous", "a photo", "I am", "money"],
)  # fmt: skip
def test_S26_2_folds_stop_there(text: str) -> None:
    """The threat model: what the folds don't catch passes, and ordinary words stay words."""
    assert S._word_hits(f"We saw {text} today.") == [], text


@pytest.mark.parametrize(
    ("q", "want"),
    [
        ({"name": "p_best", "value": 0.9996, "unit": "ratio"}, "more than 99%"),
        ({"name": "p_best", "value": 99.96, "unit": "percent"}, "more than 99%"),
        ({"name": "p_exceeds", "value": 0.0004, "unit": "ratio"}, "less than 1%"),
        ({"name": "p_best", "value": 62.1, "unit": "percent"}, "62%"),
        ({"name": "x", "value": 0.0004, "unit": "probability"}, "less than 1%"),
    ],
)
def test_R7_R8_every_probability_is_guarded(q: dict, want: str) -> None:
    assert S._nb_value(q, "purchase") == want


def test_R7_R8_run_p_exceeds_is_guarded(env: J4REnv) -> None:
    run = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    qid = env.set_quantity(run, IMG3_ID, "ctr", status="estimable", q50=0.9996, mean=0.9996)

    def rename(d: dict) -> None:
        for q in d["quantities"]:
            if q["quantity_id"] == qid:
                q["name"] = "p_exceeds"
                q["evidence_class"] = "platform_attributed"

    env._patch(run, rename)
    res = env.render(f"{fig_run(run, qid, 'start')}.")
    assert res["ok"], res["reasons"]
    assert "more than 99%" in res["text"], res["text"]


@pytest.mark.parametrize(
    ("q", "want"),
    [
        ({"name": "amount_spent", "value": -0.001, "unit": "USD"}, "less than $0.01 below zero"),
        ({"name": "lift", "value": -0.0004, "unit": "ratio"}, "less than 0.1% below zero"),
        ({"name": "n", "value": -0.4, "unit": "count"}, "less than 1 below zero"),
        ({"name": "amount_spent", "value": -5, "unit": "USD"}, "-$5.00"),
        ({"name": "amount_spent", "value": 0, "unit": "USD"}, "$0.00"),
        ({"name": "lift", "value": -0.0, "unit": "ratio"}, "0.0%"),
    ],
)
def test_R23_R24_no_minus_on_zero(q: dict, want: str) -> None:
    assert S._nb_value(q, "purchase") == want


@pytest.mark.parametrize("value", [0.4, 1.4, 1.5])
def test_R18_fractional_days_fail(value: float) -> None:
    with pytest.raises(S._Fail, match=S.R_UNIT):
        S._nb_value({"name": "d", "value": value, "unit": "days"}, "purchase")


@pytest.mark.parametrize("name", ["...", " - ", "Spring\nSale"])
def test_R25_R26_names_that_cannot_be_rendered(name: str) -> None:
    assert S.R_NAME_UNRENDERABLE in (S._name_states_a_figure(name) or "")


@pytest.mark.parametrize(
    "name",
    ["Save 50 dollars", "FiftyPercentOff", "50% off", "Price $5", "USD promo", "Promo {x}",
     "Ad\u200bTwo", "Ad\x07", "Ten basis points", "Two bucks"],
)  # fmt: skip
def test_S27_names_fail_only_on_percent_currency_braces_and_controls(name: str) -> None:
    assert S.R_NAME_FIGURE in (S._name_states_a_figure(name) or ""), name


@pytest.mark.parametrize(
    "name",
    ["IMG3_TXT1", "IMG2_TXT1 \u2013 Updated.", "Spring Xii", "Promo B2", "Top 10 ads", "Save50",
     "Ten2", "IMG3 x2", "Over9", "Up to 30", "Ad 7", "Ad 2", "Spring | Video A",
     "[Prospecting] Spring", "Single Image Spring", "Spring \U0001f525", "Three ads", "Ad #2"],
)  # fmt: skip
def test_S27_client_names_render(name: str) -> None:
    """S27: names are the client's own data; R6's extra digit rules are withdrawn."""
    assert S._name_states_a_figure(name) is None, name


def test_R9_kind_from_the_runs_before_the_purchase_default(env: J4REnv) -> None:
    old = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    new = env.lead_run_at(X.START_NEW, X.WINDOW_NEW, started_at=X.STARTED_NEW)
    env.rewrite(new, lambda d: d.update(conversion_kind=None))
    assert env.snapshot(old).conversion_kind == "lead"
    (env.config_root / f"{CLIENT}.yaml").write_text("not: [valid")
    cpa = {"name": "cpa", "value": 12.0, "unit": "USD", "subject": ACCOUNT}
    rel = env.release([_nb_entry(cpa)])
    res = env.render(f"{_nb(rel, 'cpa')}.")
    assert res["text"] == "the cost per sign-up of $12.00.", res


def test_R10_release_whose_catalog_and_id_name_two_clients_is_unreadable(env: J4REnv) -> None:
    import json

    from bayesian_marketing.notebook import release as nb_release

    env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    rel = env.other_release()
    folder = env.release_folder(rel, X.OTHER)
    cat = json.loads((folder / "catalog.json").read_text())
    cat["client_id"] = CLIENT
    (folder / "catalog.json").write_bytes(nb_release.canonical(cat) + b"\n")
    integ = json.loads((folder / "integrity.json").read_text())
    integ["files"]["catalog.json"] = nb_release.sha((folder / "catalog.json").read_bytes())
    integ["release_hash"] = nb_release.release_hash(integ["files"])
    (folder / "integrity.json").write_bytes(nb_release.canonical(integ) + b"\n")
    res = env.render("{fig:nb/" + rel + f"/{X.E_OTHER}/account_spending_limit}}.")
    assert res["ok"] is False
    assert any(rel in r and "cannot be read" in r for r in res["reasons"]), res["reasons"]


def test_R15_R16_an_unnamed_ad_fails_and_no_id_reaches_the_text(env: J4REnv) -> None:
    run = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    env.set_names(run, {IMG2_ID: "IMG2_TXT1"})
    qid = env.ctr_44(run)
    res = env.render(f"{fig_run(run, qid)}.")
    assert res["ok"] is False and res["text"] is None
    assert any(S.R_NO_NAME in r for r in res["reasons"]), res["reasons"]
    assert all(IMG3_ID not in t for i in env.menu()["slots"] for t in i["forms"].values())


def test_R17_a_subject_level_the_name_source_contradicts_fails(env: J4REnv) -> None:
    env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    q = {"name": "lifetime_budget", "value": 1500, "unit": "USD",
         "subject": {"level": "campaign", "id": IMG3_ID}}  # fmt: skip
    rel = env.release([_nb_entry(q)])
    res = env.render(f"{_nb(rel, 'lifetime_budget')}.")
    assert res["ok"] is False
    assert any(S.R_LEVEL in r for r in res["reasons"]), res["reasons"]


@pytest.mark.parametrize(
    "text",
    ["Nobody signed up.", "Nothing came from the clicks.", "No one clicked the link clicks.",
     "Not one click came.", "Not any sign-ups yet.", "Neither ad got clicks.",
     "Not a click came from the ads."],
)  # fmt: skip
def test_R30_more_words_that_state_zero(env: J4REnv, text: str) -> None:
    res = env.render(text)
    assert res["ok"] is False
    assert any(S.R_ZERO_OR_ALL in r for r in res["lint"]), res


@pytest.mark.parametrize("word", ["outshines", "outshone", "pulls away from", "versus", "vs.",
                                  "brings", "brought"])  # fmt: skip
def test_R27_lint_extra_words(env: J4REnv, word: str) -> None:
    env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    res = env.render(f"{name_slot(IMG3_ID)} {word} {name_slot(IMG2_ID)}.")
    assert any(S.R_COMPARATIVE in r for r in res["lint"]), res


def test_R29_a_cmp_slot_names_its_leader_for_the_lint(env: J4REnv) -> None:
    run = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    env.set_p_best(run, {IMG3_ID: 0.621, IMG2_ID: 0.379})
    res = env.render("{cmp:run/" + run + "}, and it is far better than the others.")
    assert any(S.R_COMPARATIVE in r for r in res["lint"]), res


def test_S26_1_every_menu_slot_renders_the_same_alone_and_beside_every_other(
    env: J4REnv,
) -> None:
    """S26 (1), R13, R14: same slot, same text, byte for byte.

    Amended for J4R.2 (check (b)): the colliding store name makes IMG3 a candidate under rule 2,
    so IMG3 is given an ad set and renders "IMG3_TXT1 (Set A)" in every slot."""
    run = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    env._patch(
        run,
        lambda d: d.update(
            entity_names={**d["entity_names"], "sA": "Set A"}, entity_parents={IMG3_ID: "sA"}
        ),
    )
    env.ctr_44(run)
    env.set_p_best(run, {IMG3_ID: 0.621, IMG2_ID: 0.379})
    env.store_names = {"999": IMG3.lower()}  # a colliding store name, ranked below the snapshot
    quantities = [
        {"name": "account_spending_limit", "value": 1500, "unit": "USD", "subject": ACCOUNT},
        {"name": "amount_spent", "value": 750, "unit": "USD",
         "subject": {"level": "ad", "id": IMG3_ID}},
        {"name": "p_best", "value": 0.621, "unit": "probability",
         "subject": {"level": "ad", "id": IMG2_ID}},
    ]  # fmt: skip
    env.release([X._entry("nbe_lead_client_0009", "figure", "Figures.", "observed", "account",
                          quantities=quantities)])  # fmt: skip
    items = env.menu()["slots"]
    kinds = {i["kind"] for i in items}
    assert {"fig", "cmp", "name"} <= kinds and any(i["release_id"] for i in items), items
    alone = {}
    for i in items:
        res = env.render(i["token"])
        assert res["ok"], (i["token"], res["reasons"])
        assert res["text"] == i["forms"]["full"]
        alone[i["token"]] = res["text"]
    for i in items:
        for j in items:
            res = env.render(f"{i['token']} and {j['token']}")
            rows = res["slots"]
            assert rows[0]["rendered"] == alone[i["token"]], (i["token"], j["token"])
            assert rows[1]["rendered"] == alone[j["token"]], (i["token"], j["token"])


# ------------------------------------------------------------------ S27, the third review


@pytest.mark.parametrize(
    ("name", "x", "want"),
    [
        ("cpa", 0.43, "$0.43"),
        ("cpc", 1.5, "$1.50"),
        ("cpm", 0.4, "$0.40"),
        ("contribution_per_click", 0.35, "$0.35"),
        ("contribution", 1234.5, "$1,235"),
    ],
)
def test_S27_per_unit_money_at_cents_whatever_the_kind(name: str, x: float, want: str) -> None:
    assert S._fmt_money(x, "USD", S._money_decimals(name)) == want


@pytest.mark.parametrize(
    ("value", "want"), [(0.4, "$0.40"), (99.99, "$99.99"), (100, "$100"), (1500, "$1,500")]
)
def test_S27_notebook_money_under_100_at_cents(value: float, want: str) -> None:
    q = {"name": "amount_spent", "value": value, "unit": "USD"}
    assert S._nb_value(q, "purchase") == want


@pytest.mark.parametrize(
    ("fn", "x", "want"),
    [
        (S._fmt_percent, 0.0004, "less than 0.1%"),
        (S._fmt_percent, 0.00004, "less than 0.1%"),
        (S._fmt_percent, 0.0, "0.0%"),
        (S._fmt_count, 0.3, "less than 1"),
        (S._fmt_count, 0.0, "0"),
        (S._fmt_ratio, 0.001, "less than 0.01"),
    ],
)
def test_S27_a_nonzero_value_never_shows_as_zero(fn: object, x: float, want: str) -> None:
    assert fn(x) == want  # type: ignore[operator]


def test_S27_less_than_money_and_no_about_before_it() -> None:
    assert S._fmt_money(0.004, "USD", 2) == "less than $0.01"
    forms = S._forms("X's rate", True, "less than 0.1%", "marginal", "")
    assert forms["full"] == f"X's rate of less than 0.1%, {S.ROUGH}"
    assert forms["start"] == f"X's rate is less than 0.1%, {S.ROUGH}"


@pytest.mark.parametrize("x", [1e30, 10**40, float("1e300")])
def test_S27_a_value_beyond_decimal_precision_fails_the_slot(x: float) -> None:
    with pytest.raises(S._Fail, match=S.R_VALUE):
        S._fmt_money(x, "USD", 0)


@pytest.mark.parametrize(
    ("shown", "want"),
    [("8%", "an"), ("11%", "an"), ("18%", "an"), ("80%", "an"), ("85%", "an"), ("89%", "an"),
     ("800", "an"), ("$8", "an"), ("11,000", "an"), ("18,500", "an"), ("1%", "a"), ("62%", "a"),
     ("90%", "a"), ("180", "a"), ("1,800", "a"), ("more than 99%", "a"), ("less than 1%", "a")],
)  # fmt: skip
def test_S27_the_article(shown: str, want: str) -> None:
    assert S._article(shown) == want


@pytest.mark.parametrize("word", S.QUANTITY_WORDS_S27)
def test_S27_the_list_gains(word: str) -> None:
    assert word in S.quantity_word_forms()
    assert S._word_hits(f"We saw {word} today."), word


@pytest.mark.parametrize(
    "text",
    ["Hi Sam,\r\nBoth ads ran.", "Hi Sam,\rBoth ads ran.", "Hi Sam,\tboth ads ran.",
     "Both\u00a0ads ran.", "Both\u202fads ran.", "*Both* ads ran.", "_Both_ ads ran.",
     "~Both~ ads ran.", "`Both` ads ran.", "\u2022 Both ads ran.", "> Both ads ran.",
     "Sign\u2011ups are tracked."],
)  # fmt: skip
def test_S27_pasted_characters_and_slack_marks_pass(text: str) -> None:
    assert S._numeral_reasons(text) == [], text


@pytest.mark.parametrize("ch", ["\U0001f44d", "\U0001f525", "\u2764"])
def test_S27_emoji_stay_refused(ch: str) -> None:
    assert any(S.R_CHARACTER in r for r in S._numeral_reasons(f"Both ads ran {ch}"))


@pytest.mark.parametrize(
    "text",
    ["Nobody clicked.", "Neither ad converted.", "<A> did not get any clicks.",
     "<A> didn't get any sign-ups.", "<A> did not convert.", "<A> has not converted.",
     "Nobody bought.", "<A> took the whole spend.", "The entire spend was on <A>.",
     "Everything went to <A>.", "All of the spend went to <A>."],
)  # fmt: skip
def test_S27_A4_more_ways_to_state_zero_or_the_whole(env: J4REnv, text: str) -> None:
    env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    res = env.render(text.replace("<A>", name_slot(IMG3_ID)))
    assert res["ok"] is False
    assert any(S.R_ZERO_OR_ALL in r for r in res["lint"]), res


@pytest.mark.parametrize(
    "text", ["None of this changes your plan.", "Each ad is live, and neither is paused."]
)
def test_S27_A4_still_passes_without_a_measure(env: J4REnv, text: str) -> None:
    env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    assert env.render(text)["ok"] is True


@pytest.mark.parametrize(
    ("p_best", "neither"),
    [
        ({IMG3_ID: 0.52, IMG2_ID: 0.48}, True),
        ({IMG3_ID: 0.525, IMG2_ID: 0.475}, True),
        ({IMG3_ID: 0.5, IMG2_ID: 0.5}, True),
        ({IMG3_ID: 0.45, IMG2_ID: 0.30}, True),
        ({IMG3_ID: 0.56, IMG2_ID: 0.44}, False),
        ({IMG3_ID: 0.621, IMG2_ID: 0.379}, False),
    ],
)
def test_S27_cmp_names_no_leader_when_close_or_under_half(
    env: J4REnv, p_best: dict, neither: bool
) -> None:
    run = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    env.set_p_best(run, p_best)
    for form in ("full", "start"):
        res = env.render("{cmp:run/" + run + "|" + form + "}.")
        assert res["ok"], res["reasons"]
        if neither:
            assert "either ad leads yet on clicks, still a rough estimate" in res["text"]
            assert IMG3 not in res["text"] and "%" not in res["text"], res["text"]
        else:
            assert IMG3 in res["text"] and "leads" in res["text"], res["text"]


def test_S27_cmp_drops_the_name_s_stop_and_says_an(env: J4REnv) -> None:
    run = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    env.set_p_best(run, {IMG3_ID: 0.2, IMG2_ID: 0.8})
    full = env.render("{cmp:run/" + run + "}.")["text"]
    start = env.render("{cmp:run/" + run + "|start}.")["text"]
    assert (
        full == "IMG2_TXT1 \u2013 Updated, which leads on clicks with an 80% chance of being best."
    )
    assert start == "IMG2_TXT1 \u2013 Updated leads on clicks, with an 80% chance of being best."
    assert env.render(f"The ad {name_slot(IMG2_ID)} is live.")["text"] == (
        f"The ad {IMG2_NAME} is live."  # a name slot keeps the full name
    )


def test_S27_duplicate_names_refused_by_writer_and_verifier_and_failed_by_the_renderer(
    env: J4REnv,
) -> None:
    from bayesian_marketing.notebook import release as nb_release

    env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    q = [{"name": "amount_spent", "value": v, "unit": "USD", "subject": ACCOUNT} for v in (1, 2)]
    entry = X._entry("nbe_lead_client_0009", "figure", "Two.", "observed", "account", quantities=q)
    with pytest.raises(ValueError, match="two quantities of one name"):
        env.release([dict(entry)])
    with pytest.raises(ValueError, match="two quantities of one name"):
        nb_release._check_entry(entry, {b["source_id"] for b in entry["basis"]})
    rel = env.release()

    def load(rid: str) -> object:
        catalog, _, sources = env.release_files(rel)
        return catalog, [entry], sources

    res = env.render(_nb(rel, "amount_spent") + ".", load_release=load)
    assert res["ok"] is False
    assert any(S.R_DUPLICATE in r for r in res["reasons"]), res["reasons"]
    assert all("amount_spent" not in i["token"] for i in env.menu(load_release=load)["slots"])


@pytest.mark.parametrize("quantities", [5, "x", {"name": "a"}])
def test_S27_non_list_quantities_fail_the_slot_and_never_raise(
    env: J4REnv, quantities: object
) -> None:
    env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    rel = env.release()

    def load(rid: str) -> object:
        catalog, _, sources = env.release_files(rel)
        return catalog, [{"entry_id": X.E_LIMIT, "quantities": quantities}], sources

    res = env.render("{fig:nb/" + rel + f"/{X.E_LIMIT}/account_spending_limit}}", load_release=load)
    assert res["ok"] is False and res["text"] is None
    env.menu(load_release=load)  # never raises


# ------------------------------------------------------------------ J4R.1: quantity labels

WEEK = "click-through rate for the week of 7 to 13 November"


def _labelled(label: object, **extra: object) -> dict:
    q = {"name": "ctr_week1", "value": 0.072, "unit": "ratio",
         "subject": {"level": "ad", "id": IMG3_ID}, "label": label}  # fmt: skip
    q.update(extra)
    return _nb_entry(q)


@pytest.mark.parametrize(
    ("form", "want"),
    [
        ("full", f"We looked at {IMG3}'s {WEEK} of 7.2%."),
        ("start", f"{IMG3}'s {WEEK} is 7.2%."),
    ],
)
def test_J4R1_a_label_is_the_measure_wording_in_both_forms(
    env: J4REnv, form: str, want: str
) -> None:
    env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    rel = env.release([_labelled(WEEK)])
    slot = "{fig:nb/" + rel + "/nbe_lead_client_0009/ctr_week1|" + form + "}"
    template = f"{slot}." if form == "start" else f"We looked at {slot}."
    res = env.render(template)
    assert res["ok"], res["reasons"]
    assert res["text"] == want


def test_J4R1_a_label_on_an_account_subject_and_in_the_menu(env: J4REnv) -> None:
    env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    label = "chance the account's best ad stays ahead on clicks"
    q = {"name": "p_best_clicks", "value": 0.62, "unit": "probability", "subject": ACCOUNT}
    q["label"] = label
    rel = env.release([_nb_entry(q)])
    items = [i for i in env.menu()["slots"] if i["release_id"] == rel]
    assert [i["forms"] for i in items] == [
        {
            "full": "the chance the account's best ad stays ahead on clicks of 62%",
            "start": "The chance the account's best ad stays ahead on clicks is 62%",
        }
    ]


@pytest.mark.parametrize(
    "label",
    ["rate {week}", "rate in % terms", "share in percent", "cost in USD", "cost in dollars",
     "cost per $", "two\nlines", "tab\x07bell", "a" * 121, "", "   ", 5, None],
)  # fmt: skip
def test_J4R1_a_bad_label_is_refused_on_write(env: J4REnv, label: object) -> None:
    with pytest.raises(ValueError, match="label"):
        env.release([_labelled(label)])


def test_J4R1_a_label_of_120_characters_is_accepted(env: J4REnv) -> None:
    env.release([_labelled("a" * 120)])


def test_J4R1_verify_refuses_a_bad_label_written_past_the_writer(env: J4REnv) -> None:
    import json

    from bayesian_marketing.notebook import release as nb_release

    rel = env.release([_labelled(WEEK)])
    folder = env.release_folder(rel)
    entries = [json.loads(x) for x in (folder / "entries.jsonl").read_text().splitlines()]
    entries[0]["quantities"][0]["label"] = "rate in % terms"
    (folder / "entries.jsonl").write_bytes(
        b"".join(nb_release.canonical(e) + b"\n" for e in entries)
    )
    integ = json.loads((folder / "integrity.json").read_text())
    integ["files"]["entries.jsonl"] = nb_release.sha((folder / "entries.jsonl").read_bytes())
    integ["release_hash"] = nb_release.release_hash(integ["files"])
    (folder / "integrity.json").write_bytes(nb_release.canonical(integ) + b"\n")
    with pytest.raises(ValueError, match="label"):
        nb_release.verify(folder)


def test_J4R1_the_renderer_fails_a_bad_label_a_loader_gives(env: J4REnv) -> None:
    env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    rel = env.release([_labelled(WEEK)])

    def load(rid: str) -> object:
        catalog, entries, sources = env.release_files(rel)
        entries[0]["quantities"][0]["label"] = "rate in % terms"
        return catalog, entries, sources

    res = env.render("{fig:nb/" + rel + "/nbe_lead_client_0009/ctr_week1}.", load_release=load)
    assert res["ok"] is False and res["text"] is None
    assert any(S.R_NAME_FIGURE in r for r in res["reasons"]), res["reasons"]


def test_J4R1_a_1_1_0_release_still_renders_as_before_and_refuses_a_label(
    env: J4REnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bayesian_marketing.notebook import release as nb_release

    env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    monkeypatch.setattr(nb_release, "SCHEMA", "bayes-notebook-1.1.0")
    q = {"name": "amount_spent", "value": 750, "unit": "USD",
         "subject": {"level": "ad", "id": IMG3_ID}}  # fmt: skip
    rel = env.release([_nb_entry(q)])
    folder = env.release_folder(rel)
    assert '"schema":"bayes-notebook-1.1.0"' in (folder / "catalog.json").read_text()
    assert nb_release.verify(folder)
    res = env.render(f"{_nb(rel, 'amount_spent')}.")
    assert res["text"] == f"{IMG3}'s amount spent of $750.", res
    with pytest.raises(ValueError, match=r"1\.2\.0"):
        env.release([_labelled(WEEK)], day="20261124")


def test_J4R1_no_label_keeps_the_name_wording(env: J4REnv) -> None:
    env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    q = {"name": "ctr", "value": 0.044, "unit": "ratio", "subject": {"level": "ad", "id": IMG3_ID}}
    rel = env.release([_nb_entry(q)])
    res = env.render(f"{_nb(rel, 'ctr')}.")
    assert res["text"] == f"{IMG3}'s click-through rate of 4.4%.", res


# ------------------------------------------------------------------ J4R.1: the AtmaOS client id

AID = "01a1a97d-bce7-7000-8462-dc1e8af439a0"
OTHER_AID = "01a1a97d-bce7-7000-8462-00000000beef"


def _alias(env: J4REnv, client_id: str = CLIENT, aid: str = AID) -> None:
    from tests.acceptance.test_J5 import LEAD
    from tests.acceptance.test_L5 import config

    kw = dict(LEAD) if client_id == CLIENT else {}
    env.write_config(config(**{**kw, "client_id": client_id, "atmaos_client_id": aid}))


def _same(a: dict, b: dict, drop: tuple[str, ...]) -> tuple[dict, dict]:
    return ({k: v for k, v in a.items() if k not in drop},
            {k: v for k, v in b.items() if k not in drop})  # fmt: skip


def test_J4R1_either_id_gives_the_same_menu_and_rendering(env: J4REnv) -> None:
    _alias(env)
    run = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    env.set_p_best(run, {IMG3_ID: 0.621, IMG2_ID: 0.379})
    q = {"name": "amount_spent", "value": 750, "unit": "USD", "subject": ACCOUNT}
    env.release([_nb_entry(q)])
    by_slug, by_aid = env.menu(CLIENT), env.menu(AID)
    assert by_slug["client_id"] == by_aid["client_id"] == CLIENT
    assert (by_slug["client_ref"], by_aid["client_ref"]) == (CLIENT, AID)
    assert by_slug["slots"] and by_slug["slots"] == by_aid["slots"]
    assert by_slug["reasons"] == by_aid["reasons"] == []
    template = " ".join(i["token"] for i in by_slug["slots"]) + "."
    a, b = env.render(template, CLIENT), env.render(template, AID)
    assert a["ok"] is True, a["reasons"]
    assert (a["client_id"], b["client_id"], a["client_ref"], b["client_ref"]) == (
        CLIENT, CLIENT, CLIENT, AID
    )  # fmt: skip
    left, right = _same(a, b, ("client_ref", "checked_at"))
    assert left == right


def test_J4R1_an_atmaos_id_of_another_client_is_walled(env: J4REnv) -> None:
    _alias(env)
    env.other_release()
    _alias(env, X.OTHER, OTHER_AID)
    run = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    qid = env.ctr_44(run)
    res = env.render(f"We looked at {fig_run(run, qid)}.", OTHER_AID)
    assert res["client_id"] == X.OTHER and res["client_ref"] == OTHER_AID
    assert res["ok"] is False and res["text"] is None
    assert any(S.R_OTHER_CLIENT in r for r in res["reasons"]), res["reasons"]
    assert all(i["run_id"] != run for i in env.menu(OTHER_AID)["slots"])


def test_J4R1_two_configs_claiming_one_atmaos_id_fail_and_never_pick(env: J4REnv) -> None:
    _alias(env)
    env.other_release()
    _alias(env, X.OTHER, AID)
    run = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    qid = env.ctr_44(run)
    res = env.render(f"We looked at {fig_run(run, qid)}.", AID)
    assert res["ok"] is False and res["text"] is None and res["slots"] == []
    assert any(S.R_CLIENT_REF in r for r in res["reasons"]), res["reasons"]
    menu = env.menu(AID)
    assert menu["slots"] == [] and any(S.R_CLIENT_REF in r for r in menu["reasons"])
    with pytest.raises(ValueError, match="more than one"):
        R.resolve_client(AID)
    assert env.render("Both ads are live.", CLIENT)["ok"] is True  # the slug still resolves


def test_J4R1_an_id_naming_one_config_and_another_s_alias_fails(env: J4REnv) -> None:
    env.other_release()
    _alias(env, X.OTHER, CLIENT)  # the other client claims the lead client's own id
    with pytest.raises(ValueError, match="more than one"):
        R.resolve_client(CLIENT)


def test_J4R1_an_unknown_id_comes_back_unchanged(env: J4REnv) -> None:
    assert R.resolve_client("nobody_at_all") == "nobody_at_all"
    assert R.resolve_client(CLIENT) == CLIENT
    menu = env.menu("nobody_at_all")
    assert (menu["client_id"], menu["client_ref"], menu["slots"]) == (
        "nobody_at_all", "nobody_at_all", []
    )  # fmt: skip


def test_J4R1_the_config_field_is_optional() -> None:
    from bayesian_marketing import core as C

    base = {"client_id": "c", "timezone": "UTC", "currency": "USD", "accounts": {"meta": "1"}}
    assert C.ClientConfig(**base).atmaos_client_id is None
    assert C.ClientConfig(**base, atmaos_client_id=AID).atmaos_client_id == AID
