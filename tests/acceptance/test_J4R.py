"""J4R: rendered figure slots (Brain join spec v0.4, J4R "Checks" and A1 to A6).

Every case calls through the socket entries ``bayesian_marketing.atmaos.socket.client_slots`` and
``render_client_text`` against fixture runs and fixture notebook releases (``j4_fixtures``,
``j4r_fixtures``), never the live store, the real notebook or ``configs/``.

Kept from J4, as slot rendering: (f) below floor, (i) unreadable refs, (m) two clients, (p)
staleness, P4 loaders, S16 names, S21 newest and the J5 lead labels. Reasons are asserted by
substring of the skeleton's ``R_*`` constants in ``claims/slots.py``, and every numeral-rule
refusal must also quote the word or character it refused (A6).

Rendered phrases are the J4R forms table with the fixture's names and values: IMG3_TXT1's ctr at
a median and mean of 4.4%, the account spending limit of $1,500, and a comparison record giving
IMG3_TXT1 a p_best of 0.621 on clicks. The "as of" date of a ref that is not the newest is the
day its figures are as of: 7 November for the older run (window end, as_of and started_at all
agree) and 20 November for the older release (day, created_at and entries' as_of all agree).

C7: every case of the two blind-review files of the free-text J4 (tests/review/test_J4_review.py
at 71f4a75 and test_J4_review2.py at b3e71c9) is re-expressed as the text the persona might write:
the same sentence, its ads as ``name`` slots and its figure written out. Ad names hold digits
("IMG3_TXT1"), so a name written out would trip the numeral rule by itself and prove nothing;
written as a slot, the only thing left to trip it is the figure. Each such case must fail the
numeral rule quoting its figure. Cases whose wrong content was a comparative ("A leads B",
"likely the best") must fail the comparative lint with the figure moved into its slot.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import pytest

from bayesian_marketing.atmaos import socket as sock
from bayesian_marketing.claims import slots as S
from bayesian_marketing.notebook import release as nb_release
from tests.acceptance import j4_fixtures as X
from tests.acceptance.j4_fixtures import (
    CLIENT,
    E_LIMIT,
    E_OTHER,
    IMG2_ID,
    IMG2_NAME,
    IMG3,
    IMG3_ID,
    OTHER,
)
from tests.acceptance.j4r_fixtures import (
    CURRENCY_SIGNS,
    ISO_CODES,
    NUMERIC_CHARS,
    WORD_FORMS,
    J4REnv,
    cmp_run,
    date_slot,
    fig_nb,
    fig_run,
    name_slot,
    slot_of_token,
)

pytestmark = pytest.mark.piece("J4R")

UTC = dt.UTC
A, B = name_slot(IMG3_ID), name_slot(IMG2_ID)
LIMIT = "account_spending_limit"

# The forms table (C4), IMG3_TXT1's ctr at 4.4%.
FULL = {
    "estimable": f"{IMG3}'s click-through rate of 4.4%",
    "marginal": f"{IMG3}'s click-through rate of about 4.4%, still a rough estimate",
    "below_floor": f"{IMG3}'s click-through rate, which is not knowable yet",
}
START = {
    "estimable": f"{IMG3}'s click-through rate is 4.4%",
    "marginal": f"{IMG3}'s click-through rate is about 4.4%, still a rough estimate",
    "below_floor": f"{IMG3}'s click-through rate is not knowable yet",
}
OBSERVED_FULL = "the account spending limit of $1,500"
OBSERVED_START = "The account spending limit is $1,500"
CMP_FULL = f"{IMG3}, which leads on clicks with a 62% chance of being best"
CMP_START = f"{IMG3} leads on clicks, with a 62% chance of being best"  # A5
CMP_FLOOR = "which ad is best, not knowable yet"
ROUGH = "still a rough estimate"
AS_OF_RUN = ", as of 7 November"
AS_OF_REL = ", as of 20 November"


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> J4REnv:
    return J4REnv(tmp_path, monkeypatch)


@pytest.fixture
def run(env: J4REnv) -> str:
    """One lead run (the client's only, so newest); IMG3_TXT1's ctr marginal at 4.4%."""
    run_id = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    env.ctr_44(run_id)
    return run_id


@pytest.fixture
def rel(env: J4REnv) -> str:
    """The fixture notebook release (the client's only, so newest)."""
    return env.release()


# ------------------------------------------------------------------ helpers


def all_reasons(res: dict[str, Any]) -> str:
    parts = list(res["reasons"]) + list(res.get("lint") or [])
    for s in res.get("slots") or []:
        parts += s["reasons"]
    return "\n".join(parts)


def why(res: dict[str, Any]) -> str:
    return repr({"ok": res.get("ok"), "text": res.get("text"), "reasons": all_reasons(res)})


def assert_ok(res: dict[str, Any], text: str) -> None:
    assert res["ok"] is True, why(res)
    assert res["text"] == text, (res["text"], text)
    assert res["reasons"] == [], res["reasons"]


def assert_refused(res: dict[str, Any], reason: str, word: str | None = None) -> None:
    """``ok`` False, ``text`` None, and a reason holding ``reason`` (and ``word``, case folded)."""
    assert res["ok"] is False, why(res)
    assert res["text"] is None  # never a partial rendering
    lines = all_reasons(res).splitlines()
    hits = [r for r in lines if reason in r]
    assert hits, (reason, lines)
    if word is not None:
        forms = {word.casefold(), unicodedata.normalize("NFKC", word).casefold()}
        assert any(f in r.casefold() for r in hits for f in forms), (word, hits)  # A6


def assert_failed_naming(res: dict[str, Any], name: str) -> None:
    assert res["ok"] is False, why(res)
    assert res["text"] is None
    assert name in all_reasons(res), (name, all_reasons(res))


def slot_rows(res: dict[str, Any], **match: Any) -> list[dict[str, Any]]:
    return [s for s in res["slots"] if all(s.get(k) == v for k, v in match.items())]


def one_row(res: dict[str, Any], **match: Any) -> dict[str, Any]:
    rows = slot_rows(res, **match)
    assert len(rows) == 1, (match, res["slots"])
    return rows[0]


def place(form: str, rendered: str) -> tuple[str, str]:
    """A template frame for a form, and the text it should render to."""
    if form == "start":
        return "{}.", f"{rendered}."
    return "We looked at {}.", f"We looked at {rendered}."


def status_run(env: J4REnv, status: str) -> tuple[str, str]:
    run_id = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    return run_id, env.ctr_44(run_id, status=status)


# ------------------------------------------------------------------ the calls' shape


def test_J4R_render_result_shape(env: J4REnv, run: str) -> None:
    qid = env.qid(run, IMG3_ID, "ctr")
    template = f"We looked at {fig_run(run, qid)}."
    res = env.render(template)
    assert set(res) >= set(S.Rendered.__annotations__)
    assert res["template"] == template  # the input, unchanged
    assert isinstance(res["engine_version"], str) and res["engine_version"]
    assert re.fullmatch(r"[0-9a-f]{64}", res["inputs_hash"])
    checked = dt.datetime.fromisoformat(res["checked_at"].replace("Z", "+00:00"))
    assert checked.utcoffset() == dt.timedelta(0)
    json.dumps(res)  # JSON-native
    row = one_row(res, run_id=run)
    assert set(row) >= set(S.SlotOut.__annotations__)
    assert row["ok"] is True
    assert row["rendered"] == FULL["marginal"]
    assert row["release_id"] is None
    assert row["quantity"] == {"name": "ctr", "subject": IMG3_ID, "status": "marginal"}
    assert row["newest"] is True
    assert run in row["ref"] and qid in row["ref"]


def test_J4R_inputs_hash_covers_the_text(env: J4REnv, run: str) -> None:
    qid = env.qid(run, IMG3_ID, "ctr")
    a = env.render(f"We looked at {fig_run(run, qid)}.")
    b = env.render(f"We looked at {fig_run(run, qid)}.")
    c = env.render(f"We checked {fig_run(run, qid)}.")
    assert a["inputs_hash"] == b["inputs_hash"]
    assert a["inputs_hash"] != c["inputs_hash"]


def test_J4R_menu_shape(env: J4REnv, run: str, rel: str) -> None:
    menu = env.menu()
    assert set(menu) >= set(S.Menu.__annotations__)
    assert menu["client_id"] == CLIENT
    json.dumps(menu)
    assert menu["slots"], menu
    for item in menu["slots"]:
        assert set(item) >= set(S.MenuItem.__annotations__)
        assert item["kind"] in ("fig", "cmp", "name", "date")
        assert "#" not in item["token"]  # no claim id
        assert "|" not in item["token"]  # no form
        assert set(item["forms"]) >= {"full", "start"}


# ------------------------------------------------------------------ each status in each form


@pytest.mark.parametrize("form", ["full", "start"])
@pytest.mark.parametrize("status", ["estimable", "marginal", "below_floor"])
def test_J4R_fig_status_renders_its_phrase(env: J4REnv, status: str, form: str) -> None:
    """The forms table, rows estimable, marginal and below floor (J4 (f) kept as rendering)."""
    run_id, qid = status_run(env, status)
    frame, expected = place(form, (FULL if form == "full" else START)[status])
    res = env.render(frame.format(fig_run(run_id, qid, form)))
    assert_ok(res, expected)
    row = one_row(res, run_id=run_id)
    assert row["quantity"]["status"] == status
    assert row["newest"] is True


@pytest.mark.parametrize("form", ["full", "start"])
def test_J4R_fig_observed_notebook_renders_its_phrase(env: J4REnv, rel: str, form: str) -> None:
    frame, expected = place(form, OBSERVED_FULL if form == "full" else OBSERVED_START)
    res = env.render(frame.format(fig_nb(rel, E_LIMIT, LIMIT, form)))
    assert_ok(res, expected)
    row = one_row(res, release_id=rel)
    assert row["quantity"] == {"name": LIMIT, "subject": "account", "status": None}
    assert row["run_id"] is None
    assert row["newest"] is True


def test_J4R_fig_without_a_form_is_full(env: J4REnv, run: str) -> None:
    """The grammar's form is optional; without one the slot reads as ``full`` (inferred)."""
    qid = env.qid(run, IMG3_ID, "ctr")
    a = env.render(f"We looked at {fig_run(run, qid)}.")
    b = env.render(f"We looked at {fig_run(run, qid, 'full')}.")
    assert_ok(a, f"We looked at {FULL['marginal']}.")
    assert a["text"] == b["text"]


@pytest.mark.parametrize(
    ("measure", "summary", "full"),
    [
        ("cpa", {"q50": 3.35, "mean": 3.35}, f"{IMG3}'s cost per sign-up of $3.35"),
        ("cvr", {"q50": 0.244, "mean": 0.244}, f"{IMG3}'s sign-up rate of 24.4%"),
    ],
    ids=["cpa", "cvr"],
)
def test_J4R_J5_lead_labels(
    env: J4REnv, measure: str, summary: dict[str, float], full: str
) -> None:
    """J5's lead labels on a lead account; cost-per money at cents (J5, S11)."""
    run_id = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    qid = env.set_quantity(run_id, IMG3_ID, measure, status="estimable", **summary)
    res = env.render(f"We looked at {fig_run(run_id, qid)}.")
    assert_ok(res, f"We looked at {full}.")


def test_J4R_J5_lead_menu_never_says_order(env: J4REnv, run: str) -> None:
    menu = env.menu()
    assert menu["slots"]
    for item in menu["slots"]:
        for text in item["forms"].values():
            assert not re.search(r"\b(orders?|purchases?)\b", text, re.I), (item["token"], text)


# ------------------------------------------------------------------ not newest: "as of" (p, P3)


@pytest.mark.parametrize("form", ["full", "start"])
@pytest.mark.parametrize("status", ["estimable", "marginal", "below_floor"])
def test_J4R_p_fig_on_an_older_run_says_as_of(env: J4REnv, status: str, form: str) -> None:
    old, new = env.old_and_new_runs()
    q_old = env.ctr_44(old, status=status)
    q_new = env.ctr_44(new, status=status)
    rendered = (FULL if form == "full" else START)[status]
    frame, stale = place(form, rendered + AS_OF_RUN)
    res = env.render(frame.format(fig_run(old, q_old, form)))
    assert_ok(res, stale)
    assert one_row(res, run_id=old)["newest"] is False
    frame, fresh = place(form, rendered)
    res = env.render(frame.format(fig_run(new, q_new, form)))
    assert_ok(res, fresh)  # the newest run carries no date
    assert one_row(res, run_id=new)["newest"] is True


@pytest.mark.parametrize("form", ["full", "start"])
def test_J4R_p_fig_on_a_superseded_release_says_as_of(env: J4REnv, form: str) -> None:
    r1, r2 = env.releases_dated_alike()
    rendered = OBSERVED_FULL if form == "full" else OBSERVED_START
    frame, stale = place(form, rendered + AS_OF_REL)
    res = env.render(frame.format(fig_nb(r1, E_LIMIT, LIMIT, form)))
    assert_ok(res, stale)
    assert one_row(res, release_id=r1)["newest"] is False
    frame, fresh = place(form, rendered)
    res = env.render(frame.format(fig_nb(r2, E_LIMIT, LIMIT, form)))
    assert_ok(res, fresh)
    assert one_row(res, release_id=r2)["newest"] is True


@pytest.mark.parametrize("form", ["full", "start"])
def test_J4R_p_cmp_on_an_older_run_says_as_of(env: J4REnv, form: str) -> None:
    old, new = env.old_and_new_runs()
    for r in (old, new):
        env.set_p_best(r, {IMG3_ID: 0.621, IMG2_ID: 0.379})
    rendered = CMP_FULL if form == "full" else CMP_START
    res = env.render(f"{cmp_run(old, form)}.")
    assert_ok(res, f"{rendered}{AS_OF_RUN}.")
    res = env.render(f"{cmp_run(new, form)}.")
    assert_ok(res, f"{rendered}.")


# ------------------------------------------------------------------ S21: newest


def test_J4R_S21_newest_run_by_run_record_started_at(env: J4REnv) -> None:
    """The run written second, with the newer file mtime, is the older by started_at."""
    old, new = env.old_and_new_runs()
    assert env.snapshot_file(old).stat().st_mtime > env.snapshot_file(new).stat().st_mtime
    q_old, q_new = env.qid(old, IMG3_ID, "ctr"), env.qid(new, IMG3_ID, "ctr")
    res = env.render(f"We looked at {fig_run(old, q_old)} and {fig_run(new, q_new)}.")
    assert res["ok"] is True, why(res)
    assert one_row(res, run_id=old)["newest"] is False
    assert one_row(res, run_id=new)["newest"] is True
    assert ", as of " in one_row(res, run_id=old)["rendered"]
    assert ", as of " not in one_row(res, run_id=new)["rendered"]


def test_J4R_S21_newest_release_by_day_and_parent_not_created_at(env: J4REnv) -> None:
    r1, r2 = env.releases_adversarial()
    res = env.render(f"We looked at {fig_nb(r1, E_LIMIT, LIMIT)} and {fig_nb(r2, E_LIMIT, LIMIT)}.")
    assert res["ok"] is True, why(res)
    assert one_row(res, release_id=r1)["newest"] is False
    assert one_row(res, release_id=r2)["newest"] is True
    assert ", as of " in one_row(res, release_id=r1)["rendered"]
    assert ", as of " not in one_row(res, release_id=r2)["rendered"]


def test_J4R_S21_newest_release_by_n_within_a_day(env: J4REnv) -> None:
    a = env.release(day="20261126", created_at=dt.datetime(2026, 11, 26, 18, 0, tzinfo=UTC))
    b = env.release(day="20261126", created_at=dt.datetime(2026, 11, 26, 9, 0, tzinfo=UTC))
    assert a.endswith("_1") and b.endswith("_2")
    res = env.render(f"We looked at {fig_nb(a, E_LIMIT, LIMIT)} and {fig_nb(b, E_LIMIT, LIMIT)}.")
    assert one_row(res, release_id=a)["newest"] is False
    assert one_row(res, release_id=b)["newest"] is True


def test_J4R_S21_a_parent_release_is_never_newest(env: J4REnv) -> None:
    top = env.release(day="20261126", created_at=dt.datetime(2026, 11, 26, 15, 0, tzinfo=UTC))
    env.release(day="20261121", created_at=dt.datetime(2026, 11, 27, 15, 0, tzinfo=UTC), parent=top)
    res = env.render(f"We looked at {fig_nb(top, E_LIMIT, LIMIT)}.")
    assert one_row(res, release_id=top)["newest"] is False
    assert ", as of " in one_row(res, release_id=top)["rendered"]


# ------------------------------------------------------------------ cmp (C5)


@pytest.mark.parametrize(("form", "rendered"), [("full", CMP_FULL), ("start", CMP_START)])
def test_J4R_cmp_renders_from_the_comparison_record(
    env: J4REnv, run: str, form: str, rendered: str
) -> None:
    """The record gives IMG3_TXT1 0.621 while IMG2's ctr is the higher in the quantities: only
    the record names IMG3_TXT1 the leader."""
    env.set_p_best(run, {IMG3_ID: 0.621, IMG2_ID: 0.379})
    res = env.render(f"{cmp_run(run, form)}.")
    assert_ok(res, f"{rendered}.")
    row = one_row(res, run_id=run)
    assert row["ok"] is True and row["newest"] is True


def test_J4R_cmp_no_subtraction(env: J4REnv, run: str) -> None:
    """Changing an ad's quantities in the snapshot, the comparison untouched, changes nothing in
    the cmp rendering: nothing is worked out from two figures (C5)."""
    env.set_p_best(run, {IMG3_ID: 0.621, IMG2_ID: 0.379})
    template = f"{cmp_run(run)}. Also: {cmp_run(run, 'start')}."
    before = env.render(template)
    assert before["ok"] is True, why(before)
    record = env.comparison(run)
    env.set_quantity(run, IMG3_ID, "ctr", q50=0.01, mean=0.01, q05=0.008, q95=0.012)
    env.set_quantity(run, IMG2_ID, "ctr", q50=0.09, mean=0.09, q05=0.085, q95=0.095)
    assert env.comparison(run) == record  # precondition: the record is untouched
    after = env.render(template)
    assert after["ok"] is True, why(after)
    assert after["text"] == before["text"]


@pytest.mark.parametrize("form", ["full", "start"])
def test_J4R_cmp_marginal_decision_carries_the_caveat(env: J4REnv, run: str, form: str) -> None:
    env.set_p_best(run, {IMG3_ID: 0.621, IMG2_ID: 0.379})
    env.set_decision(run, "marginal")
    res = env.render(f"{cmp_run(run, form)}.")
    assert res["ok"] is True, why(res)
    assert res["text"].startswith(CMP_FULL if form == "full" else CMP_START)
    assert ROUGH in res["text"]


@pytest.mark.parametrize("form", ["full", "start"])
def test_J4R_cmp_leader_under_half_carries_the_caveat(env: J4REnv, run: str, form: str) -> None:
    """The leader's p_best under 0.5 (the record set so; the decision stays estimable)."""
    env.set_p_best(run, {IMG3_ID: 0.45, IMG2_ID: 0.30})
    res = env.render(f"{cmp_run(run, form)}.")
    assert res["ok"] is True, why(res)
    # Amended by the integrator (B31): under S27 (5) a leader under 0.5 names no ad.
    assert "neither ad leads yet on clicks" in res["text"].lower(), res["text"]
    assert IMG3 not in res["text"], res["text"]
    assert ROUGH in res["text"]


def test_J4R_cmp_estimable_leader_over_half_has_no_caveat(env: J4REnv, run: str) -> None:
    env.set_p_best(run, {IMG3_ID: 0.621, IMG2_ID: 0.379})
    res = env.render(f"{cmp_run(run)}.")
    assert res["ok"] is True, why(res)
    assert ROUGH not in res["text"]


@pytest.mark.parametrize("form", ["full", "start"])
def test_J4R_cmp_below_floor(env: J4REnv, run: str, form: str) -> None:
    env.set_p_best(run, {IMG3_ID: 0.621, IMG2_ID: 0.379})
    env.set_decision(run, "below_floor")
    res = env.render(f"We checked {cmp_run(run, form)}.")
    assert res["ok"] is True, why(res)
    if form == "full":
        assert res["text"] == f"We checked {CMP_FLOOR}."
    else:
        assert "not knowable yet" in res["text"]  # A5: floor wording as in full
    assert "%" not in res["text"] and IMG3 not in res["text"]


# ------------------------------------------------------------------ name and date slots


@pytest.mark.parametrize(("ad", "name"), [(IMG3_ID, IMG3), (IMG2_ID, IMG2_NAME)])
def test_J4R_name_slot_renders_the_display_name(env: J4REnv, run: str, ad: str, name: str) -> None:
    res = env.render(f"The ad {name_slot(ad)} is live.")
    assert_ok(res, f"The ad {name} is live.")


def test_J4R_S16_names_from_load_names_when_the_snapshot_has_none(env: J4REnv, run: str) -> None:
    env.set_names(run, {})
    env.store_names = {IMG3_ID: IMG3, IMG2_ID: IMG2_NAME}
    qid = env.qid(run, IMG3_ID, "ctr")
    res = env.render(f"The ad {A} is live, and we looked at {fig_run(run, qid)}.")
    assert_ok(res, f"The ad {IMG3} is live, and we looked at {FULL['marginal']}.")
    assert CLIENT in env.names_calls  # P4: the injected load_names was used


@pytest.mark.parametrize(
    "value",
    ["2026-11-26", "2026-11-26T15:00:00+00:00", "2026-11-26T15:00:00Z"],
    ids=["date", "datetime_offset", "datetime_z"],
)
def test_J4R_A2_date_slot_passes_through_untouched(env: J4REnv, run: str, value: str) -> None:
    qid = env.qid(run, IMG3_ID, "ctr")
    template = f"On {date_slot(value)}, we looked at {fig_run(run, qid)}."
    res = env.render(template)
    assert_ok(res, f"On {date_slot(value)}, we looked at {FULL['marginal']}.")


@pytest.mark.parametrize(
    "value",
    ["next week", "2026-13-01", "2026-02-30", "26 November 2026", "2026/11/26", "2026-11-26T25:00"],
)
def test_J4R_A2_bad_date_slot_fails(env: J4REnv, run: str, value: str) -> None:
    assert_refused(env.render(f"On {date_slot(value)}, the ad is live."), S.R_BAD_DATE)


# ------------------------------------------------------------------ claim ids (A5)


def test_J4R_A5_claim_id_is_echoed_and_not_rendered(env: J4REnv, run: str, rel: str) -> None:
    env.set_p_best(run, {IMG3_ID: 0.621, IMG2_ID: 0.379})
    qid = env.qid(run, IMG3_ID, "ctr")
    plain = env.render(f"We looked at {fig_run(run, qid)} and {fig_nb(rel, E_LIMIT, LIMIT)}.")
    tagged = env.render(
        f"We looked at {fig_run(run, qid, claim='clm_0001')} and "
        f"{fig_nb(rel, E_LIMIT, LIMIT, claim='clm_0002')}."
    )
    assert tagged["ok"] is True, why(tagged)
    assert tagged["text"] == plain["text"]
    assert one_row(tagged, run_id=run)["claim_id"] == "clm_0001"
    assert one_row(tagged, release_id=rel)["claim_id"] == "clm_0002"
    assert "clm_" not in tagged["text"]
    cmp_res = env.render("{}.".format(cmp_run(run, claim="clm_0003")))
    assert cmp_res["ok"] is True, why(cmp_res)
    assert one_row(cmp_res, run_id=run)["claim_id"] == "clm_0003"


# ------------------------------------------------------------------ ok False gives text None


def test_J4R_partial_rendering_is_never_returned(env: J4REnv, run: str) -> None:
    qid = env.qid(run, IMG3_ID, "ctr")
    res = env.render(f"We looked at {fig_run(run, qid)} and {fig_run(run, 'q_00000000')}.")
    assert res["ok"] is False
    assert res["text"] is None
    good = [s for s in res["slots"] if s["ok"]]
    assert good and good[0]["rendered"] == FULL["marginal"]  # the row may render; the text never
    assert any(not s["ok"] for s in res["slots"])


def test_J4R_numeral_rule_failure_gives_text_none(env: J4REnv, run: str) -> None:
    qid = env.qid(run, IMG3_ID, "ctr")
    res = env.render(f"We looked at {fig_run(run, qid)}, up 2 points.")
    assert_refused(res, S.R_FIGURE_OUTSIDE_SLOT, "2")
    assert all(s["ok"] for s in res["slots"])  # every slot rendered, and still no text


# ------------------------------------------------------------------ unknown refs, grammar, braces


@pytest.mark.parametrize("which", ["quantity", "nb_quantity", "entity"])
def test_J4R_unknown_slot_ref_fails(env: J4REnv, run: str, rel: str, which: str) -> None:
    slot = {
        "quantity": fig_run(run, "q_00000000"),
        "nb_quantity": fig_nb(rel, E_LIMIT, "no_such_quantity"),
        "entity": name_slot("999999999999999999"),
    }[which]
    assert_refused(env.render(f"We looked at {slot}."), S.R_UNKNOWN_SLOT)


@pytest.mark.parametrize(
    "slot",
    [
        "{figure:run/RUN/QID}",
        "{fig:RUN/QID}",
        "{fig:run/RUN/QID|short}",
        "{fig:run/RUN/QID|start|full}",
        "{fig:}",
        "{:run/RUN/QID}",
        "{fig run/RUN/QID}",
        "{name:RUN}",
        "{}",
    ],
)
def test_J4R_A2_slot_outside_the_grammar_fails(env: J4REnv, run: str, slot: str) -> None:
    """A malformed slot fails as outside the grammar, or as braces left over (A2)."""
    slot = slot.replace("RUN", run).replace("QID", env.qid(run, IMG3_ID, "ctr"))
    res = env.render(f"We looked at {slot}.")
    assert res["ok"] is False, why(res)
    assert res["text"] is None
    reasons = all_reasons(res)
    assert S.R_BAD_SLOT in reasons or S.R_BRACE in reasons, reasons


@pytest.mark.parametrize(
    "template",
    ["Here is a } brace.", "Here is a { brace.", "Braces {{NAME}} doubled.", "A {NAME}} tail."],
)
def test_J4R_A2_leftover_braces_fail(env: J4REnv, run: str, template: str) -> None:
    assert_refused(env.render(template.replace("{NAME}", A)), S.R_BRACE)


# ------------------------------------------------------------------ A1 and (m): clients


def test_J4R_A1_refs_of_another_client_fail(env: J4REnv, run: str) -> None:
    """Every ref belongs to lead_client; the call is for other_client."""
    env.other_release()  # other_client is configured and has a release of its own
    env.set_p_best(run, {IMG3_ID: 0.621, IMG2_ID: 0.379})
    qid = env.qid(run, IMG3_ID, "ctr")
    template = f"We looked at {fig_run(run, qid)}. {cmp_run(run)}."
    good = env.render(template)
    assert good["ok"] is True, why(good)  # guard: the same template renders for its own client
    assert_refused(env.render(template, OTHER), S.R_OTHER_CLIENT)


def test_J4R_A1_notebook_ref_of_another_client_fails(env: J4REnv, run: str) -> None:
    other = env.other_release()
    res = env.render(f"We looked at {fig_nb(other, E_OTHER, LIMIT)}.")
    assert res["ok"] is False, why(res)
    assert res["text"] is None
    reasons = all_reasons(res)
    assert S.R_OTHER_CLIENT in reasons or other in reasons, reasons


@pytest.mark.parametrize("client", [CLIENT, OTHER])
def test_J4R_m_refs_from_two_clients_fail(env: J4REnv, run: str, client: str) -> None:
    other = env.other_release()
    qid = env.qid(run, IMG3_ID, "ctr")
    res = env.render(
        f"We looked at {fig_run(run, qid)} and {fig_nb(other, E_OTHER, LIMIT)}.", client
    )
    assert res["ok"] is False, why(res)
    assert res["text"] is None
    reasons = all_reasons(res)
    assert S.R_TWO_CLIENTS in reasons or S.R_OTHER_CLIENT in reasons, reasons


# ------------------------------------------------------------------ the numeral rule: words (A6)


@pytest.mark.parametrize("word", sorted(set(S.QUANTITY_WORDS) | set(WORD_FORMS)))
def test_J4R_A6_quantity_word_fails_naming_it(env: J4REnv, word: str) -> None:
    """Every QUANTITY_WORDS word and its -fold, -ly, -s and -th forms; the reason names it."""
    assert_refused(env.render(f"Imani said {word} today."), S.R_FIGURE_OUTSIDE_SLOT, word)


@pytest.mark.parametrize("word", ["Twenty", "TWO", "Half", "Dozens", "Tenfold"])
def test_J4R_A3_quantity_word_fails_in_any_case(env: J4REnv, word: str) -> None:
    assert_refused(env.render(f"{word} came today."), S.R_FIGURE_OUTSIDE_SLOT, word)


@pytest.mark.parametrize("phrase", S.QUANTITY_PHRASES)
def test_J4R_A6_quantity_phrase_fails_naming_it(env: J4REnv, phrase: str) -> None:
    assert_refused(
        env.render(f"Imani saw {phrase} visitors today."), S.R_FIGURE_OUTSIDE_SLOT, phrase
    )


def test_J4R_A6_only_one_sign_up_fails(env: J4REnv, run: str) -> None:
    assert_refused(env.render(f"{A} has only one sign-up so far."), S.R_FIGURE_OUTSIDE_SLOT, "one")


def test_J4R_A6_quantity_word_forms_cover_the_list() -> None:
    """``quantity_word_forms`` holds every listed word and every form this file asserts."""
    forms = S.quantity_word_forms()
    missing = (set(S.QUANTITY_WORDS) | set(WORD_FORMS)) - set(forms)
    assert not missing, sorted(missing)


@pytest.mark.parametrize(
    ("text", "word"),
    [
        ("We saw twenty-five visitors.", "twenty"),
        ("We saw twenty-five visitors.", "five"),
        ("We saw two-thirds of them.", "two"),
        ("We saw two-thirds of them.", "thirds"),
        ("We saw t\u200dwo visitors.", "two"),  # zero-width joiner
        ("We saw tw\u200do visitors.", "two"),
        ("We saw tw\u00ado visitors.", "two"),  # soft hyphen, also category Cf
        ("We saw \uff54\uff57\uff4f visitors.", "two"),  # fullwidth, NFKC
        ("We saw two/three visitors.", "two"),
        ("We saw two\u2013three visitors.", "two"),  # en dash between words
    ],
    ids=[
        "twenty_five_a",
        "twenty_five_b",
        "two_thirds_a",
        "two_thirds_b",
        "zwj_1",
        "zwj_2",
        "soft_hyphen",
        "fullwidth",
        "slash",
        "en_dash",
    ],
)
def test_J4R_A3_normalisation_and_word_breaks(env: J4REnv, text: str, word: str) -> None:
    assert_refused(env.render(text), S.R_FIGURE_OUTSIDE_SLOT, word)


def test_J4R_A3_whole_words_only(env: J4REnv) -> None:
    """Guard: number words inside other words are no hit ("someone", "often", "almost",
    "weightless", "tendency", "content")."""
    text = "Someone often posts a photo, almost weightless, with a tendency to content."
    assert_ok(env.render(text), text)


# ------------------------------------------------------------------ the numeral rule: characters


_SCRIPTS = {unicodedata.name(c).split(" ")[0] for c in NUMERIC_CHARS}


@pytest.mark.parametrize("ch", NUMERIC_CHARS, ids=[f"U+{ord(c):04X}" for c in NUMERIC_CHARS])
def test_J4R_unicode_numeric_character_fails(env: J4REnv, ch: str) -> None:
    """50 characters across Nd, No and Nl in many scripts (the sample's spread is asserted too).
    Each must fail on its raw category: NFKC turns some into letters ("\u216b" into "XII")."""
    assert len(NUMERIC_CHARS) == 50
    assert {unicodedata.category(c) for c in NUMERIC_CHARS} == {"Nd", "No", "Nl"}
    assert len(_SCRIPTS) >= 15, _SCRIPTS
    assert unicodedata.category(ch) in ("Nd", "No", "Nl"), unicodedata.category(ch)
    assert_refused(env.render(f"Imani saw {ch} new faces today."), S.R_FIGURE_OUTSIDE_SLOT, ch)


@pytest.mark.parametrize("word", list(S.PERCENT_SIGNS) + list(S.PERCENT_WORDS))
def test_J4R_percent_sign_or_word_fails(env: J4REnv, word: str) -> None:
    assert_refused(env.render(f"The rate moved by a {word} today."), S.R_FIGURE_OUTSIDE_SLOT, word)


@pytest.mark.parametrize("sign", CURRENCY_SIGNS, ids=[f"U+{ord(c):04X}" for c in CURRENCY_SIGNS])
def test_J4R_currency_sign_fails(env: J4REnv, sign: str) -> None:
    assert unicodedata.category(sign) == "Sc"
    assert_refused(env.render(f"Prices are in {sign} now."), S.R_FIGURE_OUTSIDE_SLOT, sign)


@pytest.mark.parametrize("code", ISO_CODES)
def test_J4R_iso_currency_code_fails(env: J4REnv, code: str) -> None:
    assert_refused(env.render(f"Prices are in {code} now."), S.R_FIGURE_OUTSIDE_SLOT, code)


# ------------------------------------------------------------------ allowed words, A4


def test_J4R_both_ads_passes(env: J4REnv) -> None:
    assert_ok(env.render("Both ads are live."), "Both ads are live.")


def test_J4R_two_ads_fails(env: J4REnv) -> None:
    assert_refused(env.render("Two ads are live."), S.R_FIGURE_OUTSIDE_SLOT, "two")


def test_J4R_allowed_determiners_pass(env: J4REnv) -> None:
    text = "Each ad is live, either way, and neither is paused. All of this is good news."
    assert_ok(env.render(text), text)


@pytest.mark.parametrize(
    "text",
    [
        "No sign-ups yet.",
        "There are no sign-ups yet.",
        "No leads came in today.",
        "All the clicks came from phones.",
        "None of the spend went to search.",
        "All the impressions were on phones.",
        "No link clicks yet.",
        "There is no cost per sign-up yet.",
    ],
)
def test_J4R_A4_none_or_all_with_a_measure_fails(env: J4REnv, text: str) -> None:
    assert_refused(env.render(text), S.R_ZERO_OR_ALL)


def test_J4R_A4_none_of_this_changes_your_plan_passes(env: J4REnv) -> None:
    text = "None of this changes your plan."
    assert_ok(env.render(text), text)


# ------------------------------------------------------------------ the comparative lint (C1)


@pytest.mark.parametrize(
    "template",
    [
        "<A> beat <B>.",
        "<A> is the best ad.",
        "<A> did better than <B>.",
        "<A> drove the sign-ups.",
    ],
    ids=["beat", "best", "better", "causal_drove"],
)
def test_J4R_comparative_outside_a_cmp_slot_fails(env: J4REnv, run: str, template: str) -> None:
    res = env.render(template.replace("<A>", A).replace("<B>", B))
    assert_refused(res, S.R_COMPARATIVE)
    assert res["lint"], res


def test_J4R_comparative_inside_a_cmp_slot_passes(env: J4REnv, run: str) -> None:
    env.set_p_best(run, {IMG3_ID: 0.621, IMG2_ID: 0.379})
    res = env.render(f"Right now, {cmp_run(run)}.")
    assert_ok(res, f"Right now, {CMP_FULL}.")
    assert res["lint"] == []


def test_J4R_comparative_word_without_an_ad_passes(env: J4REnv, run: str) -> None:
    """The lint needs a sentence that names an ad (C1)."""
    text = "The weather is better today."
    assert_ok(env.render(text), text)


# ------------------------------------------------------------------ C7: the J4 review cases

# (id, template, figure the reason must quote, names to set on the run or None).
# <A> is IMG3_TXT1 and <B> IMG2_TXT1 <en dash> Updated., both as name slots.
_R = ", still a rough estimate"
REVIEW_NUMERAL: list[tuple[str, str, str, dict[str, str] | None]] = [
    # tests/review/test_J4_review.py (71f4a75)
    ("r1_year_total", f"<A> had a total of 2000 link clicks{_R}.", "2", None),
    ("r1_year_rise", f"<A> saw clicks rise by 2000{_R}.", "2", None),
    ("r1_fraction_glyph", "Roughly \u2154 of the sign-ups came from <A>.", "\u2154", None),
    ("r1_a_sixth", "Roughly a sixth of the sign-ups went to <A>.", "sixth", None),
    ("r1_a_dozen", "Roughly a dozen sign-ups came from <A>.", "dozen", None),
    ("r1_minus_hyphen", f"<A> had a click-through rate of -4.4%{_R}.", "4", None),
    ("r1_minus_sign", f"<A> had a click-through rate of \u22124.4%{_R}.", "4", None),
    (
        "r1_numeric_name",
        f"<B> has a cost per sign-up of $10{_R}.",
        "1",
        {IMG3_ID: "10", IMG2_ID: IMG2_NAME},
    ),
    ("r1_limit_750", "The limit is $750.", "7", None),
    ("r1_account_budget_750", "The account budget is $750.", "7", None),
    ("r1_cap_750", "The cap is $750.", "7", None),
    ("r1_percent_on_cost", "<A> had a cost per sign-up of 25%.", "2", None),
    ("r1_other_named_ad", f"<A> and <B> both have a ctr of 5.9%{_R}.", "5", None),
    ("r1_bound_at_least", f"<A> had a click-through rate of at least 4.7%{_R}.", "4", None),
    ("r1_bound_no_less", f"<A> had a click-through rate of no less than 4.7%{_R}.", "4", None),
    ("r1_bound_at_most", f"<A> had a click-through rate of at most 4.0%{_R}.", "4", None),
    ("r1_bound_as_low", f"<A> had a click-through rate of as low as 4.7%{_R}.", "4", None),
    ("r1_bound_as_high", f"<A> had a click-through rate of as high as 4.0%{_R}.", "4", None),
    (
        "r1_negated_caveat_not",
        "<A> had a click-through rate of 4.4%, not a rough estimate.",
        "4",
        None,
    ),
    (
        "r1_negated_caveat_no_longer",
        "<A> had a click-through rate of 4.4%, and this is no longer a rough estimate.",
        "4",
        None,
    ),
    ("r1_stale_as_of_now", "<A> has a click-through rate of 4.4% as of now.", "4", None),
    ("r1_stale_as_of_today", "<A> has a click-through rate of 4.4% as of today.", "4", None),
    ("r1_stale_as_of_iso", "<A> has a click-through rate of 4.4%, as of 2026-11-26.", "4", None),
    (
        "r1_stale_today_data",
        "<A> has a click-through rate of 4.4% today (2026-11-07 data).",
        "4",
        None,
    ),
    (
        "r1_stale_other_clause",
        "On November 7 <A> had a click-through rate of 4.4%, and today it has a "
        "click-through rate of 4.4%.",
        "4",
        None,
    ),
    ("r1_malformed_entry", "The amount is $1.", "1", None),
    (
        "r1_exact_observed",
        "<A> has a 0.621 chance of being the best ad, a rough estimate.",
        "6",
        None,
    ),
    ("r1_many_figures", " ".join(["4.4%"] * 3000), "4", None),
    ("r1_half_even_4", "<A> had a click-through rate of 4%.", "4", None),
    ("r1_half_even_5", "<A> had a click-through rate of 5%.", "5", None),
    # review2/J4: tests/review/test_J4_review2.py (b3e71c9)
    ("r2_in_year_drew", f"<A> drew in 1999 clicks{_R}.", "1", None),
    ("r2_in_year_pulled", f"<A> pulled in 1999 clicks{_R}.", "1", None),
    ("r2_month_count_99", f"In November 99 sign-ups came from <A>{_R}.", "9", None),
    ("r2_month_count_40", f"<A> got March 40 sign-ups{_R}.", "4", None),
    ("r2_month_count_2000", f"In November 2000 link clicks came from <A>{_R}.", "2", None),
    ("r2_list_after", f"A click-through rate of 5.9% for <B> and <A>{_R}.", "5", None),
    ("r2_list_paren", f"<A> (and <B>) both have a click-through rate of 5.9%{_R}.", "5", None),
    ("r2_list_as_well", f"<A> as well as <B> have a click-through rate of 5.9%{_R}.", "5", None),
    ("r2_list_or", f"<A> or <B> has a click-through rate of 5.9%{_R}.", "5", None),
    ("r2_list_along", f"<A>, along with <B>, has a click-through rate of 5.9%{_R}.", "5", None),
    ("r2_list_plus", f"<A> plus <B> have a click-through rate of 5.9%{_R}.", "5", None),
    ("r2_list_slash", f"<A> / <B> have a click-through rate of 5.9%{_R}.", "5", None),
    (
        "r2_two_measures_a",
        f"<A> has a click-through rate of 24%, sign-up rate 4.4%{_R}.",
        "2",
        None,
    ),
    (
        "r2_two_measures_b",
        f"<A> has a sign-up rate of 4.4%, click-through rate 24%{_R}.",
        "4",
        None,
    ),
    (
        "r2_negation_any_way",
        "<A> has a click-through rate of 4.4%, and this is not in any way a rough estimate.",
        "4",
        None,
    ),
    (
        "r2_negation_cannot_call",
        "<A> has a click-through rate of 4.4%, and we cannot call it a rough estimate.",
        "4",
        None,
    ),
    (
        "r2_negation_far_from",
        "<A> has a click-through rate of 4.4%, which is far from a rough estimate.",
        "4",
        None,
    ),
    (
        "r2_negation_rather_than",
        "<A> has a click-through rate of 4.4%, rather than a rough estimate.",
        "4",
        None,
    ),
    ("r2_en_dash_minus", f"<A> had a click-through rate of \u20134.4%{_R}.", "4", None),
    (
        "r2_p_best_a",
        "<B> has a 100% chance of being the best, and <A> is likely the best.",
        "1",
        None,
    ),
    (
        "r2_p_best_b",
        "<B> has a 100% chance of being the best, so <A> is likely the best ad.",
        "1",
        None,
    ),
    (
        "r2_p_best_c",
        "<A> is likely the best ad, and <B> has a 100% chance of being the best.",
        "1",
        None,
    ),
    (
        "r2_stale_comma_list",
        f"On November 7, <B> had a click-through rate of 5.9%, <A> has a click-through rate "
        f"of 4.4%{_R}.",
        "5",
        None,
    ),
    (
        "r2_stale_launch",
        "<A> has a click-through rate of 4.4% (launched on 2026-10-01).",
        "4",
        None,
    ),
    (
        "r2_stale_same_as",
        "<A> has a click-through rate of 4.4%, the same as on 2020-01-01.",
        "4",
        None,
    ),
    ("r2_stale_on_iso", "On 2026-10-01 <A> had a click-through rate of 4.4%.", "4", None),
    (
        "r2_stale_other_year",
        "On November 7, 2025, <A> had a click-through rate of 4.4%.",
        "4",
        None,
    ),
    ("r2_money_spent", f"<A> spent $1.00{_R}.", "1", None),
    ("r2_money_budget", f"<A> has a budget of $1.00{_R}.", "1", None),
    ("r2_money_of_spend", f"<A> took 24% of the spend{_R}.", "2", None),
    ("r2_unknown_bounce", f"<A> has a bounce rate of 24%{_R}.", "2", None),
    ("r2_unknown_frequency", f"<A> has a frequency of 24%{_R}.", "2", None),
    ("r2_unknown_view_through", f"<A> has a view-through rate of 24%{_R}.", "2", None),
    ("r2_change_rose", f"<A>'s click-through rate rose by 4.4%{_R}.", "4", None),
    ("r2_change_up", f"<A>'s click-through rate is up 4.4%{_R}.", "4", None),
    ("r2_change_fell", f"<A>'s cost per sign-up fell $1.00{_R}.", "1", None),
    ("r2_change_lower_than", f"<A>'s click-through rate is 4.4% lower than <B>'s{_R}.", "4", None),
    ("r2_threefold", "<B> has a threefold higher click-through rate than <A>.", "threefold", None),
    ("r2_three_fold", "<B> has a three-fold higher click-through rate than <A>.", "three", None),
    ("r2_tenfold", "<B> converts tenfold better than <A>.", "tenfold", None),
    ("r2_one_lead", f"<A> had one lead{_R}.", "one", None),
    ("r2_one_sign_up", f"<A> got one sign-up{_R}.", "one", None),
    (
        "r2_licensed_doubled",
        f"<A> has a click-through rate of 4.4% and <B> one of 5.9%, so sign-ups doubled{_R}.",
        "doubled",
        None,
    ),
    (
        "r2_licensed_majority",
        f"<A> has a click-through rate of 4.4% and <B> one of 5.9%, and a majority of sign-ups "
        f"came from <B>{_R}.",
        "majority",
        None,
    ),
    (
        "r2_licensed_fourfold",
        f"<A> has a click-through rate of 4.4% and <B> one of 5.9%, and sign-ups grew "
        f"fourfold{_R}.",
        "fourfold",
        None,
    ),
    ("r2_notebook_subject", f"<B> has a 0.621 chance of being the best ad{_R}.", "6", None),
    (
        "r2_one_letter_names",
        f"<B> has a click-through rate of 4.4%{_R}.",
        "4",
        {IMG3_ID: "A", IMG2_ID: "B"},
    ),
]

# Cases whose wrong content was a comparative: the figure goes into its cmp slot (<CMP>), and the
# comparative left in the persona's words must fail the lint.
REVIEW_COMPARATIVE: list[tuple[str, str]] = [
    ("r1_leads", "<A> leads <B>."),
    ("r1_lead_ad", "<A> is the lead ad."),
    ("r2_p_best_a", "<CMP>, and <A> is likely the best."),
    ("r2_p_best_b", "<CMP>, so <A> is likely the best ad."),
    ("r2_p_best_c", "<A> is likely the best ad, and <CMP>."),
]


def _fill(template: str, run_id: str) -> str:
    return template.replace("<A>", A).replace("<B>", B).replace("<CMP>", cmp_run(run_id))


@pytest.mark.parametrize(
    ("template", "figure", "names"),
    [c[1:] for c in REVIEW_NUMERAL],
    ids=[c[0] for c in REVIEW_NUMERAL],
)
def test_J4R_C7_review_case_fails_the_numeral_rule(
    env: J4REnv, run: str, template: str, figure: str, names: dict[str, str] | None
) -> None:
    if names is not None:
        env.set_names(run, names)
    res = env.render(_fill(template, run))
    assert_refused(res, S.R_FIGURE_OUTSIDE_SLOT, figure)


@pytest.mark.parametrize(
    "template", [c[1] for c in REVIEW_COMPARATIVE], ids=[c[0] for c in REVIEW_COMPARATIVE]
)
def test_J4R_C7_review_comparative_case_fails_the_lint(
    env: J4REnv, run: str, template: str
) -> None:
    res = env.render(_fill(template, run))
    assert_refused(res, S.R_COMPARATIVE)
    assert res["lint"], res


def test_J4R_C7_review_order_of_magnitude_case_fails(env: J4REnv, run: str) -> None:
    """review2 "B has an order of magnitude more clicks than A". No QUANTITY_WORDS word is in it,
    and "more clicks" is a generic phrase the comparative lexicon never counts, so under the
    frozen lists it passes both rules. C7 says every case must fail; the manifest flags this one
    as a conflict for the Principal Architect."""
    res = env.render(_fill("<B> has an order of magnitude more clicks than <A>.", run))
    assert res["ok"] is False, why(res)
    assert res["text"] is None
    reasons = all_reasons(res)
    assert S.R_FIGURE_OUTSIDE_SLOT in reasons or S.R_COMPARATIVE in reasons, reasons


def test_J4R_C7_guard_names_alone_pass(env: J4REnv, run: str) -> None:
    """Guard: with the figures gone, the review sentences' ad slots render and pass."""
    res = env.render(_fill("<A> and <B> are live.", run))
    assert_ok(res, f"{IMG3} and {IMG2_NAME} are live.")


# ------------------------------------------------------------------ client_slots (C3)


def test_J4R_menu_lists_only_the_newest_run_and_release(env: J4REnv) -> None:
    old, new = env.old_and_new_runs()
    r1, r2 = env.releases_adversarial()
    menu = env.menu()
    items = menu["slots"]
    assert any(i["run_id"] == new and i["kind"] == "fig" for i in items), items
    assert any(i["run_id"] == new and i["kind"] == "cmp" for i in items), items
    assert any(i["release_id"] == r2 and i["kind"] == "fig" for i in items), items
    for i in items:
        assert i["run_id"] in (new, None), i
        assert i["release_id"] in (r2, None), i
        assert old not in i["token"] and r1 not in i["token"], i
        assert i["newest"] is True, i


def test_J4R_menu_every_listed_slot_renders(env: J4REnv, run: str, rel: str) -> None:
    env.set_p_best(run, {IMG3_ID: 0.621, IMG2_ID: 0.379})
    menu = env.menu()
    assert menu["slots"]
    for item in menu["slots"]:
        res = env.render(slot_of_token(item["token"]))
        assert res["ok"] is True, (item["token"], why(res))
        assert res["text"] == item["forms"]["full"], (item["token"], res["text"])
        if item["kind"] in ("fig", "cmp"):
            res = env.render(slot_of_token(item["token"], "start"))
            assert res["ok"] is True, (item["token"], why(res))
            assert res["text"] == item["forms"]["start"], (item["token"], res["text"])


def test_J4R_menu_items_describe_their_slots(env: J4REnv, run: str, rel: str) -> None:
    env.set_p_best(run, {IMG3_ID: 0.621, IMG2_ID: 0.379})
    qid = env.qid(run, IMG3_ID, "ctr")
    items = env.menu()["slots"]
    (ctr,) = [i for i in items if i["kind"] == "fig" and qid in i["token"]]
    assert ctr["run_id"] == run and ctr["release_id"] is None
    assert (ctr["measure"], ctr["subject"], ctr["status"]) == ("ctr", IMG3_ID, "marginal")
    assert ctr["forms"] == {"full": FULL["marginal"], "start": START["marginal"]}
    (limit,) = [i for i in items if i["kind"] == "fig" and LIMIT in i["token"]]
    assert limit["release_id"] == rel and limit["run_id"] is None
    assert (limit["measure"], limit["subject"], limit["status"]) == (LIMIT, "account", None)
    assert limit["forms"] == {"full": OBSERVED_FULL, "start": OBSERVED_START}
    (comparison,) = [i for i in items if i["kind"] == "cmp"]
    assert comparison["run_id"] == run
    assert comparison["forms"] == {"full": CMP_FULL, "start": CMP_START}


def test_J4R_menu_of_another_client_lists_none_of_this_clients(env: J4REnv, run: str) -> None:
    other = env.other_release()
    menu = env.menu(OTHER)
    assert menu["client_id"] == OTHER
    for i in menu["slots"]:
        assert i["run_id"] != run, i
        assert i["release_id"] in (other, None), i


# ------------------------------------------------------------------ P4: the loaders


def _ctr_51(run_id: str) -> Any:
    def fn(d: dict[str, Any]) -> None:
        for q in d["quantities"]:
            if q["name"] == "ctr" and q["scope"]["ids"] == {"ad": IMG3_ID}:
                q["estimate"]["summary"].update(q50=0.051, mean=0.051, q05=0.047, q95=0.055)

    return fn


def test_J4R_P4_load_run_is_used(env: J4REnv, run: str) -> None:
    """The loader's snapshot gives 5.1%; the file on disk says 4.4%."""
    snap = env.snapshot_with(run, _ctr_51(run))
    calls: list[str] = []

    def load_run(run_id: str) -> Any:
        calls.append(run_id)
        if run_id != run:
            raise KeyError(run_id)
        return snap

    qid = env.qid(run, IMG3_ID, "ctr")
    res = env.render(f"We looked at {fig_run(run, qid)}.", load_run=load_run)
    assert run in calls
    assert_ok(res, f"We looked at {IMG3}'s click-through rate of about 5.1%, {ROUGH}.")


def _limit_1600(env: J4REnv, rel: str) -> Any:
    catalog, entries, srcs = env.release_files(rel)
    for e in entries:
        for q in e.get("quantities", []):
            if q["name"] == LIMIT:
                q["value"] = 1600
    calls: list[str] = []

    def load_release(release_id: str) -> tuple[dict, list[dict], list[dict]]:
        calls.append(release_id)
        if release_id != rel:
            raise KeyError(release_id)
        return catalog, entries, srcs

    return load_release, calls


def test_J4R_P4_load_release_is_used(env: J4REnv, rel: str) -> None:
    load_release, calls = _limit_1600(env, rel)
    res = env.render(f"We looked at {fig_nb(rel, E_LIMIT, LIMIT)}.", load_release=load_release)
    assert rel in calls
    assert_ok(res, "We looked at the account spending limit of $1,600.")


def test_J4R_P4_menu_uses_the_loaders(env: J4REnv, run: str, rel: str) -> None:
    snap = env.snapshot_with(run, _ctr_51(run))
    run_calls: list[str] = []

    def load_run(run_id: str) -> Any:
        run_calls.append(run_id)
        if run_id != run:
            raise KeyError(run_id)
        return snap

    load_release, rel_calls = _limit_1600(env, rel)
    menu = env.menu(load_run=load_run, load_release=load_release)
    assert run in run_calls and rel in rel_calls
    texts = [t for i in menu["slots"] for t in i["forms"].values()]
    assert f"{IMG3}'s click-through rate of about 5.1%, {ROUGH}" in texts
    assert "the account spending limit of $1,600" in texts


# ------------------------------------------------------------------ (i): unreadable refs, types


def test_J4R_i_unknown_run_fails_naming_it(env: J4REnv) -> None:
    res = env.render(f"We looked at {fig_run('run_00000bad', 'q_00000000')}.")
    assert_failed_naming(res, "run_00000bad")


def test_J4R_i_release_failing_verify_fails_naming_it(env: J4REnv) -> None:
    bad = env.release(day="20261121", created_at=dt.datetime(2026, 11, 21, 15, 0, tzinfo=UTC))
    path = env.release_folder(bad) / "entries.jsonl"
    path.write_text(path.read_text().replace("$1,500", "$1,600", 1))
    with pytest.raises(ValueError):
        nb_release.verify(env.release_folder(bad))  # the fixture really fails verify
    assert_failed_naming(env.render(f"We looked at {fig_nb(bad, E_LIMIT, LIMIT)}."), bad)


def test_J4R_i_unknown_release_fails_naming_it(env: J4REnv, rel: str) -> None:
    missing = "nb_lead_client_20261101_1"
    assert_failed_naming(env.render(f"We looked at {fig_nb(missing, E_LIMIT, LIMIT)}."), missing)


def test_J4R_i_unknown_entry_fails_naming_it(env: J4REnv, rel: str) -> None:
    unknown = "nbe_lead_client_9999"
    assert_failed_naming(env.render(f"We looked at {fig_nb(rel, unknown, LIMIT)}."), unknown)


def test_J4R_i_load_run_that_raises_fails_without_raising(env: J4REnv, run: str) -> None:
    def load_run(run_id: str) -> Any:
        raise ValueError(f"{run_id} cannot be read")

    qid = env.qid(run, IMG3_ID, "ctr")
    assert_failed_naming(env.render(f"We looked at {fig_run(run, qid)}.", load_run=load_run), run)


def test_J4R_i_load_release_that_raises_fails_without_raising(env: J4REnv, rel: str) -> None:
    def load_release(release_id: str) -> Any:
        raise ValueError(f"{release_id} does not verify")

    res = env.render(f"We looked at {fig_nb(rel, E_LIMIT, LIMIT)}.", load_release=load_release)
    assert_failed_naming(res, rel)


@pytest.mark.parametrize(
    ("text", "client_id"),
    [
        (123, CLIENT),
        (None, CLIENT),
        (b"Both ads are live.", CLIENT),
        ("Both ads.", 123),
        ("Both ads.", None),
    ],
    ids=["text_int", "text_none", "text_bytes", "client_int", "client_none"],
)
def test_J4R_render_wrong_argument_type_raises(text: Any, client_id: Any) -> None:
    with pytest.raises(TypeError):
        sock.render_client_text(text, client_id)


@pytest.mark.parametrize("client_id", [123, None, [CLIENT]], ids=["int", "none", "list"])
def test_J4R_menu_wrong_argument_type_raises(client_id: Any) -> None:
    with pytest.raises(TypeError):
        sock.client_slots(client_id)
