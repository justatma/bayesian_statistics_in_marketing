"""L4 review tests (review/L4 eec529b), F1 adjusted to build log B12."""

from __future__ import annotations

import contextlib
import datetime as dt
import os
import re
import types
from pathlib import Path

import pytest
from tests.acceptance.test_L4 import (
    CLIENT,
    START,
    Env,
    config,
    propose_ctr_prior,
    seed_poll,
    write_economics,
)

from bayesian_marketing import core as C
from bayesian_marketing import pipeline
from bayesian_marketing.core import GateFailure


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch)
    e.iso = os.environ["BAYES_DATA_DIR"]
    return e


def _gr():
    return types.SimpleNamespace(gate="G9", reasons=["a", "b"])


def _error_poll(store):
    rec = seed_poll(store)
    err = rec.model_copy(
        update={
            "poll_id": "poll_err00001",
            "status": "error",
            "error": "X: y",
            "n_rows": 0,
            "pull_id": None,
            "started_at": START + dt.timedelta(hours=1),
        }
    )
    store.begin_poll(err)
    store.finish_poll(err, [])
    return err


def test_error_poll_gets_no_refresh(env):
    write_economics(env.config_root)
    err = _error_poll(env.store)
    r = env.run(config(), err)
    assert r.status == "skipped" and r.run_id is None  # B12
    assert r.reason == f"poll {err.poll_id} is error; no engine run"  # B12
    assert env.store.refreshes(CLIENT) == []  # C3: none after an error poll


def test_interrupted_poll_gets_no_refresh(env):
    write_economics(env.config_root)
    rec = seed_poll(env.store)
    p = rec.model_copy(
        update={"poll_id": "poll_int00001", "started_at": START + dt.timedelta(hours=2)}
    )
    env.store.begin_poll(p)
    got = env.store.polls(CLIENT, limit=10)[0]
    assert got.status == "interrupted"
    r = env.run(config(), got)
    assert r.status == "skipped" and r.run_id is None  # B12
    assert r.reason == f"poll {got.poll_id} is interrupted; no engine run"  # B12
    assert env.store.refreshes(CLIENT) == []  # C3


def test_env_unset_before_stays_unset(env, monkeypatch):
    write_economics(env.config_root)
    rec = seed_poll(env.store)
    monkeypatch.delenv("BAYES_DATA_DIR")
    try:
        env.run(config(), rec)
        assert "BAYES_DATA_DIR" not in os.environ
    finally:
        monkeypatch.setenv("BAYES_DATA_DIR", env.iso)


@pytest.mark.parametrize("exc", [GateFailure(_gr()), ValueError("v"), KeyboardInterrupt()])
def test_env_restored_on_raise(env, monkeypatch, exc):
    write_economics(env.config_root)
    rec = seed_poll(env.store)
    seen = {}

    def boom(*a, **k):
        seen["d"] = os.environ["BAYES_DATA_DIR"]
        raise exc

    monkeypatch.setattr(pipeline, "execute", boom)
    with contextlib.suppress(KeyboardInterrupt):
        env.run(config(), rec)
    assert seen["d"] == str(env.data_dir)
    assert os.environ["BAYES_DATA_DIR"] == env.iso


def test_zero_ads(env):
    write_economics(env.config_root)
    rec = seed_poll(env.store)
    env.store._rows[rec.poll_id] = []
    r = env.run(config(), rec)
    assert (r.status, r.reason) == ("skipped", "one ad, nothing to compare")


def test_missing_economics_file_does_not_raise(env):
    rec = seed_poll(env.store)
    r = env.run(config(economics_path="economics/nope.json"), rec)
    assert r.status in ("skipped", "failed") and r.reason
    assert env.store.latest_refresh(CLIENT) == r


def test_conversions_none_rows(env):
    write_economics(env.config_root)
    rec = seed_poll(env.store)
    env.store._rows[rec.poll_id] = [
        x.model_copy(update={"conversions_reported": None, "conversions_observed": None})
        for x in env.store.rows(rec.poll_id)
    ]
    pid = propose_ctr_prior(env.data_dir, env.monkeypatch, approve=True)
    r = env.run(config(priors={"ctr": pid}), rec)
    assert r.status == "ran", r.reason


def test_other_poll_rows_ignored(env):
    write_economics(env.config_root)
    pid = propose_ctr_prior(env.data_dir, env.monkeypatch, approve=True)
    a = seed_poll(env.store, {"ad_a": (1000, 20), "ad_b": (1000, 35)})
    seed_poll(
        env.store,
        {"ad_a": (1, 1), "ad_b": (1, 1), "ad_c": (1, 0)},
        started=START + dt.timedelta(hours=1),
    )
    r = env.run(config(priors={"ctr": pid}), a)
    assert r.status == "ran", r.reason
    snap = env.snapshot(r.run_id)
    assert sorted(snap.variants.values()) == ["ad_a", "ad_b"]
    assert sum(1 for q in snap.quantities if q.name == "ctr") == 2


def test_repo_default_data_dir_untouched(env):
    write_economics(env.config_root)
    pid = propose_ctr_prior(env.data_dir, env.monkeypatch, approve=True)
    rec = seed_poll(env.store)
    before = set(Path(env.iso).rglob("*"))
    r = env.run(config(priors={"ctr": pid}), rec)
    assert r.status == "ran", r.reason
    assert set(Path(env.iso).rglob("*")) == before
    assert any(env.data_dir.rglob(f"*{r.run_id}*"))


def test_gate_reason_is_gate_text(env):
    write_economics(env.config_root, loss_tolerance=None)
    pid = propose_ctr_prior(env.data_dir, env.monkeypatch, approve=True)
    rec = seed_poll(env.store)
    r = env.run(config(priors={"ctr": pid}), rec)
    print(repr(r.reason))
    assert r.status == "skipped"
    assert "no loss tolerance set" in r.reason
    assert not r.reason.startswith("G9 failed:")  # C2: reasons joined, no gate prefix


def test_gate_failure_without_args(env, monkeypatch):
    write_economics(env.config_root)
    rec = seed_poll(env.store)

    def boom(*a, **k):
        raise GateFailure(_gr())

    monkeypatch.setattr(pipeline, "execute", boom)
    r = env.run(config(), rec)
    assert r.status == "skipped"
    assert r.reason == "a; b"  # C2: the gate's reasons joined with "; "


def test_currency_from_rows(env, monkeypatch):
    write_economics(env.config_root)
    rec = seed_poll(env.store)
    env.store._rows[rec.poll_id] = [
        x.model_copy(update={"spend": C.Money(amount="10.00", currency="EUR")})
        for x in env.store.rows(rec.poll_id)
    ]
    got = {}

    def spy(manifest, *a, **k):
        got["c"] = manifest.currency
        got["v"] = a
        raise RuntimeError("stop")

    monkeypatch.setattr(pipeline, "execute", spy)
    env.run(config(), rec)
    assert got["c"] == "EUR"


def test_variants_sorted(env, monkeypatch):
    write_economics(env.config_root)
    rec = seed_poll(env.store, {"ad_z": (10, 1), "ad_b": (10, 1), "ad_m": (10, 1)})
    got = {}

    def spy(manifest, request, **k):
        got["v"] = request.variants
        raise RuntimeError("stop")

    monkeypatch.setattr(pipeline, "execute", spy)
    env.run(config(), rec)
    assert got["v"] == ["ad_b", "ad_m", "ad_z"]


def test_id_format(env):
    rec = seed_poll(env.store)
    r = env.run(config(economics_path=None), rec)
    assert re.fullmatch(r"lv_[0-9a-f]{8}", r.refresh_id)
