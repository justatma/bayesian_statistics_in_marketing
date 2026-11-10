"""L7 unit checks beyond the frozen tests: the latest-file rule (B18), foreign names ignored, a
non-Beta prior in force leaves the path without candidates, the page escapes ad names and reads
the file only, and ``live score-priors`` reports a scorer failure with exit 1."""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
from typing import Any

import pytest
import yaml
from tests.fakes.live import FakeStore, FixedClock

from bayesian_marketing import cli
from bayesian_marketing import core as C
from bayesian_marketing.core import registries
from bayesian_marketing.live import prior_score as ps
from bayesian_marketing.live import view
from bayesian_marketing.live.contracts import LiveRow, PollRecord
from bayesian_marketing.live.registry import load_live_registry

UTC = dt.UTC
CLIENT = "unit_client"
NOW = dt.datetime(2026, 11, 10, 18, 0, tzinfo=UTC)
DAY = dt.date(2026, 11, 7)


def _config() -> C.ClientConfig:
    return C.ClientConfig(
        client_id=CLIENT, timezone="UTC", currency="USD", accounts={"meta": "act_1"}
    )


def _poll(store: FakeStore, started: dt.datetime, ads: list[tuple[str, str, int, int]]) -> None:
    pid = "poll_" + hashlib.sha256(started.isoformat().encode()).hexdigest()[:8]
    rec = PollRecord(
        poll_id=pid, client_id=CLIENT, platform="meta", account_id="act_1",
        started_at=started, finished_at=started, window=(DAY, DAY), status="ok", error=None,
        pull_id="pull_meta_00000001", n_rows=len(ads), n_quarantined=0, empty_account=False,
        timezone="UTC", currency="USD", account={}, recording_dir=None,
    )  # fmt: skip
    rows = [
        LiveRow(
            poll_id=pid,
            client_id=CLIENT,
            platform="meta",
            entity_ids={"account": "1", "campaign": "c", "ad_set": "s", "ad": ad},
            entity_names={"ad": name},
            objective=None,
            date=DAY,
            impressions=imp,
            clicks=clk,
            spend=C.Money(amount="1.00", currency="USD"),
            conversions_reported=1.0,
            conversions_observed=None,
            revenue_reported=None,
            attribution_window="7d_click",
        )
        for ad, name, imp, clk in ads
    ]
    store.begin_poll(rec)
    store.finish_poll(rec, rows)


def _empty(at: dt.datetime) -> ps.PriorScore:
    return ps.PriorScore(
        client_id=CLIENT, scored_at=at, conversion_kind="purchase", days=None, paths={},
        not_scored={"ctr": ps.NO_ADS_WITH_DATA},
    )  # fmt: skip


def test_latest_file_takes_the_greatest_suffix_not_the_last_name(tmp_path: Path) -> None:
    first = ps.write_score(_empty(NOW), tmp_path)
    for _ in range(9):
        ps.write_score(_empty(NOW), tmp_path)
    tenth = first.with_name("20261110T180000Z-10.json")
    assert tenth.exists()
    marked = _empty(NOW + dt.timedelta(microseconds=7))  # same second, so suffix -11
    path = ps.write_score(marked, tmp_path)
    assert path.name == "20261110T180000Z-11.json"
    # lexicographically "-9" sorts after "-11"; B18 takes (timestamp, N)
    assert ps.load_latest_score(CLIENT, tmp_path) == marked


def test_foreign_names_in_the_folder_are_ignored(tmp_path: Path) -> None:
    ps.write_score(_empty(NOW), tmp_path)
    folder = tmp_path / ps.SCORES_DIR / CLIENT
    (folder / "zzz.json").write_text("{not json")
    (folder / "20261110T180000Z.json.tmp").write_text("x")
    assert ps.load_latest_score(CLIENT, tmp_path) == _empty(NOW)


def test_non_beta_prior_in_force_leaves_the_path_without_candidates(iso: Any) -> None:
    def ctr_normal(data: dict[str, Any]) -> None:
        data["records"]["ctr"] = {"family": "normal", "params": {"loc": 0.02, "scale": 0.01}}

    iso.edit_yaml("priors/default", ctr_normal)
    store = FakeStore()
    _poll(store, NOW - dt.timedelta(hours=1), [("ad_a", "A", 1000, 20)])
    score = ps.score_priors(_config(), store, FixedClock(NOW), data_dir=iso.store)
    assert "ctr" not in score.paths
    assert [k for k in score.not_scored if k.startswith("ctr:")]
    assert "cvr" in score.paths


def test_page_escapes_ad_names_and_never_writes(tmp_path: Path) -> None:
    store = FakeStore()
    _poll(store, NOW - dt.timedelta(minutes=30), [("ad_x", "<b>bold</b>", 400, 4)])
    score = ps.score_priors(_config(), store, FixedClock(NOW), data_dir=tmp_path)
    ps.write_score(score, tmp_path)
    before = sorted(p.name for p in tmp_path.rglob("*"))
    page = view.render(
        store, CLIENT, FixedClock(NOW), registry=load_live_registry(),
        phrasing=registries.load("phrasing"), data_dir=tmp_path, config=_config(),
    )  # fmt: skip
    assert "<b>bold</b>" not in page and "&lt;b&gt;bold&lt;/b&gt;" in page
    assert sorted(p.name for p in tmp_path.rglob("*")) == before


def test_cli_score_priors_reports_a_failure_and_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / f"{CLIENT}.yaml").write_text(yaml.safe_dump(_config().model_dump(mode="json")))
    monkeypatch.setenv("BAYES_LIVE_DIR", str(tmp_path / "live"))
    monkeypatch.setenv("BAYES_CONFIG_DIR", str(configs))

    def boom(*args: Any, **kw: Any) -> Any:
        raise RuntimeError("no registry")

    monkeypatch.setattr(ps, "score_priors", boom)
    assert cli.main(["live", "score-priors", "--client", CLIENT]) == 1
    out = [x for x in capsys.readouterr().out.splitlines() if x.strip()]
    assert len(out) == 1 and "no registry" in out[0]
