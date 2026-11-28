"""Shared fixtures for the L12 acceptance set (live view spec v0.2, L12 items 1 to 7 and L12.1 to
L12.6; D55).

Everything lives under the test's ``tmp_path``. ``L12Env`` lays the folders out the way
``scripts/export_history.py`` expects them under its ``LIVE``: the live store is a real
``SqliteStore`` at ``tmp_path / "live" / "live.sqlite"`` and the engine's data dir is
``tmp_path / "live" / "engine"``, which ``BAYES_DATA_DIR`` names for the whole test. The export's
``runs()`` is loaded from the script and run with its module-level ``LIVE`` pointed at
``tmp_path / "live"``. Nothing reads ``data/live/``, ``notebook/`` or ``configs/``.

Dates: the account is in America/New_York and every poll ends on ``END`` (7 November 2026). A
28-day poll's window is ``W28`` (11 October to 7 November); its analysis window, the last seven
days, is ``W7`` (1 to 7 November). "Old" days are the 21 days of ``W28`` before ``W7``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import sqlite3
from collections.abc import Iterable, Iterator
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from bayesian_marketing import core as C
from bayesian_marketing import pipeline
from bayesian_marketing.decision import run_record
from bayesian_marketing.live.contracts import LiveRow, PollRecord, RefreshRecord
from bayesian_marketing.live.refresh import data_dir_env, refresh
from bayesian_marketing.live.store import SqliteStore
from bayesian_marketing.prior_registry import registry as prior_registry
from tests.fakes import builders as B
from tests.fakes.live import FixedClock

REPO = Path(__file__).resolve().parents[2]
EXPORT_SCRIPT = REPO / "scripts" / "export_history.py"
UTC = dt.UTC
CLIENT = "l12_client"
TZ = "America/New_York"
ACCOUNT = "act_1212"
ECON_ID = "l12_econ"
PREFIX = "bayes-rows-c1:"

END = dt.date(2026, 11, 7)
T0 = dt.datetime(2026, 11, 7, 17, 30, 0, 123456, tzinfo=UTC)  # 12:30 in New York, on END


def window(days: int, end: dt.date = END) -> tuple[dt.date, dt.date]:
    return end - dt.timedelta(days=days - 1), end


def days_of(w: tuple[dt.date, dt.date]) -> list[dt.date]:
    return [w[0] + dt.timedelta(days=i) for i in range((w[1] - w[0]).days + 1)]


W28 = window(28)
W7 = window(7)
DAYS28 = days_of(W28)
DAYS7 = days_of(W7)
OLD = [d for d in DAYS28 if d < W7[0]]  # the 21 days before the analysis window
assert len(OLD) == 21 and len(DAYS7) == 7

WIN_LABEL = "7d_click_1d_view"  # the attribution label on the analysis window's rows
OLD_LABEL = "1d_view_7d_click_1d_ev"  # a different label on old rows; sorts before WIN_LABEL
assert OLD_LABEL < WIN_LABEL

NAMES = {
    "ad_a": {"account": "Acme", "campaign": "Autumn", "ad_set": "Set 1", "ad": "Autumn A"},
    "ad_b": {"account": "Acme", "campaign": "Autumn", "ad_set": "Set 1", "ad": "Autumn B"},
    "ad_x": {"account": "Acme", "campaign": "Autumn", "ad_set": "Set 9", "ad": "Old extra"},
}
ADSET = {"ad_a": "s1", "ad_b": "s1", "ad_x": "s9"}
WIN_CLICKS = {"ad_a": 20, "ad_b": 35, "ad_x": 50}


def poll_id(started: dt.datetime, client_id: str = CLIENT) -> str:
    return (
        "poll_" + hashlib.sha256(f"{client_id}|meta|{started.isoformat()}".encode()).hexdigest()[:8]
    )


def live_row(
    pid: str,
    ad: str,
    day: dt.date,
    *,
    clicks: int | None = None,
    impressions: int | None = None,
    spend: str | None = None,
    attribution: str | None = None,
    currency: str = "USD",
    observed: int | None = 2,
    reported: float | None = 1.0,
    client_id: str = CLIENT,
) -> LiveRow:
    """A row for ``ad`` on ``day``. Defaults differ by period: a window day has 1,000
    impressions, ``WIN_CLICKS[ad]`` clicks, 10.00 spend and ``WIN_LABEL``; an old day has 500
    impressions, 5 clicks, 10.00 spend and ``OLD_LABEL``, so an old row priced into the horizon,
    counted into a sum or read for a label shows."""
    old = day < W7[0]
    return LiveRow(
        poll_id=pid,
        client_id=client_id,
        platform="meta",
        entity_ids={"account": "1212", "campaign": "c1", "ad_set": ADSET[ad], "ad": ad},
        entity_names=dict(NAMES[ad]),
        objective="OUTCOME_SALES",
        date=day,
        impressions=impressions if impressions is not None else (500 if old else 1000),
        clicks=clicks if clicks is not None else (5 if old else WIN_CLICKS[ad]),
        spend=C.Money(amount=Decimal(spend or "10.00"), currency=currency),
        conversions_reported=reported,
        conversions_observed=observed,
        revenue_reported=None,
        attribution_window=attribution or (OLD_LABEL if old else WIN_LABEL),
    )


def poll_record(
    started: dt.datetime,
    w: tuple[dt.date, dt.date],
    *,
    pid: str | None = None,
    n_rows: int = 0,
    client_id: str = CLIENT,
) -> PollRecord:
    pid = pid or poll_id(started, client_id)
    return PollRecord(
        poll_id=pid,
        client_id=client_id,
        platform="meta",
        account_id=ACCOUNT,
        started_at=started,
        finished_at=started + dt.timedelta(seconds=5),
        window=w,
        status="ok",
        error=None,
        pull_id=f"pull_meta_{pid[5:]}",
        n_rows=n_rows,
        n_quarantined=0,
        empty_account=False,
        timezone=TZ,
        currency="USD",
        account={"currency": "USD", "timezone_name": TZ},
        recording_dir=None,
    )


def add_poll(
    store: Any,
    started: dt.datetime,
    w: tuple[dt.date, dt.date],
    rows: Iterable[LiveRow],
    *,
    pid: str | None = None,
) -> PollRecord:
    """A finished ok poll; ``rows`` are given with any poll id and stored under this poll's."""
    pid = pid or poll_id(started)
    stored = [r.model_copy(update={"poll_id": pid}) for r in rows]
    rec = poll_record(started, w, pid=pid, n_rows=len(stored))
    store.begin_poll(rec)
    store.finish_poll(rec, stored)
    return rec


