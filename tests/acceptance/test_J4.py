"""J4: check_client_figures (Brain join spec v0.3, J4 checks (a) to (q); S5 to S10; P1 to P5).

Every case calls through the socket entry ``bayesian_marketing.atmaos.socket.check_client_figures``
against fixture runs and a fixture notebook release (``tests/acceptance/j4_fixtures.py``), never
the live store. Runs are lead runs of test_L5's client; their saved snapshots are edited per case
to set a quantity's summary or status, as test_J5 does. Two cases pass explicit ``load_run`` and
``load_release`` (P4) whose returns differ from the files on disk, so only a check that uses the
loaders passes them.

Reasons are asserted by substring of the skeleton's fixed reason constants (``R_*`` in
``claims/figures.py``), never as whole sentences.

Ad ids are numeric. Names come from the snapshot's ``entity_names`` (set by the fixture), from
notebook ``meta_object`` sources, or from a fake ``load_names`` (S16); see j4_fixtures. The
integrator's rulings S16 to S22 (26 Nov) are tested in the sections marked with them.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

import pytest

from bayesian_marketing import pipeline
from bayesian_marketing.atmaos import socket as sock
from bayesian_marketing.claims import figures as F
from bayesian_marketing.notebook import release as nb_release
from tests.acceptance import j4_fixtures as X
from tests.acceptance.j4_fixtures import (
    E_AD2,
    E_BUDGET,
    E_LIMIT,
    E_OTHER,
    E_PBEST,
    E_SPENT,
    IMG2_ID,
    IMG2_NAME,
    IMG3,
    IMG3_ID,
    IMG4,
    IMG4_ID,
    OTHER,
    J4Env,
    claim_ref,
    entry_ref,
    run_ref,
)
from tests.acceptance.test_L5 import config

pytestmark = pytest.mark.piece("J4")

UTC = dt.UTC


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> J4Env:
    return J4Env(tmp_path, monkeypatch)


@pytest.fixture
def run(env: J4Env) -> str:
    """One lead run; IMG3_TXT1's ctr is marginal at a median of 4.4% (q05 4.0%, q95 4.7%)."""
    run_id = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    env.ctr_44(run_id)
    return run_id


@pytest.fixture
def rel(env: J4Env) -> str:
    """The fixture notebook release (one release for the client, so it is the newest)."""
    return env.release()


# ------------------------------------------------------------------ helpers


def all_reasons(res: dict[str, Any]) -> str:
    parts = list(res["reasons"])
    for f in res["figures"]:
        parts += f["reasons"]
    return "\n".join(parts)


def figure(res: dict[str, Any], text: str) -> dict[str, Any]:
    hits = [f for f in res["figures"] if f["text"] == text or text in f["text"]]
    assert len(hits) == 1, (text, res["figures"])
    return hits[0]


def ref_out(res: dict[str, Any], **match: str) -> dict[str, Any]:
    hits = [r for r in res["refs"] if all(r["ref"].get(k) == v for k, v in match.items())]
    assert len(hits) == 1, (match, res["refs"])
    return hits[0]


def comparable(f: dict[str, Any]) -> dict[str, Any]:
    """A figure's result without its ref, to compare a claim ref with its engine item."""
    return {k: v for k, v in f.items() if k != "ref"}


# ------------------------------------------------------------------ the call's shape


def test_J4_result_shape(env: J4Env, run: str) -> None:
    text = f"{IMG3} had a click-through rate of 4.4%, but it is still a rough estimate."
    res = env.figures(text, [run_ref(run)])
    assert set(res) >= {
        "passed",
        "figures",
        "refs",
        "reasons",
        "engine_version",
        "inputs_hash",
        "checked_at",
    }
    assert isinstance(res["engine_version"], str) and res["engine_version"]
    assert re.fullmatch(r"[0-9a-f]{64}", res["inputs_hash"])
    checked = dt.datetime.fromisoformat(res["checked_at"].replace("Z", "+00:00"))
    assert checked.utcoffset() == dt.timedelta(0)  # UTC ISO 8601
    json.dumps(res)  # JSON-native
    f = res["figures"][0]
    assert set(f) >= set(F.FigureOut.__annotations__)
    assert set(res["refs"][0]) >= set(F.RefOut.__annotations__)


def test_J4_inputs_hash_covers_text_and_refs(env: J4Env, run: str) -> None:
    text = f"{IMG3} had a click-through rate of 4.4%, but it is still a rough estimate."
    a = env.figures(text, [run_ref(run)])
    b = env.figures(text, [run_ref(run)])
    c = env.figures(text.replace("but it", "and it"), [run_ref(run)])
    assert a["inputs_hash"] == b["inputs_hash"]
    assert a["inputs_hash"] != c["inputs_hash"]


# ------------------------------------------------------------------ (a), (b): caveat on marginal


def test_J4_a_marginal_ctr_with_caveat_passes(env: J4Env, run: str) -> None:
    text = f"{IMG3} had a click-through rate of 4.4%, but it is still a rough estimate."
    res = env.figures(text, [run_ref(run)])
    assert res["passed"] is True, all_reasons(res)  # J4 check (a)
    f = figure(res, "4.4%")
    assert f["placed"] is True
    assert f["value_at_rounding"] == "4.4%"
    assert f["should_read"] is None
    assert f["caveat_required"] is True and f["caveat_present"] is True
    assert f["reasons"] == []
    assert f["quantity"]["name"] == "ctr"
    assert f["quantity"]["subject"] == IMG3_ID
    assert f["quantity"]["status"] == "marginal"
    assert f["ref"]["kind"] == "run" and f["ref"]["run_id"] == run
    r = ref_out(res, kind="run", run_id=run)
    assert r["newest"] is True
    assert r["window_end"] == "2026-11-07"
    assert isinstance(r["saved_at"], str) and r["saved_at"]


