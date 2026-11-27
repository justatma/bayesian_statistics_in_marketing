"""J4R.2: ads that share a name (Brain join spec v0.4, the J4R.2 section, rules 1 to 10 and checks
(a) to (m)).

Every slot case calls through the socket entries ``client_slots`` and ``render_client_text``
against fixture runs and releases in ``tmp_path`` (``j4r2_fixtures``). The two new loaders are
injected as fakes unless a case asks for a default; the defaults are pointed at a SQLite store and
a client config inside ``tmp_path``. Check (m) drives the refresh on ``j2_fixtures``' fixed poll
and holds test_J2's pinned run id and seed.

"Unnamed" is asserted the way the menu and the render show it: the ad has no name item and no fig
item on the menu, and a slot that names it fails (``ok`` False, ``text`` None). The reason
wording for a raising loader is left free by the spec; the tests ask only that the menu gains a
reason.

Check (b) rests on the J4R and J5 suites passing unchanged; the test here adds that a client with
no shared names gives the same menu with and without a ``display_names`` alias.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from bayesian_marketing import core as C
from bayesian_marketing import pipeline
from bayesian_marketing.claims import slots as S
from bayesian_marketing.live import config as live_config
from bayesian_marketing.live.contracts import LiveRow, PollRecord
from bayesian_marketing.live.refresh import data_dir_env
from bayesian_marketing.live.store import SqliteStore
from bayesian_marketing.prior_registry import registry as prior_registry
from tests.acceptance import j2_fixtures as J2
from tests.acceptance import j4_fixtures as X
from tests.acceptance.j4_fixtures import CLIENT, IMG2_ID, IMG3_ID
from tests.acceptance.j4r2_fixtures import (
    CREATIVE,
    IMG2_PAUSED,
    IMG2_UPDATED,
    LIVE_ADS,
    LIVE_EXPECTED,
    MAIN,
    MAIN_ALIAS,
    MAIN_META,
    PAUSED_EXPECTED,
    J4R2Env,
    ad_source,
    event_entry,
    fig_items,
    name_items,
    name_slot_of,
    typed_source,
)
from tests.acceptance.j4r_fixtures import cmp_run, fig_nb, fig_run
from tests.acceptance.test_J2 import RUN_ID_BEFORE_J2, SEED_BEFORE_J2, T_APPROVE, T_RUN
from tests.acceptance.test_J5 import LEAD
from tests.acceptance.test_L5 import config

pytestmark = pytest.mark.piece("J4R2")

UTC = dt.UTC
EN = chr(0x2013)  # en dash
REPO = Path(__file__).resolve().parents[2]
READ_AT = "2026-11-20T15:00:00+00:00"
STORE_AD = "120000000000000003"  # an ad only the store names (the "C" of rule 2's example)
STORE_AD2 = "120000000000000004"
ROUGH = "still a rough estimate"


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> J4R2Env:
    monkeypatch.delenv("BAYES_LIVE_DIR", raising=False)
    return J4R2Env(tmp_path, monkeypatch)


@pytest.fixture
def j2env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[J2.J2Env]:
    yield from J2.make_env(tmp_path, monkeypatch)


# ------------------------------------------------------------------ helpers


def all_reasons(res: dict[str, Any]) -> str:
    parts = list(res["reasons"]) + list(res.get("lint") or [])
    for s in res.get("slots") or []:
        parts += s.get("reasons") or []
    return "\n".join(parts)


def why(res: dict[str, Any]) -> str:
    return repr({"ok": res.get("ok"), "text": res.get("text"), "reasons": all_reasons(res)})


def assert_named(env: J4R2Env, ad: str, shown: str, **kw: Any) -> None:
    """The menu lists the ad's name item with ``shown``, and its name slot renders ``shown``."""
    menu_names = name_items(env.menu(**kw))
    assert menu_names.get(ad) == shown, (ad, menu_names)
    res = env.render(f"The ad {name_slot_of(ad)} is live.", **kw)
    assert res["ok"] is True, why(res)
    assert res["text"] == f"The ad {shown} is live.", res["text"]


def assert_unnamed(env: J4R2Env, ad: str, **kw: Any) -> None:
    menu = env.menu(**kw)
    assert ad not in name_items(menu), (ad, name_items(menu))
    assert fig_items(menu, ad) == [], fig_items(menu, ad)
    res = env.render(f"The ad {name_slot_of(ad)} is live.", **kw)
    assert res["ok"] is False, why(res)
    assert res["text"] is None
    assert res["slots"][0]["ok"] is False


def render_name(env: J4R2Env, ad: str, **kw: Any) -> str | None:
    res = env.render(f"The ad {name_slot_of(ad)} is live.", **kw)
    if not res["ok"]:
        return None
    text = res["text"]
    assert text.startswith("The ad ") and text.endswith(" is live."), text
    return text[len("The ad ") : -len(" is live.")]


def two_set_names(**extra: str) -> dict[str, str]:
    """IMG3 and IMG2 of the J4 run both named "V", in ad sets "Set A" and "Set B"."""
    return {IMG3_ID: "V", IMG2_ID: "V", "sA": "Set A", "sB": "Set B", **extra}


