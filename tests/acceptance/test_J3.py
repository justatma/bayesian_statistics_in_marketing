"""J3: hand-off markers (Brain join spec v0.4, J3, S6, S12, S33 to S35).

Runs come from ``refresh`` on ``j2_fixtures``' SQLite history in ``tmp_path``; releases from
``notebook.release.write_release`` into ``BAYES_NOTEBOOK_DIR`` (``tmp_path / "notebook"``). The
markers folder is ``BAYES_DATA_DIR / "markers"``, and the refresh's ``data_dir`` is the same
folder, so the test doesn't depend on which of the two the marker writer reads.

A marker's file name is found by either reading of the J3 table: ``run_<run_id>.json`` taken
literally (``run_run_1a2b3c4d.json``), or the run id as the name (``run_1a2b3c4d.json``); the same
for ``nb_<release_id>.json``. The spec's text gives the first; the second is what a reader who
took ``<run_id>`` as the hex part would build. Either passes.

The interrupted write (check c) makes ``os.replace`` raise for any destination in ``markers/``.
A file ``.<marker name>.tmp`` may be left by it: S33 names that temporary file and doesn't
require it removed on a failure, and no reader takes a dot-file ending ``.tmp`` for a marker.
Nothing else may be left, and the next write must succeed and consume it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from bayesian_marketing import pipeline
from bayesian_marketing.live import markers as M
from bayesian_marketing.notebook import release as nb_release
from tests.acceptance.j2_fixtures import (
    CLIENT,
    ENGINE_RUN_FIELDS,
    PREFIX,
    RELEASE_FIELDS,
    T0,
    J2Env,
    add_poll,
    base_figures,
    canonical_marker,
    failing_replace,
    make_env,
    marker_name_ok,
    run_marker_names,
)

pytestmark = pytest.mark.piece("J3")


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[J2Env]:
    yield from make_env(tmp_path, monkeypatch)


REPO = Path(__file__).resolve().parents[2]
UTC = dt.UTC
WRITTEN_AT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\+00:00|Z)$")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_bytes().decode("utf-8"))


def _written_at_ok(value: str, before: dt.datetime, after: dt.datetime) -> None:
    assert WRITTEN_AT.match(value), value  # S33: UTC, ISO 8601, to the second
    at = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert at.utcoffset() == dt.timedelta(0)
    assert before.replace(microsecond=0) <= at <= after


def _ran(env: J2Env, name: str) -> str:
    rec = env.refresh(env.polls[name])
    assert rec.status == "ran", rec.reason
    return str(rec.run_id)


def _assert_run_marker(env: J2Env, run_id: str, path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    assert canonical_marker(data)  # S33: canonical, one trailing line feed
    assert data.endswith(b"\n") and not data.endswith(b"\n\n")
    m = _load(path)
    # J3's fields exactly, plus J7's timezone and fit_route (S41 (2))
    assert set(m) == ENGINE_RUN_FIELDS | {"timezone", "fit_route"}
    snap_file = env.snapshot_file(run_id)
    snap = env.snapshot(run_id)
    assert m["kind"] == "engine_run"
    assert m["run_id"] == run_id
    assert m["client_id"] == snap.client_id == CLIENT
    assert m["snapshot_path"] == str(snap_file.resolve())  # absolute and resolved
    assert Path(m["snapshot_path"]).is_absolute()
    assert m["snapshot_sha256"] == _sha(snap_file)  # over the bytes on disk
    return m


# ------------------------------------------------------------------ (a) a saved run


def test_J3_a_a_refresh_that_saves_a_run_leaves_one_marker_naming_it(env: J2Env) -> None:
    env.client()
    env.history(upto="P2")
    before = dt.datetime.now(UTC)
    run1 = _ran(env, "P1")
    after = dt.datetime.now(UTC)
    files = env.marker_files()
    assert len(files) == 1 and files[0].name in run_marker_names(run1)
    m = _assert_run_marker(env, run1, files[0])
    snap = env.snapshot(run1)
    assert m["rows_form"] == "bayes-rows-c1" == snap.rows_form
    assert m["rows_sha256"] == snap.dataset_hashes[0].removeprefix(PREFIX)
    assert snap.dataset_hashes[0].startswith(PREFIX)
    assert m["row_keys"] == snap.row_keys and m["row_keys"]
    _written_at_ok(m["written_at"], before, after)
    assert env.stray_files() == []  # the temporary file was moved into place
    run2 = _ran(env, "P2")
    assert len(env.marker_files()) == 2
    _assert_run_marker(env, run2, env.run_marker(run2))
    assert env.run_marker(run1).read_bytes() == files[0].read_bytes()  # the first is untouched


def test_J3_S12_markers_dir_follows_data_dir_at_the_time_of_the_call(
    env: J2Env, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert M.markers_dir() == env.data_dir / "markers"
    monkeypatch.setenv("BAYES_DATA_DIR", str(tmp_path / "elsewhere"))
    assert M.markers_dir() == tmp_path / "elsewhere" / "markers"
    assert M.MARKERS_DIR == "markers" and M.DONE_DIR == "done"


# ------------------------------------------------------------------ (b) skipped or failed


def _one_ran(env: J2Env) -> list[Path]:
    """A ran refresh first, so "leaves none" is read against a folder that holds a marker."""
    run1 = _ran(env, "P1")
    files = env.marker_files()
    assert [p.name for p in files] == [env.run_marker(run1).name]
    return files


def test_J3_b_a_skipped_refresh_leaves_no_marker(env: J2Env) -> None:
    env.client()
    env.history(upto="P1")
    files = _one_ran(env)
    later = T0 + dt.timedelta(hours=5)
    one_ad = add_poll(env.store, later, {k: v for k, v in base_figures().items() if k[0] == "ad_a"})
    rec = env.refresh(one_ad)
    assert rec.status == "skipped"
    assert env.marker_files() == files and env.stray_files() == []


def test_J3_b_an_error_poll_leaves_no_marker(env: J2Env) -> None:
    env.client()
    polls = env.history(upto="ERR")
    files = _one_ran(env)
    rec = env.refresh(polls["ERR"])
    assert rec.status == "skipped"
    assert env.marker_files() == files


def test_J3_b_a_failed_refresh_leaves_no_marker(
    env: J2Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    env.client()
    polls = env.history(upto="P2")
    files = _one_ran(env)

    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(pipeline, "execute", boom)
    rec = env.refresh(polls["P2"])
    assert rec.status == "failed"
    assert env.marker_files() == files and env.stray_files() == []


def test_J3_b_S30_a_refresh_failed_on_its_rows_leaves_no_marker(env: J2Env) -> None:
    env.client()
    p1 = add_poll(env.store, T0, base_figures())
    add_poll(env.store, T0 - dt.timedelta(hours=1), base_figures(), timezone="Europe/London")
    rec = env.refresh(p1)
    assert rec.status == "failed"
    assert env.marker_files() == [] and env.run_files() == []


# ------------------------------------------------------------------ (c) never without its run


def _no_marker_left(env: J2Env) -> None:
    assert env.marker_files() == []
    for p in env.stray_files():  # allowed: only S33's own temporary name, see the docstring
        assert p.name.startswith(".") and p.name.endswith(".tmp"), p.name
        assert marker_name_ok(p.name[1 : -len(".tmp")]), p.name


def test_J3_c_an_interrupted_write_leaves_no_marker(
    env: J2Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    env.client()
    env.history(upto="P1")
    run1 = _ran(env, "P1")
    env.run_marker(run1).unlink()
    restore = failing_replace(monkeypatch)
    with pytest.raises(Exception):  # noqa: B017
        M.engine_run_marker(run1)
    _no_marker_left(env)
    restore()
    path = M.engine_run_marker(run1)  # a later write succeeds
    assert path == env.run_marker(run1)
    _assert_run_marker(env, run1, path)
    assert env.stray_files() == []  # and the temporary file was consumed


def test_J3_c_S34_a_refresh_whose_marker_fails_stays_ran(
    env: J2Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    env.client()
    polls = env.history(upto="P1")
    restore = failing_replace(monkeypatch, "disk full")
    rec = env.refresh(polls["P1"])
    restore()
    assert rec.status == "ran"
    assert rec.run_id and env.snapshot_file(rec.run_id).is_file()  # the run file is saved
    assert rec.reason == "marker not written: OSError: disk full"
    assert env.store.latest_refresh(CLIENT) == rec
    _no_marker_left(env)
    assert M.backfill()["engine_run"] == 1  # the backfill writes it later
    _assert_run_marker(env, rec.run_id, env.run_marker(rec.run_id))


def test_J3_c_no_marker_for_a_run_without_its_file(env: J2Env) -> None:
    env.client()
    env.history(upto="P1")
    files = _one_ran(env)
    with pytest.raises(Exception):  # noqa: B017
        M.engine_run_marker("run_0badf00d")
    assert env.marker_files() == files and env.stray_files() == []


# ------------------------------------------------------------------ S33 idempotence, S12


def test_J3_S33_an_existing_marker_is_left_untouched(env: J2Env) -> None:
    env.client()
    env.history(upto="P1")
    run1 = _ran(env, "P1")
    path = env.run_marker(run1)
    path.write_bytes(b"left as it was\n")
    assert M.engine_run_marker(run1) == path  # its path is returned
    assert path.read_bytes() == b"left as it was\n"
    assert env.marker_files() == [path]


def test_J3_S12_S33_a_marker_moved_to_done_is_not_written_again(env: J2Env) -> None:
    env.client()
    env.history(upto="P1")
    run1 = _ran(env, "P1")
    path = env.run_marker(run1)
    env.done.mkdir(parents=True)
    moved = env.done / path.name
    os.replace(path, moved)
    assert M.engine_run_marker(run1) == moved
    assert env.marker_files() == []  # nothing new in markers/
    assert M.backfill() == {"engine_run": 0, "notebook_release": 0}
    assert env.marker_files() == [] and moved.is_file()


# ------------------------------------------------------------------ (e) the backfill, S6


def test_J3_e_backfill_on_three_runs_and_one_marker_writes_two_then_none(env: J2Env) -> None:
    env.client()
    env.history(upto="P4")
    runs = [_ran(env, n) for n in ("P1", "P2", "P4")]
    keep = env.run_marker(runs[0])
    kept = keep.read_bytes()
    for r in runs[1:]:
        env.run_marker(r).unlink()  # as a crash between the run file and the marker leaves it
    assert len(env.marker_files()) == 1
    assert M.backfill() == {"engine_run": 2, "notebook_release": 0}
    assert len(env.marker_files()) == 3
    for r in runs:
        _assert_run_marker(env, r, env.run_marker(r))
    assert keep.read_bytes() == kept
    after = {p.name: p.read_bytes() for p in env.marker_files()}
    assert M.backfill() == {"engine_run": 0, "notebook_release": 0}
    assert {p.name: p.read_bytes() for p in env.marker_files()} == after


def test_J3_S6_S33_a_pre_J3_snapshot_gets_null_pointer_fields(env: J2Env) -> None:
    env.client()
    env.history(upto="P1")
    run1 = _ran(env, "P1")
    d = json.loads(env.snapshot_file(run1).read_text())
    for k in ("row_keys", "rows_form"):
        d.pop(k)
    d["dataset_hashes"] = []
    d["run_id"] = old = "run_0000aaaa"
    old_file = env.snapshot_file(old)
    old_file.write_text(json.dumps(d))  # a run file as saved before J2 and J3
    assert pipeline.load_snapshot(old).rows_form is None
    assert M.backfill() == {"engine_run": 1, "notebook_release": 0}
    m = _assert_run_marker(env, old, env.run_marker(old))
    assert m["rows_form"] is None and m["rows_sha256"] is None and m["row_keys"] is None


def test_J3_S35_the_script_writes_both_kinds_and_names_a_bad_release(env: J2Env) -> None:
    env.client()
    env.history(upto="P2")
    runs = [_ran(env, n) for n in ("P1", "P2")]
    good = env.release("20261120")
    bad = env.release("20261121")
    with (bad / "entries.jsonl").open("ab") as f:
        f.write(b'{"tampered":true}\n')
    with pytest.raises(ValueError):
        nb_release.verify(bad)
    for p in env.marker_files():
        p.unlink()
    script = REPO / "scripts" / "markers_backfill.py"
    child = {
        **os.environ,
        "BAYES_DATA_DIR": str(env.data_dir),
        "BAYES_NOTEBOOK_DIR": str(env.nb_root),
    }

    def backfill() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-I", str(script)],
            capture_output=True,
            text=True,
            env=child,
            cwd=env.tmp,
            timeout=120,
        )

    first = backfill()
    assert first.returncode == 0, first.stderr
    assert first.stdout.strip()  # it prints the count written per kind
    assert bad.name in first.stderr  # a release that fails verify is named on stderr
    for r in runs:
        _assert_run_marker(env, r, env.run_marker(r))
    gm = _load(env.release_marker(good.name))
    assert gm["release_hash"] == nb_release.verify(good)
    assert len(env.marker_files()) == 3  # two runs, one good release, none for the bad one
    names = {p.name: p.read_bytes() for p in env.marker_files()}
    second = backfill()
    assert second.returncode == 0, second.stderr
    assert {p.name: p.read_bytes() for p in env.marker_files()} == names  # idempotent


# ------------------------------------------------------------------ (d) releases, S34


def test_J3_d_a_new_release_leaves_a_marker_with_verify_s_hash(env: J2Env) -> None:
    before = dt.datetime.now(UTC)
    folder = env.release()
    after = dt.datetime.now(UTC)
    files = env.marker_files()
    assert len(files) == 1
    path = env.release_marker(folder.name)
    data = path.read_bytes()
    assert canonical_marker(data)
    m = _load(path)
    assert set(m) == RELEASE_FIELDS  # exactly the J3 table's fields
    assert m["kind"] == "notebook_release"
    assert m["client_id"] == CLIENT
    assert m["release_id"] == folder.name
    assert m["release_path"] == str(folder.resolve())
    assert m["release_hash"] == nb_release.verify(folder)  # J3 (d)
    _written_at_ok(m["written_at"], before, after)
    assert env.stray_files() == []


def test_J3_S35_a_release_that_fails_verify_gets_no_marker(
    env: J2Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(folder: Path) -> str:
        raise ValueError("release hash does not recompute")

    first = env.release("20261119")
    files = env.marker_files()
    assert [p.name for p in files] == [env.release_marker(first.name).name]
    monkeypatch.setattr(nb_release, "verify", refuse)
    with pytest.raises(ValueError):
        env.release()
    assert env.marker_files() == files and env.stray_files() == []


def test_J3_S34_write_release_raises_when_its_marker_fails_and_backfill_writes_it(
    env: J2Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    restore = failing_replace(monkeypatch)
    with pytest.raises(Exception):  # noqa: B017
        env.release()
    restore()
    folders = sorted((env.nb_root / CLIENT / "releases").iterdir())
    assert len(folders) == 1  # the release folder stays
    folder = folders[0]
    h = nb_release.verify(folder)
    _no_marker_left(env)
    assert M.backfill() == {"engine_run": 0, "notebook_release": 1}
    assert _load(env.release_marker(folder.name))["release_hash"] == h


def test_J3_S35_backfill_skips_a_release_that_fails_verify(
    env: J2Env, capfd: pytest.CaptureFixture[str]
) -> None:
    good, bad = env.release("20261120"), env.release("20261121")
    (bad / "catalog.json").write_bytes(b"{}\n")
    for p in env.marker_files():
        p.unlink()
    assert M.backfill() == {"engine_run": 0, "notebook_release": 1}
    env.release_marker(good.name)
    assert len(env.marker_files()) == 1
    assert bad.name in capfd.readouterr().err