def test_J4_b_marginal_ctr_without_caveat_fails(env: J4Env, run: str) -> None:
    res = env.figures(f"{IMG3} had a click-through rate of 4.4%.", [run_ref(run)])
    assert res["passed"] is False  # J4 check (b)
    f = figure(res, "4.4%")
    assert f["placed"] is True
    assert f["caveat_required"] is True and f["caveat_present"] is False
    assert any(F.R_CAVEAT in r for r in f["reasons"]), f["reasons"]  # names the caveat


@pytest.mark.parametrize(
    "caveat",
    ["this estimate is still rough", "still rough", "a rough estimate", "still an estimate"],
)
def test_J4_caveat_registry_phrases_pass(env: J4Env, run: str, caveat: str) -> None:
    """J4 point 5, S7: caveat_marginal or any caveat_marginal_aliases entry, anywhere."""
    res = env.figures(f"{IMG3} had a click-through rate of 4.4%, and {caveat}.", [run_ref(run)])
    assert res["passed"] is True, all_reasons(res)
    assert figure(res, "4.4%")["caveat_present"] is True


def test_J4_caveat_before_a_clause_split_still_counts(env: J4Env, run: str) -> None:
    """J4 point 5: a clause split must not cut the caveat off."""
    text = f"It is still a rough estimate, but {IMG3} had a click-through rate of 4.4%."
    res = env.figures(text, [run_ref(run)])
    assert res["passed"] is True, all_reasons(res)


def test_J4_caveat_in_another_sentence_does_not_count(env: J4Env, run: str) -> None:
    text = f"This is still a rough estimate. {IMG3} had a click-through rate of 4.4%."
    res = env.figures(text, [run_ref(run)])
    assert res["passed"] is False
    assert figure(res, "4.4%")["caveat_present"] is False


def test_J4_estimable_needs_no_caveat(env: J4Env) -> None:
    run_id = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    env.ctr_44(run_id, status="estimable")
    res = env.figures(f"{IMG3} had a click-through rate of 4.4%.", [run_ref(run_id)])
    assert res["passed"] is True, all_reasons(res)
    f = figure(res, "4.4%")
    assert f["caveat_required"] is False
    assert f["quantity"]["status"] == "estimable"


# ------------------------------------------------------------------ (c): lead vocabulary


@pytest.mark.parametrize("metric", ["Cost per sign-up", "Cost per lead"])
def test_J4_c_cost_per_sign_up_on_lead_passes(env: J4Env, run: str, metric: str) -> None:
    env.set_quantity(run, IMG3_ID, "cpa", q50=3.35, mean=3.35)
    res = env.figures(f"{metric} for {IMG3} was $3.35, a rough estimate.", [run_ref(run)])
    assert res["passed"] is True, all_reasons(res)  # J4 check (c)
    f = figure(res, "$3.35")
    assert f["placed"] is True
    assert f["quantity"]["name"] == "cpa"
    assert f["value_at_rounding"] == "$3.35"  # cost-per money at unit_money_decimals (2)


def test_J4_c_cost_per_order_on_lead_fails_naming_sign_ups(env: J4Env, run: str) -> None:
    env.set_quantity(run, IMG3_ID, "cpa", q50=3.35, mean=3.35)
    res = env.figures(f"Cost per order for {IMG3} was $3.35, a rough estimate.", [run_ref(run)])
    assert res["passed"] is False  # J4 check (c)
    assert F.R_PURCHASE_WORD in all_reasons(res)


def test_J4_c_purchase_word_on_lead_fails(env: J4Env, run: str) -> None:
    """J4 point 3: "order" and "purchase" fail on a lead account."""
    env.set_quantity(run, IMG3_ID, "cpa", q50=3.35, mean=3.35)
    res = env.figures(f"Each purchase from {IMG3} cost $3.35, a rough estimate.", [run_ref(run)])
    assert res["passed"] is False
    assert F.R_PURCHASE_WORD in all_reasons(res)


def test_J4_cost_per_money_compares_at_cents(env: J4Env, run: str) -> None:
    """J4 point 4: cost-per money compares at unit_money_decimals; $3.36 is not $3.35."""
    env.set_quantity(run, IMG3_ID, "cpa", q50=3.35, mean=3.35)
    res = env.figures(f"Cost per sign-up for {IMG3} was $3.36, a rough estimate.", [run_ref(run)])
    assert res["passed"] is False
    f = figure(res, "$3.36")
    assert f["placed"] is False
    assert f["should_read"] == "$3.35"
    assert f["value_at_rounding"] == "$3.35"


# ------------------------------------------------------------------ (d), (e): notebook figures


def test_J4_d_spending_limit_passes_on_notebook_entry(env: J4Env, rel: str) -> None:
    res = env.figures("The account spending limit is $1,500.", [entry_ref(rel, E_LIMIT)])
    assert res["passed"] is True, all_reasons(res)  # J4 check (d)
    f = figure(res, "$1,500")
    assert f["placed"] is True
    assert f["value_at_rounding"] == "$1,500"
    assert f["should_read"] is None
    assert f["quantity"]["name"] == "account_spending_limit"
    assert f["quantity"]["subject"] == "account"
    assert f["quantity"]["status"] is None  # an observed figure has no status
    assert f["caveat_required"] is False
    r = ref_out(res, kind="notebook_entry", release_id=rel, entry_id=E_LIMIT)
    assert r["newest"] is True
    assert r["window_end"] is None
    assert r["saved_at"] == "2026-11-20T15:00:00+00:00"  # the release's created_at


def test_J4_d_spending_limit_named_among_other_money_passes(env: J4Env, rel: str) -> None:
    """The metric words pick the spending limit out of two $1,500 quantities."""
    refs = [entry_ref(rel, E_LIMIT), entry_ref(rel, E_BUDGET)]
    res = env.figures("The account spending limit is $1,500.", refs)
    assert res["passed"] is True, all_reasons(res)
    assert figure(res, "$1,500")["quantity"]["name"] == "account_spending_limit"


