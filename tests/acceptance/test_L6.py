"""L6: the framework lead prior, chosen by conversion kind (prior learning spec v0.2 §4, §8).

The lead record's family and params are read from ``registries/priors/default.yaml``
(``lead_records.cvr``, skeleton step 1, D48) at test time, never hard-coded. When the table is
absent the tests that need it fail with a plain message rather than erroring at collection.

Pipeline checks run ``refresh`` against ``FakeStore`` in a temp config root with real economics,
as in test_L4 and test_L5. ``pipeline.execute`` is wrapped (never replaced) to capture what
``refresh`` hands it, so the same manifest and pulls can be run again with another request.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
from pathlib import Path
from typing import Any

import pytest
from scipy import stats

from bayesian_marketing import core as C
from bayesian_marketing import pipeline
from bayesian_marketing.core import registries
from bayesian_marketing.live.contracts import LiveRow, PollRecord
from bayesian_marketing.live.refresh import refresh
from bayesian_marketing.prior_registry import registry as prior_registry
from tests.fakes import builders as B
from tests.fakes.live import FakeStore, FixedClock

pytestmark = pytest.mark.piece("L6")

UTC = dt.UTC
CLIENT = "lead_prior_client"
ECON_ID = "lead_prior_econ"
START = dt.datetime(2026, 11, 7, 17, 30, 0, 123456, tzinfo=UTC)
WINDOW = (dt.date(2026, 11, 1), dt.date(2026, 11, 7))
AS_OF = dt.datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
LEAD_EVENT = "offsite_conversion.fb_pixel_lead"
LEAD_HOP = "default:priors/default/lead_records/cvr@v1"
LEAD_REF = "priors/default/lead_records/cvr@v1"


# ------------------------------------------------- registry facts (read at test time)


def default_file() -> dict[str, Any]:
    return registries.load("priors/default")


def lead_cvr() -> tuple[str, dict[str, float], dict[str, Any]]:
    """(family, params, raw entry) of ``lead_records.cvr``; fails cleanly when it is absent."""
    entry = (default_file().get("lead_records") or {}).get("cvr")
    if entry is None:
        pytest.fail("registries/priors/default.yaml has no lead_records.cvr (skeleton step 1, D48)")
    return entry["family"], {k: float(v) for k, v in entry["params"].items()}, entry


def purchase(path: str) -> tuple[str, dict[str, float]]:
    entry = default_file()["records"][path]
    return entry["family"], {k: float(v) for k, v in entry["params"].items()}


def lead_id() -> str:
    _, params, _ = lead_cvr()
    return C.make_id("pr_", {"default": "cvr", "params": params, "table": "lead_records"})  # C1


def purchase_id(path: str) -> str:
    _, params = purchase(path)
    return C.make_id("pr_", {"default": path, "params": params})  # R15: base formula


def ceiling(key: str, path: str = "cvr") -> float:
    return float(registries.load("bounds")["plausibility"][key][path])


# ------------------------------------------------------------------ pipeline env (as test_L5)


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
        pull_id="pull_meta_00000006",
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
        self.tmp = tmp_path
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

    def snapshot(self, run_id: str) -> pipeline.RunSnapshot:
        self.mp.setenv("BAYES_DATA_DIR", str(self.data_dir))
        try:
            return pipeline.load_snapshot(run_id)
        finally:
            self.mp.setenv("BAYES_DATA_DIR", self.iso)

    def in_data_dir(self, path: Path | None = None) -> None:
        self.mp.setenv("BAYES_DATA_DIR", str(path or self.data_dir))

    def restore(self) -> None:
        self.mp.setenv("BAYES_DATA_DIR", self.iso)

    def client_prior(self, path: str, params: dict[str, float], **approve_kw: Any) -> str:
        """An approved client prior in the registry under ``data_dir``."""
        self.in_data_dir()
        try:
            rec = B.prior_record(path, "beta", params, approved=False, client_id=CLIENT)
            pid = prior_registry.propose(rec)
            prior_registry.approve(pid, "owner", **approve_kw)
        finally:
            self.restore()
        return pid


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    return Env(tmp_path, monkeypatch)


# ------------------------------------------------------------------ C1, R1: resolve


def test_L6_lead_cvr_resolves_to_the_lead_default() -> None:
    family, params, entry = lead_cvr()
    rec = prior_registry.resolve("cvr", "no_priors_client", AS_OF, conversion_kind="lead")
    assert rec.prior_id == lead_id()  # C1: id formula with "table": "lead_records"
    assert rec.prior_id != purchase_id("cvr")  # C1: can never equal a purchase default's id
    assert rec.family == family and rec.params == params
    assert rec.resolution_path == [  # C1: every hop, last hop names the lead table
        "client:no_priors_client:none",
        "vertical:unmapped",
        LEAD_HOP,
    ]
    assert rec.elicitation.evidence_refs == [LEAD_REF]  # R1
    assert rec.approved  # C4: approved through its own elicitation block
    own = entry.get("elicitation")
    if own is not None:  # C4, D32: the per-record block, not the file-wide one
        assert rec.elicitation.rationale == own["rationale"]
        assert rec.elicitation.approved_by == own["approved_by"]


@pytest.mark.parametrize("path", ["ctr", "conversions_per_dollar", "cpm_impressions_per_dollar"])
def test_L6_paths_absent_from_lead_records_resolve_as_purchase(path: str) -> None:
    lead_cvr()  # the lead table exists; these paths are not in it
    assert path not in default_file()["lead_records"]
    lead = prior_registry.resolve(path, "no_priors_client", AS_OF, conversion_kind="lead")
    buy = prior_registry.resolve(path, "no_priors_client", AS_OF)
    assert lead.prior_id == buy.prior_id == purchase_id(path)  # C1: absent path as for purchase
    assert lead.resolution_path == buy.resolution_path
    assert lead.resolution_path[-1] == f"default:priors/default/records/{path}@v1"


def test_L6_purchase_cvr_id_is_pinned_to_the_base_formula() -> None:
    """Guard (R15, C3): passes before the build and must keep passing."""
    for kw in ({}, {"conversion_kind": "purchase"}):
        rec = prior_registry.resolve("cvr", "no_priors_client", AS_OF, **kw)
        assert rec.prior_id == purchase_id("cvr")  # R15
        assert rec.resolution_path[-1] == "default:priors/default/records/cvr@v1"
        assert rec.params == purchase("cvr")[1]


def test_L6_client_cvr_prior_wins_over_the_lead_default_in_the_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guard (C1, client hop unchanged): passes before the build."""
    rec = B.prior_record("cvr", "beta", {"a": 6.0, "b": 24.0}, approved=False, client_id=CLIENT)
    pid = prior_registry.propose(rec)
    prior_registry.approve(pid, "owner")
    got = prior_registry.resolve("cvr", CLIENT, AS_OF, conversion_kind="lead")
    assert got.prior_id == pid
    assert got.resolution_path == [f"client:{CLIENT}:{pid}"]


