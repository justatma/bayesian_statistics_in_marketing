"""Fixture runs and notebook releases for the J4 acceptance set (Brain join spec v0.3, J4).

Runs are built as in test_L5 and test_J5: ``refresh`` against ``FakeStore`` with real economics,
a lead client config (``conversion_event = {"meta": LEAD_EVENT}``) written into a tmp
``BAYES_CONFIG_DIR``. The only difference from test_L5's ``seed_poll`` is that the poll's start,
window and ad ids are parameters, so a second, newer run can be made for the staleness cases (p).

Entity names: a ``RunSnapshot`` carries no entity names (its fields are fixed, ``extra="forbid"``,
and ``refresh`` passes ``LiveRow.entity_names`` only into the pull, not the snapshot). So the run's
ads are named here by id: the ad the spec calls "IMG3_TXT1" has the ad id ``IMG3_TXT1``, which a
sentence names by id. The ad "IMG2_TXT1 <en dash> Updated." has a numeric id, and its name exists
only in a notebook ``meta_object`` source, so check (j) exercises name matching through a notebook
source.

A quantity's summary or status is set for a case by editing the saved snapshot file, the way
test_J5's ``with_cpa_q50`` does.

Releases are written with ``notebook.release.write_release`` into ``tmp_path / "notebook"``, with
``BAYES_NOTEBOOK_DIR`` pointed there. ``created_at`` is pinned per release (``write_release``
reads ``datetime.now``), so an older and a newer release differ in it as well as in day and parent.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from bayesian_marketing import core as C
from bayesian_marketing.atmaos import socket as sock
from bayesian_marketing.live.contracts import LiveRow, PollRecord
from bayesian_marketing.live.refresh import refresh
from bayesian_marketing.notebook import release as nb_release
from tests.acceptance.test_J5 import LEAD, J5Env
from tests.acceptance.test_L5 import config
from tests.fakes.live import FakeStore, FixedClock

UTC = dt.UTC
CLIENT = "lead_client"  # test_L5's client, marked lead by its config
OTHER = "other_client"

IMG3 = "IMG3_TXT1"  # ad id in the run (the run holds no names)
IMG2_ID = "120253899504590527"
IMG2_NAME = "IMG2_TXT1 \u2013 Updated."  # with an en dash; only in a notebook source

START_OLD = dt.datetime(2026, 11, 7, 17, 30, tzinfo=UTC)
WINDOW_OLD = (dt.date(2026, 11, 1), dt.date(2026, 11, 7))
START_NEW = dt.datetime(2026, 11, 8, 17, 30, tzinfo=UTC)
WINDOW_NEW = (dt.date(2026, 11, 2), dt.date(2026, 11, 8))

ENGINE_VERSION = "bayesian-marketing 0.2.0.dev0"

# Notebook entry ids (stable across releases, ``nbe_<client_id>_<nnnn>``).
E_LIMIT = f"nbe_{CLIENT}_0001"  # observed account_spending_limit 1500 USD
E_BUDGET = f"nbe_{CLIENT}_0002"  # observed lifetime_budget 1500 USD
E_SPENT = f"nbe_{CLIENT}_0003"  # observed amount_spent 750 USD
E_PBEST = f"nbe_{CLIENT}_0004"  # estimated p_best 0.621 for IMG3_TXT1
E_AD2 = f"nbe_{CLIENT}_0005"  # event naming the ad "IMG2_TXT1 <en dash> Updated." (no quantities)
E_OTHER = f"nbe_{OTHER}_0001"


# ------------------------------------------------------------------ runs


def seed_poll(
    store: FakeStore,
    start: dt.datetime,
    window: tuple[dt.date, dt.date],
    ads: dict[str, tuple[int, int]],
    pull_n: int,
) -> PollRecord:
    """test_L5's ``seed_poll`` with the start, window and ads as parameters."""
    pid = "poll_" + hashlib.sha256(f"{CLIENT}|meta|{start.isoformat()}".encode()).hexdigest()[:8]
    days = (window[1] - window[0]).days + 1
    rows = [
        LiveRow(
            poll_id=pid,
            client_id=CLIENT,
            platform="meta",
            entity_ids={"account": "555", "campaign": "c1", "ad_set": "s1", "ad": ad},
            entity_names={},
            objective="OUTCOME_LEADS",
            date=window[0] + dt.timedelta(days=i),
            impressions=imp,
            clicks=clk,
            spend=C.Money(amount="10.00", currency="USD"),
            conversions_reported=float(clk // 4),
            conversions_observed=None,
            revenue_reported=None,
            attribution_window="7d_click_1d_view",
        )
        for ad, (imp, clk) in ads.items()
        for i in range(days)
    ]
    rec = PollRecord(
        poll_id=pid,
        client_id=CLIENT,
        platform="meta",
        account_id="act_555",
        started_at=start,
        finished_at=start + dt.timedelta(seconds=5),
        window=window,
        status="ok",
        error=None,
        pull_id=f"pull_meta_{pull_n:08d}",
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


ADS = {IMG3: (1000, 40), IMG2_ID: (1000, 60)}


# ------------------------------------------------------------------ notebook


def _source(kind: str, ref: dict[str, Any], content: dict[str, Any]) -> dict[str, Any]:
    return nb_release.source(kind, ref, content)


def sources() -> dict[str, dict[str, Any]]:
    return {
        "account": _source(
            "meta_object",
            {
                "object_type": "account",
                "object_id": "act_555",
                "read_at": "2026-11-20T15:00:00+00:00",
            },
            {"id": "act_555", "currency": "USD", "spend_cap": "150000", "amount_spent": "75000"},
        ),
        "campaign": _source(
            "meta_object",
            {"object_type": "campaign", "object_id": "c1", "read_at": "2026-11-20T15:00:00+00:00"},
            {"id": "c1", "lifetime_budget": "150000"},
        ),
        "ad2": _source(
            "meta_object",
            {"object_type": "ad", "object_id": IMG2_ID, "read_at": "2026-11-20T15:00:00+00:00"},
            {"id": IMG2_ID, "name": IMG2_NAME, "status": "ACTIVE"},
        ),
        "run": _source(
            "engine_run",
            {"run_id": "run_0000f1x7"},
            {"run_id": "run_0000f1x7", "comparison": {"p_best": {IMG3: 0.621}}},
        ),
    }


def _entry(eid: str, kind: str, statement: str, method: str, src: str, **kw: Any) -> dict:
    srcs = sources()
    e = {
        "entry_id": eid,
        "kind": kind,
        "statement": statement,
        "method": method,
        "date": "2026-11-20",
        "as_of": "2026-11-20T15:00:00+00:00",
        "basis": [{"source_id": srcs[src]["source_id"], "role": "primary"}],
    }
    e.update(kw)
    return e


def entries(limit: float = 1500) -> list[dict[str, Any]]:
    """Fresh entry dicts (``write_release`` fills defaults in place)."""
    return [
        _entry(
            E_LIMIT,
            "constraint",
            "The account spending limit is $1,500.",
            "observed",
            "account",
            quantities=[{"name": "account_spending_limit", "value": limit, "unit": "USD"}],
            tags=["spending_limit"],
        ),
        _entry(
            E_BUDGET,
            "figure",
            "The lifetime budget is $1,500.",
            "observed",
            "campaign",
            quantities=[{"name": "lifetime_budget", "value": 1500, "unit": "USD"}],
        ),
        _entry(
            E_SPENT,
            "figure",
            "The amount spent to date is $750.",
            "observed",
            "account",
            quantities=[{"name": "amount_spent", "value": 750, "unit": "USD"}],
        ),
        _entry(
            E_PBEST,
            "finding",
            f"{IMG3} has a 0.621 chance of being the best ad.",
            "estimated",
            "run",
            quantities=[
                {
                    "name": "p_best",
                    "value": 0.621,
                    "unit": "probability",
                    "p05": 0.48,
                    "p50": 0.621,
                    "p95": 0.75,
                    "level": 0.9,
                }
            ],
        ),
        _entry(E_AD2, "event", f"The ad {IMG2_NAME} was published.", "observed", "ad2"),
    ]


class _FixedNow(dt.datetime):
    at: dt.datetime = dt.datetime(2026, 11, 20, 15, 0, tzinfo=UTC)

    @classmethod
    def now(cls, tz: Any = None) -> dt.datetime:  # type: ignore[override]
        return cls.at


def write_nb(
    root: Path,
    client_id: str,
    day: str,
    created_at: dt.datetime,
    entry_list: list[dict[str, Any]],
    source_list: list[dict[str, Any]],
    parent: str | None = None,
) -> str:
    """``write_release`` with ``created_at`` pinned; returns the release id."""
    fixed = type("FixedNow", (_FixedNow,), {"at": created_at})
    with mock.patch.object(nb_release, "datetime", fixed):
        folder = nb_release.write_release(
            root,
            client_id,
            entry_list,
            source_list,
            parent_release_id=parent,
            engine_version=ENGINE_VERSION,
            day=day,
        )
    nb_release.verify(folder)
    return folder.name


# ------------------------------------------------------------------ the environment


class J4Env(J5Env):
    """test_J5's env, plus a notebook root under ``BAYES_NOTEBOOK_DIR`` and runs at chosen times."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        super().__init__(tmp_path, monkeypatch)
        self.nb_root = tmp_path / "notebook"
        self.nb_root.mkdir()
        monkeypatch.setenv("BAYES_NOTEBOOK_DIR", str(self.nb_root))
        self.write_config(config(**LEAD))
        self._pulls = 10

    # runs

    def lead_run_at(self, start: dt.datetime, window: tuple[dt.date, dt.date]) -> str:
        self._pulls += 1
        self.clock = FixedClock(start + dt.timedelta(minutes=30))
        rec = refresh(
            config(**LEAD),
            seed_poll(self.store, start, window, ADS, self._pulls),
            self.store,
            self.clock,
            data_dir=self.data_dir,
            config_root=self.config_root,
        )
        assert rec.status == "ran", rec.reason
        return rec.run_id

    def old_and_new_runs(self) -> tuple[str, str]:
        old = self.lead_run_at(START_OLD, WINDOW_OLD)
        new = self.lead_run_at(START_NEW, WINDOW_NEW)
        assert old != new
        t_old = START_OLD.timestamp() + 1800
        os.utime(self.snapshot_file(old), (t_old, t_old))
        t_new = START_NEW.timestamp() + 1800
        os.utime(self.snapshot_file(new), (t_new, t_new))
        return old, new

    def quantity(self, run_id: str, ad: str, name: str) -> dict[str, Any]:
        data = json.loads(self.snapshot_file(run_id).read_text())
        hits = [
            q for q in data["quantities"] if q["name"] == name and q["scope"]["ids"] == {"ad": ad}
        ]
        assert len(hits) == 1, hits
        return hits[0]

    def set_quantity(
        self, run_id: str, ad: str, name: str, *, status: str | None = None, **summary: float
    ) -> str:
        """Edit one quantity's summary values and status in the saved snapshot; returns its id."""
        qid: list[str] = []

        def patch(d: dict[str, Any]) -> None:
            hits = [
                q for q in d["quantities"] if q["name"] == name and q["scope"]["ids"] == {"ad": ad}
            ]
            assert len(hits) == 1, hits
            hits[0]["estimate"]["summary"].update(summary)
            if status is not None:
                hits[0]["feasibility"]["status"] = status
                if status == "below_floor":
                    hits[0]["feasibility"]["required"] = 4000.0
            qid.append(hits[0]["quantity_id"])

        mtime = self.snapshot_file(run_id).stat().st_mtime
        self.rewrite(run_id, patch)
        os.utime(self.snapshot_file(run_id), (mtime, mtime))
        self.snapshot(run_id)  # the edited file still loads
        return qid[0]

    def ctr_44(self, run_id: str, status: str = "marginal") -> str:
        """IMG3_TXT1's ctr: median and mean 4.4%, q05 4.0%, q95 4.7%."""
        return self.set_quantity(
            run_id, IMG3, "ctr", status=status, q50=0.044, mean=0.044, q05=0.040, q95=0.047
        )

    # notebook

    def release(self, entry_list: list[dict[str, Any]] | None = None, **kw: Any) -> str:
        kw.setdefault("day", "20261120")
        kw.setdefault("created_at", dt.datetime(2026, 11, 20, 15, 0, tzinfo=UTC))
        return write_nb(
            self.nb_root,
            kw.pop("client_id", CLIENT),
            kw.pop("day"),
            kw.pop("created_at"),
            entry_list if entry_list is not None else entries(),
            list(sources().values()),
            parent=kw.pop("parent", None),
        )

    def release_folder(self, release_id: str, client_id: str = CLIENT) -> Path:
        return self.nb_root / client_id / "releases" / release_id

    # the call

    def figures(self, text: str, refs: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
        """``socket.check_client_figures`` with ``BAYES_DATA_DIR`` at the runs' data dir."""
        return self.in_data(lambda: sock.check_client_figures(text, refs, **kw))


def run_ref(run_id: str) -> dict[str, Any]:
    return {"kind": "run", "run_id": run_id}


def entry_ref(release_id: str, entry_id: str) -> dict[str, Any]:
    return {"kind": "notebook_entry", "release_id": release_id, "entry_id": entry_id}


def claim_ref(claim_id: str, **engine_item: str) -> dict[str, Any]:
    return {"kind": "claim", "claim_id": claim_id, "engine_item": dict(engine_item)}