TWO_SETS = {IMG3_ID: "sA", IMG2_ID: "sB"}


# ------------------------------------------------------------------ (a) the live shape


def test_J4R2_a_live_shape_names_all_seven_ads(env: J4R2Env) -> None:
    env.live_run()
    env.store_names = {IMG2_PAUSED: IMG2_UPDATED}
    env.store_parents = {IMG2_PAUSED: CREATIVE}
    env.display = {MAIN: MAIN_ALIAS}
    names = name_items(env.menu())
    assert names == LIVE_EXPECTED, names
    assert set(names) == set(LIVE_ADS)  # each name item's subject is the ad id


def test_J4R2_a_live_shape_each_ad_has_its_figures(env: J4R2Env) -> None:
    """Every ad of the run, the four shared-name ones included, has fig items on the menu, each
    naming the ad by its rendered name followed by the possessive."""
    env.live_run()
    env.store_names = {IMG2_PAUSED: IMG2_UPDATED}
    env.store_parents = {IMG2_PAUSED: CREATIVE}
    env.display = {MAIN: MAIN_ALIAS}
    menu = env.menu()
    for ad, shown in LIVE_EXPECTED.items():
        figs = fig_items(menu, ad)
        assert figs, (ad, shown)
        for item in figs:
            assert item["forms"]["full"].startswith(f"{shown}'s "), item["forms"]
            res = env.render(f"We looked at {item['token']}.")
            assert res["ok"] is True, why(res)


def test_J4R2_a_live_shape_paused_copy_is_named_by_its_ad_set(env: J4R2Env) -> None:
    """The paused copy, known only to the store layers, is the third holder of its name and is
    named by Creative Test (rules 2 to 5)."""
    env.live_run()
    env.store_names = {IMG2_PAUSED: IMG2_UPDATED}
    env.store_parents = {IMG2_PAUSED: CREATIVE}
    env.display = {MAIN: MAIN_ALIAS}
    assert render_name(env, IMG2_PAUSED) == PAUSED_EXPECTED


def test_J4R2_a_live_shape_with_the_config_alias_through_the_default_loader(
    env: J4R2Env,
) -> None:
    """Rule 9: the default ``load_display_names`` reads the client's config (in tmp_path)."""
    env.write_config(config(**LEAD, display_names={MAIN: MAIN_ALIAS}))
    env.live_run()
    names = name_items(env.menu(load_display_names=None))
    assert names == LIVE_EXPECTED, names


def test_J4R2_9_default_loader_resolves_the_atmaos_alias(env: J4R2Env) -> None:
    aos = "aos-0000-j4r2"
    env.write_config(config(**LEAD, atmaos_client_id=aos, display_names={MAIN: MAIN_ALIAS}))
    env.live_run()
    menu = env.menu(aos, load_display_names=None)
    assert menu["client_id"] == CLIENT
    assert name_items(menu) == LIVE_EXPECTED


def test_J4R2_a_main_ad_set_without_its_alias_leaves_its_shared_ads_unnamed(
    env: J4R2Env,
) -> None:
    """The main ad set's Meta name holds "$", so without the alias its two shared-name ads have
    no name; the creative-test and IMG2-test ads still do."""
    env.live_run()
    names = name_items(env.menu())
    for ad in ("120253899504560526", "120253993297010526"):
        assert ad not in names, names
    assert names["120254012200990526"] == "VID1_TXT1 (Creative Test)"
    assert names["120254063879420526"] == f"IMG2_TXT1 {EN} Updated (IMG2 test)"
    assert MAIN_META not in json.dumps(env.menu(), ensure_ascii=False)


# ------------------------------------------------------------------ (b) nothing changes


def test_J4R2_b_no_shared_names_menu_is_identical_with_and_without_an_alias(
    env: J4R2Env,
) -> None:
    run_id = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)  # IMG3_TXT1 and IMG2_TXT1 - Updated.
    env.set_names_and_parents(
        run_id, {**X.RUN_NAMES, "s1": "Set One"}, {IMG3_ID: "s1", IMG2_ID: "s1"}
    )
    env.ctr_44(run_id)
    env.release()
    plain = env.menu(load_display_names=lambda c: {})
    aliased = env.menu(load_display_names=lambda c: {"s1": "the only ad set"})

    def body(m: dict[str, Any]) -> str:
        return json.dumps({k: v for k, v in m.items() if k != "checked_at"}, sort_keys=True)

    assert body(plain) == body(aliased)
    assert name_items(plain) == {IMG3_ID: X.IMG3, IMG2_ID: X.IMG2_NAME}


def test_J4R2_b_unique_name_renders_as_before_beside_a_qualified_one(env: J4R2Env) -> None:
    """IMG3 keeps its bare name while a store-only ad shares IMG2's name: only the holders of
    the shared name change."""
    env.shared_run({IMG3_ID: "IMG3_TXT1", IMG2_ID: "V", "sA": "Set A", "sB": "Set B"}, TWO_SETS)
    env.store_names = {STORE_AD: "V"}
    env.store_parents = {STORE_AD: "sA"}
    assert_named(env, IMG3_ID, "IMG3_TXT1")
    assert_named(env, IMG2_ID, "V (Set B)")
    assert render_name(env, STORE_AD) == "V (Set A)"