def test_J4_d_spending_limit_fails_with_only_a_run_ref(env: J4Env, run: str) -> None:
    res = env.figures("The account spending limit is $1,500.", [run_ref(run)])
    assert res["passed"] is False  # J4 check (d)
    f = figure(res, "$1,500")
    assert f["placed"] is False
    assert F.R_NOT_FOUND in "\n".join(f["reasons"])


def test_J4_e_wrong_spending_limit_gives_should_read(env: J4Env, rel: str) -> None:
    res = env.figures("The account spending limit is $1,600.", [entry_ref(rel, E_LIMIT)])
    assert res["passed"] is False  # J4 check (e)
    f = figure(res, "$1,600")
    assert f["placed"] is False
    assert f["should_read"] == "$1,500"
    assert f["value_at_rounding"] == "$1,500"
    assert f["quantity"]["name"] == "account_spending_limit"


def test_J4_unplaced_figure_gives_should_read_from_same_measure(env: J4Env, run: str) -> None:
    """J4 point 6: a quantity of the same unit, subject and metric with another value."""
    text = f"{IMG3} had a click-through rate of 9.9%, still a rough estimate."
    res = env.figures(text, [run_ref(run)])
    assert res["passed"] is False
    f = figure(res, "9.9%")
    assert f["placed"] is False
    assert f["should_read"] == "4.4%"


def test_J4_unplaced_figure_with_nothing_matched_has_nulls(env: J4Env, rel: str) -> None:
    """J4 point 6 and S7: nothing of the same unit and measure; both values null, never silent."""
    res = env.figures("The account has 37 sign-ups.", [entry_ref(rel, E_LIMIT)])
    assert res["passed"] is False
    f = figure(res, "37")
    assert f["placed"] is False
    assert f["value_at_rounding"] is None and f["should_read"] is None
    assert F.R_NOT_FOUND in "\n".join(f["reasons"])


# ------------------------------------------------------------------ (f): below floor


def test_J4_f_below_floor_fails_not_knowable(env: J4Env) -> None:
    run_id = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    env.ctr_44(run_id, status="below_floor")
    text = f"{IMG3} had a click-through rate of 4.4%, still a rough estimate."
    res = env.figures(text, [run_ref(run_id)])
    assert res["passed"] is False  # J4 check (f)
    f = figure(res, "4.4%")
    assert f["quantity"]["status"] == "below_floor"
    assert any(F.R_NOT_KNOWABLE in r for r in f["reasons"]), f["reasons"]


# ------------------------------------------------------------------ (g): claim refs


@pytest.mark.parametrize("amount", ["$1,500", "$1,600"])
def test_J4_g_notebook_claim_checked_like_its_entry(env: J4Env, rel: str, amount: str) -> None:
    text = f"The account spending limit is {amount}."
    by_entry = env.figures(text, [entry_ref(rel, E_LIMIT)])
    claim = claim_ref("clm_0001", release_id=rel, entry_id=E_LIMIT)
    by_claim = env.figures(text, [claim])
    assert by_claim["passed"] is by_entry["passed"]  # J4 check (g)
    assert by_claim["passed"] is (amount == "$1,500")
    assert [comparable(f) for f in by_claim["figures"]] == [
        comparable(f) for f in by_entry["figures"]
    ]
    f = figure(by_claim, amount)
    assert f["ref"]["kind"] == "claim" and f["ref"]["claim_id"] == "clm_0001"  # echoed
    assert any(r["ref"].get("claim_id") == "clm_0001" for r in by_claim["refs"])


def test_J4_g_posterior_claim_checked_like_its_quantity(env: J4Env, run: str) -> None:
    qid = env.quantity(run, IMG3_ID, "ctr")["quantity_id"]
    text = f"{IMG3} had a click-through rate of 4.4%, still a rough estimate."
    claim = claim_ref("clm_0002", run_id=run, quantity_id=qid)
    by_claim = env.figures(text, [claim])
    by_run = env.figures(text, [run_ref(run)])
    assert by_claim["passed"] is True, all_reasons(by_claim)
    assert [comparable(f) for f in by_claim["figures"]] == [
        comparable(f) for f in by_run["figures"]
    ]
    f = figure(by_claim, "4.4%")
    assert f["ref"]["claim_id"] == "clm_0002"


def test_J4_g_posterior_claim_checks_that_quantity_only(env: J4Env, run: str) -> None:
    """S5: the figure is checked against the claim's quantity only. 5.9% is the other ad's ctr
    in the same run, so it places with a run ref but not with a claim on IMG3_TXT1's ctr."""
    qid = env.quantity(run, IMG3_ID, "ctr")["quantity_id"]
    other = env.quantity(run, IMG2_ID, "ctr")["estimate"]["summary"]
    assert f"{other['q50'] * 100:.1f}%" == "5.9%"
    text = "The click-through rate was 5.9%, still a rough estimate."
    assert env.figures(text, [run_ref(run)])["passed"] is True
    res = env.figures(text, [claim_ref("clm_0003", run_id=run, quantity_id=qid)])
    assert res["passed"] is False
    assert figure(res, "5.9%")["placed"] is False


# ------------------------------------------------------------------ (h): no figures


def test_J4_h_no_figures_passes(env: J4Env, run: str) -> None:
    res = env.figures("The account is live and the ads are running.", [run_ref(run)])
    assert res["passed"] is True, all_reasons(res)
    assert res["figures"] == []
    assert res["reasons"] == []


def test_J4_h_date_and_ids_are_not_figures(env: J4Env, run: str, rel: str) -> None:
    text = f"On 26 November, run {run} was saved, and release {rel} holds entry {E_LIMIT}."
    res = env.figures(text, [run_ref(run), entry_ref(rel, E_LIMIT)])
    assert res["passed"] is True, all_reasons(res)  # J4 check (h)
    assert res["figures"] == []


