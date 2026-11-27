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
    ["\t", "\r", " ", "×", "÷", "ƀ", "а", "#", "+", "=", "_", "{", "@"],
)
def test_S25_1_characters_outside_the_set_fail_by_code_point(ch: str) -> None:
    reasons = S._numeral_reasons(f"a{ch}b")
    assert any(S.R_CHARACTER in r and f"U+{ord(ch):04X}" in r for r in reasons), reasons


def test_S25_1_the_allowed_set() -> None:
    text = "AbÀſ .,;:!?'\"()-/& ’‘“”–—…\n"
    assert all(c in S.ALLOWED_CHARACTERS for c in text)
    assert S._numeral_reasons("Café — “good”, isn’t it…") == []


@pytest.mark.parametrize("token", ["IV", "xii", "MMXXVI", "vii", "mix", "CM"])
def test_S25_2_roman_numerals_fail(token: str) -> None:
    assert token in S._word_hits(f"See {token} here.")


@pytest.mark.parametrize("text", ["I said so.", "Mix it.", "Did it."])
def test_S25_2_single_I_and_mixed_case_pass(text: str) -> None:
    assert S._word_hits(text) == []


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
        ("EUR", 20, "€20"),
        ("CHF", 20, "20 CHF"),
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
    assert S._nb_value({"name": "cpa", "value": 12, "unit": "USD"}, "purchase") == "$12"


@pytest.mark.parametrize(
    ("subject", "want"),
    [
        (None, ("account", None)),
        ({"level": "account"}, ("account", None)),
        ({"level": "campaign", "id": "c1"}, ("campaign", "c1")),
        ({"level": "ad", "id": "a1"}, ("ad", "a1")),
    ],
)
def test_S25_7_subject_from_the_quantity(subject: object, want: object) -> None:
    q = {"name": "x", "value": 1, "unit": "count"}
    if subject is not None:
        q["subject"] = subject
    assert S._nb_subject(q) == want


@pytest.mark.parametrize(
    "subject", [{"level": "country", "id": "x"}, {"level": "ad"}, "ad", {"level": "ad", "id": 5}]
)
def test_S25_7_malformed_subject_fails(subject: object) -> None:
    with pytest.raises(S._Fail):
        S._nb_subject({"name": "x", "value": 1, "unit": "count", "subject": subject})


@pytest.mark.parametrize(
    "name",
    ["Promo {date:2026-01-01}", "Save 50% today", "Price $5", "Three ads", "Ad​Two", "Ad #2"],
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
        ("A e.g.\nB.", 2),
    ],
)
def test_S25_11_no_split_after_abbreviations(text: str, n: int) -> None:
    assert len([x for x in S._sentences(text) if x.strip()]) == n


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
    assert merged == {"1": "Alpha"}  # "Gamma" and "gamma" name two ids: both unnamed


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
    assert env.names_calls == []  # the snapshot had names for every id needed
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
    assert res["text"] == "campaign c1's lifetime budget of $1,500.", res


def test_S25_7_release_format_accepts_and_checks_the_subject(env: J4REnv) -> None:
    from bayesian_marketing.notebook import release as nb_release

    assert nb_release.SCHEMA == "bayes-notebook-1.1.0"
    bad = {"name": "x", "value": 1, "unit": "count", "subject": {"level": "country", "id": "x"}}
    with pytest.raises(ValueError, match="subject"):
        env.release([_nb_entry(bad)])
    good = {"name": "x", "value": 1, "unit": "count", "subject": {"level": "ad", "id": IMG3_ID}}
    rel = env.release([_nb_entry(good)], day="20261122")
    assert nb_release.verify(env.release_folder(rel))


def test_S25_7_a_1_0_0_release_still_verifies(env: J4REnv, monkeypatch: pytest.MonkeyPatch) -> None:
    from bayesian_marketing.notebook import release as nb_release

    monkeypatch.setattr(nb_release, "SCHEMA", "bayes-notebook-1.0.0")
    rel = env.release()
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

    rel = env.release([_nb_entry({"name": "cpa", "value": 12, "unit": "USD"})])
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
    env.set_names(run, {IMG3_ID: "Three for one", IMG2_ID: IMG2_NAME})
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