# ------------------------------------------------------------------ (c) one ad set, one name


@pytest.mark.parametrize("order", ["forward", "reversed"])
def test_J4R2_c_two_ads_with_one_name_in_one_ad_set_stay_unnamed(env: J4R2Env, order: str) -> None:
    names = {IMG3_ID: "V", IMG2_ID: "V", "sA": "Set A", "sB": "Set B"}
    parents = {IMG3_ID: "sA", IMG2_ID: "sA"}
    if order == "reversed":
        names = dict(reversed(list(names.items())))
        parents = dict(reversed(list(parents.items())))
    env.shared_run(names, parents)
    env.store_names = {STORE_AD: "V"}
    env.store_parents = {STORE_AD: "sB"}
    assert_unnamed(env, IMG3_ID)
    assert_unnamed(env, IMG2_ID)
    # the third holder of the name, alone in its ad set, is still named (rule 6: all at once)
    assert render_name(env, STORE_AD) == "V (Set B)"


# ------------------------------------------------------------------ (d) the ad set's display name


def test_J4R2_d_failing_meta_name_and_no_alias_leaves_its_ads_unnamed(env: J4R2Env) -> None:
    env.shared_run(two_set_names(sA=MAIN_META), TWO_SETS)
    assert_unnamed(env, IMG3_ID)
    assert_named(env, IMG2_ID, "V (Set B)")


def test_J4R2_d_alias_rescues_a_failing_meta_name(env: J4R2Env) -> None:
    env.shared_run(two_set_names(sA=MAIN_META), TWO_SETS)
    env.display = {"sA": MAIN_ALIAS}
    assert_named(env, IMG3_ID, "V (the main ad set)")


def test_J4R2_d_alias_wins_over_a_passing_meta_name(env: J4R2Env) -> None:
    env.shared_run(two_set_names(), TWO_SETS)
    env.display = {"sA": "the first set"}
    assert_named(env, IMG3_ID, "V (the first set)")
    assert_named(env, IMG2_ID, "V (Set B)")


def test_J4R2_d_meta_name_is_used_without_an_alias(env: J4R2Env) -> None:
    env.shared_run(two_set_names(), TWO_SETS)
    assert_named(env, IMG3_ID, "V (Set A)")
    assert_named(env, IMG2_ID, "V (Set B)")


@pytest.mark.parametrize(
    "meta",
    ["Set {A}", "Fifty percent set", "Set 50%", "Set €", "USD set", "Set\nA", "Set\x07A"],
    ids=["brace", "percent_word", "percent_sign", "currency_sign", "iso_code", "lf", "control"],
)
def test_J4R2_4_meta_name_failing_the_display_name_rule_gives_no_name(
    env: J4R2Env, meta: str
) -> None:
    env.shared_run(two_set_names(sA=meta), TWO_SETS)
    assert_unnamed(env, IMG3_ID)
    assert_named(env, IMG2_ID, "V (Set B)")


# ------------------------------------------------------------------ (e) the config and the loader


def _write_yaml(env: J4R2Env, display_block: str) -> None:
    base = config(**LEAD).model_dump(mode="json")
    base.pop("display_names", None)
    text = yaml.safe_dump(base, sort_keys=False) + display_block
    (env.config_root / f"{CLIENT}.yaml").write_text(text)


@pytest.mark.parametrize(
    "value",
    ["Cap@$1500", "Fifty percent", "Set 50%", "{set}", "USD set", "Line\\nbreak", "Bell\\x07"],
    ids=["currency_sign", "percent_word", "percent_sign", "brace", "iso_code", "lf", "control"],
)
def test_J4R2_e_failing_display_name_fails_load_client_naming_the_key(
    env: J4R2Env, value: str
) -> None:
    _write_yaml(env, f'display_names:\n  "{MAIN}": "{value}"\n')
    with pytest.raises(Exception) as got:
        live_config.load_client(CLIENT)
    assert MAIN in str(got.value), str(got.value)


def test_J4R2_8_passing_display_names_load(env: J4R2Env) -> None:
    _write_yaml(env, f'display_names:\n  "{MAIN}": "{MAIN_ALIAS}"\n  "s2": "Test 2"\n')
    cfg = live_config.load_client(CLIENT)
    assert cfg.display_names == {MAIN: MAIN_ALIAS, "s2": "Test 2"}


def test_J4R2_8_unquoted_key_fails_load_client(env: J4R2Env) -> None:
    _write_yaml(env, f'display_names:\n  {MAIN}: "{MAIN_ALIAS}"\n')
    with pytest.raises(Exception):  # noqa: B017  # the spec names no type
        live_config.load_client(CLIENT)


