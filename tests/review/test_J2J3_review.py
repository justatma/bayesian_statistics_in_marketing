"""Blind review of J2 and J3 at 9629732. Every test is a finding or a recorded pass."""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from tests.acceptance import j2_oracle
from tests.acceptance.conftest import iso  # noqa: F401
from tests.acceptance.j2_fixtures import J2Env, make_env

from bayesian_marketing.live import markers as M
from bayesian_marketing.live.rows import canonical, versioned
from bayesian_marketing.live.store import SqliteStore

pytestmark = [pytest.mark.piece("J2"), pytest.mark.piece("J3")]
UTC = dt.UTC
REAL = Path("/Users/atma1/gh_all/atmaos/bayesian/data/live/live.sqlite")


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[J2Env]:
    yield from make_env(tmp_path, monkeypatch)


def _ran(env: J2Env, name: str) -> str:
    rec = env.refresh(env.polls[name])
    assert rec.status == "ran", rec
    return rec.run_id


def test_R1_backfill_survives_one_unreadable_run_file(env: J2Env) -> None:
    """One bad run file should not stop the other markers (spec silent; backfill is a recovery tool)."""
    env.client()
    env.history(upto="P2")
    runs = [_ran(env, "P1"), _ran(env, "P2")]
    for r in runs:
        env.run_marker(r).unlink()
    bad = env.data_dir / "runs" / "run_000bad.json"
    bad.write_text("{not json")
    got = M.backfill()
    assert got["engine_run"] == 2


def test_R2_marker_dir_unwritable_keeps_refresh_ran_and_never_raises(env: J2Env) -> None:
    env.client()
    env.history(upto="P1")
    (env.data_dir / "markers").write_text("a file where the folder should be")
    rec = env.refresh(env.polls["P1"])
    assert rec.status == "ran" and rec.run_id and rec.reason.startswith("marker not written:")


def test_R3_no_marker_names_a_hash_that_differs_from_its_file(env: J2Env) -> None:
    import hashlib
    import json

    env.client()
    env.history(upto="P2")
    for n in ("P1", "P2"):
        _ran(env, n)
    for p in env.marker_files():
        m = json.loads(p.read_text())
        f = Path(m["snapshot_path"])
        assert f.is_file() and hashlib.sha256(f.read_bytes()).hexdigest() == m["snapshot_sha256"]


@pytest.mark.skipif(not REAL.exists(), reason="no real live store here")
def test_R4_versioned_equals_the_e983942_export_on_a_copy_of_the_real_store(tmp_path: Path) -> None:
    copy = tmp_path / "live.sqlite"
    src = sqlite3.connect(f"file:{REAL}?mode=ro", uri=True)
    dst = sqlite3.connect(copy)
    src.backup(dst)
    dst.close()
    src.close()
    c = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    st = SqliteStore.open(copy, read_only=True)
    for (cid,) in c.execute("SELECT DISTINCT client_id FROM polls").fetchall():
        tz = {
            r[0]
            for r in c.execute(
                "SELECT DISTINCT o.timezone FROM poll_outcomes o JOIN polls p USING (poll_id) "
                "WHERE p.client_id = ? AND o.status = 'ok'",
                (cid,),
            )
            if r[0]
        }.pop()
        rows, seen = j2_oracle.polls(c, cid, tz)
        reads = list(j2_oracle.POLL_READS)
        n_rows, n_seen, n_reads = versioned(st, cid)
        assert [canonical(x) for x in rows] == [canonical(x) for x in n_rows]
        assert seen == n_seen
        assert [canonical(x) for x in reads] == [canonical(x) for x in n_reads]


def test_R5_acceptance_tests_leave_no_marker_in_default_data_dir() -> None:
    """The default data dir is data/generated; no markers folder may appear there from tests."""
    from bayesian_marketing import pipeline

    assert not (pipeline.DEFAULT_DATA_DIR / "markers").exists()
