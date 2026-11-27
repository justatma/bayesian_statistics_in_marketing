"""J2: row hashes in the engine's own run record (Brain join spec v0.4, J1, J2, S1 to S14,
S28 to S32).

The refresh runs against a real ``SqliteStore`` in ``tmp_path`` holding ``j2_fixtures``' history
(a rename with figures unchanged, a restated figure, confirmed versions, a non-ASCII ad name, an
error poll, an interrupted poll and another client's poll). "The export's ``rows_sha256``" is
what ``scripts/export_history.py``'s ``runs()`` wrote at commit e983942: the keys its ``polls()``
says the run's poll saw, hashed under J1. ``polls()`` at e983942 is copied verbatim into
``tests/acceptance/j2_oracle.py`` and the J1 hash is the test writer's own (``j1_hash``), written
from J1's text alone (S4 check f).

J2 (c): the run id and seed of a refresh on a fixed poll are held two ways. The constants below
were taken by running this fixture at commit 509296b (before J2; the refresh then passed none of
the J2 keywords), with the prior registry's and the pipeline's clocks pinned. The test also
recomputes both from the manifest and request the refresh passed, the way ``pipeline`` does (S13).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import inspect
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from bayesian_marketing import pipeline
from bayesian_marketing.atmaos import socket as sock
from bayesian_marketing.core import inputs_hash, make_id
from bayesian_marketing.live import refresh as refresh_mod
from bayesian_marketing.live import rows as live_rows
from bayesian_marketing.prior_registry import registry as prior_registry
from tests.acceptance.j2_fixtures import (
    CLIENT,
    EMPTY_SHA,
    J1_KEYS,
    NAMES_A,
    NAMES_A2,
    OTHER,
    PREFIX,
    T0,
    TZ,
    J2Env,
    add_error_poll,
    add_poll,
    base_figures,
    fake_store_copy,
    file_bytes,
    j1_bytes,
    j1_hash,
    make_env,
)
from tests.fakes.live import FakeStore

pytestmark = pytest.mark.piece("J2")


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[J2Env]:
    yield from make_env(tmp_path, monkeypatch)


REPO = Path(__file__).resolve().parents[2]
UTC = dt.UTC

# J2 (c): taken at commit 509296b on this fixture (see the module docstring).
T_APPROVE = dt.datetime(2026, 11, 7, 12, 0, 0, tzinfo=UTC)
T_RUN = dt.datetime(2026, 11, 7, 17, 40, 0, tzinfo=UTC)
RUN_ID_BEFORE_J2 = "run_81c61671"
SEED_BEFORE_J2 = 1820359372


# ------------------------------------------------------------------ J1 by the test writer's hand

#: Three rows with known bytes (J1 check a). Row 2 holds a non-ASCII name, row 3 a float
#: conversion count and a nested ``names`` object whose keys are out of order as written.
J1_ROWS: list[dict[str, Any]] = [
    {
        "key": "meta:111:2026-11-01:v1",
        "restates": None,
        "describes": "2026-11-01",
        "known_at": "2026-11-02T10:00:00+00:00",
        "timezone": "America/New_York",
        "poll_id": "poll_aaaaaaaa",
        "platform": "meta",
        "account": "777",
        "campaign": "c1",
        "ad_set": "s1",
        "ad": "111",
        "names": {"ad": "Spring A", "account": "Acme"},
        "link_clicks": 20,
        "impressions": 1000,
        "spend_amount": "12.34",
        "spend_currency": "USD",
        "conversions_reported": None,
        "conversions_observed": 2,
        "revenue_amount": "45.60",
        "revenue_currency": "USD",
        "attribution_window": "7d_click_1d_view",
        "objective": "OUTCOME_SALES",
    },
    {
        "key": "meta:222:2026-11-01:v1",
        "restates": None,
        "describes": "2026-11-01",
        "known_at": "2026-11-02T10:00:00+00:00",
        "timezone": "America/New_York",
        "poll_id": "poll_aaaaaaaa",
        "platform": "meta",
        "account": "777",
        "campaign": "c1",
        "ad_set": "s1",
        "ad": "222",
        "names": {"ad": "Café ☕ naïve ü"},
        "link_clicks": 7,
        "impressions": 300,
        "spend_amount": "3.10",
        "spend_currency": "USD",
        "conversions_reported": 1.0,
        "conversions_observed": None,
        "revenue_amount": None,
        "revenue_currency": None,
        "attribution_window": "7d_click_1d_view",
        "objective": None,
    },
    {
        "key": "meta:111:2026-11-01:v2",
        "restates": "meta:111:2026-11-01:v1",
        "describes": "2026-11-01",
        "known_at": "2026-11-02T11:00:00+00:00",
        "timezone": "America/New_York",
        "poll_id": "poll_bbbbbbbb",
        "platform": "meta",
        "account": "777",
        "campaign": "c1",
        "ad_set": "s1",
        "ad": "111",
        "names": {"campaign": "Spring", "ad": "Spring A"},
        "link_clicks": 21,
        "impressions": 1010,
        "spend_amount": "12.50",
        "spend_currency": "USD",
        "conversions_reported": 2.5,
        "conversions_observed": 2,
        "revenue_amount": "45.60",
        "revenue_currency": "USD",
        "attribution_window": "7d_click_1d_view",
        "objective": "OUTCOME_SALES",
    },
]
J1_BYTES = (
    '{"account":"777","ad":"111","ad_set":"s1","attribution_window":"7d_click_1d_view",'
    '"campaign":"c1","conversions_observed":2,"conversions_reported":null,'
    '"describes":"2026-11-01","impressions":1000,"key":"meta:111:2026-11-01:v1",'
    '"known_at":"2026-11-02T10:00:00+00:00","link_clicks":20,'
    '"names":{"account":"Acme","ad":"Spring A"},"objective":"OUTCOME_SALES",'
    '"platform":"meta","poll_id":"poll_aaaaaaaa","restates":null,"revenue_amount":"45.60",'
    '"revenue_currency":"USD","spend_amount":"12.34","spend_currency":"USD",'
    '"timezone":"America/New_York"}\n'
    '{"account":"777","ad":"111","ad_set":"s1","attribution_window":"7d_click_1d_view",'
    '"campaign":"c1","conversions_observed":2,"conversions_reported":2.5,'
    '"describes":"2026-11-01","impressions":1010,"key":"meta:111:2026-11-01:v2",'
    '"known_at":"2026-11-02T11:00:00+00:00","link_clicks":21,'
    '"names":{"ad":"Spring A","campaign":"Spring"},"objective":"OUTCOME_SALES",'
    '"platform":"meta","poll_id":"poll_bbbbbbbb","restates":"meta:111:2026-11-01:v1",'
    '"revenue_amount":"45.60","revenue_currency":"USD","spend_amount":"12.50",'
    '"spend_currency":"USD","timezone":"America/New_York"}\n'
    '{"account":"777","ad":"222","ad_set":"s1","attribution_window":"7d_click_1d_view",'
    '"campaign":"c1","conversions_observed":null,"conversions_reported":1.0,'
    '"describes":"2026-11-01","impressions":300,"key":"meta:222:2026-11-01:v1",'
    '"known_at":"2026-11-02T10:00:00+00:00","link_clicks":7,"names":{"ad":"Café ☕ naïve ü"},'
    '"objective":null,"platform":"meta","poll_id":"poll_aaaaaaaa","restates":null,'
    '"revenue_amount":null,"revenue_currency":null,"spend_amount":"3.10",'
    '"spend_currency":"USD","timezone":"America/New_York"}\n'
).encode()
J1_SHA = hashlib.sha256(J1_BYTES).hexdigest()


def test_J1_a_f_the_three_row_fixture_hash_by_a_second_implementation() -> None:
    assert set(J1_ROWS[0]) == J1_KEYS  # the fixture is J1-shaped
    assert j1_bytes(J1_ROWS) == J1_BYTES  # the test writer's implementation gives the known bytes
    assert j1_hash(J1_ROWS) == J1_SHA  # J1 (a), S4 check (f)
    assert live_rows.rows_sha256(J1_ROWS) == J1_SHA  # the engine's one implementation agrees
    for r in J1_ROWS:
        assert live_rows.canonical(r) + b"\n" in J1_BYTES  # J1 point 3, per row
    assert live_rows.ROWS_FORM == "bayes-rows-c1" and live_rows.HASH_PREFIX == PREFIX


def test_J1_b_order_does_not_matter() -> None:
    for order in ([2, 1, 0], [1, 0, 2], [0, 2, 1]):
        assert live_rows.rows_sha256([J1_ROWS[i] for i in order]) == J1_SHA


def test_J1_c_any_one_value_changed_changes_the_hash() -> None:
    for i, row in enumerate(J1_ROWS):
        for k, v in row.items():
            if k == "key":
                continue
            changed = [dict(r) for r in J1_ROWS]
            changed[i][k] = {"x": 1} if isinstance(v, dict) else (0 if v is None else None)
            assert live_rows.rows_sha256(changed) != J1_SHA, (i, k)
    changed = [dict(r) for r in J1_ROWS]
    changed[1]["names"] = {"ad": "Café ☕ naïve u"}
    assert live_rows.rows_sha256(changed) != J1_SHA


def test_J1_e_non_ascii_hashes_over_utf8_not_escapes() -> None:
    row = J1_ROWS[1]
    assert "Café ☕".encode() in live_rows.canonical(row)
    assert b"\\u" not in live_rows.canonical(row)
    escaped = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    assert (
        live_rows.rows_sha256([row]) == hashlib.sha256(live_rows.canonical(row) + b"\n").hexdigest()
    )
    assert live_rows.rows_sha256([row]) != hashlib.sha256(escaped + b"\n").hexdigest()


def test_J1_empty_set_hashes_the_empty_string() -> None:
    assert live_rows.rows_sha256([]) == EMPTY_SHA


# ------------------------------------------------------------------ S28, check (f): the oracle


def test_J2_f_S28_versioned_matches_the_export_at_e983942(env: J2Env) -> None:
    env.history()
    want_rows, want_seen, want_reads = env.oracle()
    rows, seen, reads = live_rows.versioned(env.store, CLIENT)
    assert file_bytes(rows) == file_bytes(want_rows)  # polls rows, byte for byte and in order
    assert seen == want_seen
    by_key = sorted(want_reads, key=lambda r: r["key"])
    assert file_bytes(sorted(reads, key=lambda r: r["key"])) == file_bytes(by_key)  # reads.jsonl
    # the fixture holds what S28 names, so the equality above is not vacuous
    keys = [r["key"] for r in rows]
    assert "meta:ad_b:2026-11-07:v2" in keys and "meta:ad_a:2026-11-07:v2" in keys  # restated
    assert all(set(r) == J1_KEYS for r in rows)
    assert any("☕" in r["names"]["ad"] for r in rows)  # non-ASCII
    assert len(reads) > len(rows)  # confirmations


def test_J2_f_S28_rename_with_figures_unchanged_keeps_key_and_first_names(env: J2Env) -> None:
    polls = env.history(upto="P2")
    rows, seen, _ = live_rows.versioned(env.store, CLIENT)
    a = [r for r in rows if r["ad"] == "ad_a"]
    assert [r["key"] for r in a] == [
        f"meta:ad_a:{d}:v1" for d in sorted({r["describes"] for r in a})
    ]
    assert all(r["names"] == NAMES_A for r in a)  # J1 point 6, check (g): the first poll's names
    p1, p2 = set(seen[polls["P1"].poll_id]), set(seen[polls["P2"].poll_id])
    assert {k for k in p1 if ":ad_a:" in k} == {k for k in p2 if ":ad_a:" in k}  # same keys
    a_keys = sorted(k for k in p1 if ":ad_a:" in k)
    by_key = {r["key"]: r for r in rows}
    before = live_rows.rows_sha256([by_key[k] for k in a_keys])
    env.history(upto="P4")  # more history never changes a stored key's content
    rows2, _, _ = live_rows.versioned(env.store, CLIENT)
    by_key2 = {r["key"]: r for r in rows2}
    assert live_rows.rows_sha256([by_key2[k] for k in a_keys]) == before
    v2 = by_key2["meta:ad_a:2026-11-07:v2"]
    assert v2["names"] == NAMES_A2  # the next version carries the rename (P6)
    assert v2["restates"] == "meta:ad_a:2026-11-07:v1"


def test_J2_f_S28_values_are_the_stored_text_forms(env: J2Env) -> None:
    polls = env.history(upto="P1")
    rows, _, _ = live_rows.versioned(env.store, CLIENT)
    a = next(r for r in rows if r["ad"] == "ad_a")
    b = next(r for r in rows if r["ad"] == "ad_b")
    assert a["spend_amount"] == "10.00" and b["spend_amount"] == "12.30"  # str(Decimal)
    assert b["revenue_amount"] == "45.60" and a["revenue_amount"] is None
    assert a["conversions_reported"] == 1.0 and isinstance(a["conversions_reported"], float)
    assert b["conversions_reported"] is None
    assert a["known_at"] == polls["P1"].started_at.isoformat() == T0.isoformat()
    assert a["describes"] == "2026-11-01" and a["timezone"] == TZ
    assert a["link_clicks"] == 20 and "clicks" not in a


def test_J2_f_S28_a_figure_set_that_returns_follows_the_oracle(env: J2Env) -> None:
    """P5 puts ad_b's last day back to P1's figures. The export at e983942 cuts a version
    whenever the figures differ from the version before (J1 point 7 says "distinct figure sets";
    S28 makes the export the oracle)."""
    env.history(flip=True)
    want_rows, want_seen, want_reads = env.oracle()
    rows, seen, reads = live_rows.versioned(env.store, CLIENT)
    assert file_bytes(rows) == file_bytes(want_rows)
    assert seen == want_seen
    assert sorted(json.dumps(r, sort_keys=True) for r in reads) == sorted(
        json.dumps(r, sort_keys=True) for r in want_reads
    )


def test_J2_f_S28_versioned_reads_through_the_store_contract(env: J2Env) -> None:
    env.history()
    fake = fake_store_copy(env)
    assert isinstance(fake, FakeStore)
    got_fake = live_rows.versioned(fake, CLIENT)
    got_sql = live_rows.versioned(env.store, CLIENT)
    assert file_bytes(got_fake[0]) == file_bytes(got_sql[0])
    assert got_fake[1] == got_sql[1]
    key = lambda r: r["key"]  # noqa: E731
    assert file_bytes(sorted(got_fake[2], key=key)) == file_bytes(sorted(got_sql[2], key=key))


def test_J2_J1_d_two_reads_of_one_store_agree(env: J2Env) -> None:
    env.history()
    first, second = live_rows.versioned(env.store, CLIENT), live_rows.versioned(env.store, CLIENT)
    assert file_bytes(first[0]) == file_bytes(second[0]) and first[1] == second[1]


def test_J2_S28_only_ok_polls_and_only_the_client_count(env: J2Env) -> None:
    polls = env.history()
    rows, seen, reads = live_rows.versioned(env.store, CLIENT)
    assert polls["ERR"].poll_id not in seen and polls["INT"].poll_id not in seen
    assert polls["OTHER"].poll_id not in seen
    assert all(r["ad"] != "ad_z" for r in rows) and all(r["ad"] != "ad_z" for r in reads)
    other_rows, _, _ = live_rows.versioned(env.store, OTHER)
    assert [r["ad"] for r in other_rows] == ["ad_z"]
    assert other_rows[0]["timezone"] == "Asia/Tokyo"


def test_J2_pointer_is_the_versions_the_poll_read(env: J2Env) -> None:
    polls = env.history()
    rows, seen, _ = live_rows.versioned(env.store, CLIENT)
    for name in ("P1", "P2", "P4"):
        keys, sha = live_rows.pointer(rows, seen, polls[name].poll_id)
        assert (keys, sha) == env.oracle_pointer(polls[name].poll_id)
    assert live_rows.pointer(rows, seen, polls["ERR"].poll_id) == ([], EMPTY_SHA)


# ------------------------------------------------------------------ S29 the time zone


def test_J2_S29_two_time_zones_among_ok_polls_raise(env: J2Env) -> None:
    add_poll(env.store, T0, base_figures())
    add_poll(env.store, T0 + dt.timedelta(hours=1), base_figures(), timezone="Europe/London")
    with pytest.raises(ValueError):
        live_rows.versioned(env.store, CLIENT)


def test_J2_S29_an_error_poll_or_null_zone_does_not_count(env: J2Env) -> None:
    add_poll(env.store, T0, base_figures())
    add_error_poll(env.store, T0 + dt.timedelta(minutes=30), "Europe/London")
    add_poll(env.store, T0 + dt.timedelta(hours=1), base_figures(), timezone=None)
    rows, _, _ = live_rows.versioned(env.store, CLIENT)
    assert rows and all(r["timezone"] == TZ for r in rows)


def test_J2_S29_no_time_zone_gives_null(env: J2Env) -> None:
    add_poll(env.store, T0, base_figures(), timezone=None)
    rows, _, _ = live_rows.versioned(env.store, CLIENT)
    assert rows and all(r["timezone"] is None for r in rows)


# ------------------------------------------------------------------ J2 (a) the refresh


def test_J2_a_every_refreshed_run_names_its_rows(env: J2Env) -> None:
    """Refreshes interleaved with the polls, as the live job runs them; the export is taken at
    the end over the full history."""
    env.client()
    order = ["P1", "OTHER", "P2", "INT", "ERR", "P4"]
    runs: dict[str, str] = {}
    for name in order:
        polls = env.history(upto=name)
        if name in ("P1", "P2", "P4"):
            rec = env.refresh(polls[name])
            assert rec.status == "ran", rec.reason
            runs[name] = str(rec.run_id)
    for name, run_id in runs.items():
        keys, sha = env.oracle_pointer(env.polls[name].poll_id)
        assert keys  # the poll read rows
        want = [f"{PREFIX}{sha}"]
        record, snap = env.record(run_id), env.snapshot(run_id)
        assert [h for h in record.dataset_hashes if h.startswith(PREFIX)] == want  # exactly one
        assert record.dataset_hashes == want  # a live manifest has no files (S31)
        assert snap.dataset_hashes == want
        assert snap.row_keys == keys  # S1: the run keeps its own keys
        assert snap.rows_form == "bayes-rows-c1"
    # the versions differ by poll, so each run's hash is its own
    assert len({tuple(env.snapshot(r).dataset_hashes) for r in runs.values()}) == 3


def test_J2_a_S3_dataset_snapshot_hash_names_the_content(env: J2Env) -> None:
    env.client()
    polls = env.history(upto="P1")
    rec = env.refresh(polls["P1"])
    assert rec.status == "ran", rec.reason
    snap = env.snapshot(str(rec.run_id))
    ev = sock.observation_evidence(sock.result_of(snap), "tr_j2")
    _, sha = env.oracle_pointer(polls["P1"].poll_id)
    want = inputs_hash({"manifest": snap.manifest_id, "files": [f"{PREFIX}{sha}"]})
    assert ev["dataset_snapshot_hash"] == want
    assert set(ev) == set(sock.EVIDENCE_KEYS)  # S32: EVIDENCE_KEYS doesn't change
    assert sock.EVIDENCE_KEYS == (
        "tool_version",
        "dataset_snapshot_hash",
        "window",
        "metric",
        "priors",
        "configuration",
        "segments",
        "result",
        "uncertainty",
        "tool_result_id",
    )


def test_J2_S30_versioned_raising_fails_the_refresh(
    env: J2Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    env.client()
    polls = env.history(upto="P1")

    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("no rows form")

    monkeypatch.setattr(live_rows, "versioned", boom)
    if hasattr(refresh_mod, "versioned"):
        monkeypatch.setattr(refresh_mod, "versioned", boom)
    rec = env.refresh(polls["P1"])
    assert rec.status == "failed" and rec.run_id is None
    assert rec.reason and "no rows form" in rec.reason
    assert env.run_files() == []  # no live run without its pointer
    assert env.store.latest_refresh(CLIENT) == rec


def test_J2_S29_S30_two_time_zones_fail_the_refresh(env: J2Env) -> None:
    env.client()
    p1 = add_poll(env.store, T0, base_figures())
    add_poll(env.store, T0 - dt.timedelta(hours=1), base_figures(), timezone="Europe/London")
    rec = env.refresh(p1)
    assert rec.status == "failed" and rec.run_id is None
    assert rec.reason and rec.reason.startswith("ValueError: ")
    assert env.run_files() == []


# ------------------------------------------------------------------ J2 (b) older runs


def test_J2_b_runs_made_before_J2_are_not_rewritten(env: J2Env) -> None:
    env.client()
    polls = env.history(upto="P1")
    calls = env.capture_execute()
    assert env.refresh(polls["P1"]).status == "ran"
    old = env.pre_j2_run(calls[0])  # as every caller but the refresh: none of the J2 keywords
    old_id = old.snapshot.run_id
    old_bytes = env.snapshot_file(old_id).read_bytes()
    assert env.record(old_id).dataset_hashes == []
    assert old.snapshot.dataset_hashes == [] and old.snapshot.row_keys == []
    assert old.snapshot.rows_form is None
    polls = env.history(upto="P4")
    for name in ("P2", "P4"):
        assert env.refresh(polls[name]).status == "ran"
    assert env.snapshot_file(old_id).read_bytes() == old_bytes  # never rewritten
    assert env.record(old_id).dataset_hashes == []  # their dataset_hashes stay empty
    # the export still gives their rows_sha256: from the rows, for the poll the run read
    rows, seen, _ = live_rows.versioned(env.store, CLIENT)
    assert live_rows.pointer(rows, seen, polls["P1"].poll_id) == env.oracle_pointer(
        polls["P1"].poll_id
    )


def test_J2_b_a_snapshot_saved_before_J2_still_loads(env: J2Env) -> None:
    env.client()
    polls = env.history(upto="P1")
    rec = env.refresh(polls["P1"])
    d = json.loads(env.snapshot_file(str(rec.run_id)).read_text())
    assert d["rows_form"] == "bayes-rows-c1" and d["row_keys"]  # a post-J2 file, stripped below
    d.pop("row_keys", None)
    d.pop("rows_form", None)
    d["dataset_hashes"] = []
    snap = pipeline.RunSnapshot.model_validate(d)
    assert snap.row_keys == [] and snap.rows_form is None


# ------------------------------------------------------------------ J2 (c) seed and run id


def _request_key(request: Any) -> Any:
    """The request as pipeline hashes it before J2 (S13; ``_request_key`` at 509296b)."""
    if request.conversion_kind == "purchase":
        return request.model_dump(mode="json", exclude={"conversion_kind", "horizon_basis"})
    return request.model_dump(mode="json", exclude={"horizon_basis"})


def test_J2_c_seed_and_run_id_of_a_fixed_poll_are_unchanged(
    env: J2Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(prior_registry, "utcnow", lambda: T_APPROVE)
    env.client()
    monkeypatch.setattr(pipeline, "utcnow", lambda: T_RUN)
    polls = env.history(upto="P1")
    calls = env.capture_execute()
    rec = env.refresh(polls["P1"])
    assert rec.status == "ran", rec.reason
    run_id = str(rec.run_id)
    record, snap = env.record(run_id), env.snapshot(run_id)
    # the J2 pointer is there, so the run is a post-J2 run
    assert snap.rows_form == "bayes-rows-c1" and snap.dataset_hashes[0].startswith(PREFIX)
    # held: the values this fixture gave before J2
    assert run_id == RUN_ID_BEFORE_J2
    assert record.seeds["fit"] == SEED_BEFORE_J2
    # recomputed the way pipeline does (S13), from what the refresh passed
    args, kwargs = calls[0]
    manifest = kwargs.get("manifest", args[0] if args else None)
    request = kwargs.get("request", args[1] if len(args) > 1 else None)
    sha8 = hashlib.sha256(f"{CLIENT}|{polls['P1'].poll_id}".encode()).hexdigest()[:8]
    assert manifest.manifest_id == snap.manifest_id == record.manifest_id == f"ds_{sha8}"
    key = {"manifest": manifest.manifest_id, "request": _request_key(request)}
    assert record.seeds["fit"] == int(inputs_hash(key)[:8], 16) == snap.configuration["seed"]
    assert run_id == make_id("run_", {**key, "at": T_RUN.isoformat()})
    assert record.started_at == T_RUN


# ------------------------------------------------------------------ S31 the execute keywords


def test_J2_S31_execute_keywords_change_only_their_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bayesian_marketing import core as C
    from bayesian_marketing.cli import _window as scenario_window
    from bayesian_marketing.decision import run_record
    from bayesian_marketing.simulate.generate import MANIFEST_NAME, generate

    out = tmp_path / "scenario"
    generate(REPO / "data" / "scenarios" / "north_pier_day14.yaml", 1, out)
    m = C.DatasetManifest.load(out / MANIFEST_NAME)
    platform = pipeline.comparison_platform(m, sorted(m.entity_map))
    from decimal import Decimal

    req = C.CompareRequest(
        metric="ctr",
        variants=sorted(m.entity_map),
        priors={},
        window=scenario_window(m, out, platform),
        horizon=C.Horizon(unit="impressions", amount=Decimal(1000)),
    )
    at = dt.datetime.now(UTC).replace(microsecond=0)
    monkeypatch.setattr(pipeline, "utcnow", lambda: at)
    extra = ["zz:9", f"{PREFIX}{'0' * 64}"]
    keys = ["meta:b:2026-11-02:v1", "meta:a:2026-11-01:v2"]

    def run(where: str, **kw: Any) -> tuple[pipeline.RunSnapshot, Any]:
        monkeypatch.setenv("BAYES_DATA_DIR", str(tmp_path / where))
        snap = pipeline.execute(m, req, manifest_dir=out, **kw).snapshot
        rec = run_record.read("RunRecord", run_id=snap.run_id)[0]
        return snap, rec

    plain, plain_rec = run("plain")
    given, given_rec = run(
        "given", extra_dataset_hashes=extra, row_keys=keys, rows_form="bayes-rows-c1"
    )
    files = sorted(f.sha256 for f in m.files)
    assert files  # a file manifest, so the sort with file hashes is tested
    assert plain.dataset_hashes == files == plain_rec.dataset_hashes  # every other caller
    assert plain.row_keys == [] and plain.rows_form is None
    assert given.dataset_hashes == sorted([*files, *extra]) == given_rec.dataset_hashes
    assert given.row_keys == sorted(keys) and given.rows_form == "bayes-rows-c1"
    fields = {"dataset_hashes", "row_keys", "rows_form"}

    # nothing else changes: wall-clock stamps from modules other than pipeline are left out, and
    # each run's own data dir (in the samples path) is read as one name
    def same(a: dict[str, Any], b: dict[str, Any]) -> bool:
        def norm(x: dict[str, Any], where: str) -> str:
            text = json.dumps(_clockless(x), sort_keys=True, default=str)
            return text.replace(str(tmp_path / where), "<data_dir>")

        return norm(a, "plain") == norm(b, "given")

    assert same(plain.model_dump(exclude=fields), given.model_dump(exclude=fields))
    assert same(
        plain_rec.model_dump(exclude={"dataset_hashes"}),
        given_rec.model_dump(exclude={"dataset_hashes"}),
    )


def _clockless(x: Any) -> Any:
    """``x`` without the keys ending ``_at`` (``checked_at``, ``computed_at``), which other
    modules stamp from their own clocks."""
    if isinstance(x, dict):
        return {k: _clockless(v) for k, v in x.items() if not str(k).endswith("_at")}
    if isinstance(x, list):
        return [_clockless(v) for v in x]
    return x


# ------------------------------------------------------------------ J2 (e), S32 result_of


POINTER = ("rows_form", "rows_sha256", "row_keys")


def test_J2_e_S32_result_of_carries_the_pointer_on_every_posterior_entry(env: J2Env) -> None:
    env.client()
    polls = env.history(upto="P1")
    rec = env.refresh(polls["P1"])
    assert rec.status == "ran", rec.reason
    snap = env.snapshot(str(rec.run_id))
    keys, sha = env.oracle_pointer(polls["P1"].poll_id)
    result = sock.result_of(snap)
    assert result["posterior"]
    for entry in result["posterior"].values():
        assert entry["rows_form"] == "bayes-rows-c1"
        assert entry["rows_sha256"] == sha  # the hex, without the prefix (S32)
        assert entry["row_keys"] == keys
        assert entry["quantity_id"] and entry["status"] != "below_floor"  # beside the quantity
    assert result["uncertainty"]["run_id"] == snap.run_id
    ev = sock.observation_evidence(result, "tr_j2")
    for entry in ev["result"]["posterior"].values():  # through observation_evidence (S2, S32)
        assert (entry["rows_sha256"], entry["row_keys"]) == (sha, keys)
    # below-floor entries carry it too (S32)
    floor = sock.result_of(snap.model_copy(update={"quantities": []}))
    for entry in floor["posterior"].values():
        assert entry["status"] == "below_floor"
        assert (entry["rows_form"], entry["rows_sha256"], entry["row_keys"]) == (
            "bayes-rows-c1",
            sha,
            keys,
        )


def test_J2_e_a_run_before_J2_gives_null_and_an_empty_list(env: J2Env) -> None:
    env.client()
    polls = env.history(upto="P1")
    calls = env.capture_execute()
    assert env.refresh(polls["P1"]).status == "ran"
    old = env.pre_j2_run(calls[0]).snapshot
    d = json.loads(env.snapshot_file(old.run_id).read_text())
    d.pop("row_keys", None)
    d.pop("rows_form", None)
    legacy = pipeline.RunSnapshot.model_validate(d)  # as saved before the fields existed
    for snap in (old, legacy, legacy.model_copy(update={"quantities": []})):
        result = sock.result_of(snap)
        assert result["posterior"]
        for entry in result["posterior"].values():
            assert {k: entry[k] for k in POINTER} == {
                "rows_form": None,
                "rows_sha256": None,
                "row_keys": [],
            }
    ev = sock.observation_evidence(sock.result_of(old), "tr_old")
    for entry in ev["result"]["posterior"].values():
        assert entry["rows_sha256"] is None and entry["row_keys"] == []


def test_J2_S32_rows_sha256_comes_only_from_a_prefixed_hash(env: J2Env) -> None:
    env.client()
    polls = env.history(upto="P1")
    snap = env.snapshot(str(env.refresh(polls["P1"]).run_id))
    files_only = snap.model_copy(update={"dataset_hashes": ["ab" * 32]})
    for entry in sock.result_of(files_only)["posterior"].values():
        assert entry["rows_sha256"] is None


# ------------------------------------------------------------------ the export uses live.rows


def test_J2_export_history_imports_the_one_implementation() -> None:
    path = REPO / "scripts" / "export_history.py"
    spec = importlib.util.spec_from_file_location("export_history_j2", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.rows_sha256 is live_rows.rows_sha256  # in place of its own copy
    src = inspect.getsource(mod)
    assert "def rows_sha256" not in src
    assert "bayesian_marketing.live.rows" in src or "from bayesian_marketing.live import" in src
    assert "versioned(" in src  # the version numbering is the shared function's (J2, S14)