def test_J4_h_years_and_times_are_not_figures(env: J4Env, run: str) -> None:
    res = env.figures("The ads went live at 9:30 on 7 November 2026.", [run_ref(run)])
    assert res["passed"] is True, all_reasons(res)
    assert res["figures"] == []


# ------------------------------------------------------------------ (i): unreadable refs


def test_J4_i_unknown_run_fails_naming_it(env: J4Env) -> None:
    res = env.figures("The account is live.", [run_ref("run_00000bad")])
    assert res["passed"] is False  # J4 check (i), no raise
    assert "run_00000bad" in all_reasons(res)


def test_J4_i_release_failing_verify_fails_naming_it(env: J4Env) -> None:
    bad = env.release(day="20261121", created_at=dt.datetime(2026, 11, 21, 15, 0, tzinfo=UTC))
    path = env.release_folder(bad) / "entries.jsonl"
    path.write_text(path.read_text().replace("$1,500", "$1,600", 1))
    with pytest.raises(ValueError):
        nb_release.verify(env.release_folder(bad))  # the fixture really fails verify
    res = env.figures("The account spending limit is $1,500.", [entry_ref(bad, E_LIMIT)])
    assert res["passed"] is False  # J4 check (i), no raise
    assert bad in all_reasons(res)


def test_J4_i_unknown_release_fails_naming_it(env: J4Env, rel: str) -> None:
    missing = "nb_lead_client_20261101_1"
    res = env.figures("The account is live.", [entry_ref(missing, E_LIMIT)])
    assert res["passed"] is False
    assert missing in all_reasons(res)


def test_J4_i_unknown_entry_fails_naming_it(env: J4Env, rel: str) -> None:
    unknown = "nbe_lead_client_9999"
    res = env.figures("The account is live.", [entry_ref(rel, unknown)])
    assert res["passed"] is False  # J4 check (i), no raise
    assert unknown in all_reasons(res)


def test_J4_i_unknown_claim_item_fails_naming_it(env: J4Env, rel: str) -> None:
    unknown = "nbe_lead_client_9998"
    res = env.figures(
        "The account is live.", [claim_ref("clm_0009", release_id=rel, entry_id=unknown)]
    )
    assert res["passed"] is False
    reasons = all_reasons(res)
    assert unknown in reasons or "clm_0009" in reasons


# ------------------------------------------------------------------ wrong argument types


@pytest.mark.parametrize(
    ("text", "refs"),
    [(123, []), (None, []), ("The account is live.", "run_x"), ("The account is live.", {})],
    ids=["text_int", "text_none", "refs_str", "refs_dict"],
)
def test_J4_wrong_argument_type_raises(text: Any, refs: Any) -> None:
    with pytest.raises(TypeError):
        sock.check_client_figures(text, refs)


# ------------------------------------------------------------------ (j): names with an en dash


@pytest.mark.parametrize(
    "name",
    [
        "IMG2_TXT1 \u2013 Updated.",  # as in the source, with an en dash
        "IMG2_TXT1 - Updated.",  # hyphen
        "IMG2_TXT1 Updated.",  # spaces
        "img2_txt1 - updated.",  # case ignored
    ],
    ids=["en_dash", "hyphen", "spaces", "lower_case"],
)
def test_J4_j_name_with_en_dash_matches(env: J4Env, rel: str, name: str) -> None:
    """Both ads' ctr is 5.9% here, so the figure places only if the name picks IMG2's ad,
    and the name is known only from the notebook source object (the snapshot's names are
    emptied, and the fake load_names gives none)."""
    run_id = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    env.set_names(run_id, {})
    for ad in (IMG3_ID, IMG2_ID):
        env.set_quantity(run_id, ad, "ctr", q50=0.059, mean=0.059, q05=0.055, q95=0.064)
    refs = [run_ref(run_id), entry_ref(rel, E_AD2)]
    res = env.figures(f"{name} had a click-through rate of 5.9%, still a rough estimate.", refs)
    assert res["passed"] is True, all_reasons(res)  # J4 check (j)
    f = figure(res, "5.9%")
    assert f["placed"] is True
    assert f["quantity"]["subject"] == IMG2_ID


def test_J4_j_ambiguous_without_the_name(env: J4Env, rel: str) -> None:
    """S10, and the guard for (j): with no ad named, two equal ctrs are ambiguous."""
    run_id = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    env.set_names(run_id, {})
    for ad in (IMG3_ID, IMG2_ID):
        env.set_quantity(run_id, ad, "ctr", q50=0.059, mean=0.059, q05=0.055, q95=0.064)
    refs = [run_ref(run_id), entry_ref(rel, E_AD2)]
    res = env.figures("The click-through rate was 5.9%, still a rough estimate.", refs)
    assert res["passed"] is False
    f = figure(res, "5.9%")
    assert F.R_AMBIGUOUS in "\n".join(f["reasons"])
    reasons = "\n".join(f["reasons"])
    assert IMG3_ID in reasons or IMG3 in reasons  # lists both candidates
    assert IMG2_ID in reasons or "IMG2_TXT1" in reasons


# ------------------------------------------------------------------ (k): probability


@pytest.mark.parametrize("said", ["a 62% chance", "a 0.62 chance"], ids=["percent", "decimal"])
def test_J4_k_probability_as_percent_or_decimal(env: J4Env, rel: str, said: str) -> None:
    res = env.figures(f"{IMG3} has {said}, still an estimate.", [entry_ref(rel, E_PBEST)])
    assert res["passed"] is True, all_reasons(res)  # J4 check (k), S8
    f = res["figures"][0]
    assert len(res["figures"]) == 1
    assert f["placed"] is True
    assert f["quantity"]["name"] == "p_best"
    assert f["value_at_rounding"] in ("62%", "0.62")


def test_J4_k_probability_wrong_value_fails(env: J4Env, rel: str) -> None:
    res = env.figures(f"{IMG3} has a 71% chance, still an estimate.", [entry_ref(rel, E_PBEST)])
    assert res["passed"] is False
    assert figure(res, "71%")["placed"] is False