def window_rows(pid: str = "poll_x", ads: tuple[str, ...] = ("ad_a", "ad_b"), **kw: Any) -> list:
    """The analysis window's rows: ``ads`` on each of the last seven days."""
    return [live_row(pid, ad, d, **kw) for d in DAYS7 for ad in ads]


def old_rows(
    pid: str = "poll_x", ads: tuple[str, ...] = ("ad_a", "ad_b", "ad_x"), **kw: Any
) -> list:
    """The 21 old days' rows: ``ads`` on each, ``ad_x`` among them by default (an extra ad that
    is not in the analysis window)."""
    return [live_row(pid, ad, d, **kw) for d in OLD for ad in ads]


# ------------------------------------------------------------------ the environment


class L12Env:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tmp = tmp_path
        self.monkeypatch = monkeypatch
        self.live = tmp_path / "live"
        self.data_dir = self.live / "engine"
        self.data_dir.mkdir(parents=True)
        monkeypatch.setenv("BAYES_DATA_DIR", str(self.data_dir))
        monkeypatch.setenv("BAYES_LIVE_DIR", str(self.live))
        monkeypatch.setenv("BAYES_NOTEBOOK_DIR", str(tmp_path / "notebook"))
        self.config_root = tmp_path / "configs"
        self.config_root.mkdir()
        self.store_path = self.live / "live.sqlite"
        self.store = SqliteStore.open(self.store_path)
        self.clock = FixedClock(T0 + dt.timedelta(minutes=10))
        self.cfg: C.ClientConfig | None = None

    def client(self, *, test_budget: Any = None, approve_at: dt.datetime | None = None) -> Any:
        """Approved economics (with ``test_budget`` when given) and an approved client CTR
        prior, as test_L4 and the J2 fixtures build them. ``approve_at`` pins the prior
        registry's clock for the proposal and approval."""
        econ = B.economics(
            economics_id=ECON_ID,
            client_id=CLIENT,
            loss_tolerance=150,
            fixed_price=795,
            variable_cost=235,
            test_budget=test_budget,
            approved=True,
        )
        path = self.config_root / "economics" / f"{ECON_ID}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(econ.model_dump_json())
        if approve_at is not None:
            self.monkeypatch.setattr(prior_registry, "utcnow", lambda: approve_at)
        rec = B.prior_record("ctr", "beta", {"a": 2.0, "b": 98.0}, approved=False, client_id=CLIENT)
        pid = prior_registry.propose(rec)
        prior_registry.approve(pid, "owner")
        self.cfg = C.ClientConfig(
            client_id=CLIENT,
            timezone=TZ,
            currency="USD",
            accounts={"meta": ACCOUNT},
            economics_path=f"economics/{ECON_ID}.json",
            priors={"ctr": pid},
        )
        return econ

    def refresh(self, poll: PollRecord, store: Any = None) -> RefreshRecord:
        assert self.cfg is not None, "call client() first"
        self.clock.at = poll.started_at + dt.timedelta(minutes=10)
        return refresh(
            self.cfg,
            poll,
            store if store is not None else self.store,
            self.clock,
            data_dir=self.data_dir,
            config_root=self.config_root,
        )

    def snapshot(self, run_id: str) -> pipeline.RunSnapshot:
        with data_dir_env(self.data_dir):
            return pipeline.load_snapshot(run_id)

    def snapshot_file(self, run_id: str) -> Path:
        return self.data_dir / "runs" / f"{run_id}.json"

    def record(self, run_id: str) -> C.RunRecord:
        got = run_record.read("RunRecord", run_id=run_id)
        assert len(got) == 1, got
        return got[0]  # type: ignore[return-value]

    def capture_execute(self) -> list[dict[str, Any]]:
        """Wrap ``pipeline.execute`` (the real one still runs); each call's manifest, request,
        keywords and context are kept."""
        calls: list[dict[str, Any]] = []
        real = pipeline.execute

        def spy(*args: Any, **kwargs: Any) -> Any:
            manifest = kwargs.get("manifest", args[0] if args else None)
            request = kwargs.get("request", args[1] if len(args) > 1 else None)
            call = {"manifest": manifest, "request": request, "kwargs": dict(kwargs)}
            calls.append(call)
            call["ctx"] = ctx = real(*args, **kwargs)
            return ctx

        self.monkeypatch.setattr(pipeline, "execute", spy)
        return calls

    # the export

    def export_module(self) -> ModuleType:
        """``scripts/export_history.py`` loaded fresh, its ``LIVE`` pointed at this test's
        ``live`` folder (the run record and run files are under ``LIVE / "engine"``)."""
        spec = importlib.util.spec_from_file_location("export_history_l12", EXPORT_SCRIPT)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.monkeypatch.setattr(mod, "LIVE", self.live)
        return mod

    def export_runs(self, mod: ModuleType | None = None) -> dict[str, dict[str, Any]]:
        """A fresh export's ``runs.jsonl`` rows for the client, by run id, as ``main`` builds
        them: ``versioned`` over the store, then ``runs()``."""
        mod = mod or self.export_module()
        conn = sqlite3.connect(f"{self.store_path.resolve().as_uri()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            ro = SqliteStore.open(self.store_path, read_only=True)
            try:
                rows, seen, _ = mod.versioned(ro, CLIENT)
            finally:
                ro.close()
            out = mod.runs(conn, CLIENT, TZ, rows, seen)
        finally:
            conn.close()
        return {r["key"]: r for r in out}


def make_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[L12Env]:
    e = L12Env(tmp_path, monkeypatch)
    yield e
    e.store.close()


def posteriors(snap: pipeline.RunSnapshot) -> dict[tuple[str, str | None], Any]:
    """Each quantity's estimate by (name, ad), without ``samples_path`` (which names the run)."""
    out: dict[tuple[str, str | None], Any] = {}
    for q in snap.quantities:
        key = (q.name, q.scope.ids.get("ad"))
        est = q.estimate.model_dump(mode="json")
        out[key] = {k: est.get(k) for k in ("kind", "family", "params", "n_samples", "summary")}
    return out


# ------------------------------------------------------------------ a multi-page 28-day Meta pull

PAGE = 25  # L12.5: Meta gives 25 rows a page
META_ADS = ("m1", "m2", "m3", "m4")


def meta_rows_28(days: list[dt.date]) -> list[dict[str, Any]]:
    """Four ads on each of ``days`` in the shape of ``tests.fakes.meta_api._meta_row``, named,
    with clicks that differ by day so every row is told apart."""
    from tests.fakes.meta_api import _meta_row

    out = []
    for i, day in enumerate(days):
        for j, ad in enumerate(META_ADS):
            out.append(
                _meta_row(
                    ad,
                    day.isoformat(),
                    ad_name=f"Ad {ad}",
                    inline_link_clicks=str(10 + i + j),
                    actions=[{"action_type": "link_click", "value": str(10 + i + j)}],
                )
            )
    return out


def paging_handler(rows: list[dict[str, Any]]) -> Any:
    """A Graph API stand-in that pages the insights in ``PAGE`` rows a page, each page's
    ``paging.next`` naming the following cursor (F2 §5), the account node as ``meta_api``'s."""
    import json as _json_mod
    from urllib.parse import parse_qs, urlsplit

    from bayesian_marketing.data_contract.connectors import meta
    from tests.fakes.meta_api import ACCOUNT, META_TOKEN, _json

    def handle(req: Any) -> Any:
        url = urlsplit(str(req.url))
        q = parse_qs(url.query)
        assert q["access_token"] == [META_TOKEN]
        if url.path.endswith("/act_111"):
            return _json(dict(ACCOUNT))
        assert url.path.endswith("/act_111/insights"), url.path
        if "after" not in q:
            tr = _json_mod.loads(q["time_range"][0])
            assert (tr["since"], tr["until"]) == (rows[0]["date_start"], rows[-1]["date_start"]), tr
            k = 0
        else:
            k = int(q["after"][0].removeprefix("PAGE"))
        page = rows[k * PAGE : (k + 1) * PAGE]
        body: dict[str, Any] = {"data": page, "paging": {"cursors": {"after": f"PAGE{k + 1}"}}}
        if (k + 1) * PAGE < len(rows):
            body["paging"]["next"] = (
                f"{meta.GRAPH}act_111/insights?access_token={META_TOKEN}&after=PAGE{k + 1}"
            )
        return _json(body)

    return handle