# ------------------------------------------------------------------ C2, R2, R13: resolve_priors


def test_L6_resolve_priors_lead_without_client_priors() -> None:
    priors, g8 = pipeline.resolve_priors(
        {}, "no_priors_client", False, AS_OF, conversion_kind="lead"
    )
    assert g8.passed  # C4: the lead default is approved, so G8 passes on client data
    cvr = priors.records["cvr"]
    assert cvr.prior_id == lead_id()  # C2
    assert cvr.resolution_path[-1] == LEAD_HOP
    ctr = priors.records["ctr"]
    assert ctr.prior_id == purchase_id("ctr")  # C1: ctr is not in lead_records
    assert ctr.resolution_path[-1] == "default:priors/default/records/ctr@v1"
    assert purchase_id("cvr") not in {r.prior_id for r in priors.records.values()}  # R2


def test_L6_requested_purchase_default_id_on_a_lead_run_fails_g8() -> None:
    lead_cvr()
    with pytest.raises(C.GateFailure) as exc:  # C2, R13
        pipeline.resolve_priors(
            {"cvr": purchase_id("cvr")}, "no_priors_client", False, AS_OF, conversion_kind="lead"
        )
    assert exc.value.result.gate == "G8"
    text = " ".join(exc.value.result.reasons)
    assert purchase_id("cvr") in text and lead_id() in text  # names what it resolves to


