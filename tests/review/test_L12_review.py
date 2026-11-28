"""Blind review of L12 at 128b7be. Every test here is a finding or a recorded pass."""

from __future__ import annotations

import ast
import datetime as dt
import io
import logging
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from tests.acceptance import j2_fixtures as J2
from tests.acceptance.conftest import iso  # noqa: F401
from tests.acceptance.l12_fixtures import (
    CLIENT,
    OLD,
    OLD_LABEL,
    T0,
    W7,
    W28,
    L12Env,
    add_poll,
    live_row,
    make_env,
    old_rows,
    window_rows,
)
from tests.acceptance.test_J7 import CONFIG_HASH_AFTER_L12, CONFIG_HASH_BEFORE_J7
from tests.acceptance.test_J2 import RUN_ID_BEFORE_J2, SEED_BEFORE_J2, T_APPROVE, T_RUN
from tests.fakes.live import FakeStore

from bayesian_marketing import cli, pipeline
from bayesian_marketing.core import registries
from bayesian_marketing.live.refresh import analysis_window
from bayesian_marketing.live.registry import load_live_registry
from bayesian_marketing.prior_registry import registry as prior_registry

pytestmark = pytest.mark.piece("L12")

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[L12Env]:
    yield from make_env(tmp_path, monkeypatch)


@pytest.fixture
def j2env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[J2.J2Env]:
    yield from J2.make_env(tmp_path, monkeypatch)