def test_J4R2_8_display_name_check_is_the_release_label_check(
    env: J4R2Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 8: the config check uses the function ``notebook/release.py`` uses
    (``claims.slots._name_states_a_figure``), so patching it changes what the load refuses."""
    _write_yaml(env, f'display_names:\n  "{MAIN}": "{MAIN_ALIAS}"\n')
    monkeypatch.setattr(S, "_name_states_a_figure", lambda name: f"refused {name!r}")
    with pytest.raises(Exception) as got:
        live_config.load_client(CLIENT)
    assert MAIN in str(got.value)


def test_J4R2_8_jovannah_config_aliases_the_main_ad_set() -> None:
    cfg = live_config.load_client("jovannah", REPO / "configs")
    assert cfg.display_names.get(MAIN) == MAIN_ALIAS


def test_J4R2_e_failing_load_display_names_qualifies_nothing_and_says_so(env: J4R2Env) -> None:
    env.shared_run(two_set_names(), TWO_SETS)
    baseline = env.menu()
    assert name_items(baseline) == {IMG3_ID: "V (Set A)", IMG2_ID: "V (Set B)"}

    def boom(client_id: str) -> dict[str, str]:
        raise RuntimeError("display names unreadable")

    menu = env.menu(load_display_names=boom)
    assert IMG3_ID not in name_items(menu) and IMG2_ID not in name_items(menu)
    assert len(menu["reasons"]) > len(baseline["reasons"]), menu["reasons"]
    # it never falls back to the Meta name: the slot fails
    res = env.render(f"The ad {name_slot_of(IMG3_ID)} is live.", load_display_names=boom)
    assert res["ok"] is False and res["text"] is None
    assert res["reasons"], res


def test_J4R2_9_alias_of_an_ad_id_is_ignored_with_a_reason(env: J4R2Env) -> None:
    """An alias keyed by an ad's id (typed ad by the run's variants) is ignored: the shared-name
    ads are still named by their ad sets, the alias shows nowhere, and the menu gains a
    reason."""
    env.shared_run(two_set_names(), TWO_SETS)
    baseline = env.menu()
    env.display = {IMG3_ID: "the third image"}
    menu = env.menu()
    assert name_items(menu) == {IMG3_ID: "V (Set A)", IMG2_ID: "V (Set B)"}
    assert "the third image" not in json.dumps(menu)
    assert len(menu["reasons"]) > len(baseline["reasons"]), menu["reasons"]


def test_J4R2_9_alias_of_a_campaign_id_is_ignored_with_a_reason(env: J4R2Env) -> None:
    """A campaign id (typed by a release source) aliased in ``display_names``: ignored, with a
    reason, and the ad whose parent it is named gets no name from it."""
    env.shared_run(two_set_names(), {IMG3_ID: "c9", IMG2_ID: "sB"})
    env.release_of([typed_source("campaign", "c9", "Spring campaign", READ_AT)])
    baseline = env.menu()
    env.display = {"c9": "the spring campaign"}
    menu = env.menu()
    assert len(menu["reasons"]) > len(baseline["reasons"]), menu["reasons"]
    assert "the spring campaign" not in json.dumps(menu)
    assert_unnamed(env, IMG3_ID)
    assert_named(env, IMG2_ID, "V (Set B)")


# ------------------------------------------------------------------ (f) rule 2's A, B and C


def test_J4R2_f_store_only_holder_of_a_shared_name_is_a_candidate(env: J4R2Env) -> None:
    """The snapshot names A and B "V"; the store alone names C "V" (merge_names keeps C bare
    today). All three are candidates, each named by its own ad set."""
    env.shared_run(two_set_names(sC="Set C"), TWO_SETS)
    env.store_names = {STORE_AD: "V"}
    env.store_parents = {STORE_AD: "sC"}
    assert_named(env, IMG3_ID, "V (Set A)")
    assert_named(env, IMG2_ID, "V (Set B)")
    assert render_name(env, STORE_AD) == "V (Set C)"


def test_J4R2_2_candidate_without_a_parent_loses_its_bare_name(env: J4R2Env) -> None:
    """C, kept bare by merge_names today, has no parent anywhere: it is removed from the final
    names and stays unnamed (rules 2 and 6)."""
    env.shared_run(two_set_names(), TWO_SETS)
    env.store_names = {STORE_AD: "V"}
    assert render_name(env, STORE_AD) is None
    assert_named(env, IMG3_ID, "V (Set A)")


def test_J4R2_2_an_ad_sharing_a_name_with_a_campaign_is_qualified(env: J4R2Env) -> None:
    env.shared_run({IMG3_ID: "V", IMG2_ID: "W", "c9": "V", "sA": "Set A"}, {IMG3_ID: "sA"})
    assert_named(env, IMG3_ID, "V (Set A)")
    assert_named(env, IMG2_ID, "W")


# ------------------------------------------------------------------ (g) parent layers


def _parent_case(env: J4R2Env, case: str) -> None:
    """A (IMG3) is given "High set" by the higher layer and "Low set" by the lower one."""
    names = two_set_names(sHi="High set", sLo="Low set")
    snap_parents = {IMG2_ID: "sB"}
    if case in ("snapshot_vs_release", "snapshot_vs_loader"):
        snap_parents[IMG3_ID] = "sHi"
    env.shared_run(names, snap_parents)
    if case == "snapshot_vs_release":
        env.release_of([ad_source(IMG3_ID, "V", "sLo", READ_AT)])
    elif case == "snapshot_vs_loader":
        env.store_parents = {IMG3_ID: "sLo"}
    elif case == "release_vs_loader":
        env.release_of([ad_source(IMG3_ID, "V", "sHi", READ_AT)])
        env.store_parents = {IMG3_ID: "sLo"}
    elif case == "newer_release_vs_older":
        r1 = env.release_of(
            [ad_source(IMG3_ID, "V", "sLo", READ_AT)],
            day="20261120",
            created_at=dt.datetime(2026, 11, 20, 15, 0, tzinfo=UTC),
        )
        env.release_of(
            [ad_source(IMG3_ID, "V", "sHi", "2026-11-26T15:00:00+00:00")],
            day="20261126",
            created_at=dt.datetime(2026, 11, 26, 15, 0, tzinfo=UTC),
            parent=r1,
        )
    else:
        raise AssertionError(case)


@pytest.mark.parametrize(
    "case",
    ["snapshot_vs_release", "snapshot_vs_loader", "release_vs_loader", "newer_release_vs_older"],
)
def test_J4R2_g_the_higher_parent_layer_wins(env: J4R2Env, case: str) -> None:
    _parent_case(env, case)
    assert_named(env, IMG3_ID, "V (High set)")
    assert_named(env, IMG2_ID, "V (Set B)")


@pytest.mark.parametrize("layer", ["snapshot", "release", "loader"])
def test_J4R2_3_each_parent_layer_alone_gives_the_parent(env: J4R2Env, layer: str) -> None:
    names = two_set_names()
    env.shared_run(names, TWO_SETS if layer == "snapshot" else {IMG2_ID: "sB"})
    if layer == "release":
        env.release_of([ad_source(IMG3_ID, "V", "sA", READ_AT)])
    elif layer == "loader":
        env.store_parents = {IMG3_ID: "sA"}
    assert_named(env, IMG3_ID, "V (Set A)")


def test_J4R2_g_a_raising_parent_loader_is_skipped_with_a_reason(env: J4R2Env) -> None:
    env.shared_run(two_set_names(), {IMG3_ID: "sA"})
    env.store_parents = {IMG2_ID: "sB"}
    baseline = env.menu()
    assert name_items(baseline) == {IMG3_ID: "V (Set A)", IMG2_ID: "V (Set B)"}

    def boom(client_id: str) -> dict[str, str]:
        raise RuntimeError("store locked")

    menu = env.menu(load_parents=boom)
    names = name_items(menu)
    assert names.get(IMG3_ID) == "V (Set A)"  # the snapshot layer still counts
    assert IMG2_ID not in names  # its only parent was in the skipped layer
    assert len(menu["reasons"]) > len(baseline["reasons"]), menu["reasons"]


@pytest.mark.parametrize("parent_type", ["ad", "campaign"])
def test_J4R2_3_a_parent_typed_ad_or_campaign_is_refused(env: J4R2Env, parent_type: str) -> None:
    """The parent is an id a release source types as an ad or a campaign, with a name that would
    pass the display-name rule."""
    env.shared_run(two_set_names(), {IMG2_ID: "sB"})
    env.release_of([typed_source(parent_type, "p9", "Some object", READ_AT)])
    env.store_parents = {IMG3_ID: "p9"}
    assert_unnamed(env, IMG3_ID)
    assert_named(env, IMG2_ID, "V (Set B)")


def test_J4R2_3_default_load_parents_reads_the_store_newest_row(
    env: J4R2Env, tmp_path: Path
) -> None:
    """Rule 3's default: the live store (here a SQLite store in tmp_path, found as the live
    store is), read only, the newest row per ad."""
    env.shared_run(two_set_names(sOld="Old set", sNew="New set"), {IMG3_ID: "sA"})
    store = SqliteStore.open(tmp_path / "live" / "live.sqlite")
    try:
        for n, (when, adset) in enumerate(
            [
                (dt.datetime(2026, 11, 5, 17, 0, tzinfo=UTC), "sOld"),
                (dt.datetime(2026, 11, 6, 17, 0, tzinfo=UTC), "sNew"),
            ]
        ):
            _store_poll(store, when, {IMG2_ID: adset}, n)
    finally:
        store.close()
    before = (tmp_path / "live" / "live.sqlite").read_bytes()
    assert_named(env, IMG2_ID, "V (New set)", load_parents=None)
    assert (tmp_path / "live" / "live.sqlite").read_bytes() == before  # read only


def _store_poll(store: Any, started: dt.datetime, parents: dict[str, str], n: int) -> None:
    pid = J2.poll_id(CLIENT, started)
    rows = [
        LiveRow(
            poll_id=pid,
            client_id=CLIENT,
            platform="meta",
            entity_ids={"account": "555", "campaign": "c1", "ad_set": adset, "ad": ad},
            entity_names={"ad": "V"},
            objective="OUTCOME_LEADS",
            date=dt.date(2026, 11, 1),
            impressions=100,
            clicks=4,
            spend=C.Money(amount="1.00", currency="USD"),
            conversions_reported=1.0,
            conversions_observed=None,
            revenue_reported=None,
            attribution_window="7d_click_1d_view",
        )
        for ad, adset in parents.items()
    ]
    rec = PollRecord(
        poll_id=pid,
        client_id=CLIENT,
        platform="meta",
        account_id="act_555",
        started_at=started,
        finished_at=started + dt.timedelta(seconds=5),
        window=(dt.date(2026, 11, 1), dt.date(2026, 11, 1)),
        status="ok",
        error=None,
        pull_id=f"pull_meta_{90 + n:08d}",
        n_rows=len(rows),
        n_quarantined=0,
        empty_account=False,
        timezone="America/New_York",
        currency="USD",
        account={"currency": "USD"},
        recording_dir=None,
    )
    store.begin_poll(rec)
    store.finish_poll(rec, rows)


# ------------------------------------------------------------------ (h) a shared ad set name


def test_J4R2_h_ad_set_sharing_its_name_with_a_campaign_gives_no_display_name(
    env: J4R2Env,
) -> None:
    env.shared_run(two_set_names(), TWO_SETS)
    env.release_of([typed_source("campaign", "c9", "Set A", READ_AT)])
    assert_unnamed(env, IMG3_ID)
    assert_named(env, IMG2_ID, "V (Set B)")


def test_J4R2_h_two_ad_sets_of_one_name_give_no_display_name(env: J4R2Env) -> None:
    env.shared_run({IMG3_ID: "V", IMG2_ID: "V", "sA": "Set A", "sB": "Set A"}, TWO_SETS)
    env.store_names = {STORE_AD: "V", "sC": "Set C"}
    env.store_parents = {STORE_AD: "sC"}
    assert_unnamed(env, IMG3_ID)
    assert_unnamed(env, IMG2_ID)
    assert render_name(env, STORE_AD) == "V (Set C)"  # the third holder is named


def test_J4R2_h_ad_set_sharing_its_name_with_a_store_only_id_gives_none(env: J4R2Env) -> None:
    """Rule 4 reads the ad set's final name after steps 1 and 2, which every layer feeds."""
    env.shared_run(two_set_names(), TWO_SETS)
    env.store_names = {"sZ": "Set A"}
    assert_unnamed(env, IMG3_ID)
    assert_named(env, IMG2_ID, "V (Set B)")