def test_L6_requested_lead_default_id_on_a_lead_run_passes_g8() -> None:
    priors, g8 = pipeline.resolve_priors(
        {"cvr": lead_id()}, "no_priors_client", False, AS_OF, conversion_kind="lead"
    )
    assert g8.passed and priors.records["cvr"].prior_id == lead_id()  # C2


def test_L6_purchase_resolve_priors_unchanged() -> None:
    """Guard (C3): purchase ids and resolution paths as on the base; passes before the build."""
    a, ga = pipeline.resolve_priors({}, "no_priors_client", False, AS_OF)
    b, gb = pipeline.resolve_priors(
        {}, "no_priors_client", False, AS_OF, conversion_kind="purchase"
    )
    assert ga.passed and gb.passed
    for path, rec in a.records.items():
        assert rec.prior_id == b.records[path].prior_id == purchase_id(path)  # C3, R15
        assert rec.resolution_path == b.records[path].resolution_path
        assert rec.resolution_path == [
            "client:no_priors_client:none",
            "vertical:unmapped",
            f"default:priors/default/records/{path}@v1",
        ]


# ------------------------------------------------------------------ C2, C5, R2: lead run end to end


def test_L6_lead_run_snapshot_names_the_lead_default(env: Env) -> None:
    lead_cvr()
    rec = env.run(config(conversion_event={"meta": LEAD_EVENT}))
    assert rec.status == "ran", rec.reason  # C4: G8 passes the lead default on client data
    assert env.calls[0]["request"].conversion_kind == "lead"
    snap = env.snapshot(rec.run_id)
    assert snap.priors["cvr"] == lead_id()  # C5, R2
    assert snap.priors["ctr"] == purchase_id("ctr")  # C1
    assert purchase_id("cvr") not in snap.priors.values()  # R2: no records.cvr id appears
    assert snap.configuration["priors"] == snap.priors


def test_L6_client_cvr_prior_wins_on_a_lead_run(env: Env) -> None:
    pid = env.client_prior("cvr", {"a": 6.0, "b": 24.0})
    rec = env.run(config(conversion_event={"meta": LEAD_EVENT}))
    assert rec.status == "ran", rec.reason
    snap = env.snapshot(rec.run_id)
    assert snap.priors["cvr"] == pid  # C1: the client prior is the client's own and wins
    assert lead_id() not in snap.priors.values()


def test_L6_lead_run_requesting_the_purchase_default_is_skipped_by_g8(env: Env) -> None:
    lead_cvr()
    cfg = config(conversion_event={"meta": LEAD_EVENT}, priors={"cvr": purchase_id("cvr")})
    rec = env.run(cfg)
    assert rec.status == "skipped"  # R13: a requested id that no longer matches fails G8
    assert rec.run_id is None
    assert rec.reason and purchase_id("cvr") in rec.reason


# ------------------------------------------------------------------ C3, R15: purchase run unchanged


