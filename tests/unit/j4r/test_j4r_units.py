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
from tests.acceptance.j4_fixtures import CLIENT, IMG2_ID, IMG3, IMG3_ID
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
    assert not {"first", "second", "none", "no"} & forms


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
def test_numeral_hits(text: str, hit: str) -> None:
    assert hit in S._numeral_hits(text)


@pytest.mark.parametrize("text", ["all ads try the top cup.", "Usd is not a code here.", "first"])
def test_numeral_no_hits(text: str) -> None:
    assert S._numeral_hits(text) == []


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


def test_zero_or_all_reason_names_its_word(env: J4REnv) -> None:
    res = env.render("Every click came from phones.")
    assert res["ok"] is False
    assert any(S.R_ZERO_OR_ALL in r and "'every'" in r and "'click'" in r for r in res["lint"])