def test_J4R2_4_alias_names_an_ad_set_whose_name_is_shared(env: J4R2Env) -> None:
    env.shared_run({IMG3_ID: "V", IMG2_ID: "V", "sA": "Set A", "sB": "Set A"}, TWO_SETS)
    env.display = {"sA": "the first set"}
    assert_named(env, IMG3_ID, "V (the first set)")
    assert_unnamed(env, IMG2_ID)


# ------------------------------------------------------------------ (i) trailing punctuation


def test_J4R2_i_V_dot_and_V_in_one_ad_set_both_stay_unnamed(env: J4R2Env) -> None:
    """ "V" (IMG3) and "V." (IMG2) both in Set A. Each name is also held by an ad in another ad
    set, so all four are candidates (rule 2 groups by ``norm_name``, which keeps the stop). After
    the stop is stripped, IMG3 and IMG2 both render "V (Set A)", so both stay unnamed; the other
    two, alone in their ad sets, are named."""
    env.shared_run(
        {IMG3_ID: "V", IMG2_ID: "V.", "sA": "Set A", "sB": "Set B", "sC": "Set C"},
        {IMG3_ID: "sA", IMG2_ID: "sA"},
    )
    env.store_names = {STORE_AD: "V", STORE_AD2: "V."}
    env.store_parents = {STORE_AD: "sB", STORE_AD2: "sC"}
    assert_unnamed(env, IMG3_ID)
    assert_unnamed(env, IMG2_ID)
    assert render_name(env, STORE_AD) == "V (Set B)"
    assert render_name(env, STORE_AD2) == "V (Set C)"