def test_L6_purchase_run_ids_and_seed_equal_the_base(env: Env) -> None:
    """Guard (C3, R15): passes before the build and must keep passing.

    The purchase run made by refresh is run again with ``conversion_kind`` left at its default,
    at the same frozen start time, into a second data dir. Run id, seed and prior ids must match,
    and the seed and run id must equal the base's formulas (the request hashed without the kind).
    """
    rec = env.run(config())
    assert rec.status == "ran", rec.reason
    call = env.calls[0]
    assert call["request"].conversion_kind == "purchase"
    at = dt.datetime(2026, 11, 7, 18, 30, tzinfo=UTC)
    env.mp.setattr(pipeline, "utcnow", lambda: at)
    req_kind = call["request"]
    req_default = C.CompareRequest(**req_kind.model_dump(exclude={"conversion_kind"}))
    assert "conversion_kind" not in req_default.model_fields_set
    snaps = []
    for i, req in enumerate((req_kind, req_default)):
        env.in_data_dir(env.tmp / f"rerun_{i}")
        try:
            ctx = env.real_execute(
                call["manifest"], req, manifest_dir=call["manifest_dir"], pulls=call["pulls"]
            )
        finally:
            env.restore()
        snaps.append(ctx.snapshot)
    a, b = snaps
    assert a.run_id == b.run_id  # C3
    assert a.configuration["seed"] == b.configuration["seed"]  # C3
    assert a.priors == b.priors  # C3
    assert a.priors["cvr"] == purchase_id("cvr")  # R15
    assert a.priors["ctr"] == purchase_id("ctr")
    manifest = call["manifest"]
    key = req_kind.model_dump(mode="json", exclude={"conversion_kind"})
    want_seed = int(C.inputs_hash({"manifest": manifest.manifest_id, "request": key})[:8], 16)
    assert a.configuration["seed"] == want_seed  # C3: the base's seed formula
    want_run = C.make_id(
        "run_", {"manifest": manifest.manifest_id, "request": key, "at": at.isoformat()}
    )
    assert a.run_id == want_run  # C3: the base's run id formula


# ------------------------------------------------------------------ R3: predictive check by kind


def test_L6_lead_default_passes_the_predictive_check_under_the_lead_ceiling() -> None:
    family, params, _ = lead_cvr()
    lead_ceiling = ceiling("ceiling_q99_lead")
    rec = B.prior_record("cvr", family, params, approved=False, client_id=None)
    out = prior_registry.predictive_check(rec, conversion_kind="lead")  # R3
    assert out["ceiling_applies"] == 1.0
    assert out["ceiling"] == lead_ceiling  # R3: the lead table, not ceiling_q99
    assert out["passed"] == 1.0
    want_q99 = float(stats.beta(params["a"], params["b"]).ppf(0.99))
    assert abs(out["q99"] - want_q99) < 1e-12
    assert want_q99 <= lead_ceiling


def test_L6_purchase_predictive_check_keeps_the_purchase_ceiling() -> None:
    """Guard (R3, C3): the default kind still uses ceiling_q99; passes before the build."""
    rec = B.prior_record("cvr", "beta", {"a": 6.0, "b": 24.0}, approved=False, client_id=None)
    for kw in ({}, {"conversion_kind": "purchase"}):
        out = prior_registry.predictive_check(rec, **kw)
        assert out["ceiling"] == ceiling("ceiling_q99")


def test_L6_client_lead_prior_between_the_ceilings_approved_only_as_lead() -> None:
    purchase_ceiling = ceiling("ceiling_q99")
    lead_ceiling = ceiling("ceiling_q99_lead")
    params = {"a": 4.0, "b": 8.0}
    q99 = float(stats.beta(params["a"], params["b"]).ppf(0.99))
    assert purchase_ceiling < q99 < lead_ceiling, q99  # the case R3 names: between the two
    rec = B.prior_record("cvr", "beta", params, approved=False, client_id=CLIENT)
    pid = prior_registry.propose(rec)
    with pytest.raises(prior_registry.PriorRefused):  # R3: refused with the default kind
        prior_registry.approve(pid, "owner")
    approved = prior_registry.approve(pid, "owner", conversion_kind="lead")  # R3
    assert approved.approved
    assert approved.predictive_check is not None
    assert approved.predictive_check["ceiling"] == lead_ceiling
    got = prior_registry.resolve("cvr", CLIENT, AS_OF, conversion_kind="lead")
    assert got.prior_id == pid and got.approved
