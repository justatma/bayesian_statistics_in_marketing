"""L0 skeleton: the shared pieces L0 fills itself (spec v0.2 §5 L0)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from tests.fakes.live import AppendOnlyError, FakeStore, FixedClock

from bayesian_marketing.cli import main
from bayesian_marketing.core import registries
from bayesian_marketing.core.data import PlatformPull
from bayesian_marketing.core.records import ClientConfig
from bayesian_marketing.data_contract.connectors import http, meta
from bayesian_marketing.floors.estimability import event_floor
from bayesian_marketing.live import Clock, PollRecord, Store, load_live_registry
from bayesian_marketing.live.config import all_clients, load_client
from bayesian_marketing.live.store import APPEND_ONLY, SCHEMA, TABLES
from bayesian_marketing.reporting.render import finding_lines, not_knowable_lines


def _poll(pid: str, minute: int, client: str = "c1") -> PollRecord:
    return PollRecord(
        poll_id=pid,
        client_id=client,
        platform="meta",
        account_id="act_1",
        started_at=datetime(2026, 11, 7, 12, minute, tzinfo=UTC),
        finished_at=None,
        window=(date(2026, 11, 1), date(2026, 11, 7)),
        status="ok",
        error=None,
        pull_id=None,
        n_rows=0,
        n_quarantined=0,
        empty_account=False,
        timezone=None,
        currency=None,
        account={},
        recording_dir=None,
    )


def test_event_floor_matches_registry() -> None:
    assert (event_floor("marginal"), event_floor("estimable")) == (17, 68)


def test_live_registry() -> None:
    r = load_live_registry()
    assert (r.interval_seconds, r.lookback_days, r.stale_after_seconds) == (3600, 7, 7200)
    assert (r.bind, r.port, r.recordings_keep_days, r.page_refresh_seconds) == (
        "127.0.0.1",
        8765,
        7,
        300,
    )
    assert r.account_status["1"] == "active" and "4" not in r.account_status


def test_phrasing_live_strings_clean() -> None:
    p = registries.load("phrasing")
    banned = p["causal_lexicon"]["negation_frames"] + p["comparative_lexicon"]["generic_phrases"]
    for k, v in {**p["live"], **p["status_labels"]}.items():
        assert not [b for b in banned if b.lower() in v.lower()], k
    assert registries.resolve("phrasing/notices/too_few_ads@v1")  # version unchanged (B3)


def test_client_configs() -> None:
    j = load_client("jovannah")
    assert j.accounts["meta"].startswith("act_") and j.economics_path == "economics/jovannah.json"
    assert j.conversion_event == {"meta": "offsite_conversion.fb_pixel_lead"}  # D44
    assert j.conversion_event_confirmed == {} and j.priors == {}  # provisional; priors not yet
    assert [c.client_id for c in all_clients()] == sorted(c.client_id for c in all_clients())
    with pytest.raises(ValueError):
        load_client("../x")


def test_config_and_pull_defaults() -> None:
    c = ClientConfig(client_id="x", timezone="UTC", currency="USD", accounts={})
    assert c.conversion_event_confirmed == {}
    assert PlatformPull.model_fields["account"].default_factory() == {}


def test_meta_field_constants() -> None:
    for f in ("account_name", "campaign_name", "adset_name", "ad_name"):
        assert f in meta.INSIGHT_FIELDS
    assert ("objective" in meta.INSIGHT_FIELDS) is meta.OBJECTIVE_REQUESTED
    assert set(meta.ACCOUNT_FIELDS) >= {"name", "account_status", "spend_cap", "amount_spent"}


def test_redact_text_access_token() -> None:
    s = "HTTP 400 for https://x/?a=1&access_token=abc123secret&b=2 and access_token=REDACTED"
    out = http.redact_text(s)
    assert "abc123secret" not in out and out.count("access_token=REDACTED") == 2


def test_schema_append_only_and_idempotent(tmp_path: Path) -> None:
    c = sqlite3.connect(tmp_path / "s.sqlite")
    c.executescript(SCHEMA)
    c.executescript(SCHEMA)
    c.execute(
        "INSERT INTO polls VALUES ('poll_1','c','meta','act','2026-11-07','2026-11-01',"
        "'2026-11-07',NULL)"
    )
    c.execute(
        "INSERT INTO poll_outcomes VALUES ('poll_1','2026-11-07','ok',NULL,NULL,0,0,0,NULL,"
        "NULL,'{}')"
    )
    c.execute(
        "INSERT INTO rows VALUES ('poll_1','c','meta','a1','2026-11-07','{}','{}',NULL,1,0,"
        "'0','USD',NULL,NULL,NULL,NULL,'7d_click')"
    )
    c.execute("INSERT INTO refreshes VALUES ('lv_1','poll_1','c','2026-11-07','skipped','x',NULL)")
    for t in TABLES:
        assert c.execute(f"SELECT count(*) FROM {t}").fetchone() == (1,)
        for stmt in (f"UPDATE {t} SET poll_id = poll_id", f"DELETE FROM {t}"):
            with pytest.raises(sqlite3.DatabaseError, match=APPEND_ONLY):
                c.execute(stmt)


def test_fake_store_contract() -> None:
    s = FakeStore()
    assert isinstance(s, Store) and isinstance(FixedClock(), Clock)
    s.begin_poll(_poll("poll_a", 0))
    assert s.latest_poll("c1") is None
    assert s.latest_poll("c1", ok_only=False).status == "interrupted"
    s.finish_poll(_poll("poll_a", 0).model_copy(update={"n_rows": 0}), [])
    assert s.latest_poll("c1").poll_id == "poll_a"
    with pytest.raises(AppendOnlyError):
        s.finish_poll(_poll("poll_a", 0), [])
    s.begin_poll(_poll("poll_b", 5))
    s.finish_poll(_poll("poll_b", 5).model_copy(update={"status": "error", "error": "x"}), [])
    assert s.latest_poll("c1").poll_id == "poll_a"
    assert s.latest_poll("c1", ok_only=False).status == "error"
    assert [p.poll_id for p in s.polls("c1", limit=5)] == ["poll_b", "poll_a"]
    assert s.clients() == ["c1"]


def test_cli_has_live_commands(capsys: pytest.CaptureFixture[str]) -> None:
    for cmd in ("poll", "serve", "prune", "refresh"):
        with pytest.raises(SystemExit) as e:
            main(["live", cmd, "--help"])
        assert e.value.code == 0
        if cmd == "poll":
            assert "--record" in capsys.readouterr().out


def test_public_render_helpers_are_the_report_helpers() -> None:
    from bayesian_marketing.reporting import render as R

    assert finding_lines.__doc__ and not_knowable_lines.__doc__
    assert R._finding and R._not_knowable