def test_J4R2_i_ad_set_names_differing_by_a_stop_collide(env: J4R2Env) -> None:
    env.shared_run({IMG3_ID: "V", IMG2_ID: "V", "sA": "Set A", "sB": "Set A."}, TWO_SETS)
    env.store_names = {STORE_AD: "V", "sC": "Set C"}
    env.store_parents = {STORE_AD: "sC"}
    assert_unnamed(env, IMG3_ID)
    assert_unnamed(env, IMG2_ID)
    assert render_name(env, STORE_AD) == "V (Set C)"  # the third holder is named


def test_J4R2_5_trailing_stops_and_spaces_are_dropped_from_both_parts(env: J4R2Env) -> None:
    env.shared_run({IMG3_ID: "V!? ", IMG2_ID: "V!? ", "sA": "Set A;: ", "sB": "Set B."}, TWO_SETS)
    assert_named(env, IMG3_ID, "V (Set A)")
    assert_named(env, IMG2_ID, "V (Set B)")


def test_J4R2_i_V_dot_and_V_each_held_once_stay_bare(env: J4R2Env) -> None:
    """Reading of (i): "V." and "V" are distinct under ``norm_name``, so with each held by one
    id neither is a candidate, and nothing changes for them."""
    env.shared_run({IMG3_ID: "V", IMG2_ID: "V.", "sA": "Set A"}, {IMG3_ID: "sA", IMG2_ID: "sA"})
    assert_named(env, IMG3_ID, "V")
    assert_named(env, IMG2_ID, "V.")


# ------------------------------------------------------------------ rule 6 against bare names


