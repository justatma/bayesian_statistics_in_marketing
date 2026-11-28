"""L5: a lead is counted, never valued (decision D46, D33, D41).

``refresh`` runs against ``FakeStore`` in a temp config root with ``synthetic=False`` and real
economics, as in test_L4. ``pipeline.execute`` is wrapped (never replaced) to capture what
``refresh`` hands it, so the same manifest and pulls can be run again with another metric.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from bayesian_marketing import core as C
from bayesian_marketing import pipeline
from bayesian_marketing.live.contracts import LiveRow, PollRecord
from bayesian_marketing.live.refresh import refresh
from tests.fakes import builders as B
from tests.fakes.live import FakeStore, FixedClock

pytestmark = pytest.mark.piece("L5")

UTC = dt.UTC
CLIENT = "lead_client"
ECON_ID = "lead_econ"
START = dt.datetime(2026, 11, 7, 17, 30, 0, 123456, tzinfo=UTC)
WINDOW = (dt.date(2026, 11, 1), dt.date(2026, 11, 7))
LEAD_EVENT = "offsite_conversion.fb_pixel_lead"
VALUED = ("aov", "roas", "contribution_per_click")
LEAD_TEXT = "a lead is counted, never valued (D33)"


def write_economics(config_root: Path) -> None:
    econ = B.economics(
        economics_id=ECON_ID,
        client_id=CLIENT,
        loss_tolerance=150,
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


def seed_poll(store: FakeStore) -> PollRecord:
    ads = {"ad_a": (1000, 40), "ad_b": (1000, 60)}
    pid = "poll_" + hashlib.sha256(f"{CLIENT}|meta|{START.isoformat()}".encode()).hexdigest()[:8]
    rows = [
        LiveRow(
            poll_id=pid,
            client_id=CLIENT,
            platform="meta",
            entity_ids={"account": "555", "campaign": "c1", "ad_set": "s1", "ad": ad},
            entity_names={},
            objective="OUTCOME_LEADS",
            date=WINDOW[0] + dt.timedelta(days=i),
            impressions=imp,
            clicks=clk,
            spend=C.Money(amount="10.00", currency="USD"),
            conversions_reported=float(clk // 4),
            conversions_observed=None,
            revenue_reported=None,
            attribution_window="7d_click_1d_view",
        )
        for ad, (imp, clk) in ads.items()
        for i in range(7)
    ]
    rec = PollRecord(
        poll_id=pid,
        client_id=CLIENT,
        platform="meta",
        account_id="act_555",
        started_at=START,
        finished_at=START + dt.timedelta(seconds=5),
        window=WINDOW,
        status="ok",
        error=None,
        pull_id="pull_meta_00000002",
        n_rows=len(rows),
        n_quarantined=0,
        empty_account=False,
        timezone="America/New_York",
        currency="USD",
        account={"currency": "USD"},
        recording_dir=None,
    )
    store.begin_poll(rec)
    store.finish_poll(rec, rows)
    return rec


class Env:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.config_root = tmp_path / "configs"
        self.config_root.mkdir()
        self.data_dir = tmp_path / "engine_data"
        self.data_dir.mkdir()
        self.store = FakeStore()
        self.clock = FixedClock(dt.datetime(2026, 11, 7, 18, 0, 0, 654321, tzinfo=UTC))
        self.mp = monkeypatch
        self.iso = os.environ["BAYES_DATA_DIR"]
        self.calls: list[dict[str, Any]] = []
        real = pipeline.execute

        def capture(manifest: Any, request: Any, **kw: Any) -> Any:
            self.calls.append({"manifest": manifest, "request": request, **kw})
            return real(manifest, request, **kw)

        self.real_execute = real
        monkeypatch.setattr(pipeline, "execute", capture)
        write_economics(self.config_root)

    def run(self, cfg: C.ClientConfig) -> Any:
        return refresh(
            cfg,
            seed_poll(self.store),
            self.store,
            self.clock,
            data_dir=self.data_dir,
            config_root=self.config_root,
        )

    def in_data_dir(self) -> None:
        self.mp.setenv("BAYES_DATA_DIR", str(self.data_dir))

    def snapshot(self, run_id: str) -> pipeline.RunSnapshot:
        self.in_data_dir()
        try:
            return pipeline.load_snapshot(run_id)
        finally:
            self.mp.setenv("BAYES_DATA_DIR", self.iso)

    def files(self) -> list[Path]:
        return sorted(p for p in self.data_dir.rglob("*") if p.is_file())


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    return Env(tmp_path, monkeypatch)


def test_L5_constant_and_request_field() -> None:
    assert pipeline.LEAD_NOT_VALUED == LEAD_TEXT  # D46 (2)
    req = dict(
        metric="ctr",
        variants=["a", "b"],
        priors={},
        window=WINDOW,
        horizon=C.Horizon(unit="impressions", amount="1000"),
    )
    assert C.CompareRequest(**req).conversion_kind == "purchase"  # D46: default unchanged
    assert C.CompareRequest(**req, conversion_kind="lead").conversion_kind == "lead"
    with pytest.raises(ValidationError):
        C.CompareRequest(**req, conversion_kind="signup")


@pytest.mark.parametrize(
    ("event", "kind"),
    [
        (LEAD_EVENT, "lead"),
        ("lead", "lead"),
        ("onsite_web_lead", "lead"),
        ("offsite_conversion.fb_pixel_purchase", "purchase"),
        (None, "purchase"),
    ],
)
def test_L5_refresh_passes_the_conversion_kind(env: Env, event: str | None, kind: str) -> None:
    cfg = config(conversion_event={"meta": event} if event else {})
    rec = env.run(cfg)
    assert rec.status == "ran", rec.reason
    assert len(env.calls) == 1
    assert env.calls[0]["request"].conversion_kind == kind  # D46: refresh sets the kind


def test_L5_lead_run_derives_no_value(env: Env) -> None:
    rec = env.run(config(conversion_event={"meta": LEAD_EVENT}))
    assert rec.status == "ran", rec.reason
    snap = env.snapshot(rec.run_id)
    names = {q.name for q in snap.quantities}
    assert not names & set(VALUED), names  # D46 (2): never derived
    for ad in ("ad_a", "ad_b"):
        got = {q.name for q in snap.quantities if q.scope.ids.get("ad") == ad}
        assert {"ctr", "cvr"} <= got, got  # D46 (4): the lead rate stays
        for name in VALUED:
            assert snap.not_estimable[ad][name] == LEAD_TEXT  # D46 (2)
    assert snap.notices.count(LEAD_TEXT) == 1  # D46 (3)
    for r in snap.recommendations:  # nothing priced from a lead reaches a recommendation
        text = r.model_dump_json()
        assert "contribution_per_click" not in text and "contribution per click" not in text


def test_L5_purchase_run_is_unchanged(env: Env) -> None:
    rec = env.run(config())
    assert rec.status == "ran", rec.reason
    snap = env.snapshot(rec.run_id)
    cpc = [q for q in snap.quantities if q.name == "contribution_per_click"]
    assert sorted(q.scope.ids["ad"] for q in cpc) == ["ad_a", "ad_b"]
    assert LEAD_TEXT not in snap.notices
    assert all(LEAD_TEXT not in v.values() for v in snap.not_estimable.values())


@pytest.mark.parametrize("metric", ["cpa", "roas", "contribution_per_click", "contribution"])
def test_L5_lead_non_rate_metric_refused_before_anything_is_written(env: Env, metric: str) -> None:
    rec = env.run(config(conversion_event={"meta": LEAD_EVENT}))
    assert rec.status == "ran", rec.reason
    call = env.calls[0]
    before = env.files()
    request = call["request"].model_copy(update={"metric": metric})
    env.in_data_dir()
    try:
        with pytest.raises(C.NotInScope) as exc:  # D46 (1)
            env.real_execute(
                call["manifest"],
                request,
                manifest_dir=call["manifest_dir"],
                pulls=call["pulls"],
            )
    finally:
        env.mp.setenv("BAYES_DATA_DIR", env.iso)
    want = pipeline.PLANNED_OBJECTIVE.format(
        metric="leads", model=pipeline.PLANNED_TARGETS["leads"]
    )
    assert str(exc.value) == want
    assert env.files() == before  # D46 (1), D38.2: no fit, save or publish


def test_L5_lead_cvr_metric_runs(env: Env) -> None:
    rec = env.run(config(conversion_event={"meta": LEAD_EVENT}))
    call = env.calls[0]
    horizon = C.Horizon(unit=pipeline.horizon_unit("cvr"), amount=call["request"].horizon.amount)
    request = call["request"].model_copy(update={"metric": "cvr", "horizon": horizon})
    env.in_data_dir()
    try:
        ctx = env.real_execute(
            call["manifest"], request, manifest_dir=call["manifest_dir"], pulls=call["pulls"]
        )
    finally:
        env.mp.setenv("BAYES_DATA_DIR", env.iso)
    assert rec.status == "ran"
    snap = env.snapshot(ctx.result.run.run_id)
    assert snap.metric == "cvr"
    assert not {q.name for q in snap.quantities} & set(VALUED)
    assert snap.notices.count(LEAD_TEXT) == 1