# ------------------------------------------------------------------ (l): ambiguity


def test_J4_l_two_equal_figures_unnamed_fails_listing_both(env: J4Env, rel: str) -> None:
    refs = [entry_ref(rel, E_LIMIT), entry_ref(rel, E_BUDGET)]
    res = env.figures("The figure we have is $1,500.", refs)
    assert res["passed"] is False  # J4 check (l)
    f = figure(res, "$1,500")
    assert f["placed"] is False
    reasons = "\n".join(f["reasons"])
    assert F.R_AMBIGUOUS in reasons
    low = reasons.lower()
    assert "spending_limit" in low or "spending limit" in low  # lists both candidates
    assert "lifetime_budget" in low or "lifetime budget" in low


# ------------------------------------------------------------------ (m): two clients


def test_J4_m_refs_from_two_clients_fail(env: J4Env, run: str) -> None:
    env.write_config(config(client_id=OTHER))
    other_entry = X._entry(
        E_OTHER,
        "constraint",
        "The account spending limit is $1,500.",
        "observed",
        "account",
        quantities=[{"name": "account_spending_limit", "value": 1500, "unit": "USD"}],
    )
    other = env.release([other_entry], client_id=OTHER)
    refs = [run_ref(run), entry_ref(other, E_OTHER)]
    text = f"{IMG3} had a click-through rate of 4.4%, still a rough estimate."
    res = env.figures(text, refs)
    assert res["passed"] is False  # J4 check (m)
    assert F.R_TWO_CLIENTS in "\n".join(res["reasons"])


# ------------------------------------------------------------------ (n): quantities in words


def test_J4_n_spelled_dollars_place_on_cpa(env: J4Env, run: str) -> None:
    """S17: "three dollars" compares at whole dollars and places on a cpa of 3.35; on a lead run
    value_at_rounding gives the 2-decimal display."""
    env.set_quantity(run, IMG3_ID, "cpa", q50=3.35, mean=3.35)
    text = f"{IMG3} came to about three dollars a sign-up, still a rough estimate."
    res = env.figures(text, [run_ref(run)])
    assert res["passed"] is True, all_reasons(res)  # J4 check (n)
    assert len(res["figures"]) == 1
    f = res["figures"][0]
    assert f["placed"] is True
    assert f["quantity"]["name"] == "cpa"
    assert f["value_at_rounding"] == "$3.35"  # S17
    assert f["should_read"] is None


def test_J4_n_spelled_dollars_fail_on_another_cpa(env: J4Env, run: str) -> None:
    env.set_quantity(run, IMG3_ID, "cpa", q50=4.0, mean=4.0)
    text = f"{IMG3} came to about three dollars a sign-up, still a rough estimate."
    res = env.figures(text, [run_ref(run)])
    assert res["passed"] is False  # J4 check (n)
    assert len(res["figures"]) == 1
    assert res["figures"][0]["placed"] is False


@pytest.mark.parametrize(
    "text",
    [f"Sign-ups for {IMG3} doubled.", "The ads have used a third of the budget."],
    ids=["doubled", "a_third"],
)
def test_J4_n_quantities_in_words_fail(env: J4Env, run: str, rel: str, text: str) -> None:
    res = env.figures(text, [run_ref(run), entry_ref(rel, E_LIMIT), entry_ref(rel, E_BUDGET)])
    assert res["passed"] is False  # J4 check (n), P1
    assert F.R_WORDS in all_reasons(res)


def test_J4_n_quantity_in_words_passes_with_its_figures_placed(env: J4Env, rel: str) -> None:
    """P1: a fraction passes when the figures it rests on are in the sentence and placed."""
    text = "The amount spent is $750, half of the account spending limit of $1,500."
    res = env.figures(text, [entry_ref(rel, E_SPENT), entry_ref(rel, E_LIMIT)])
    assert res["passed"] is True, all_reasons(res)
    assert figure(res, "$750")["placed"] is True
    assert figure(res, "$1,500")["placed"] is True
    assert F.R_WORDS not in all_reasons(res)


def test_J4_n_quantity_in_words_fails_when_a_figure_is_not_placed(env: J4Env, rel: str) -> None:
    text = "The amount spent is $700, half of the account spending limit of $1,500."
    res = env.figures(text, [entry_ref(rel, E_SPENT), entry_ref(rel, E_LIMIT)])
    assert res["passed"] is False
    assert F.R_WORDS in all_reasons(res)


# ------------------------------------------------------------------ (o): bounds


def test_J4_o_lone_q95_as_value_fails(env: J4Env, run: str) -> None:
    text = f"The click rate for {IMG3} is 4.7%, still a rough estimate."
    res = env.figures(text, [run_ref(run)])
    assert res["passed"] is False  # J4 check (o), P2
    f = figure(res, "4.7%")
    assert f["should_read"] == "4.4%"
    assert any(F.R_LONE_BOUND in r for r in f["reasons"]), f["reasons"]


@pytest.mark.parametrize(
    "said",
    ["is between 4.0% and 4.7%", "is 4.0% to 4.7%", "could be as high as 4.7%"],
    ids=["between", "to", "as_high_as"],
)
def test_J4_o_bounds_marked_as_bounds_pass(env: J4Env, run: str, said: str) -> None:
    text = f"The click rate for {IMG3} {said}, still a rough estimate."
    res = env.figures(text, [run_ref(run)])
    assert res["passed"] is True, all_reasons(res)  # J4 check (o)
    assert all(f["placed"] for f in res["figures"])
    assert "4.7%" in {f["text"] for f in res["figures"]} or any(
        "4.7%" in f["text"] for f in res["figures"]
    )


def test_J4_o_at_least_lower_bound_passes(env: J4Env, run: str) -> None:
    text = f"The click rate for {IMG3} is at least 4.0%, still a rough estimate."
    res = env.figures(text, [run_ref(run)])
    assert res["passed"] is True, all_reasons(res)


