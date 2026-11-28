"""J9.2: a measure that doesn't apply, on Imani's menu (Brain join spec v0.4, J9.2 v2 checks (a)
to (g), and S49, which governs where it differs from J9.2's text).

Runs are J9's (``j9_fixtures.J9Env.run9``): three ads of a lead client (``lead_client``, marked
lead by its config), each with ctr, cvr and cpa, with aov, roas and contribution_per_click in
``not_estimable`` (D33), variant labels that differ from the ad ids. All data is synthetic; no
case reads ``data/live``.

The token is ``{na:run/<run_id>/<name>}`` with an optional ``|full`` or ``|start``. It renders the
J5 label for the run's kind and nothing else, only when S49 (1)'s rule holds: the name is in
``pipeline.VALUED``, the run's kind is "lead", the run has a variant, and no variant's ad holds a
quantity of that name. The rule is ``claims.applies.applies(snap, kind, ad, name)`` (S49 (2)).

Check (g) is pinned against ``claims/slots.py`` as it stood at ``PRE_J9_2_COMMIT`` (99cbdc9,
before any J9.2 build), loaded from git as a module of its own: every menu item that isn't ``na``
is the same, byte for byte, and fig, cmp and name renders are the same. Those pins pass before
J9.2 is built.

Readings the spec leaves to the test writer, and how they are read here:

* S49 (6) names ``R_NA_CLAIM`` and ``R_NA_APPLIES`` and gives their text. Each is read from
  ``slots`` and its text asserted, and the refusals are asserted by that text, so a missing
  constant fails as an assertion. S49 (1)'s "not a measure that can fail to apply" has no named
  constant; it is asserted by its text.
* A purchase run's ``na`` token: on that run the name applies, so it is refused with
  ``R_NA_APPLIES`` (S49 (6)), the same as a lead run holding the quantity (check (d)).
* Check (f) against S49 (4): a non-newest run's ``na`` token renders, with ``newest`` false, and
  with no "as of" suffix (S49 governs, so it does not take the fig slot's suffix).
* S49 (3) "skips ``ctx.held``": a text whose only slot is ``na`` never calls ``load_held``, and a
  loader that raises or gives null stops neither the render nor the menu's ``na`` items.
* The menu's ``na`` item is J9.2 (4)'s dict exactly, its token with braces as fig tokens are.
* An unreadable run gives the fig slots' run reason, compared with the reason a fig token for
  the same run gets.
"""

from __future__ import annotations

import ast
import inspect
import json
import subprocess
import sys
import types
import typing
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from bayesian_marketing import pipeline
from bayesian_marketing.atmaos import socket as sock
from bayesian_marketing.claims import slots, vocab
from tests.acceptance.j4_fixtures import IMG2_ID, IMG3_ID, IMG4_ID, OTHER
from tests.acceptance.j4r_fixtures import cmp_run, fig_run, name_slot
from tests.acceptance.j7_fixtures import E, M, write_garbage
from tests.acceptance.j9_fixtures import BASE, H1, LABELS, VALUED, J9Env, kind_of

pytestmark = pytest.mark.piece("J9.2")

REPO = Path(__file__).resolve().parents[2]
SLOTS_PATH = "src/bayesian_marketing/claims/slots.py"
PRE_J9_2_COMMIT = "99cbdc9"
"""S49's commit: ``slots.py`` there is the menu and renderer before J9.2's build."""

ADS = (IMG3_ID, IMG2_ID, IMG4_ID)

#: S49 (6), verbatim.
NA_CLAIM_TEXT = "an na slot carries no claim"
NA_APPLIES_TEXT = "the measure applies to this account on that run"
#: S49 (1), verbatim.
NOT_A_MEASURE_TEXT = "not a measure that can fail to apply"

#: J9.2 (4) and S49 (7): the plain reasons.
REASONS = {
    "roas": "a sign-up is given no money value",
    "contribution_per_click": "a sign-up is given no money value",
    "aov": "there are no orders",
}
#: J9.2 (2), S49 (11): J5's lead label (``METRIC_LABELS_LEAD``), and with a capital.
FULL = {
    "aov": "average value per sign-up",
    "roas": "return on ad spend",
    "contribution_per_click": "contribution per click",
}
START = {
    "aov": "Average value per sign-up",
    "roas": "Return on ad spend",
    "contribution_per_click": "Contribution per click",
}


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[J9Env]:
    e = J9Env(tmp_path, monkeypatch)
    yield e
    e.close()


