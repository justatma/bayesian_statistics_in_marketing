"""The client_slots contract with AtmaOS (Brain join spec v0.4, S55).

AtmaOS's contract test feeds ``spec/contracts/client_slots_menu.json`` through its menu reader
and fails on empty wording or a slot kind it doesn't know. This test holds the engine to that
file: the real ``client_slots``, on synthetic runs and a synthetic notebook release that between
them give every slot kind, must produce it exactly, apart from ``checked_at`` and
``engine_version``. No client data: the repo is public.

The file changes only with the join spec's version, and the change is announced to the Head
Engineer. To rewrite it on purpose: ``BAYES_WRITE_CONTRACT=1 pytest tests/acceptance/test_contract_client_slots.py``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from tests.acceptance import j4_fixtures as X
from tests.acceptance import j4r_fixtures as _j4r
from tests.acceptance.j4r_fixtures import J4REnv

CONTRACT = Path(__file__).resolve().parents[2] / "spec" / "contracts" / "client_slots_menu.json"
STAMP = {
    "contract": "bayes-client-slots-c1",
    "join_spec": "Brain_Join_Specification_v0.4",
    "settled_in": "S55",
    "synthetic": True,
}
KINDS = {"fig", "cmp", "name", "na"}


def _menu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    _j4r.hold_raw(monkeypatch)
    env = J4REnv(tmp_path, monkeypatch)
    run_id = env.lead_run_at(X.START_OLD, X.WINDOW_OLD)
    env.ctr_44(run_id)
    env.release()
    menu = dict(env.menu())
    menu.pop("checked_at")
    menu.pop("engine_version")
    return menu


def test_client_slots_matches_the_contract_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    got = {"stamp": STAMP, "menu": _menu(tmp_path, monkeypatch)}
    text = json.dumps(got, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if os.environ.get("BAYES_WRITE_CONTRACT") == "1":
        CONTRACT.parent.mkdir(parents=True, exist_ok=True)
        CONTRACT.write_text(text, encoding="utf-8")
    assert CONTRACT.read_text(encoding="utf-8") == text


def test_the_contract_file_covers_every_kind_with_wording() -> None:
    menu = json.loads(CONTRACT.read_text(encoding="utf-8"))["menu"]
    kinds = {s["kind"] for s in menu["slots"]}
    assert kinds == KINDS, kinds
    assert any(s["release_id"] for s in menu["slots"])  # a notebook fig slot
    assert any(s["run_id"] for s in menu["slots"] if s["kind"] == "fig")  # a run fig slot
    for s in menu["slots"]:
        assert s["forms"]["full"].strip() and s["forms"]["start"].strip(), s