# ------------------------------------------------------------------ (p): staleness


def test_J4_p_run_refs_report_newest(env: J4Env) -> None:
    old, new = env.old_and_new_runs()
    env.ctr_44(old)
    env.ctr_44(new)
    text = f"{IMG3} had a click-through rate of 4.4%, still a rough estimate."
    res_old = env.figures(text, [run_ref(old)])
    res_new = env.figures(text, [run_ref(new)])
    r_old = ref_out(res_old, kind="run", run_id=old)
    r_new = ref_out(res_new, kind="run", run_id=new)
    assert r_old["newest"] is False and r_old["window_end"] == "2026-11-07"
    assert r_new["newest"] is True and r_new["window_end"] == "2026-11-08"
    assert res_new["passed"] is True, all_reasons(res_new)


def test_J4_p_stale_run_in_present_tense_fails(env: J4Env) -> None:
    old, _new = env.old_and_new_runs()
    env.ctr_44(old)
    text = f"{IMG3} has a click-through rate of 4.4%, still a rough estimate."
    res = env.figures(text, [run_ref(old)])
    assert res["passed"] is False  # J4 check (p), P3
    f = figure(res, "4.4%")
    assert any(F.R_STALE in r for r in f["reasons"]), f["reasons"]


@pytest.mark.parametrize(
    "lead_in", ["As of 20 November, ", "On 7 November, "], ids=["as_of", "date"]
)
def test_J4_p_stale_run_dated_passes(env: J4Env, lead_in: str) -> None:
    old, _new = env.old_and_new_runs()
    env.ctr_44(old)
    text = f"{lead_in}{IMG3} had a click-through rate of 4.4%, still a rough estimate."
    res = env.figures(text, [run_ref(old)])
    assert res["passed"] is True, all_reasons(res)  # J4 check (p)
    assert F.R_STALE not in all_reasons(res)


def _two_releases(env: J4Env) -> tuple[str, str]:
    """S21: r2 has the greater day and names r1 as its parent; its created_at is the earlier,
    so created_at alone would pick r1."""
    r1 = env.release(day="20261120", created_at=dt.datetime(2026, 11, 26, 15, 0, tzinfo=UTC))
    r2 = env.release(
        day="20261126", created_at=dt.datetime(2026, 11, 20, 15, 0, tzinfo=UTC), parent=r1
    )
    return r1, r2


def test_J4_p_superseded_release_reports_not_newest(env: J4Env) -> None:
    r1, r2 = _two_releases(env)
    text = "As of 20 November, the account spending limit was $1,500."
    res1 = env.figures(text, [entry_ref(r1, E_LIMIT)])
    res2 = env.figures(text, [entry_ref(r2, E_LIMIT)])
    assert ref_out(res1, kind="notebook_entry", release_id=r1)["newest"] is False
    assert ref_out(res2, kind="notebook_entry", release_id=r2)["newest"] is True


def test_J4_p_superseded_release_in_present_tense_fails(env: J4Env) -> None:
    r1, _r2 = _two_releases(env)
    res = env.figures("The account spending limit is $1,500.", [entry_ref(r1, E_LIMIT)])
    assert res["passed"] is False  # J4 check (p)
    f = figure(res, "$1,500")
    assert any(F.R_STALE in r for r in f["reasons"]), f["reasons"]


def test_J4_p_superseded_release_dated_passes(env: J4Env) -> None:
    r1, _r2 = _two_releases(env)
    res = env.figures(
        "As of 20 November, the account spending limit was $1,500.", [entry_ref(r1, E_LIMIT)]
    )
    assert res["passed"] is True, all_reasons(res)  # J4 check (p)


def test_J4_p_newest_release_in_present_tense_passes(env: J4Env) -> None:
    _r1, r2 = _two_releases(env)
    res = env.figures("The account spending limit is $1,500.", [entry_ref(r2, E_LIMIT)])
    assert res["passed"] is True, all_reasons(res)


# ------------------------------------------------------------------ (q): derived figures


def test_J4_q_derived_difference_fails_naming_derived(env: J4Env, run: str) -> None:
    res = env.figures(f"{IMG3} spent $200 more than last week.", [run_ref(run)])
    assert res["passed"] is False  # J4 check (q), P5
    f = figure(res, "$200")
    assert f["placed"] is False
    reasons = "\n".join(f["reasons"])
    assert F.R_NOT_FOUND in reasons
    assert "derived" in reasons


# ------------------------------------------------------------------ P4: the loaders


def test_J4_P4_load_run_is_used(env: J4Env, run: str) -> None:
    """The loader's snapshot gives IMG3_TXT1's ctr as 5.1%; the file on disk says 4.4%."""
    data = json.loads(env.snapshot_file(run).read_text())
    for q in data["quantities"]:
        if q["name"] == "ctr" and q["scope"]["ids"] == {"ad": IMG3_ID}:
            q["estimate"]["summary"].update(q50=0.051, mean=0.051, q05=0.047, q95=0.055)
    snap = pipeline.RunSnapshot.model_validate(data)
    calls: list[str] = []

    def load_run(run_id: str) -> pipeline.RunSnapshot:
        calls.append(run_id)
        if run_id != run:
            raise KeyError(run_id)
        return snap

    text = f"{IMG3} had a click-through rate of 5.1%, still a rough estimate."
    res = env.figures(text, [run_ref(run)], load_run=load_run)
    assert run in calls  # P4
    assert res["passed"] is True, all_reasons(res)
    assert figure(res, "5.1%")["value_at_rounding"] == "5.1%"