def _git_show(rev: str, path: str) -> str:
    return subprocess.run(
        ["git", "show", f"{rev}:{path}"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout


# ---- 128b7be is layout only -----------------------------------------------------------------


def test_R1_the_ruff_reformat_commit_changes_layout_only() -> None:
    """128b7be on scripts/export_history.py: same AST (code, strings, docstrings), same comments."""
    try:
        a, b = _git_show("7d70fab", "scripts/export_history.py"), _git_show(
            "128b7be", "scripts/export_history.py"
        )
    except subprocess.CalledProcessError:
        pytest.skip("the two commits are not in this clone")
    assert ast.dump(ast.parse(a)) == ast.dump(ast.parse(b))
    comments = lambda s: [l.split("#", 1)[1].strip() for l in s.splitlines() if "#" in l]  # noqa: E731
    assert sorted(comments(a)) == sorted(comments(b))


# ---- the J7 (k) change ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "want"),
    [("2026-11-07", CONFIG_HASH_BEFORE_J7), ("2026-11-27", CONFIG_HASH_AFTER_L12)],
)
def test_R2_j7_k_the_old_config_hash_returns_with_the_old_live_yaml_version(
    j2env: J2.J2Env, iso: Any, monkeypatch: pytest.MonkeyPatch, version: str, want: str
) -> None:
    """The builder's claim, with lookback 28 and analysis 7 kept: only live.yaml's ``version``
    separates the old constant from the new one, so check (k) still holds the rest of the config
    hash, the run id and the seed."""
    iso.edit_yaml("live", lambda d: d.update(version=version))
    monkeypatch.setattr(prior_registry, "utcnow", lambda: T_APPROVE)
    j2env.client()
    monkeypatch.setattr(pipeline, "utcnow", lambda: T_RUN)
    polls = j2env.history(upto="P1")
    rec = j2env.refresh(polls["P1"])
    assert rec.status == "ran", rec.reason
    run_id = str(rec.run_id)
    assert run_id == RUN_ID_BEFORE_J2
    assert j2env.record(run_id).seeds["fit"] == SEED_BEFORE_J2
    assert j2env.snapshot(run_id).config_hash == want


# ---- the registry rule ------------------------------------------------------------------------


@pytest.mark.parametrize("analysis", [0, -1, 29, 7.5])
def test_R3_bad_analysis_days_fail_to_load(iso: Any, analysis: Any) -> None:
    iso.edit_yaml("live", lambda d: d.update(lookback_days=28, analysis_days=analysis))
    with pytest.raises(Exception):  # noqa: B017
        load_live_registry(iso.registry)


def test_R3b_a_file_without_analysis_days_cannot_slip_a_narrow_lookback_through(iso: Any) -> None:
    """The default (7) is checked against lookback_days, so dropping the key under a lookback
    below 7 still fails to load; with 28 it loads at the default, 7."""

    def drop(d: dict[str, Any]) -> None:
        d.pop("analysis_days")
        d["lookback_days"] = 5

    iso.edit_yaml("live", drop)
    with pytest.raises(Exception):  # noqa: B017
        load_live_registry(iso.registry)
    iso.edit_yaml("live", lambda d: d.update(lookback_days=28))
    assert load_live_registry(iso.registry).analysis_days == 7


def test_R3c_refresh_takes_the_registry_rule_even_when_none_is_passed(
    env: L12Env, iso: Any
) -> None:
    """refresh() with no registry reads the file; a file that breaks the rule is a failed
    refresh (never a raise, never a run on a bad window)."""
    iso.edit_yaml("live", lambda d: d.update(lookback_days=7, analysis_days=9))
    env.client()
    store = FakeStore()
    p = add_poll(store, T0, W28, [*window_rows(), *old_rows()])
    rec = env.refresh(p, store)
    assert rec.status == "failed" and rec.run_id is None, rec


def test_R3d_analysis_window_never_inverts_for_registry_legal_values() -> None:
    for width in (1, 3, 7, 28):
        for n in range(1, 29):
            lo, hi = analysis_window(window(width), n)
            assert lo <= hi and hi == W28[1]


def window(width: int) -> tuple[dt.date, dt.date]:
    return W28[1] - dt.timedelta(days=width - 1), W28[1]


# ---- inputs from outside the window ------------------------------------------------------------


def test_R4_the_horizon_basis_and_economics_do_not_read_old_rows_but_spend_does(
    env: L12Env,
) -> None:
    """L12.1/L12.3: two stores differ only in the old days' impressions and clicks (same stored
    spend). The run's request (horizon, basis), its seed and config hash must be identical."""
    env.client(test_budget=5000)
    calls = env.capture_execute()
    out = []
    for imp, clk in ((500, 5), (9000, 400)):
        s = FakeStore()
        p = add_poll(
            s, T0, W28, [*window_rows(), *old_rows(impressions=imp, clicks=clk)], pid="poll_r4aa"
        )
        rec = env.refresh(p, s)
        assert rec.status == "ran", rec.reason
        out.append(rec)
    a, b = calls
    assert a["request"].horizon == b["request"].horizon
    assert a["request"].horizon_basis == b["request"].horizon_basis
    assert env.record(str(out[0].run_id)).seeds == env.record(str(out[1].run_id)).seeds
    assert env.record(str(out[0].run_id)).config_hash == env.record(str(out[1].run_id)).config_hash


def test_R5_extra_pull_inputs_come_from_the_poll_not_from_old_rows(env: L12Env) -> None:
    """pull_id, pulled_at, account, timezone, empty_account are the poll's; old rows carry
    renamed entities and a lone ad_x and none of it may reach names, parents or the entity map."""
    env.client()
    calls = env.capture_execute()
    s = FakeStore()
    old = [r.model_copy(update={"entity_names": {"ad": "OLD NAME", "campaign": "OLD CAMP"}})
           for r in old_rows()]
    p = add_poll(s, T0, W28, [*window_rows(), *old])
    assert env.refresh(p, s).status == "ran"
    kw = calls[0]["kwargs"]
    assert "OLD NAME" not in kw["entity_names"].values()
    assert "OLD CAMP" not in kw["entity_names"].values()
    assert {r.date for r in kw["pulls"][0].rows} <= set(
        W7[0] + dt.timedelta(days=i) for i in range(7)
    )


# ---- the pointer: refresh and export, restated and moved windows --------------------------------


def test_R6_refresh_and_export_agree_when_a_later_poll_restates_in_window_and_old_days(
    env: L12Env,
) -> None:
    """Three polls: P1 (28 days), P2 restates an old day and a window day. The run of P1 and the
    run of P2 each equal a fresh export's pointer for them; P1's is unchanged by P2 (append-only)."""
    env.client()
    s = env.store
    h = dt.timedelta(hours=1)
    p1 = add_poll(s, T0, W28, [*window_rows(), *old_rows(ads=("ad_a", "ad_b"))])
    r1 = env.refresh(p1, s)
    snap1 = env.snapshot(str(r1.run_id))
    first = env.export_runs()[str(r1.run_id)]
    rows2 = [
        *window_rows(),
        *old_rows(ads=("ad_a", "ad_b")),
    ]
    rows2 = [
        r.model_copy(update={"clicks": r.clicks + 1})
        if (r.date in (OLD[3], W7[1]) and r.entity_ids["ad"] == "ad_a")
        else r
        for r in rows2
    ]
    p2 = add_poll(s, T0 + 2 * h, W28, rows2)
    r2 = env.refresh(p2, s)
    assert r1.status == r2.status == "ran", (r1.reason, r2.reason)
    snap2 = env.snapshot(str(r2.run_id))
    ex = env.export_runs()
    assert ex[str(r1.run_id)]["row_keys"] == snap1.row_keys == first["row_keys"]
    assert ex[str(r2.run_id)]["row_keys"] == snap2.row_keys
    assert any(k.startswith("meta:ad_a:") and k.endswith(":v2") for k in snap2.row_keys)
    assert not any(OLD[3].isoformat() in k for k in snap2.row_keys)


def test_R7_a_run_file_whose_window_is_narrower_than_its_poll_exports_the_narrow_pointer(
    env: L12Env,
) -> None:
    """Export takes the window from the run file (item 4): hand a run whose window is the poll's
    own 7 days. Its keys are the 7-day keys."""
    env.client()
    p = add_poll(env.store, T0, W7, window_rows())
    r = env.refresh(p)
    assert r.status == "ran"
    keys = env.export_runs()[str(r.run_id)]["row_keys"]
    assert len(keys) == 14 and all(W7[0].isoformat() <= k.split(":")[2] <= W7[1].isoformat() for k in keys)


# ---- the view -----------------------------------------------------------------------------------


def test_R8_a_view_rendered_days_after_the_poll_shows_nothing_older_than_its_7_days(
    env: L12Env,
) -> None:
    from tests.acceptance.test_L12 import _render as render  # the acceptance renderer

    s = FakeStore()
    add_poll(s, T0, W28, [*window_rows(), *old_rows()], pid="poll_r8")
    page = render(s, env.data_dir)
    assert OLD_LABEL not in page and "ad_x" not in page


# ---- the log handler ----------------------------------------------------------------------------


@pytest.fixture
def clean_logging() -> Iterator[None]:
    names = ["bayesian_marketing.live.refresh", "httpx", "httpcore", "bayesian_marketing"]
    before = {n: (logging.getLogger(n).level, list(logging.getLogger(n).handlers)) for n in names}
    root = (logging.getLogger().level, list(logging.getLogger().handlers))
    yield
    for n, (lvl, hs) in before.items():
        lg = logging.getLogger(n)
        lg.setLevel(lvl)
        lg.handlers[:] = hs
    logging.getLogger().setLevel(root[0])
    logging.getLogger().handlers[:] = root[1]


TOKEN = "EAAB-secret-token-123"


def test_R9_the_timing_handler_lets_no_other_logger_and_no_token_reach_stderr(
    clean_logging: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stderr", buf)
    root_level = logging.getLogger().level
    cli._refresh_timing_to_stderr()
    cli._refresh_timing_to_stderr()  # twice: still one handler
    lg = logging.getLogger("bayesian_marketing.live.refresh")
    assert len([h for h in lg.handlers if getattr(h, "_bayes_timing", False)]) == 1
    assert logging.getLogger().level == root_level  # the root is not opened
    # a real httpx request whose URL carries the token, logged the way httpx does
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    with httpx.Client(transport=transport) as c:
        c.get(f"https://graph.facebook.com/v21.0/act_1/insights?access_token={TOKEN}")
    for name in ("httpx", "httpcore", "bayesian_marketing.live.poll", "bayesian_marketing",
                 "urllib3", "root"):
        lgr = logging.getLogger(None if name == "root" else name)
        lgr.info("GET https://graph.facebook.com/?access_token=%s", TOKEN)
    out = buf.getvalue()
    assert TOKEN not in out, out
    assert "HTTP Request" not in out


def test_R9b_the_refresh_timing_line_carries_no_token_and_goes_to_stderr(
    env: L12Env, clean_logging: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stderr", buf)
    cli._refresh_timing_to_stderr()
    env.client()
    s = FakeStore()
    p = add_poll(s, T0, W28, [*window_rows(), *old_rows()])
    assert env.refresh(p, s).status == "ran"
    lines = [l for l in buf.getvalue().splitlines() if "versioned" in l]
    assert len(lines) == 1 and re.search(r"versioned \d+ versions in \d+\.\d{3} s", lines[0])
    assert "token" not in buf.getvalue().lower()


# ---- writes -------------------------------------------------------------------------------------


def test_R10_the_refresh_writes_nothing_under_the_repo_data_live_or_notebook(
    env: L12Env,
) -> None:
    def snap(root: Path) -> set[tuple[str, int, int]]:
        if not root.exists():
            return set()
        return {(str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}

    watched = [REPO / "data" / "live", REPO / "notebook"]
    before = [snap(w) for w in watched]
    env.client()
    s = FakeStore()
    p = add_poll(s, T0, W28, [*window_rows(), *old_rows()])
    assert env.refresh(p, s).status == "ran"
    env.export_runs()
    assert [snap(w) for w in watched] == before