# ------------------------------------------------------------------ helpers


def na(run_id: str, name: str, form: str | None = None, claim: str | None = None) -> str:
    ref = f"run/{run_id}/{name}" + (f"#{claim}" if claim else "")
    return "{na:" + ref + (f"|{form}" if form else "") + "}"


def raw_loader(env: J9Env) -> Any:
    return lambda r: env.raw_held_map(r)


def why(res: dict[str, Any]) -> str:
    parts = list(res.get("reasons") or []) + list(res.get("lint") or [])
    for s in res.get("slots") or []:
        parts += s.get("reasons") or []
    return repr({"ok": res.get("ok"), "text": res.get("text"), "reasons": parts})


def slot_reasons(res: dict[str, Any]) -> list[str]:
    return [r for s in res["slots"] for r in s["reasons"]] + list(res["reasons"])


def render(env: J9Env, text: str, **kw: Any) -> dict[str, Any]:
    kw.setdefault("load_held", raw_loader(env))
    return env.render7(text, **kw)


def menu(env: J9Env, **kw: Any) -> dict[str, Any]:
    kw.setdefault("load_held", raw_loader(env))
    return env.menu7(**kw)


def na_items(m: dict[str, Any]) -> list[dict[str, Any]]:
    return [i for i in m["slots"] if i["kind"] == "na"]


def expected_item(run_id: str, name: str) -> dict[str, Any]:
    """J9.2 (4) and S49 (5), field for field."""
    return {
        "token": "{na:run/" + run_id + "/" + name + "}",
        "kind": "na",
        "measure": name,
        "subject": None,
        "status": None,
        "status_raw": None,
        "applies": False,
        "reason": REASONS[name],
        "newest": True,
        "run_id": run_id,
        "release_id": None,
        "forms": {"full": FULL[name], "start": START[name]},
    }


def no_d33_lines(d: dict[str, Any]) -> None:
    """A lead run saved before D46: no ``not_estimable`` line for a VALUED name."""
    for v in list(d["not_estimable"]):
        for name in VALUED:
            d["not_estimable"][v].pop(name, None)


def assert_na_renders(env: J9Env, rid: str, **kw: Any) -> None:
    for name in VALUED:
        for form, want in ((None, FULL[name]), ("full", FULL[name]), ("start", START[name])):
            res = render(env, f"Here: {na(rid, name, form)}.", **kw)
            assert res["ok"] is True, (name, form, why(res))
            assert res["text"] == f"Here: {want}.", (name, form)
            assert res["slots"][0]["rendered"] == want


def assert_na_refused(env: J9Env, rid: str, name: str, reason: str, **kw: Any) -> None:
    res = render(env, f"Here: {na(rid, name)}.", **kw)
    assert res["ok"] is False, (name, why(res))
    assert res["text"] is None
    assert res["slots"][0]["ok"] is False
    assert res["slots"][0]["rendered"] is None
    assert any(reason in r for r in slot_reasons(res)), (name, why(res))


# ------------------------------------------------------------------ the pre-J9.2 slots.py

_PRE: dict[str, types.ModuleType] = {}


