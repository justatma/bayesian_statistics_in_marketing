"""L10: regime mismatches cost one level in total; a lead takes no lag curve (D52, D53 (2)).

Spec: ``spec/Mismatch_Lead_Lag_Horizon_Fix_v0.2.md`` §2 C1 to C3 and §4 L10; §6 (S3 to S7, S10)
holds where it differs from §1 to §5.

C1 is checked by calling ``floors.estimability.quantity_feasibility`` on quantities built with the
fakes, with the regime notices taken from the phrasing registry. C2, C3, S4, S6 and S10 run
``refresh`` against ``FakeStore`` with real economics, as in test_L5, test_L8 and test_L9;
``pipeline.execute`` is wrapped (never replaced) so the captured request can be run again with
``horizon_basis`` set, another conversion kind, a pinned clock or a pull carrying a measurement
change, each into its own data dir. The pre-field request keys (S6) are pinned from commit
21f1b21, before ``horizon_basis`` existed; how they were taken is in
``spec/manifests/acceptance_tests_live.md``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import itertools
import os
from pathlib import Path
from typing import Any

import pytest

from bayesian_marketing import core as C
from bayesian_marketing import pipeline
from bayesian_marketing.core import registries
from bayesian_marketing.core.base import canonical_json
from bayesian_marketing.floors.estimability import quantity_feasibility, registry_target
from bayesian_marketing.lag import model as lag
from bayesian_marketing.live.contracts import LiveRow, PollRecord
from bayesian_marketing.live.refresh import refresh
from tests.fakes import builders as B
from tests.fakes.live import FakeStore, FixedClock

pytestmark = pytest.mark.piece("L10")

UTC = dt.UTC
CLIENT = "cap_client"
ECON_ID = "cap_econ"
START = dt.datetime(2026, 11, 7, 17, 30, 0, 123456, tzinfo=UTC)
WINDOW = (dt.date(2026, 11, 1), dt.date(2026, 11, 7))
LEAD_EVENT = "offsite_conversion.fb_pixel_lead"
META_CODE = "1d_view_7d_click_1d_ev"
PINNED_AT = dt.datetime(2026, 11, 7, 18, 30, tzinfo=UTC)

# Final strings, verbatim from the spec and the skeleton.
LEAD_NO_LAG_TEXT = "no lag curve: a lead is counted when it happens (D53)"  # C2
LEAD_NOT_VALUED_TEXT = "a lead is counted, never valued (D33)"
BASIS = "horizon: test basis sentence, L10"
CHANGE = "attribution window changed on 2026-11-04 (test)"

# Request keys at 21f1b21 (before ``horizon_basis``) for the requests ``key_request`` builds.
BASE_KEY_SHA = {
    "purchase": "d6648dc780b715e21ea224579d42c483c0c6c4a706fec2d71df03eb946667f92",
    "lead": "46b5c3dcab6eb5d1ee6a98d98f755778b75127fda7933535015f66307dbb1ded",
}
BASE_KEY_RUN_ID = {"purchase": "run_01623f98", "lead": "run_d2d54904"}


def notice(key: str) -> str:
    return registries.resolve(f"phrasing/notices/{key}@v1")


# ------------------------------------------------------------------ C1: the one-level cap

MISMATCH_KEYS = ("lag_approx", "too_few_ads", "platform_modeled", "joint_failed")
ESTIMABLE_WIDTH = (400, 19600)  # beta: relative half-width about 0.08
MARGINAL_WIDTH = (30, 970)  # beta: relative half-width about 0.30


def feasibility(width: tuple[int, int], keys: tuple[str, ...], **update: Any) -> C.Feasibility:
    q = B.quantity("ctr", estimate=B.beta_spec(*width), notices=[notice(k) for k in keys])
    if update:
        q = q.model_copy(update=update)
    return quantity_feasibility(q, registry_target())


def assert_reasons_in_notice_order(f: C.Feasibility, keys: tuple[str, ...]) -> None:
    at = []
    for k in keys:
        hits = [i for i, r in enumerate(f.reasons) if notice(k) in r]
        assert len(hits) == 1, (k, f.reasons)  # C1: every mismatch reason, once
        at.append(hits[0])
    assert at == sorted(at), f.reasons  # C1: in the order of q.notices


def test_L10_width_fixtures() -> None:
    """Guard: the two widths are what the tests take them to be; passes before the build."""
    assert feasibility(ESTIMABLE_WIDTH, ()).status == "estimable"
    assert feasibility(MARGINAL_WIDTH, ()).status == "marginal"


TWO_AND_THREE = [
    *itertools.combinations(MISMATCH_KEYS, 2),
    *itertools.combinations(MISMATCH_KEYS, 3),
    ("platform_modeled", "lag_approx"),  # reversed orders: reasons follow the notices
    ("joint_failed", "platform_modeled", "too_few_ads"),
]


@pytest.mark.parametrize("keys", TWO_AND_THREE, ids="+".join)
def test_L10_estimable_width_with_several_mismatches_is_marginal(keys: tuple[str, ...]) -> None:
    f = feasibility(ESTIMABLE_WIDTH, keys)
    assert f.status == "marginal", f.reasons  # C1, D52: one level in total
    assert_reasons_in_notice_order(f, keys)  # C1


def test_L10_jovannah_conversion_notices_are_marginal() -> None:
    keys = ("too_few_ads", "platform_modeled", "lag_approx")  # §1 E1: her cvr quantities
    f = feasibility(ESTIMABLE_WIDTH, keys)
    assert f.status == "marginal"  # C1, D52
    assert_reasons_in_notice_order(f, keys)  # C1


@pytest.mark.parametrize(
    "keys",
    [("lag_approx", "too_few_ads"), ("platform_modeled", "lag_approx", "too_few_ads")],
    ids="+".join,
)
def test_L10_marginal_width_with_several_mismatches_is_below_floor(keys: tuple[str, ...]) -> None:
    """Guard: passes before the build (one level from marginal is below_floor already)."""
    f = feasibility(MARGINAL_WIDTH, keys)
    assert f.status == "below_floor"  # C1, §4 L10
    assert_reasons_in_notice_order(f, keys)  # C1


@pytest.mark.parametrize(
    ("width", "want"),
    [(ESTIMABLE_WIDTH, "marginal"), (MARGINAL_WIDTH, "below_floor")],
    ids=["estimable", "marginal"],
)
@pytest.mark.parametrize("key", MISMATCH_KEYS)
def test_L10_one_mismatch_as_before(width: tuple[int, int], want: str, key: str) -> None:
    """Guard: one mismatch lowers one level, as before; passes before the build."""
    f = feasibility(width, (key,))
    assert f.status == want  # C1, §4 L10: one mismatch behaves as before
    assert_reasons_in_notice_order(f, (key,))


def test_L10_other_notices_do_not_count() -> None:
    """Guard: a notice outside the regime keys lowers nothing; passes before the build."""
    keys = ("lag_assumed", "lag_approx")
    f = feasibility(ESTIMABLE_WIDTH, keys)
    assert f.status == "marginal"  # C1: only regime mismatches count


def test_L10_required_projection_unchanged_under_several_mismatches() -> None:
    """C1: "the required-events projection and its reasons are as before"."""
    keys = ("lag_approx", "too_few_ads", "platform_modeled")
    capped = feasibility(ESTIMABLE_WIDTH, keys, n_events=400.0)
    assert capped.status == "marginal"  # C1
    assert capped.required is None  # C1: the width meets the target, nothing to project
    assert any("limited by a regime mismatch" in r for r in capped.reasons)  # C1: as before
    marg = feasibility(MARGINAL_WIDTH, keys, n_events=30.0)
    clean = feasibility(MARGINAL_WIDTH, (), n_events=30.0)
    assert marg.status == "below_floor"  # C1
    assert marg.required == pytest.approx(clean.required)  # C1: projection from the width
    assert marg.available == clean.available == 30.0


# ------------------------------------------------------------------ pipeline env (as test_L8)


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


LEAD = {"conversion_event": {"meta": LEAD_EVENT}}
ADS = {"ad_a": (1000, 40), "ad_b": (1000, 60)}  # impressions, clicks a day; leads clicks // 4


def seed_poll(store: FakeStore, code: str) -> PollRecord:
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
            attribution_window=code,
        )
        for ad, (imp, clk) in ADS.items()
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
        pull_id="pull_meta_00000010",
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
        self.contexts: list[Any] = []
        self.reruns = 0
        real = pipeline.execute

        def capture(manifest: Any, request: Any, **kw: Any) -> Any:
            self.calls.append({"manifest": manifest, "request": request, **kw})
            ctx = real(manifest, request, **kw)
            self.contexts.append(ctx)
            return ctx

        self.real_execute = real
        monkeypatch.setattr(pipeline, "execute", capture)
        write_economics(self.config_root)

    def run(self, cfg: C.ClientConfig, code: str = META_CODE) -> Any:
        rec = refresh(
            cfg,
            seed_poll(self.store, code),
            self.store,
            self.clock,
            data_dir=self.data_dir,
            config_root=self.config_root,
        )
        assert rec.status == "ran", rec.reason
        assert len(self.contexts) == 1
        return self.contexts[0]

    def rerun(self, *, change: str | None = None, **update: Any) -> Any:
        """The captured run again into a fresh data dir, request fields replaced; ``change``
        puts a measurement change on the pull (so WINDOW_CHANGED is a run notice)."""
        call = self.calls[0]
        if update.get("metric") and "horizon" not in update:
            unit = pipeline.horizon_unit(update["metric"])
            update["horizon"] = C.Horizon(unit=unit, amount=call["request"].horizon.amount)
        request = call["request"].model_copy(update=update)
        pulls = call["pulls"]
        if change is not None:
            pulls = [p.model_copy(update={"measurement_changes": [change]}) for p in pulls]
        self.reruns += 1
        data_dir = self.tmp / f"rerun_{self.reruns}"
        data_dir.mkdir()
        self.mp.setenv("BAYES_DATA_DIR", str(data_dir))
        try:
            return self.real_execute(
                call["manifest"], request, manifest_dir=call["manifest_dir"], pulls=pulls
            )
        finally:
            self.mp.setenv("BAYES_DATA_DIR", self.iso)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    return Env(tmp_path, monkeypatch)


def lag_free_quantities(snap: Any) -> None:
    banned = (notice("lag_approx"), notice("lag_assumed"), LEAD_NO_LAG_TEXT)
    for q in snap.quantities:
        hit = [n for n in q.notices if n in banned]
        assert not hit, (q.name, q.scope.ids, q.notices)  # S4: no lag notice on any quantity


# ------------------------------------------------------------------ C2, S4: a lead takes no lag


def test_L10_lead_no_lag_constant() -> None:
    """Guard: the skeleton carries the final string; passes before the build."""
    assert pipeline.LEAD_NO_LAG == LEAD_NO_LAG_TEXT  # C2


@pytest.mark.parametrize("code", [META_CODE, "7d_click_1d_view"])
def test_L10_lead_run_has_no_lag_curve(env: Env, code: str) -> None:
    ctx = env.run(config(**LEAD), code)
    snap = ctx.snapshot
    assert ctx.data.mature_fraction  # the run has cells
    for row in ctx.data.mature_fraction:
        assert all(f == 1.0 for f in row), row  # C2: mature fraction 1 for every cell
    assert snap.configuration["lag"] is None  # C2
    assert snap.notices.count(LEAD_NO_LAG_TEXT) == 1  # C2, S4: a run notice, once
    assert notice("lag_assumed") not in snap.notices  # C2: LEAD_NO_LAG in place of a lag notice
    assert not any("conversion lag not adjusted" in n for n in snap.notices)  # C2
    lag_free_quantities(snap)  # S4, C2: no lag_approx, no LEAD_NO_LAG on a quantity


def test_L10_lead_cvr_median_sits_near_the_raw_rate(env: Env) -> None:
    ctx = env.run(config(**LEAD))
    snap = ctx.snapshot
    data = ctx.data
    seen = 0
    for q in snap.quantities:
        if q.name != "cvr":
            continue
        i = data.entities.index(q.scope.ids["ad"])
        leads = sum(float(x) for x in data.conversions_reported[i] if x is not None)
        raw = leads / sum(data.clicks[i])
        assert raw == pytest.approx(0.25)  # the fixture: leads are clicks // 4
        q50 = q.estimate.summary["q50"]
        assert abs(q50 - raw) <= 0.1 * raw, (q.scope.ids, q50, raw)  # §4 L10, §1 E2
        assert notice("lag_approx") not in q.notices  # C2
        seen += 1
    assert seen == len(ADS)  # a cvr per ad


def test_L10_purchase_run_with_the_meta_code_keeps_the_seven_day_curve(env: Env) -> None:
    """Guard (C2: purchase runs unchanged; L9's check on a purchase run): passes before the
    build."""
    ctx = env.run(config(), META_CODE)
    snap = ctx.snapshot
    assert snap.configuration["lag"] == {"source": "registry_default", "window": META_CODE}
    seven = lag.lag_model("meta", "7d_click", None, None)  # §4 L10: the 7-day default curve
    want = [lag.mature_fraction(d, snap.as_of, seven) for d in ctx.data.dates]
    assert all(row == want for row in ctx.data.mature_fraction)
    assert min(want) < 1.0  # the curve was applied
    assert notice("lag_assumed") in snap.notices
    assert LEAD_NO_LAG_TEXT not in snap.notices  # C2: leads only
    assert all(LEAD_NO_LAG_TEXT not in q.notices for q in snap.quantities)


def test_L10_lead_cvr_comparison_has_no_immature_cohort(env: Env) -> None:
    """S3: with no lag curve no lead cohort is immature, so no stop path for a lead run."""
    env.run(config(**LEAD))
    ctx = env.rerun(metric="cvr")
    snap = ctx.snapshot
    assert snap.comparison is not None and snap.comparison.unit == "leads"
    assert all(f == 1.0 for row in ctx.data.mature_fraction for f in row)  # C2
    actions = [r.action for r in snap.recommendations]
    assert "stop_test" not in actions and "continue_test" not in actions, actions  # S3
    lag_free_quantities(snap)  # S4


# ------------------------------------------------------------------ C3, S6: the request key


def key_request(kind: str, basis: str | None) -> C.CompareRequest:
    return C.CompareRequest(
        metric="ctr",
        variants=["ad_a", "ad_b"],
        priors={},
        window=WINDOW,
        horizon=C.Horizon(unit="impressions", amount="1000"),
        conversion_kind=kind,  # type: ignore[arg-type]
        horizon_basis=basis,
    )


def test_L10_request_field() -> None:
    """Guard: the skeleton's field; passes before the build."""
    assert key_request("purchase", None).horizon_basis is None  # C3: default None
    assert key_request("purchase", BASIS).horizon_basis == BASIS


@pytest.mark.parametrize("kind", ["purchase", "lead"])
@pytest.mark.parametrize("basis", [None, BASIS], ids=["none", "set"])
def test_L10_basis_never_in_the_request_key(kind: str, basis: str | None) -> None:
    req = key_request(kind, basis)
    exclude = {"horizon_basis", "conversion_kind"} if kind == "purchase" else {"horizon_basis"}
    want = req.model_dump(mode="json", exclude=exclude)
    got = canonical_json(pipeline._request_key(req))
    assert got == canonical_json(want)  # S6: purchase drops kind and basis; lead drops basis
    assert C.inputs_hash(pipeline._request_key(req)) == BASE_KEY_SHA[kind]  # S6: as at 21f1b21
    run_id = C.make_id(
        "run_",
        {
            "manifest": "ds_00000001",
            "request": pipeline._request_key(req),
            "at": PINNED_AT.isoformat(),
        },
    )
    assert run_id == BASE_KEY_RUN_ID[kind]  # S6: every existing run id unchanged


def test_L10_kind_still_separates_lead_from_purchase() -> None:
    """Guard: a lead request keys apart from a purchase one; passes before the build."""
    a = canonical_json(pipeline._request_key(key_request("purchase", None)))
    b = canonical_json(pipeline._request_key(key_request("lead", None)))
    assert a != b  # D46: the kind is in a lead key


@pytest.mark.parametrize("kind", ["purchase", "lead"])
def test_L10_basis_leaves_run_id_and_seed_unchanged(env: Env, kind: str) -> None:
    env.run(config(**LEAD) if kind == "lead" else config())
    env.mp.setattr(pipeline, "utcnow", lambda: PINNED_AT)
    base = env.rerun(horizon_basis=None).snapshot
    said = env.rerun(horizon_basis=BASIS).snapshot
    assert said.run_id == base.run_id  # S6, §4 L10
    assert said.configuration["seed"] == base.configuration["seed"]  # S6
    assert [r.recommendation_id for r in said.recommendations] == [
        r.recommendation_id for r in base.recommendations
    ]  # S6: the run id feeds the recommendation ids
    other = env.rerun(horizon=C.Horizon(unit="impressions", amount="2000")).snapshot
    assert other.run_id != base.run_id  # S6: the horizon itself is in the key


# ------------------------------------------------------------------ C3, S10: notice order


def test_L10_lead_notice_order_with_the_basis_last(env: Env) -> None:
    env.run(config(**LEAD))
    snap = env.rerun(horizon_basis=BASIS, change=CHANGE).snapshot
    base = env.rerun(horizon_basis=None, change=CHANGE).snapshot
    n = snap.notices
    assert n[-1] == BASIS and n.count(BASIS) == 1  # C3, S10: last, once
    assert n[:-1] == base.notices  # C3: appended, nothing else moves
    changed = [i for i, x in enumerate(n) if CHANGE in x]
    assert len(changed) == 1  # the WINDOW_CHANGED notice
    fit = n.index(notice("too_few_ads"))  # a fit notice for this two-ad fixture
    assert fit < n.index(LEAD_NO_LAG_TEXT) < n.index(LEAD_NOT_VALUED_TEXT) < changed[0]  # S10
    assert changed[0] == len(n) - 2  # S10: WINDOW_CHANGED, then the basis
    assert n.count(LEAD_NO_LAG_TEXT) == 1  # C2


def test_L10_purchase_notice_order_with_the_basis_last(env: Env) -> None:
    env.run(config())
    snap = env.rerun(horizon_basis=BASIS, change=CHANGE).snapshot
    base = env.rerun(horizon_basis=None, change=CHANGE).snapshot
    n = snap.notices
    assert n[-1] == BASIS and n.count(BASIS) == 1  # C3, S10
    assert n[:-1] == base.notices  # C3
    changed = [i for i, x in enumerate(n) if CHANGE in x]
    assert len(changed) == 1
    assert n.index(notice("lag_assumed")) < changed[0] == len(n) - 2  # S10
    assert all(BASIS not in q.notices for q in snap.quantities)  # C3: a run notice only


def test_L10_no_basis_no_extra_notice(env: Env) -> None:
    """Guard (C3): a request with no basis adds no notice; passes before the build."""
    env.run(config())
    again = env.rerun(horizon_basis=None).snapshot  # refresh may set a basis once L11 lands
    assert not any(x.startswith("horizon:") for x in again.notices)  # C3