def test_J4R2_6_qualified_name_equal_to_a_bare_name_stays_unnamed(env: J4R2Env) -> None:
    """IMG3 is literally named "V (Set A)". IMG2's qualified name would be the same, so IMG2
    stays unnamed, and IMG3, not a candidate, keeps its name; the third "V" is named."""
    env.shared_run(
        {IMG3_ID: "V (Set A)", IMG2_ID: "V", "sA": "Set A", "sB": "Set B"},
        {IMG3_ID: "sA", IMG2_ID: "sA"},
    )
    env.store_names = {STORE_AD: "V"}
    env.store_parents = {STORE_AD: "sB"}
    assert_unnamed(env, IMG2_ID)
    assert_named(env, IMG3_ID, "V (Set A)")
    assert render_name(env, STORE_AD) == "V (Set B)"


# ------------------------------------------------------------------ (j) the possessive


Q = f"IMG2_TXT1 {EN} Updated (IMG2 test)"
Q3 = f"IMG2_TXT1 {EN} Updated (Set A)"


def _j_run(env: J4R2Env) -> str:
    return env.shared_run(
        {IMG3_ID: IMG2_UPDATED, IMG2_ID: IMG2_UPDATED, "sA": "Set A", "sB": "IMG2 test"},
        TWO_SETS,
    )


@pytest.mark.parametrize("form", ["full", "start"])
def test_J4R2_j_run_fig_possessive_follows_the_parenthesis(env: J4R2Env, form: str) -> None:
    run_id = _j_run(env)
    qid = env.qid(run_id, IMG2_ID, "ctr")
    res = env.render(f"We looked at {fig_run(run_id, qid, form)}.")
    assert res["ok"] is True, why(res)
    phrase = "of about 4.4%" if form == "full" else "is about 4.4%"
    assert res["text"] == f"We looked at {Q}'s click-through rate {phrase}, {ROUGH}.", res["text"]
    assert "IMG2 test's" not in res["text"]


@pytest.mark.parametrize("form", ["full", "start"])
def test_J4R2_j_notebook_fig_possessive_follows_the_parenthesis(env: J4R2Env, form: str) -> None:
    run_id = _j_run(env)
    assert run_id
    src = ad_source(IMG2_ID, IMG2_UPDATED, "sB", READ_AT)
    eid = f"nbe_{CLIENT}_0201"
    entry = event_entry(
        eid,
        src,
        kind="figure",
        statement="The ad's spend to date.",
        quantities=[
            {
                "name": "ad_spend_to_date",
                "value": 750,
                "unit": "USD",
                "subject": {"level": "ad", "id": IMG2_ID},
            }
        ],
    )
    rel = env.release_of([src], [entry])
    res = env.render(f"We looked at {fig_nb(rel, eid, 'ad_spend_to_date', form)}.")
    assert res["ok"] is True, why(res)
    assert res["text"].startswith(f"We looked at {Q}'s "), res["text"]
    assert "IMG2 test's" not in res["text"]


@pytest.mark.parametrize(
    ("form", "rendered"),
    [
        ("full", f"{Q}, which leads on clicks with a 62% chance of being best"),
        ("start", f"{Q} leads on clicks, with a 62% chance of being best"),
    ],
)
def test_J4R2_j_cmp_renders_the_qualified_leader(env: J4R2Env, form: str, rendered: str) -> None:
    run_id = _j_run(env)
    env.set_p_best(run_id, {IMG2_ID: 0.621, IMG3_ID: 0.379})
    res = env.render(f"{cmp_run(run_id, form)}.")
    assert res["ok"] is True, why(res)
    assert res["text"] == f"{rendered}.", res["text"]
    assert "IMG2 test's" not in res["text"]


def test_J4R2_j_menu_forms_never_put_the_possessive_on_the_ad_set(env: J4R2Env) -> None:
    run_id = _j_run(env)
    env.set_p_best(run_id, {IMG2_ID: 0.621, IMG3_ID: 0.379})
    menu = env.menu()
    shown = [f for s in menu["slots"] for f in s["forms"].values()]
    assert any(Q in f for f in shown) and any(Q3 in f for f in shown), shown
    for f in shown:
        assert "IMG2 test's" not in f and "Set A's" not in f, f


# ------------------------------------------------------------------ (k) digits in an ad set name


def test_J4R2_k_digit_in_an_ad_set_name_renders(env: J4R2Env) -> None:
    run_id = env.shared_run(two_set_names(sA="Test 2"), TWO_SETS)
    assert_named(env, IMG3_ID, "V (Test 2)")
    qid = env.qid(run_id, IMG3_ID, "ctr")
    res = env.render(f"We looked at {fig_run(run_id, qid)}.")
    assert res["ok"] is True, why(res)
    assert res["text"].startswith("We looked at V (Test 2)'s click-through rate"), res["text"]


def test_J4R2_k_digit_in_an_alias_renders(env: J4R2Env) -> None:
    env.shared_run(two_set_names(), TWO_SETS)
    env.display = {"sA": "Test 2"}
    assert_named(env, IMG3_ID, "V (Test 2)")


# ------------------------------------------------------------------ (l) the lint