def test_J4_P4_load_release_is_used(env: J4Env, rel: str) -> None:
    """The loader's release gives the spending limit as $1,600; the files on disk say $1,500."""
    folder = env.release_folder(rel)
    catalog = json.loads((folder / "catalog.json").read_text())
    entries = [json.loads(x) for x in (folder / "entries.jsonl").read_text().splitlines()]
    srcs = [json.loads(x) for x in (folder / "sources.jsonl").read_text().splitlines()]
    for e in entries:
        for q in e.get("quantities", []):
            if q["name"] == "account_spending_limit":
                q["value"] = 1600
    calls: list[str] = []

    def load_release(release_id: str) -> tuple[dict, list[dict], list[dict]]:
        calls.append(release_id)
        if release_id != rel:
            raise KeyError(release_id)
        return catalog, entries, srcs

    res = env.figures(
        "The account spending limit is $1,600.",
        [entry_ref(rel, E_LIMIT)],
        load_release=load_release,
    )
    assert rel in calls  # P4
    assert res["passed"] is True, all_reasons(res)
    assert figure(res, "$1,600")["value_at_rounding"] == "$1,600"


def test_J4_P4_load_release_that_raises_fails_without_raising(env: J4Env, rel: str) -> None:
    def load_release(release_id: str) -> tuple[dict, list[dict], list[dict]]:
        raise ValueError(f"{release_id} does not verify")

    res = env.figures(
        "The account spending limit is $1,500.",
        [entry_ref(rel, E_LIMIT)],
        load_release=load_release,
    )
    assert res["passed"] is False
    assert rel in all_reasons(res)


# ------------------------------------------------------------------ S16: names


def _equal_ctrs(env: J4Env) -> str:
    """A run where both ads' ctr is 4.4%, so only a resolved name can place the figure."""
    run_id = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    env.ctr_44(run_id, ad=IMG3_ID)
    env.ctr_44(run_id, ad=IMG2_ID)
    return run_id


NAMED_TEXT = f"{IMG3} had a click-through rate of 4.4%, still a rough estimate."


def test_J4_S16_a_name_from_snapshot_entity_names(env: J4Env) -> None:
    run_id = _equal_ctrs(env)
    assert env.snapshot(run_id).entity_names[IMG3_ID] == IMG3
    res = env.figures(NAMED_TEXT, [run_ref(run_id)])
    assert res["passed"] is True, all_reasons(res)  # S16 (a): run-only ref, named by name
    f = figure(res, "4.4%")
    assert f["placed"] is True
    assert f["quantity"]["subject"] == IMG3_ID


def test_J4_S16_b_name_from_load_names_when_snapshot_has_none(env: J4Env) -> None:
    run_id = _equal_ctrs(env)
    env.set_names(run_id, {})
    calls: list[str] = []

    def load_names(client_id: str) -> dict[str, str]:
        calls.append(client_id)
        return {IMG3_ID: IMG3, IMG2_ID: IMG2_NAME}

    res = env.figures(NAMED_TEXT, [run_ref(run_id)], load_names=load_names)
    assert X.CLIENT in calls  # S16 (b): the injected loader is asked for the client's names
    assert res["passed"] is True, all_reasons(res)
    assert figure(res, "4.4%")["quantity"]["subject"] == IMG3_ID


def test_J4_S16_b_guard_no_names_anywhere_is_ambiguous(env: J4Env) -> None:
    """Guard for (b): with no names from any source, the two equal ctrs cannot be told apart."""
    run_id = _equal_ctrs(env)
    env.set_names(run_id, {})
    res = env.figures(NAMED_TEXT, [run_ref(run_id)])
    assert res["passed"] is False
    assert F.R_AMBIGUOUS in "\n".join(figure(res, "4.4%")["reasons"])


def test_J4_S16_c_name_mapping_to_two_ids_is_unnamed(env: J4Env) -> None:
    run_id = _equal_ctrs(env)
    env.set_names(run_id, {IMG3_ID: IMG3, IMG2_ID: IMG3})
    res = env.figures(NAMED_TEXT, [run_ref(run_id)])
    assert res["passed"] is False  # S16 (c): treated as unnamed, so ambiguous
    f = figure(res, "4.4%")
    assert f["placed"] is False
    assert F.R_AMBIGUOUS in "\n".join(f["reasons"])


# ------------------------------------------------------------------ S17: money precision


def test_J4_S17_whole_dollars_place_on_cpa_of_3_35(env: J4Env, run: str) -> None:
    env.set_quantity(run, IMG3_ID, "cpa", q50=3.35, mean=3.35)
    res = env.figures(f"Cost per sign-up for {IMG3} was $3, a rough estimate.", [run_ref(run)])
    assert res["passed"] is True, all_reasons(res)  # S17
    f = figure(res, "$3")
    assert f["placed"] is True
    assert f["quantity"]["name"] == "cpa"
    assert f["value_at_rounding"] == "$3.35"  # S17: the lead 2-decimal display
    assert f["should_read"] is None


def test_J4_S17_cents_compare_at_cents_on_cpa_of_3_35(env: J4Env, run: str) -> None:
    env.set_quantity(run, IMG3_ID, "cpa", q50=3.35, mean=3.35)
    ok = env.figures(f"Cost per sign-up for {IMG3} was $3.35, a rough estimate.", [run_ref(run)])
    assert ok["passed"] is True, all_reasons(ok)
    bad = env.figures(f"Cost per sign-up for {IMG3} was $3.30, a rough estimate.", [run_ref(run)])
    assert bad["passed"] is False  # S17: "$3.30" is compared at cents
    f = figure(bad, "$3.30")
    assert f["placed"] is False
    assert f["should_read"] == "$3.35"


# ------------------------------------------------------------------ S18: estimated notebook


def test_J4_S18_estimated_notebook_quantity_needs_caveat(env: J4Env, rel: str) -> None:
    res = env.figures(f"{IMG3} has a 62% chance.", [entry_ref(rel, E_PBEST)])
    assert res["passed"] is False  # S18
    f = figure(res, "62%")
    assert f["placed"] is True
    assert f["caveat_required"] is True and f["caveat_present"] is False
    assert any(F.R_CAVEAT in r for r in f["reasons"]), f["reasons"]