def pre_slots() -> types.ModuleType | None:
    """``slots.py`` at ``PRE_J9_2_COMMIT``, loaded as a module of its own; None without git."""
    if "m" not in _PRE:
        try:
            src = subprocess.run(
                ["git", "-C", str(REPO), "show", f"{PRE_J9_2_COMMIT}:{SLOTS_PATH}"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError):
            return None
        name = "slots_pre_j9_2"
        mod = types.ModuleType(name)
        mod.__file__ = str(REPO / SLOTS_PATH)
        sys.modules[name] = mod  # dataclasses look their module up
        exec(compile(src, f"{PRE_J9_2_COMMIT}:{SLOTS_PATH}", "exec"), mod.__dict__)
        _PRE["m"] = mod
    return _PRE["m"]


def pre_menu(env: J9Env, **kw: Any) -> dict[str, Any]:
    mod = pre_slots()
    assert mod is not None
    kw.setdefault("load_held", raw_loader(env))
    kw.setdefault("load_names", env.load_names)
    kw.setdefault("load_parents", lambda c: {})
    kw.setdefault("load_display_names", lambda c: {})
    return env.in_data(lambda: dict(mod.client_slots(env_client(), **kw)))


def pre_render(env: J9Env, text: str, **kw: Any) -> dict[str, Any]:
    mod = pre_slots()
    assert mod is not None
    kw.setdefault("load_held", raw_loader(env))
    kw.setdefault("load_names", env.load_names)
    kw.setdefault("load_parents", lambda c: {})
    kw.setdefault("load_display_names", lambda c: {})
    return env.in_data(lambda: dict(mod.render_client_text(text, env_client(), **kw)))


def env_client() -> str:
    from tests.acceptance.j4_fixtures import CLIENT

    return CLIENT


def needs_git() -> None:
    if pre_slots() is None:
        pytest.skip(f"git or commit {PRE_J9_2_COMMIT} not available")


# ------------------------------------------------------------------ the constants (S49 (6))


def test_J9_2_S49_6_the_refusal_constants_and_their_text() -> None:
    assert getattr(slots, "R_NA_CLAIM", None) == NA_CLAIM_TEXT
    assert getattr(slots, "R_NA_APPLIES", None) == NA_APPLIES_TEXT


def test_J9_2_S49_5_slot_kind_gains_na_and_menu_item_gains_not_required_keys() -> None:
    assert "na" in typing.get_args(slots.SlotKind)
    hints = typing.get_type_hints(slots.MenuItem, include_extras=True)
    for k in ("applies", "reason"):
        assert k in hints, k
        assert typing.get_origin(hints[k]) is typing.NotRequired, (k, hints[k])
    before = {
        "token", "kind", "measure", "subject", "status", "status_raw", "newest", "run_id",
        "release_id", "forms",
    }  # fmt: skip
    for k in before:  # every key the menu had before J9.2 stays required
        assert typing.get_origin(hints[k]) is not typing.NotRequired, k


# ------------------------------------------------------------------ (a) a lead run


def test_J9_2_a_a_lead_run_gives_three_na_items_with_their_reasons(env: J9Env) -> None:
    rid = env.run9(BASE, M)
    got = na_items(menu(env))
    assert got == [expected_item(rid, name) for name in VALUED]


def test_J9_2_a_each_token_renders_the_label_in_both_forms(env: J9Env) -> None:
    rid = env.run9(BASE, M)
    assert_na_renders(env, rid)


def test_J9_2_2_the_menu_forms_are_what_the_token_renders(env: J9Env) -> None:
    env.run9(BASE, M)
    items = na_items(menu(env))
    assert len(items) == len(VALUED)
    for item in items:
        for form in ("full", "start"):
            res = render(env, item["token"][:-1] + f"|{form}}}")
            assert res["ok"] is True, why(res)
            assert res["text"] == item["forms"][form]


def test_J9_2_S49_11_the_label_is_J5_s_lead_label_and_start_capitalises_it(env: J9Env) -> None:
    rid = env.run9(BASE, M)
    for item in na_items(menu(env)):
        label = vocab.METRIC_LABELS_LEAD[item["measure"]]
        assert item["forms"]["full"] == label
        assert item["forms"]["start"] == slots._start(label, False)
    res = render(env, f"{na(rid, 'roas', 'start')} is not something this account measures.")
    assert res["ok"] is True, why(res)
    assert res["text"] == "Return on ad spend is not something this account measures."


def test_J9_2_S49_5_the_slot_out_shape(env: J9Env) -> None:
    rid = env.run9(BASE, M)
    res = render(env, f"Your {na(rid, 'roas')} isn't measured on a sign-up account.")
    assert res["ok"] is True, why(res)
    assert res["text"] == "Your return on ad spend isn't measured on a sign-up account."
    (row,) = res["slots"]
    assert row["quantity"] == {"name": "roas", "subject": "account", "status": None}
    assert row["newest"] is True
    assert row["run_id"] == rid
    assert row["release_id"] is None
    assert row["claim_id"] is None
    assert row["reasons"] == []
    assert res["lint"] == []


def test_J9_2_S49_1_a_pre_D46_lead_run_with_no_D33_lines_gives_the_same_answer(
    env: J9Env,
) -> None:
    rid = env.run9(BASE, M, also=no_d33_lines)
    d = env.snap_json(rid)
    assert not any(n in ne for ne in d["not_estimable"].values() for n in VALUED)
    assert na_items(menu(env)) == [expected_item(rid, name) for name in VALUED]
    assert_na_renders(env, rid)


def test_J9_2_S49_10_a_none_kind_lead_run_takes_its_kind_from_the_config(env: J9Env) -> None:
    rid = env.run9(BASE, M, kind=None)
    snap = env.snapshot9(rid)
    assert snap.conversion_kind is None and not snap.synthetic
    assert env.in_data(lambda: kind_of(snap)) == "lead"
    assert na_items(menu(env)) == [expected_item(rid, name) for name in VALUED]
    assert_na_renders(env, rid)


def test_J9_2_S49_10_a_none_kind_run_reads_lead_from_the_client_s_runs(env: J9Env) -> None:
    """No config for OTHER: an earlier run says lead, so ``held.run_kind`` gives lead."""
    env.run9(BASE, M, client=OTHER, kind="lead")
    rid = env.run9(BASE + H1, M, client=OTHER, kind=None)
    snap = env.snapshot9(rid)
    assert env.in_data(lambda: kind_of(snap)) == "lead"
    res = env.render7(f"Here: {na(rid, 'roas')}.", client_id=OTHER, load_held=raw_loader(env))
    assert res["ok"] is True, why(res)
    assert res["text"] == "Here: return on ad spend."


def test_J9_2_S49_10_a_synthetic_none_kind_run_is_purchase_and_gives_no_na(env: J9Env) -> None:
    rid = env.run9(BASE, M, kind=None, synthetic=True)
    assert na_items(menu(env)) == []
    for name in VALUED:
        assert_na_refused(env, rid, name, NA_APPLIES_TEXT)


# ------------------------------------------------------------------ (b) a purchase run


def test_J9_2_b_a_purchase_run_gives_no_na_and_its_token_is_refused(env: J9Env) -> None:
    rid = env.run9(BASE, E, kind="purchase")
    m = menu(env)
    assert na_items(m) == []
    assert any(i["kind"] == "fig" for i in m["slots"])  # the run is on the menu
    for name in VALUED:
        assert_na_refused(env, rid, name, NA_APPLIES_TEXT)


# ------------------------------------------------------------------ (c) a claim


@pytest.mark.parametrize("form", [None, "full", "start"])
def test_J9_2_c_a_claim_on_an_na_token_is_refused(env: J9Env, form: str | None) -> None:
    rid = env.run9(BASE, M)
    res = render(env, f"Here: {na(rid, 'roas', form, claim='c_roas1')}.")
    assert res["ok"] is False, why(res)
    assert res["text"] is None
    assert res["slots"][0]["ok"] is False
    assert any(NA_CLAIM_TEXT in r for r in res["slots"][0]["reasons"]), why(res)


# ------------------------------------------------------------------ (d) a quantity of the name


def test_J9_2_d_a_lead_run_with_a_contribution_per_click_quantity_gives_no_na_for_it(
    env: J9Env,
) -> None:
    rid = env.run9(BASE, M, add=[{"ad": IMG3_ID, "name": "contribution_per_click"}])
    got = na_items(menu(env))
    assert [i["measure"] for i in got] == ["aov", "roas"]
    assert got == [expected_item(rid, "aov"), expected_item(rid, "roas")]
    assert_na_refused(env, rid, "contribution_per_click", NA_APPLIES_TEXT)
    for name in ("aov", "roas"):
        res = render(env, f"Here: {na(rid, name)}.")
        assert res["ok"] is True, why(res)


def test_J9_2_S49_1_one_ad_holding_the_quantity_is_enough_to_refuse(env: J9Env) -> None:
    """Account level (J9.2 (3)): the slot needs every variant without the quantity."""
    rid = env.run9(BASE, M, add=[{"ad": IMG4_ID, "name": "roas"}])
    assert "roas" not in [i["measure"] for i in na_items(menu(env))]
    assert_na_refused(env, rid, "roas", NA_APPLIES_TEXT)


# ------------------------------------------------------------------ S49 (1) the names


@pytest.mark.parametrize("name", ["ctr", "cvr", "cpa", "cpm", "a_future_measure"])
def test_J9_2_S49_1_a_name_outside_valued_is_refused(env: J9Env, name: str) -> None:
    rid = env.run9(BASE, M)
    assert_na_refused(env, rid, name, NOT_A_MEASURE_TEXT)


def test_J9_2_S49_1_a_run_with_no_variant_gives_no_na(env: J9Env) -> None:
    def no_variants(d: dict[str, Any]) -> None:
        d["variants"] = {}
        d["not_estimable"] = {}
        d["quantities"] = [q for q in d["quantities"] if "ad" not in q["scope"]["ids"]]
        d["published"] = {q["quantity_id"]: True for q in d["quantities"]}
        d["comparison"] = None
        d["decision"] = None
        d["recommendations"] = []

    rid = env.run9(BASE, M, labels=None, also=no_variants)
    assert env.snapshot9(rid).variants == {}
    assert na_items(menu(env)) == []
    for name in VALUED:
        res = render(env, f"Here: {na(rid, name)}.")
        assert res["ok"] is False, (name, why(res))
        assert res["text"] is None


# ------------------------------------------------------------------ S49 (6) grammar and run reasons


@pytest.mark.parametrize(
    "body",
    ["na:account/roas", "na:run/r1", "na:run/r1/roas|bold", "na:run/r1/roas/extra", "na:roas"],
)
def test_J9_2_1_a_token_outside_the_grammar_is_refused(env: J9Env, body: str) -> None:
    env.run9(BASE, M)
    res = render(env, "Here: {" + body + "}.")
    assert res["ok"] is False
    assert any(slots.R_BAD_SLOT in r for r in res["slots"][0]["reasons"]), why(res)


def test_J9_2_S49_6_an_unreadable_run_gives_the_fig_slots_run_reason(env: J9Env) -> None:
    rid = env.run9(BASE, M)
    qid = env.qid(rid, IMG3_ID, "ctr")
    write_garbage(env.data_dir / "runs" / f"{rid}.json")
    fig = render(env, f"Here: {fig_run(rid, qid)}.")
    assert fig["ok"] is False
    want = fig["slots"][0]["reasons"]
    assert want and f"run {rid}: cannot be read" in want[0]
    res = render(env, f"Here: {na(rid, 'roas')}.")
    assert res["ok"] is False
    assert res["slots"][0]["reasons"] == want


def test_J9_2_S49_6_a_missing_run_gives_the_fig_slots_run_reason(env: J9Env) -> None:
    env.run9(BASE, M)
    fig = render(env, f"Here: {fig_run('run_nosuch01', 'q_nosuch')}.")
    res = render(env, f"Here: {na('run_nosuch01', 'roas')}.")
    assert res["ok"] is False
    assert res["slots"][0]["reasons"] == fig["slots"][0]["reasons"]
    assert any("run run_nosuch01: cannot be read" in r for r in res["slots"][0]["reasons"])


def test_J9_2_S49_6_no_na_item_when_the_newest_run_cannot_be_read(env: J9Env) -> None:
    env.run9(BASE, M)
    rid = env.run9(BASE + H1, M)
    path = env.data_dir / "runs" / f"{rid}.json"
    d = json.loads(path.read_text())
    del d["variants"]  # still the client's run (its client id reads), but it won't load
    path.write_text(json.dumps(d))
    m = menu(env)
    assert na_items(m) == []
    assert any(f"run {rid}: cannot be read" in r for r in m["reasons"])


def test_J9_2_an_na_token_for_another_client_s_run_is_refused(env: J9Env) -> None:
    env.run9(BASE, M)
    other = env.run9(BASE + H1, M, client=OTHER, kind="lead")
    res = render(env, f"Here: {na(other, 'roas')}.")
    assert res["ok"] is False, why(res)
    assert res["text"] is None


# ------------------------------------------------------------------ S49 (3) held status


def test_J9_2_S49_3_an_na_slot_never_calls_load_held(env: J9Env) -> None:
    rid = env.run9(BASE, M)
    calls: list[str] = []

    def load_held(run_id: str) -> dict:
        calls.append(run_id)
        return env.raw_held_map(run_id)

    res = render(env, f"Here: {na(rid, 'aov')}.", load_held=load_held)
    assert res["ok"] is True, why(res)
    assert calls == []


@pytest.mark.parametrize("how", ["raises", "none"])
def test_J9_2_S49_3_a_held_loader_that_fails_stops_no_na_slot(env: J9Env, how: str) -> None:
    rid = env.run9(BASE, M)

    def load_held(run_id: str) -> dict:
        if how == "raises":
            raise RuntimeError("held store unreadable for the case")
        return None  # type: ignore[return-value]

    assert_na_renders(env, rid, load_held=load_held)
    fig = render(env, f"Here: {fig_run(rid, env.qid(rid, IMG3_ID, 'ctr'))}.", load_held=load_held)
    assert fig["ok"] is False  # the fig slot of the same run is still refused (S39 (10))
    m = menu(env, load_held=load_held)
    assert not [i for i in m["slots"] if i["kind"] in ("fig", "cmp") and i["run_id"] == rid]
    assert na_items(m) == [expected_item(rid, name) for name in VALUED]


def test_J9_2_S49_3_the_default_loader_does_not_stop_an_na_slot(env: J9Env) -> None:
    """No zone anywhere: ``held_status`` raises inside the default loader."""
    rid = env.run9(BASE, M, tz=None)
    for name in VALUED:
        res = env.render7(f"Here: {na(rid, name)}.")
        assert res["ok"] is True, why(res)
        assert res["text"] == f"Here: {FULL[name]}."


def test_J9_2_S49_2_the_renderer_reads_the_snapshot_never_result_of(
    env: J9Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    rid = env.run9(BASE, M)

    def boom(*a: Any, **k: Any) -> Any:
        raise AssertionError("result_of called by the renderer")

    monkeypatch.setattr(sock, "result_of", boom)
    assert_na_renders(env, rid)
    assert na_items(menu(env)) == [expected_item(rid, name) for name in VALUED]


# ------------------------------------------------------------------ (f), S49 (4) not the newest run


def test_J9_2_f_S49_4_a_non_newest_run_renders_with_newest_false_and_no_as_of(
    env: J9Env,
) -> None:
    old = env.run9(BASE, M)
    new = env.run9(BASE + H1, M)
    fig = render(env, f"Here: {fig_run(old, env.qid(old, IMG3_ID, 'ctr'))}.")
    assert fig["ok"] is True, why(fig)
    assert ", as of " in fig["text"]  # the run is not the newest, and a fig slot says so
    for name in VALUED:
        for form, want in (("full", FULL[name]), ("start", START[name])):
            res = render(env, f"Here: {na(old, name, form)}.")
            assert res["ok"] is True, why(res)
            assert res["text"] == f"Here: {want}."
            assert "as of" not in res["text"]
            assert res["slots"][0]["newest"] is False
            assert res["slots"][0]["run_id"] == old
    assert render(env, f"Here: {na(new, 'roas')}.")["slots"][0]["newest"] is True
    # the menu lists the newest run's only
    assert {i["run_id"] for i in na_items(menu(env))} == {new}


def test_J9_2_S49_4_the_newest_run_has_no_as_of_either(env: J9Env) -> None:
    rid = env.run9(BASE, M)
    for item in na_items(menu(env)):
        assert "as of" not in item["forms"]["full"] and "as of" not in item["forms"]["start"]
    res = render(env, f"Here: {na(rid, 'aov', 'start')}.")
    assert res["text"] == "Here: Average value per sign-up."


# ------------------------------------------------------------------ (g), S49 (11) the menu's order


def test_J9_2_S49_11_na_items_come_after_fig_and_cmp_and_before_name(env: J9Env) -> None:
    env.run9(BASE, M)
    kinds = [i["kind"] for i in menu(env)["slots"]]
    assert "fig" in kinds and "cmp" in kinds and "name" in kinds and "na" in kinds
    first_na, last_na = kinds.index("na"), len(kinds) - 1 - kinds[::-1].index("na")
    assert all(k in ("fig", "cmp") for k in kinds[:first_na]), kinds
    assert all(k == "na" for k in kinds[first_na : last_na + 1]), kinds
    assert all(k == "name" for k in kinds[last_na + 1 :]), kinds
    assert [i["measure"] for i in na_items(menu(env))] == list(pipeline.VALUED)


#: Menu shapes for the pin: the case and its ``run9`` arguments, one newest run each.
PIN_RUNS: dict[str, dict[str, Any]] = {
    "lead": {},
    "lead_cpc": {"add": [{"ad": IMG3_ID, "name": "contribution_per_click"}]},
    "purchase": {"kind": "purchase", "ctr": E},
    "none_kind": {"kind": None, "labels": None, "adset": True},
}


@pytest.mark.parametrize("case", ["lead", "lead_cpc", "purchase", "none_kind", "older"])
def test_J9_2_g_every_other_menu_item_is_byte_for_byte_the_pre_J9_2_menu(
    env: J9Env, case: str
) -> None:
    needs_git()
    if case == "older":
        env.run9(BASE, M)
        env.run9(BASE + H1, E, kind="purchase")
    else:
        kw = dict(PIN_RUNS[case])
        ctr = kw.pop("ctr", M)
        env.run9(BASE, ctr, **kw)
    now = menu(env)
    before = pre_menu(env)
    assert before["slots"], "the pinned menu lists items"
    rest = [i for i in now["slots"] if i["kind"] != "na"]
    assert json.dumps(rest) == json.dumps(before["slots"]), case
    assert now["reasons"] == before["reasons"]
    for item in rest:
        assert "applies" not in item and "reason" not in item  # S49 (5)


def test_J9_2_g_the_menu_with_a_failing_held_loader_is_the_pre_J9_2_menu_beside_na(
    env: J9Env,
) -> None:
    needs_git()
    env.run9(BASE, M)

    def load_held(run_id: str) -> dict:
        raise RuntimeError("held store unreadable for the case")

    now = menu(env, load_held=load_held)
    before = pre_menu(env, load_held=load_held)
    rest = [i for i in now["slots"] if i["kind"] != "na"]
    assert json.dumps(rest) == json.dumps(before["slots"])


def test_J9_2_g_fig_cmp_and_name_renders_are_the_pre_J9_2_renders(env: J9Env) -> None:
    needs_git()
    old = env.run9(BASE, M)
    new = env.run9(BASE + H1, {IMG3_ID: E})
    texts = [
        f"Here: {fig_run(new, env.qid(new, IMG3_ID, 'ctr'), 'start')}.",
        f"Then {fig_run(old, env.qid(old, IMG2_ID, 'cvr'))} and {cmp_run(new)}.",
        f"The ad {name_slot(IMG3_ID)} is live.",
        f"Here: {fig_run(new, env.qid(new, IMG3_ID, 'ctr'), claim='c1')}.",
        "Here: {fig:run/" + new + "/q_nosuch}.",
    ]
    for text in texts:
        now, before = render(env, text), pre_render(env, text)
        for k in ("checked_at",):
            now.pop(k)
            before.pop(k)
        assert json.dumps(now) == json.dumps(before), text


# ------------------------------------------------------------------ (e), S49 (8) the numeral rule


def test_J9_2_e_S49_8_labels_and_reasons_hold_nothing_the_numeral_rule_refuses() -> None:
    for name in VALUED:
        for text in (FULL[name], START[name], REASONS[name]):
            assert slots._numeral_reasons(text) == [], (name, text)


def test_J9_2_e_the_menu_s_forms_and_reasons_pass_the_numeral_rule(env: J9Env) -> None:
    env.run9(BASE, M)
    got = na_items(menu(env))
    assert len(got) == len(VALUED)
    for item in got:
        for text in (item["forms"]["full"], item["forms"]["start"], item["reason"]):
            assert slots._numeral_reasons(text) == [], (item["measure"], text)


def test_J9_2_e_the_rendered_text_passes_the_numeral_rule(env: J9Env) -> None:
    rid = env.run9(BASE, M)
    text = (
        f"{na(rid, 'roas', 'start')} is not something this account measures, and nor is "
        f"its {na(rid, 'contribution_per_click')} or its {na(rid, 'aov')}."
    )
    res = render(env, text)
    assert res["ok"] is True, why(res)
    assert res["text"] == (
        "Return on ad spend is not something this account measures, and nor is its "
        "contribution per click or its average value per sign-up."
    )
    assert slots._numeral_reasons(res["text"]) == []


# ------------------------------------------------------------------ S49 (2) the one rule


def _applies_module() -> types.ModuleType:
    try:
        from bayesian_marketing.claims import applies as A
    except ImportError as exc:
        pytest.fail(f"no claims.applies module (S49 (2)): {exc}")
    return A


def test_J9_2_S49_2_applies_imports_neither_slots_nor_socket() -> None:
    A = _applies_module()
    tree = ast.parse(inspect.getsource(A))
    named: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            named += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            named += [base] + [f"{base}.{a.name}" for a in node.names]
    for n in named:
        assert not n.endswith(("claims.slots", ".slots", "atmaos.socket")), n
        assert n not in ("slots", "socket"), n
    assert inspect.signature(A.applies).parameters.keys() == {"snap", "kind", "ad", "name"}


def test_J9_2_S49_2_applies_is_false_only_for_a_lead_valued_name_with_no_quantity(
    env: J9Env,
) -> None:
    A = _applies_module()
    rid = env.run9(BASE, M, add=[{"ad": IMG3_ID, "name": "contribution_per_click"}])
    snap = env.snapshot9(rid)
    for ad in ADS:
        for name in (*VALUED, "ctr", "cvr", "cpa", "cpm", "a_future_measure"):
            held = any(q.name == name and q.scope.ids.get("ad") == ad for q in snap.quantities)
            want = not (name in VALUED and not held)
            assert A.applies(snap, "lead", ad, name) is want, (ad, name)
            assert A.applies(snap, "purchase", ad, name) is True, (ad, name)
    assert A.applies(snap, "lead", IMG3_ID, "contribution_per_click") is True
    assert A.applies(snap, "lead", IMG2_ID, "contribution_per_click") is False


def test_J9_2_S49_1_applies_ignores_not_estimable_lines(env: J9Env) -> None:
    A = _applies_module()
    with_lines = env.snapshot9(env.run9(BASE, M))
    without = env.snapshot9(env.run9(BASE + H1, M, also=no_d33_lines))
    for ad in ADS:
        for name in VALUED:
            assert A.applies(with_lines, "lead", ad, name) is False
            assert A.applies(without, "lead", ad, name) is False


def _fixture_runs(env: J9Env) -> list[str]:
    t = BASE
    return [
        env.run9(t, M),
        env.run9(t + H1, M, add=[{"ad": IMG3_ID, "name": "contribution_per_click"}]),
        env.run9(t + 2 * H1, E, kind="purchase", currency="EUR"),
        env.run9(t + 3 * H1, M, kind=None, adset=True),
        env.run9(t + 4 * H1, M, also=no_d33_lines),
        env.run9(t + 5 * H1, M, kind=None, synthetic=True),
        env.run9(t + 6 * H1, M, labels=None, add=[{"ad": IMG4_ID, "name": "aov"}]),
    ]


def test_J9_2_S49_2_result_of_applies_is_claims_applies_on_every_entry(env: J9Env) -> None:
    A = _applies_module()
    seen = {True: 0, False: 0}
    for rid in _fixture_runs(env):
        snap = env.snapshot9(rid)
        kind = env.in_data(lambda s=snap: kind_of(s))
        res = env.result_of_snapshot(snap)
        quantities = res["uncertainty"]["quantities"]
        for v, by_name in quantities.items():
            ad = snap.variants[v]
            for name, entry in by_name.items():
                assert "applies" in entry, (rid, v, name)
                want = A.applies(snap, kind, ad, name)
                assert entry["applies"] is want, (rid, v, name)
                seen[want] += 1
    assert seen[True] and seen[False]


def test_J9_2_S49_1_the_renderer_and_the_menu_follow_claims_applies(env: J9Env) -> None:
    A = _applies_module()
    rids = _fixture_runs(env)
    for rid in rids:
        snap = env.snapshot9(rid)
        kind = env.in_data(lambda s=snap: kind_of(s))
        for name in VALUED:
            want = (
                kind == "lead"
                and bool(snap.variants)
                and all(A.applies(snap, kind, ad, name) is False for ad in snap.variants.values())
            )
            res = render(env, f"Here: {na(rid, name)}.")
            assert res["ok"] is want, (rid, name, why(res))
            if not want:
                assert any(NA_APPLIES_TEXT in r for r in slot_reasons(res)), why(res)
    # the menu reads the newest run, the last built: a lead run with aov on IMG4 only
    assert [i["measure"] for i in na_items(menu(env))] == ["roas", "contribution_per_click"]
    assert {i["run_id"] for i in na_items(menu(env))} == {rids[-1]}


# ------------------------------------------------------------------ J9.2 (3) the per-variant labels


def test_J9_2_3_variant_labels_that_differ_from_ad_ids_change_nothing(env: J9Env) -> None:
    rid = env.run9(BASE, M, labels=LABELS)
    snap = env.snapshot9(rid)
    assert set(snap.variants) == set(LABELS.values())
    assert_na_renders(env, rid)