@pytest.mark.parametrize(
    "template", ["<A> beat <B>.", "<A> did better than <B>.", "<A> is the best ad."]
)
def test_J4R2_l_lint_fires_on_qualified_name_slots(env: J4R2Env, template: str) -> None:
    env.shared_run(two_set_names(), TWO_SETS)
    a, b = name_slot_of(IMG3_ID), name_slot_of(IMG2_ID)
    res = env.render(template.replace("<A>", a).replace("<B>", b))
    assert all(r["ok"] for r in res["slots"]), why(res)  # the slots themselves render
    assert res["ok"] is False and res["text"] is None
    assert res["lint"], res
    assert any(S.R_COMPARATIVE in r for r in res["lint"]), res["lint"]


def test_J4R2_7_free_text_mention_of_a_qualified_name_is_linted(env: J4R2Env) -> None:
    """Rule 7: qualified names are in the names, so writing one out counts as naming an ad. The
    ad set is named by its alias, which is in no name layer, so only the qualified name can
    make the sentence name an ad."""
    env.shared_run({IMG3_ID: "Spring", IMG2_ID: "Spring", "sA": MAIN_META, "sB": "Set B"}, TWO_SETS)
    env.display = {"sA": "the main set"}
    res = env.render("Spring (the main set) did better than expected.")
    assert res["ok"] is False, why(res)
    assert any(S.R_COMPARATIVE in r for r in res["lint"]), res["lint"]


def test_J4R2_7_lint_counterpart_without_a_comparative_passes(env: J4R2Env) -> None:
    env.shared_run({IMG3_ID: "Spring", IMG2_ID: "Spring", "sA": "Set A", "sB": "Set B"}, TWO_SETS)
    res = env.render(f"{name_slot_of(IMG3_ID)} is live.")
    assert res["ok"] is True, why(res)
    assert res["text"] == "Spring (Set A) is live."


# ------------------------------------------------------------------ (m) the refresh


def test_J4R2_m_refresh_stores_entity_parents_and_keeps_run_id_and_seed(
    j2env: J2.J2Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(prior_registry, "utcnow", lambda: T_APPROVE)
    j2env.client()
    # copies of the data dir as it stands before the run (the approved prior in it), for the
    # direct execute calls below
    for where in ("without", "other"):
        shutil.copytree(j2env.data_dir, j2env.tmp / where)
    monkeypatch.setattr(pipeline, "utcnow", lambda: T_RUN)
    polls = j2env.history(upto="P1")
    calls = j2env.capture_execute()
    rec = j2env.refresh(polls["P1"])
    assert rec.status == "ran", rec.reason
    run_id = str(rec.run_id)
    snap, record = j2env.snapshot(run_id), j2env.record(run_id)
    assert snap.entity_parents == {"ad_a": "s1", "ad_b": "s1"}
    assert run_id == RUN_ID_BEFORE_J2
    assert record.seeds["fit"] == SEED_BEFORE_J2

    # execute stores entity_parents as given, and nothing that names the run moves
    args, kwargs = calls[0]
    given = {k: v for k, v in kwargs.items() if k != "entity_parents"}
    out: dict[str, pipeline.RunSnapshot] = {}
    for where, extra in (("without", {}), ("other", {"entity_parents": {"x9": "y9"}})):
        with data_dir_env(j2env.tmp / where):
            out[where] = j2env._real_execute(*args, **given, **extra).snapshot
    assert out["without"].entity_parents == {}
    assert out["other"].entity_parents == {"x9": "y9"}
    for s in out.values():
        assert s.run_id == snap.run_id
        assert s.configuration["seed"] == snap.configuration["seed"]
        assert s.config_hash == snap.config_hash


def test_J4R2_m_refresh_parents_take_the_newest_day(
    j2env: J2.J2Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ad_a is in s1 on every day but the last, where the rows say s2; the rows are stored with
    the last day first, so storage order cannot decide."""
    monkeypatch.setattr(prior_registry, "utcnow", lambda: T_APPROVE)
    j2env.client()
    monkeypatch.setattr(pipeline, "utcnow", lambda: T_RUN)
    rec = J2.poll_record(J2.CLIENT, J2.T0, n_rows=2 * len(J2.DAYS))
    rows = []
    for day in reversed(J2.DAYS):
        for ad, clicks, names in (("ad_a", 20, J2.NAMES_A), ("ad_b", 35, J2.NAMES_B)):
            row = J2.live_row(rec.poll_id, ad, day, clicks, names)
            if ad == "ad_a" and day == J2.LAST:
                row = row.model_copy(update={"entity_ids": {**row.entity_ids, "ad_set": "s2"}})
            rows.append(row)
    j2env.store.begin_poll(rec)
    j2env.store.finish_poll(rec, rows)
    got = j2env.refresh(rec)
    assert got.status == "ran", got.reason
    snap = j2env.snapshot(str(got.run_id))
    assert snap.entity_parents == {"ad_a": "s2", "ad_b": "s1"}


def test_J4R2_10_snapshot_saved_before_the_field_loads_with_no_parents(env: J4R2Env) -> None:
    run_id = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    snap = env.snapshot_with(run_id, lambda d: d.pop("entity_parents", None))
    assert snap.entity_parents == {}
