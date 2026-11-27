"""Fixtures for the J4R.2 acceptance set (Brain join spec v0.4, J4R.2, "Ads that share a name").

The environment is ``j4r_fixtures.J4REnv`` (lead runs of test_L5's client built by ``refresh``
against ``FakeStore``, notebook releases under ``BAYES_NOTEBOOK_DIR`` in ``tmp_path``), with the two
new loaders injected as fakes: ``J4R2Env.load_parents`` returns ``env.store_parents`` and
``J4R2Env.load_display_names`` returns ``env.display``. A case that wants a default loader passes
``load_parents=None`` or ``load_display_names=None`` explicitly. Nothing reads ``data/live/``,
``notebook/`` or ``configs/`` (one test reads ``configs/jovannah.yaml`` for rule 8, read only).

Snapshot names and parents are set by editing the saved snapshot (``set_names_and_parents``), the
way ``j4_fixtures.set_names`` does, since at the skeleton ``refresh`` does not fill
``entity_parents``; only check (m) reads what the refresh itself writes.

The live shape (check a) is the newest live run's names as copied from
``data/live/engine/runs/run_853832a5.json`` (``entity_names`` and ``variants``): seven ads in three
ad sets, built here by a refresh of a seven-ad poll and then given those names and parents. The
paused copy of "IMG2_TXT1 <en dash> Updated." in Creative Test is in no run: it reaches the slots
through the store layers (``load_names`` and ``load_parents``), as a paused ad does live. The
campaign's name is replaced by a neutral one; it plays no part in the rule.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
from typing import Any

from bayesian_marketing import core as C
from bayesian_marketing import pipeline
from bayesian_marketing.live.contracts import LiveRow, PollRecord
from bayesian_marketing.live.refresh import refresh
from bayesian_marketing.notebook import release as nb_release
from tests.acceptance import j4_fixtures as X
from tests.acceptance.j4_fixtures import CLIENT
from tests.acceptance.j4r_fixtures import J4REnv
from tests.acceptance.test_J5 import LEAD
from tests.acceptance.test_L5 import config
from tests.fakes.live import FakeStore, FixedClock

UTC = dt.UTC
EN = chr(0x2013)  # en dash

# ------------------------------------------------------------------ the live shape (check a)

CAMPAIGN = "120253661586800526"
MAIN = "120253899504550526"
MAIN_META = f"US_AUT_Broad_25-55_W {EN} Cap@$1500"  # fails the display-name rule ($)
MAIN_ALIAS = "the main ad set"
CREATIVE = "120254012200940526"
IMG2_TEST = "120254063879400526"

VID1_MAIN = "120253899504560526"
VID1_CT = "120254012200990526"
IMG2_MAIN = "120253993297010526"
IMG2_I2T = "120254063879420526"
IMG2_PAUSED = "120254012200950526"  # paused, in Creative Test; in no run
IMG1 = "120253899504580526"
IMG3 = "120253899504590526"
IMG4 = "120253899504600526"

IMG2_UPDATED = f"IMG2_TXT1 {EN} Updated."
LIVE_NAMES: dict[str, str] = {
    CAMPAIGN: "Leads campaign",
    MAIN: MAIN_META,
    IMG1: "IMG1_TXT1",
    IMG3: "IMG3_TXT1",
    IMG4: "IMG4_TXT1",
    IMG2_MAIN: IMG2_UPDATED,
    CREATIVE: "Creative Test",
    VID1_CT: "VID1_TXT1",
    IMG2_TEST: "IMG2 test",
    IMG2_I2T: IMG2_UPDATED,
    VID1_MAIN: "VID1_TXT1",
}
#: The seven ads of the run and their ad sets. The spec names the ad sets of the four shared-name
#: ads; IMG1, IMG3 and IMG4 are given the main ad set, which changes nothing for unique names.
LIVE_PARENTS: dict[str, str] = {
    VID1_MAIN: MAIN,
    IMG1: MAIN,
    IMG3: MAIN,
    IMG4: MAIN,
    IMG2_MAIN: MAIN,
    VID1_CT: CREATIVE,
    IMG2_I2T: IMG2_TEST,
}
LIVE_ADS = tuple(LIVE_PARENTS)
LIVE_EXPECTED: dict[str, str] = {
    VID1_MAIN: "VID1_TXT1 (the main ad set)",
    VID1_CT: "VID1_TXT1 (Creative Test)",
    IMG2_MAIN: f"IMG2_TXT1 {EN} Updated (the main ad set)",
    IMG2_I2T: f"IMG2_TXT1 {EN} Updated (IMG2 test)",
    IMG1: "IMG1_TXT1",
    IMG3: "IMG3_TXT1",
    IMG4: "IMG4_TXT1",
}
PAUSED_EXPECTED = f"IMG2_TXT1 {EN} Updated (Creative Test)"

LIVE_START = dt.datetime(2026, 11, 26, 17, 30, tzinfo=UTC)
LIVE_WINDOW = (dt.date(2026, 11, 20), dt.date(2026, 11, 26))


def seed_named_poll(
    store: FakeStore,
    start: dt.datetime,
    window: tuple[dt.date, dt.date],
    ads: dict[str, tuple[int, int]],
    parents: dict[str, str],
    names: dict[str, str],
    pull_n: int,
) -> PollRecord:
    """``j4_fixtures.seed_poll`` with each ad in its own ad set and the rows carrying names."""
    pid = "poll_" + hashlib.sha256(f"{CLIENT}|meta|{start.isoformat()}".encode()).hexdigest()[:8]
    days = (window[1] - window[0]).days + 1
    rows = []
    for ad, (imp, clk) in ads.items():
        ids = {"account": "555", "campaign": CAMPAIGN, "ad_set": parents[ad], "ad": ad}
        row_names = {k: names[v] for k, v in ids.items() if v in names}
        for i in range(days):
            rows.append(
                LiveRow(
                    poll_id=pid,
                    client_id=CLIENT,
                    platform="meta",
                    entity_ids=ids,
                    entity_names=row_names,
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
            )
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


# ------------------------------------------------------------------ releases with parents


def ad_source(ad: str, name: str, adset: str | None, read_at: str) -> dict[str, Any]:
    """A ``meta_object`` source of ``object_type`` "ad", its ``content.adset_id`` the parent."""
    content: dict[str, Any] = {"id": ad, "name": name, "status": "ACTIVE"}
    if adset is not None:
        content["adset_id"] = adset
    return nb_release.source(
        "meta_object", {"object_type": "ad", "object_id": ad, "read_at": read_at}, content
    )


def typed_source(object_type: str, oid: str, name: str, read_at: str) -> dict[str, Any]:
    return nb_release.source(
        "meta_object",
        {"object_type": object_type, "object_id": oid, "read_at": read_at},
        {"id": oid, "name": name},
    )


def event_entry(eid: str, src: dict[str, Any], **kw: Any) -> dict[str, Any]:
    e = {
        "entry_id": eid,
        "kind": "event",
        "statement": "The ad was published.",
        "method": "observed",
        "date": "2026-11-20",
        "as_of": "2026-11-20T15:00:00+00:00",
        "basis": [{"source_id": src["source_id"], "role": "primary"}],
    }
    e.update(kw)
    return e


# ------------------------------------------------------------------ the environment


class J4R2Env(J4REnv):
    """J4REnv with fake ``load_parents`` and ``load_display_names`` (never the store or configs)."""

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self.store_parents: dict[str, str] = {}
        self.display: dict[str, str] = {}
        self.parents_calls: list[str] = []
        self.display_calls: list[str] = []
        self._entry_n = 100

    def load_parents(self, client_id: str) -> dict[str, str]:
        self.parents_calls.append(client_id)
        return dict(self.store_parents)

    def load_display_names(self, client_id: str) -> dict[str, str]:
        self.display_calls.append(client_id)
        return dict(self.display)

    def _loaders(self, kw: dict[str, Any]) -> dict[str, Any]:
        kw.setdefault("load_parents", self.load_parents)
        kw.setdefault("load_display_names", self.load_display_names)
        return kw

    def render(self, text: str, client_id: str = CLIENT, **kw: Any) -> dict[str, Any]:
        return super().render(text, client_id, **self._loaders(kw))

    def menu(self, client_id: str = CLIENT, **kw: Any) -> dict[str, Any]:
        return super().menu(client_id, **self._loaders(kw))

    # snapshots

    def set_names_and_parents(
        self, run_id: str, names: dict[str, str], parents: dict[str, str]
    ) -> None:
        """Set the snapshot's ``entity_names`` and ``entity_parents`` in the order given, keeping
        the file's mtime."""
        mtime = self.snapshot_file(run_id).stat().st_mtime
        self.rewrite(
            run_id, lambda d: d.update(entity_names=dict(names), entity_parents=dict(parents))
        )
        os.utime(self.snapshot_file(run_id), (mtime, mtime))
        snap = self.snapshot(run_id)
        assert snap.entity_names == names
        assert snap.entity_parents == parents

    def shared_run(self, names: dict[str, str], parents: dict[str, str], ctr: bool = True) -> str:
        """The J4 fixture's lead run (ads IMG3 and IMG2 of j4_fixtures) with the names and
        parents given, and both ads' ctr marginal at 4.4%."""
        run_id = self.lead_run_at(X.START_OLD, X.WINDOW_OLD)
        self.set_names_and_parents(run_id, names, parents)
        if ctr:
            self.ctr_44(run_id, ad=X.IMG3_ID)
            self.ctr_44(run_id, ad=X.IMG2_ID)
        return run_id

    def live_run(self) -> str:
        """A lead run of the seven live ads, given the live names and parents."""
        self._pulls += 1
        start = LIVE_START
        self.clock = FixedClock(start + dt.timedelta(minutes=30))
        at = start + dt.timedelta(minutes=30)
        self.mp.setattr(pipeline, "utcnow", lambda: at)
        ads = {ad: (1000, 30 + 5 * i) for i, ad in enumerate(LIVE_ADS)}
        rec = refresh(
            config(**LEAD),
            seed_named_poll(
                self.store, start, LIVE_WINDOW, ads, LIVE_PARENTS, LIVE_NAMES, self._pulls
            ),
            self.store,
            self.clock,
            data_dir=self.data_dir,
            config_root=self.config_root,
        )
        assert rec.status == "ran", rec.reason
        self.set_names_and_parents(rec.run_id, LIVE_NAMES, LIVE_PARENTS)
        return rec.run_id

    # releases

    def release_of(
        self,
        sources: list[dict[str, Any]],
        entries: list[dict[str, Any]] | None = None,
        **kw: Any,
    ) -> str:
        """A release holding ``sources``; with no entries, one event entry citing the first."""
        if entries is None:
            self._entry_n += 1
            entries = [event_entry(f"nbe_{CLIENT}_{self._entry_n:04d}", sources[0])]
        kw.setdefault("day", "20261120")
        kw.setdefault("created_at", dt.datetime(2026, 11, 20, 15, 0, tzinfo=UTC))
        return X.write_nb(
            self.nb_root,
            kw.pop("client_id", CLIENT),
            kw.pop("day"),
            kw.pop("created_at"),
            entries,
            sources,
            parent=kw.pop("parent", None),
        )


# ------------------------------------------------------------------ reading the results


def name_items(menu: dict[str, Any]) -> dict[str, str]:
    """The menu's name items, subject to full form. A subject listed twice fails."""
    items = [s for s in menu["slots"] if s["kind"] == "name"]
    subjects = [s["subject"] for s in items]
    assert len(subjects) == len(set(subjects)), items
    return {s["subject"]: s["forms"]["full"] for s in items}


def fig_items(menu: dict[str, Any], subject: str) -> list[dict[str, Any]]:
    return [s for s in menu["slots"] if s["kind"] == "fig" and s["subject"] == subject]


def name_slot_of(entity_id: str) -> str:
    return "{name:ad/" + entity_id + "}"
