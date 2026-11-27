"""Blind review of J4R.2 at b60ff6b. Each test holds a point the frozen acceptance set leaves open."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from bayesian_marketing.core.records import ClientConfig
from bayesian_marketing.live import config as live_config
from tests.acceptance import j4_fixtures as X  # noqa: F401
from tests.acceptance import j4r_fixtures as _j4r
from tests.acceptance.conftest import iso  # noqa: F401
from tests.acceptance.j4_fixtures import CLIENT, IMG2_ID, IMG3_ID
from tests.acceptance.j4r2_fixtures import (
    CREATIVE,
    IMG2_PAUSED,
    IMG2_UPDATED,
    LIVE_ADS,
    LIVE_EXPECTED,
    MAIN,
    MAIN_ALIAS,
    J4R2Env,
    name_items,
    name_slot_of,
)
from tests.acceptance.test_J4R2 import STORE_AD, STORE_AD2, TWO_SETS, two_set_names

pytestmark = pytest.mark.piece("J4R2")

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def env(iso, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> J4R2Env:  # noqa: F811
    _j4r.hold_raw(monkeypatch)  # J7: these cases render raw statuses (see j4r_fixtures.raw_held)
    monkeypatch.delenv("BAYES_LIVE_DIR", raising=False)
    return J4R2Env(tmp_path, monkeypatch)


def _tree(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()
    }


def rendered(env: J4R2Env, ad: str) -> str | None:
    res = env.render(f"The ad {name_slot_of(ad)} is live.")
    return res["text"][7:-9] if res["ok"] else None


def live(env: J4R2Env) -> None:
    env.live_run()
    env.store_names = {IMG2_PAUSED: IMG2_UPDATED}
    env.store_parents = {IMG2_PAUSED: CREATIVE}
    env.display = {MAIN: MAIN_ALIAS}


# ---- menu and render agree, alone and in pairs, on the live shape (rule 5, S26 (1))


def test_J4R2_review_every_live_menu_slot_renders_as_the_menu_shows_alone_and_in_pairs(
    env: J4R2Env,
) -> None:
    live(env)
    items = env.menu()["slots"]
    assert {i["subject"] for i in items if i["kind"] == "name"} >= set(LIVE_ADS)
    alone = {}
    for i in items:
        res = env.render(i["token"])
        assert res["ok"], (i["token"], res["reasons"])
        assert res["text"] == i["forms"]["full"], i["token"]
        alone[i["token"]] = res["text"]
        for ad, shown in LIVE_EXPECTED.items():
            if i["subject"] == ad:
                assert shown in res["text"]
                # the possessive never follows an ad set's name
                if "(" in shown:
                    assert f"{shown.rsplit('(', 1)[1][:-1]}'s" not in res["text"].replace(")'s", ")")
    for i in items[:12]:
        for j in items[:12]:
            res = env.render(f"{i['token']} and {j['token']}")
            assert res["slots"][0]["rendered"] == alone[i["token"]]
            assert res["slots"][1]["rendered"] == alone[j["token"]]


# ---- rule 6: uniqueness holds across groups, since the parenthesis is only text


def test_J4R2_review_two_groups_whose_qualified_names_read_the_same_all_stay_unnamed(
    env: J4R2Env,
) -> None:
    """P, Q named "A" in sets "B) (C" and "Z"; R, S named "A (B)" in sets "C" and "Y". P and R
    would both render "A (B) (C)": a reader cannot tell the two ads apart."""
    env.shared_run(
        {IMG3_ID: "A", IMG2_ID: "A", "sP": "B) (C", "sQ": "Zed"}, {IMG3_ID: "sP", IMG2_ID: "sQ"}
    )
    env.store_names = {STORE_AD: "A (B)", STORE_AD2: "A (B)", "sR": "C", "sS": "Why"}
    env.store_parents = {STORE_AD: "sR", STORE_AD2: "sS"}
    assert rendered(env, IMG3_ID) is None
    assert rendered(env, STORE_AD) is None
    assert rendered(env, IMG2_ID) == "A (Zed)"
    assert rendered(env, STORE_AD2) == "A (B) (Why)"


# ---- the display-name rule holds for a qualified name as a whole


@pytest.mark.parametrize("bare", ["Win 50% now", "Save $5", "Half off 20 percent"])
def test_J4R2_review_a_shared_ad_name_that_states_a_figure_is_not_rendered_qualified(
    env: J4R2Env, bare: str
) -> None:
    env.shared_run({IMG3_ID: bare, IMG2_ID: bare, "sA": "Set A", "sB": "Set B"}, TWO_SETS)
    assert rendered(env, IMG3_ID) is None
    assert rendered(env, IMG2_ID) is None
    assert IMG3_ID not in name_items(env.menu())


# ---- parent layers: the first layer that knows the parent decides, a lower one never overrides


def test_J4R2_review_a_higher_layers_parent_without_a_display_name_does_not_fall_through(
    env: J4R2Env,
) -> None:
    env.shared_run(
        {IMG3_ID: "V", IMG2_ID: "V", "sA": "Set A", "sB": "Set B", "sX": "100 percent set"},
        {IMG3_ID: "sX", IMG2_ID: "sB"},
    )
    env.store_parents = {IMG3_ID: "sA"}  # the store disagrees; the snapshot outranks it
    assert rendered(env, IMG3_ID) is None
    assert rendered(env, IMG2_ID) == "V (Set B)"


def test_J4R2_review_an_id_typed_as_an_ad_set_is_never_qualified(env: J4R2Env) -> None:
    env.shared_run(two_set_names(), TWO_SETS)
    env.store_names = {"sC": "V"}  # a third holder; typed ad_set by a release source
    from tests.acceptance.j4r2_fixtures import typed_source

    env.release_of([typed_source("adset", "sC", "V", "2026-11-20T15:00:00+00:00")])
    env.store_parents = {"sC": "sA"}
    assert rendered(env, "sC") is None


# ---- reasons from the new loaders never reach a render


def test_J4R2_review_a_raising_loader_leaves_a_render_without_shared_names_clean(
    env: J4R2Env,
) -> None:
    env.shared_run({IMG3_ID: "IMG3_TXT1", IMG2_ID: "IMG2_TXT1"}, {})

    def boom(_c: str) -> Any:
        raise RuntimeError("store down")

    for kw in ({"load_parents": boom}, {"load_display_names": boom}):
        res = env.render(f"The ad {name_slot_of(IMG3_ID)} is live.", **kw)
        assert res["ok"], res["reasons"]
        assert not [r for r in res["reasons"] if "store down" in r]
        assert not [r for s in res["slots"] for r in s.get("reasons") or [] if "store down" in r]
    assert env.parents_calls == [] and env.display_calls == []  # never called with no shared name


def test_J4R2_review_a_raising_loader_in_a_render_of_a_shared_name_is_a_plain_unnamed_failure(
    env: J4R2Env,
) -> None:
    env.shared_run(two_set_names(), TWO_SETS)

    def boom(_c: str) -> Any:
        raise RuntimeError("config gone")

    res = env.render(f"The ad {name_slot_of(IMG3_ID)} is live.", load_display_names=boom)
    assert res["ok"] is False and res["text"] is None
    assert not [r for r in res["reasons"] if "config gone" in r]
    menu = env.menu(load_display_names=boom)
    assert any("config gone" in r for r in menu["reasons"])


# ---- display_names validation


@pytest.mark.parametrize(
    "value", ["$5", "50%", "ten percent", "a\nb", "{x}", "USD set", "", "   ", "!!!", "\x07bell"]
)
def test_J4R2_review_display_names_refuses_a_bad_value_with_the_key_named(value: str) -> None:
    with pytest.raises(ValidationError) as e:
        ClientConfig.model_validate(_cfg({"123": value}))
    assert "123" in str(e.value)


def test_J4R2_review_display_names_unquoted_key_fails_the_load(tmp_path: Path) -> None:
    root = tmp_path / "configs"
    root.mkdir()
    body = yaml.safe_dump(_cfg({}))
    (root / "c.yaml").write_text(body + "display_names:\n  120253899504550526: 'main'\n")
    with pytest.raises(Exception):
        live_config.load_client("c", root)


def test_J4R2_review_display_names_is_checked_on_copy_construction_paths() -> None:
    cfg = ClientConfig.model_validate(_cfg({"1": "main"}))
    with pytest.raises(ValidationError):
        ClientConfig.model_validate({**cfg.model_dump(), "display_names": {"1": "$"}})


def _cfg(display: dict[str, str]) -> dict[str, Any]:
    from tests.acceptance.test_L5 import config

    base = config().model_dump(mode="json")
    base["display_names"] = display
    return base


def test_J4R2_review_shipped_configs_all_load() -> None:
    for p in (REPO / "configs").glob("*.yaml"):
        live_config.load_client(p.stem, REPO / "configs")


# ---- a name that points to one id is unchanged, and no loader is called for it


def test_J4R2_review_unshared_names_render_the_same_with_any_alias_or_parent(env: J4R2Env) -> None:
    env.shared_run({IMG3_ID: "IMG3_TXT1", IMG2_ID: "IMG2_TXT1", "sA": "Set A"}, TWO_SETS)
    before = name_items(env.menu())
    env.display = {"sA": "alias", IMG3_ID: "x"}
    env.store_parents = {IMG3_ID: "sA"}
    assert name_items(env.menu()) == before == {IMG3_ID: "IMG3_TXT1", IMG2_ID: "IMG2_TXT1"}
    assert env.parents_calls == [] and env.display_calls == []


# ---- the tests above touched neither data/live nor notebook of the repo


def test_J4R2_review_nothing_is_written_to_the_repos_live_data_or_notebook(env: J4R2Env) -> None:
    before = (_tree(REPO / "data" / "live"), _tree(REPO / "notebook"))
    live(env)
    env.menu(load_parents=None, load_display_names=None)
    env.render(f"The ad {name_slot_of(IMG3_ID)} is live.", load_parents=None)
    assert (_tree(REPO / "data" / "live"), _tree(REPO / "notebook")) == before
