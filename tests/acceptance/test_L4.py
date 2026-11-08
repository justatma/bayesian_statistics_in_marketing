"""L4 engine refresh (live view spec v0.2 §5 L4 C1 to C4).

``refresh`` runs against ``FakeStore`` in a temp config root with ``synthetic=False``. The client
economics and CTR priors are real files and records under temp directories. The one monkeypatch
is the one the spec's check names: a pipeline that raises ``RuntimeError``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
from pathlib import Path
from typing import Any

import pytest

from bayesian_marketing import core as C
from bayesian_marketing import pipeline
from bayesian_marketing.live import refresh as refresh_mod
from bayesian_marketing.live.contracts import LiveRow, PollRecord
from bayesian_marketing.live.refresh import NO_ECONOMICS_PATH, ONE_AD, refresh
from bayesian_marketing.prior_registry import registry as prior_registry
from tests.fakes import builders as B
from tests.fakes.live import FakeStore, FixedClock

pytestmark = pytest.mark.piece("L4")

UTC = dt.UTC
CLIENT = "live_client"
ECON_ID = "live_econ"
START = dt.datetime(2026, 11, 7, 17, 30, 0, 123456, tzinfo=UTC)
WINDOW = (dt.date(2026, 11, 1), dt.date(2026, 11, 7))


# ------------------------------------------------------------------ builders


def write_economics(config_root: Path, *, loss_tolerance: Any = 150) -> None:
    econ = B.economics(
        economics_id=ECON_ID,
        client_id=CLIENT,
        loss_tolerance=loss_tolerance,
        fixed_price=795,
        variable_cost=235,
        approved=True,
    )
    path = config_root / "economics" / f"{ECON_ID}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(econ.model_dump_json())


def config(**kw: Any) -> C.ClientConfig:
    base: dict[str, Any] = {
        "client_id": CLIENT,
        "timezone": "America/New_York",
        "currency": "USD",
        "accounts": {"meta": "act_555"},
        "economics_path": f"economics/{ECON_ID}.json",
    }
    base.update(kw)
    return C.ClientConfig(**base)


def propose_ctr_prior(data_dir: Path, monkeypatch: pytest.MonkeyPatch, *, approve: bool) -> str:
    """A client CTR prior in the prior registry under ``data_dir``; the process's own
    BAYES_DATA_DIR is put back afterwards so only ``refresh`` can point the run at ``data_dir``."""
    before = os.environ["BAYES_DATA_DIR"]
    monkeypatch.setenv("BAYES_DATA_DIR", str(data_dir))
    try:
        rec = B.prior_record("ctr", "beta", {"a": 2.0, "b": 98.0}, approved=False, client_id=CLIENT)
        pid = prior_registry.propose(rec)
        if approve:
            prior_registry.approve(pid, "owner")
    finally:
        monkeypatch.setenv("BAYES_DATA_DIR", before)
    return pid


def poll_rows(pid: str, ads: dict[str, tuple[int, int]]) -> list[LiveRow]:
    out = []
    for ad, (impressions, clicks) in ads.items():
        for i in range(7):
            day = WINDOW[0] + dt.timedelta(days=i)
            out.append(
                LiveRow(
                    poll_id=pid,
                    client_id=CLIENT,
                    platform="meta",
                    entity_ids={"account": "555", "campaign": "c1", "ad_set": "s1", "ad": ad},
                    entity_names={},
                    objective=None,
                    date=day,
                    impressions=impressions,
                    clicks=clicks,
                    spend=C.Money(amount="10.00", currency="USD"),
                    conversions_reported=1.0,
                    conversions_observed=None,
                    revenue_reported=None,
                    attribution_window="7d_click_1d_view",
                )
            )
    return out


def seed_poll(
    store: FakeStore,
    ads: dict[str, tuple[int, int]] | None = None,
    *,
    started: dt.datetime = START,
) -> PollRecord:
    ads = ads or {"ad_a": (1000, 20), "ad_b": (1000, 35)}
    pid = "poll_" + hashlib.sha256(f"{CLIENT}|meta|{started.isoformat()}".encode()).hexdigest()[:8]
    rec = PollRecord(
        poll_id=pid,
        client_id=CLIENT,
        platform="meta",
        account_id="act_555",
        started_at=started,
        finished_at=started + dt.timedelta(seconds=5),
        window=WINDOW,
        status="ok",
        error=None,
        pull_id="pull_meta_00000001",
        n_rows=7 * len(ads),
        n_quarantined=0,
        empty_account=False,
        timezone="America/New_York",
        currency="USD",
        account={"currency": "USD"},
        recording_dir=None,
    )
    store.begin_poll(rec)
    store.finish_poll(rec, poll_rows(pid, ads))
    return rec


class Env:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.config_root = tmp_path / "configs"
        self.config_root.mkdir()
        self.data_dir = tmp_path / "engine_data"
        self.data_dir.mkdir()
        self.store = FakeStore()
        self.clock = FixedClock(dt.datetime(2026, 11, 7, 18, 0, 0, 654321, tzinfo=UTC))
        self.monkeypatch = monkeypatch

    def run(self, cfg: C.ClientConfig, poll_rec: PollRecord) -> Any:
        return refresh(
            cfg,
            poll_rec,
            self.store,
            self.clock,
            data_dir=self.data_dir,
            config_root=self.config_root,
        )

    def snapshot(self, run_id: str) -> pipeline.RunSnapshot:
        self.monkeypatch.setenv("BAYES_DATA_DIR", str(self.data_dir))
        try:
            return pipeline.load_snapshot(run_id)
        finally:
            self.monkeypatch.setenv("BAYES_DATA_DIR", self.iso)

    iso = ""


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    e = Env(tmp_path, monkeypatch)
    e.iso = os.environ["BAYES_DATA_DIR"]
    return e


# ------------------------------------------------------------------ ran


def test_L4_approved_economics_and_prior_run_ctr_for_each_ad(env: Env) -> None:
    write_economics(env.config_root)
    prior_id = propose_ctr_prior(env.data_dir, env.monkeypatch, approve=True)
    cfg = config(priors={"ctr": prior_id})
    poll_rec = seed_poll(env.store)
    rec = env.run(cfg, poll_rec)
    assert rec.status == "ran", rec.reason  # L4 check 1
    assert rec.run_id and rec.run_id.startswith("run_")  # L4 C3: the record carries the run id
    assert rec.reason is None or rec.reason == ""
    assert rec.poll_id == poll_rec.poll_id and rec.client_id == CLIENT
    assert rec.at == env.clock.now()
    want = hashlib.sha256(f"{poll_rec.poll_id}|{rec.at.isoformat()}".encode()).hexdigest()[:8]
    assert rec.refresh_id == f"lv_{want}"  # L4 §2
    assert env.store.latest_refresh(CLIENT) == rec  # L4 C3: stored
    assert os.environ["BAYES_DATA_DIR"] == env.iso  # L4 C1: the context restores the variable

    snap = env.snapshot(rec.run_id)  # the snapshot is under data_dir, not under the process's own
    assert snap.run_id == rec.run_id
    assert snap.synthetic is False  # L4 C1
    assert snap.metric == "ctr"  # L4 C4
    assert snap.economics_id == ECON_ID  # L4 C1: the stem of economics_path
    assert snap.window == WINDOW  # L4 C1: the poll's window
    assert snap.horizon.unit == "impressions"  # L4 C1: the default CTR horizon
    assert snap.priors["ctr"] == prior_id  # L4 C1: priors=config.priors reached the pipeline
    ctr = [q for q in snap.quantities if q.name == "ctr"]
    assert sorted(q.scope.ids["ad"] for q in ctr) == ["ad_a", "ad_b"]  # L4 check 1: one per ad
    assert sorted(snap.variants.values()) == ["ad_a", "ad_b"]  # L4 C1: variants are the poll's ads
    assert sorted(snap.variants) == sorted(snap.variants.values())  # L4 C1: entity_map ad -> ad


def test_L4_two_ok_polls_give_two_refreshes(env: Env) -> None:
    write_economics(env.config_root)
    prior_id = propose_ctr_prior(env.data_dir, env.monkeypatch, approve=True)
    cfg = config(priors={"ctr": prior_id})
    first = seed_poll(env.store, started=START)
    r1 = env.run(cfg, first)
    env.clock.advance(hours=1)
    second = seed_poll(
        env.store,
        {"ad_a": (1100, 25), "ad_b": (1100, 30)},
        started=START + dt.timedelta(hours=1),
    )
    r2 = env.run(cfg, second)
    assert r1.status == "ran" and r2.status == "ran", (r1.reason, r2.reason)
    both = env.store.refreshes(CLIENT)
    assert len(both) == 2  # L4 check 6, C3: one refresh per ok poll
    assert {r.poll_id for r in both} == {first.poll_id, second.poll_id}
    assert r1.refresh_id != r2.refresh_id
    latest = env.store.latest_refresh(CLIENT)
    assert latest is not None and latest.poll_id == second.poll_id


# ------------------------------------------------------------------ skipped


def test_L4_no_loss_tolerance_is_skipped_with_the_reason(env: Env) -> None:
    write_economics(env.config_root, loss_tolerance=None)
    prior_id = propose_ctr_prior(env.data_dir, env.monkeypatch, approve=True)
    rec = env.run(config(priors={"ctr": prior_id}), seed_poll(env.store))
    assert rec.status == "skipped"  # L4 check 2
    assert rec.reason and "no loss tolerance set" in rec.reason  # L4 check 2, C2
    assert rec.run_id is None
    assert env.store.latest_refresh(CLIENT) == rec


def test_L4_unapproved_prior_is_skipped_with_the_g8_text(env: Env) -> None:
    write_economics(env.config_root)
    prior_id = propose_ctr_prior(env.data_dir, env.monkeypatch, approve=False)
    rec = env.run(config(priors={"ctr": prior_id}), seed_poll(env.store))
    assert rec.status == "skipped"  # L4 check 3, C2: any GateFailure
    assert rec.reason and "not approved" in rec.reason  # L4 check 3: the G8 reason
    assert rec.run_id is None


def test_L4_one_ad_is_skipped(env: Env) -> None:
    write_economics(env.config_root)
    rec = env.run(config(), seed_poll(env.store, {"ad_a": (1000, 20)}))
    assert rec.status == "skipped"  # L4 check 5, C2
    assert rec.reason == ONE_AD == "one ad, nothing to compare"
    assert rec.run_id is None
    assert env.store.latest_refresh(CLIENT) == rec


def test_L4_no_economics_path_is_skipped(env: Env) -> None:
    rec = env.run(config(economics_path=None), seed_poll(env.store))
    assert rec.status == "skipped"  # L4 C2
    assert rec.reason == NO_ECONOMICS_PATH == "no economics file in the client config"
    assert env.store.latest_refresh(CLIENT) == rec


# ------------------------------------------------------------------ failed


def test_L4_a_raising_pipeline_is_failed_and_never_raises(env: Env) -> None:
    write_economics(env.config_root)
    prior_id = propose_ctr_prior(env.data_dir, env.monkeypatch, approve=True)

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("boom")

    # the one monkeypatch the spec's check names; patch where a caller could have bound it, too
    env.monkeypatch.setattr(pipeline, "execute", boom)
    if hasattr(refresh_mod, "execute"):
        env.monkeypatch.setattr(refresh_mod, "execute", boom)
    rec = env.run(config(priors={"ctr": prior_id}), seed_poll(env.store))
    assert rec.status == "failed"  # L4 check 4, C2
    assert rec.reason == "RuntimeError: boom"  # L4 C2: "<ExceptionClass>: <message>"
    assert rec.run_id is None
    assert env.store.latest_refresh(CLIENT) == rec
    assert os.environ["BAYES_DATA_DIR"] == env.iso  # L4 C1: restored even when the run raises
