"""L4 unit checks beyond the frozen tests: the data-dir context and a poll with no rows."""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import pytest
from tests.fakes.live import FakeStore, FixedClock

from bayesian_marketing import core as C
from bayesian_marketing.live.contracts import PollRecord
from bayesian_marketing.live.refresh import ONE_AD, _data_dir, refresh


def test_data_dir_context_removes_a_variable_that_was_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BAYES_DATA_DIR", raising=False)
    with pytest.raises(RuntimeError), _data_dir(tmp_path):
        assert os.environ["BAYES_DATA_DIR"] == str(tmp_path)
        raise RuntimeError("x")
    assert "BAYES_DATA_DIR" not in os.environ


def test_a_poll_with_no_rows_is_the_one_ad_skip(tmp_path: Path) -> None:
    store = FakeStore()
    start = dt.datetime(2026, 11, 7, 12, tzinfo=dt.UTC)
    rec = PollRecord(
        poll_id="poll_00000000",
        client_id="c",
        platform="meta",
        account_id="act_1",
        started_at=start,
        finished_at=start,
        window=(dt.date(2026, 11, 1), dt.date(2026, 11, 7)),
        status="ok",
        error=None,
        pull_id="pull_meta_00000000",
        n_rows=0,
        n_quarantined=0,
        empty_account=True,
        timezone="UTC",
        currency="USD",
        account={},
        recording_dir=None,
    )
    store.begin_poll(rec)
    store.finish_poll(rec, [])
    cfg = C.ClientConfig(client_id="c", timezone="UTC", currency="USD", accounts={"meta": "act_1"})
    out = refresh(cfg, rec, store, FixedClock(start), data_dir=tmp_path, config_root=tmp_path)
    assert out.status == "skipped" and out.reason == ONE_AD and out.run_id is None
    assert store.latest_refresh("c") == out