def test_J4_S18_estimated_notebook_quantity_with_caveat_passes(env: J4Env, rel: str) -> None:
    res = env.figures(
        f"{IMG3} has a 62% chance, still a rough estimate.", [entry_ref(rel, E_PBEST)]
    )
    assert res["passed"] is True, all_reasons(res)  # S18
    f = figure(res, "62%")
    assert f["caveat_required"] is True and f["caveat_present"] is True


def test_J4_S18_observed_notebook_quantity_needs_no_caveat(env: J4Env, rel: str) -> None:
    res = env.figures("The account spending limit is $1,500.", [entry_ref(rel, E_LIMIT)])
    assert res["passed"] is True, all_reasons(res)
    assert figure(res, "$1,500")["caveat_required"] is False


# ------------------------------------------------------------------ S19: unreadable forms


@pytest.mark.parametrize(
    "said",
    [
        "a click-through rate of 3.3.5",
        "a click-through rate of 4,4%",
        "1e3 link clicks",
        "a cost per sign-up of $3k",
        "1.2M impressions",
    ],
    ids=["two_points", "decimal_comma", "exponent", "scaled_k", "scaled_M"],
)
def test_J4_S19_unreadable_form_fails(env: J4Env, run: str, said: str) -> None:
    res = env.figures(f"{IMG3} had {said}, still a rough estimate.", [run_ref(run)])
    assert res["passed"] is False  # S19
    assert F.R_UNREADABLE_FORM in all_reasons(res)


# ------------------------------------------------------------------ S20: comparatives


def _comparative_reasons(reasons: list[str]) -> list[str]:
    """G5's comparative reasons. G5 also reads a numeric ad id as a number ("number matches no
    bundle value"), which J4 does not (an ad is named by its id), so only these are compared."""
    return [r for r in reasons if "'beat'" in r]


def test_J4_S20_comparative_refused_by_check_narrative_fails_here(env: J4Env, run: str) -> None:
    """IMG2's ctr is the higher (p_best near 1), so "IMG3 beat IMG2" is refused by G5's comparative
    check on the same run; that reason is added here as a sentence-level reason."""
    text = f"Ad {IMG3_ID} beat ad {IMG2_ID} on click-through rate."
    g5 = _comparative_reasons(env.check(run, text)["reasons"])
    assert g5, "precondition: check_narrative refuses the comparative"
    res = env.figures(text, [run_ref(run)])
    assert res["passed"] is False  # S20
    for reason in g5:
        assert reason in res["reasons"], (reason, res["reasons"])


def test_J4_S20_guard_comparative_check_narrative_accepts(env: J4Env, run: str) -> None:
    """Guard: the comparative G5 accepts on the run ("IMG2 beat IMG3") adds no reason here."""
    text = f"Ad {IMG2_ID} beat ad {IMG3_ID} on click-through rate."
    assert not _comparative_reasons(env.check(run, text)["reasons"])  # precondition
    res = env.figures(text, [run_ref(run)])
    assert res["passed"] is True, all_reasons(res)
    assert res["figures"] == []


def test_J4_S20_comparative_without_a_run_ref_fails(env: J4Env, rel: str) -> None:
    env.store_names = {IMG3_ID: IMG3, IMG4_ID: IMG4}
    res = env.figures(f"{IMG3} beat {IMG4}.", [entry_ref(rel, E_PBEST)])
    assert res["passed"] is False  # S20
    assert F.R_NEEDS_RUN in "\n".join(res["reasons"])


# ------------------------------------------------------------------ S21: newest


def test_J4_S21_newest_run_by_run_record_started_at(env: J4Env) -> None:
    """The run written second, with the newer file mtime, is the older by started_at."""
    old, new = env.old_and_new_runs()
    assert env.snapshot_file(old).stat().st_mtime > env.snapshot_file(new).stat().st_mtime
    res = env.figures("The account is live.", [run_ref(old), run_ref(new)])
    assert ref_out(res, kind="run", run_id=old)["newest"] is False  # S21
    assert ref_out(res, kind="run", run_id=new)["newest"] is True


def test_J4_S21_newest_release_by_n_within_a_day(env: J4Env) -> None:
    a = env.release(day="20261126", created_at=dt.datetime(2026, 11, 26, 18, 0, tzinfo=UTC))
    b = env.release(day="20261126", created_at=dt.datetime(2026, 11, 26, 9, 0, tzinfo=UTC))
    assert a.endswith("_1") and b.endswith("_2")
    res = env.figures("The account is live.", [entry_ref(a, E_LIMIT), entry_ref(b, E_LIMIT)])
    assert ref_out(res, kind="notebook_entry", release_id=a)["newest"] is False  # S21
    assert ref_out(res, kind="notebook_entry", release_id=b)["newest"] is True


def test_J4_S21_a_parent_release_is_never_newest(env: J4Env) -> None:
    """The release with the greatest (day, n) is named as another's parent, so it is not newest."""
    top = env.release(day="20261126", created_at=dt.datetime(2026, 11, 26, 15, 0, tzinfo=UTC))
    env.release(day="20261121", created_at=dt.datetime(2026, 11, 27, 15, 0, tzinfo=UTC), parent=top)
    res = env.figures("The account is live.", [entry_ref(top, E_LIMIT)])
    assert ref_out(res, kind="notebook_entry", release_id=top)["newest"] is False  # S21


# ------------------------------------------------------------------ S22: generic money words


def test_J4_S22_budget_alone_does_not_settle_ambiguity(env: J4Env, rel: str) -> None:
    refs = [entry_ref(rel, E_LIMIT), entry_ref(rel, E_BUDGET)]
    res = env.figures("The budget is $1,500.", refs)
    assert res["passed"] is False  # S22: "budget" names no measure
    f = figure(res, "$1,500")
    assert f["placed"] is False
    assert F.R_AMBIGUOUS in "\n".join(f["reasons"])
