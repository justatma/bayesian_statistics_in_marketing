"""L8: a comparison carries its unit; counts are priced at their observed cost (D51).

Spec: ``spec/Units_and_Window_Fix_v0.2.md``; §5 (U1 to U11) holds where it differs from §1 to §4.

Direct checks build ``Comparison`` objects with the fakes and call ``in_money``,
``decision_feasibility``, ``survival_check``, ``reallocate`` and ``stop_or_continue``. Pipeline
checks run ``refresh`` against ``FakeStore`` in a temp config root with real economics, as in
test_L4 and test_L5; ``pipeline.execute`` is wrapped (never replaced) so a run can be repeated with
another metric, other variants or a pinned clock. Replacement costs are recomputed in the test from
the ``FunnelData`` cells the run itself used (U4), and also checked against hand numbers.

The contribution check (U5) pins digests taken from the base code at commit f7b2d28, before any
builder changed it; how they were taken is in ``spec/manifests/acceptance_tests_live.md``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from bayesian_marketing import core as C
from bayesian_marketing import pipeline
from bayesian_marketing.atmaos import socket as sock
from bayesian_marketing.claims import vocab as V
from bayesian_marketing.claims.check import check_narrative
from bayesian_marketing.cli import main as cli_main
from bayesian_marketing.decision import allocation, reallocation
from bayesian_marketing.decision import units as U
from bayesian_marketing.decision.reallocation import fmt_money
from bayesian_marketing.decision.stopping import stop_or_continue
from bayesian_marketing.floors.estimability import NO_TOLERANCE_REASON, decision_feasibility
from bayesian_marketing.live.contracts import LiveRow, PollRecord
from bayesian_marketing.live.refresh import refresh
from bayesian_marketing.reporting.render import render
from tests.fakes import builders as B
from tests.fakes.live import FakeStore, FixedClock

pytestmark = pytest.mark.piece("L8")

UTC = dt.UTC
CLIENT = "units_client"
ECON_ID = "units_econ"
START = dt.datetime(2026, 11, 7, 17, 30, 0, 123456, tzinfo=UTC)
WINDOW = (dt.date(2026, 11, 1), dt.date(2026, 11, 7))
LEAD_EVENT = "offsite_conversion.fb_pixel_lead"
TOL = 150
SINGULAR = {"clicks": "click", "orders": "order", "leads": "lead"}
COUNT_UNITS = ("clicks", "orders", "leads")
TARGET_OF = {"clicks": "clicks", "orders": "orders", "leads": "orders"}
HORIZON_OF = {"clicks": "impressions", "orders": "clicks"}

# Final strings (U9), verbatim from the spec.
NO_COST_TEXT = "no observed cost per {singular} to value a lost {singular}"
NOT_APPLIED_TEXT = "survival floor not applied: this comparison is in {unit}, not money"
VALUED_TEXT = (
    "lost {unit} valued at their observed cost, {cost} per {singular} "
    "(observed, not adjusted for late conversions)"
)


# ------------------------------------------------------------------ helpers


def amount_of(x: Any) -> float:
    """A money amount however a params dict or a JSON reply carries it."""
    if isinstance(x, C.Money):
        return float(x.amount)
    if isinstance(x, dict):
        return float(x["amount"])
    return float(x)


def count_comparison(
    unit: str,
    *,
    cost: Any = None,
    cost_currency: str = "USD",
    options: tuple[str, ...] = ("ad_a", "ad_b"),
    ev: dict[str, Any] | None = None,
    el: dict[str, Any] | None = None,
    q05: dict[str, Any] | None = None,
    p_best: dict[str, float] | None = None,
    economics_id: str = "econ_00000001",
) -> C.Comparison:
    """A comparison in ``unit`` built through the validator (so U3 runs), amounts in USD."""
    target = "contribution" if unit == "money" else TARGET_OF[unit]
    obj = B.objective(target, HORIZON_OF.get(target, "clicks"), 1000)
    base = B.comparison(
        options, obj=obj, expected_value=ev, expected_loss=el, p_best=p_best,
        economics_id=economics_id,
    )  # fmt: skip
    data = base.model_dump()
    data["unit"] = unit
    data["replacement_cost"] = None if cost is None else B.money(cost, cost_currency)
    if q05 is not None:
        data["value_q05"] = {k: B.money(v) for k, v in q05.items()}
    return C.Comparison(**data)


def valued_at_matches(assumptions: list[str], unit: str, cost: float) -> bool:
    """The one VALUED_AT assumption for ``unit`` quotes ``cost`` at the precision it shows.

    The spec leaves the {cost} format open; the registry rounds money to whole units today, so
    the quoted number is accepted when it is ``cost`` rounded to the decimals it is written with.
    """
    head, tail = VALUED_TEXT.split("{cost}")
    head = head.format(unit=unit)
    tail = tail.format(singular=SINGULAR[unit])
    hits = [a for a in assumptions if a.startswith(head) and a.endswith(tail)]
    assert len(hits) == 1, assumptions
    middle = hits[0][len(head) : -len(tail)]
    number = re.search(r"\d[\d,]*(?:\.(\d+))?", middle)
    assert number is not None, middle
    shown = float(number.group(0).replace(",", ""))
    decimals = len(number.group(1) or "")
    return abs(shown - cost) <= 0.5 * 10**-decimals + 1e-9


def pooled_cost(data: C.FunnelData, ads: list[str], unit: str) -> float | None:
    """U4 from first principles: per FunnelData cell, pooled over the compared ads."""
    spend = 0.0
    units = 0.0
    for ad in ads:
        i = data.entities.index(ad)
        for j in range(len(data.dates)):
            if unit == "clicks":
                spend += data.spend[i][j]
                units += data.clicks[i][j]
                continue
            obs, rep = data.conversions_observed[i][j], data.conversions_reported[i][j]
            known = obs if obs is not None else rep
            if known is None:
                continue  # U4: a cell with no known count gives neither spend nor count
            spend += data.spend[i][j]
            units += float(known)
    if units == 0 or spend <= 0:
        return None
    return spend / units


# ------------------------------------------------------------------ pipeline env (as test_L5)


DayRow = Callable[[str, int], dict[str, Any]]


def write_economics(config_root: Path, **kw: Any) -> None:
    econ = B.economics(
        economics_id=ECON_ID,
        client_id=CLIENT,
        loss_tolerance=kw.pop("loss_tolerance", TOL),
        fixed_price=795,
        variable_cost=235,
        approved=True,
        **kw,
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


def simple_rows(ads: dict[str, tuple[int, int, str]], conv: Any = "quarter") -> DayRow:
    """Each ad the same every day: (impressions, clicks, spend); conversions clicks // 4."""

    def row(ad: str, day: int) -> dict[str, Any]:
        imp, clk, spend = ads[ad]
        conversions = float(clk // 4) if conv == "quarter" else conv
        return {"impressions": imp, "clicks": clk, "spend": spend, "conv": conversions}

    return row


def seed_poll(store: FakeStore, ads: list[str], day_row: DayRow, code: str) -> PollRecord:
    pid = "poll_" + hashlib.sha256(f"{CLIENT}|meta|{START.isoformat()}".encode()).hexdigest()[:8]
    rows = []
    for ad in ads:
        for i in range(7):
            r = day_row(ad, i)
            rows.append(
                LiveRow(
                    poll_id=pid,
                    client_id=CLIENT,
                    platform="meta",
                    entity_ids={"account": "555", "campaign": "c1", "ad_set": "s1", "ad": ad},
                    entity_names={},
                    objective="OUTCOME_LEADS",
                    date=WINDOW[0] + dt.timedelta(days=i),
                    impressions=r["impressions"],
                    clicks=r["clicks"],
                    spend=C.Money(amount=r["spend"], currency="USD"),
                    conversions_reported=r["conv"],
                    conversions_observed=None,
                    revenue_reported=None,
                    attribution_window=code,
                )
            )
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
        pull_id="pull_meta_00000008",
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
        real = pipeline.execute

        def capture(manifest: Any, request: Any, **kw: Any) -> Any:
            self.calls.append({"manifest": manifest, "request": request, **kw})
            ctx = real(manifest, request, **kw)
            self.contexts.append(ctx)
            return ctx

        self.real_execute = real
        monkeypatch.setattr(pipeline, "execute", capture)

    def run(
        self,
        cfg: C.ClientConfig,
        ads: list[str],
        day_row: DayRow,
        code: str = "7d_click_1d_view",
    ) -> Any:
        rec = refresh(
            cfg,
            seed_poll(self.store, ads, day_row, code),
            self.store,
            self.clock,
            data_dir=self.data_dir,
            config_root=self.config_root,
        )
        assert rec.status == "ran", rec.reason
        return rec

    def rerun(self, data_dir: Path | None = None, **update: Any) -> Any:
        """The captured run again, with request fields replaced (a cvr metric gets its horizon)."""
        call = self.calls[0]
        if update.get("metric") and "horizon" not in update:
            unit = pipeline.horizon_unit(update["metric"])
            update["horizon"] = C.Horizon(unit=unit, amount=call["request"].horizon.amount)
        request = call["request"].model_copy(update=update)
        self.mp.setenv("BAYES_DATA_DIR", str(data_dir or self.data_dir))
        try:
            return self.real_execute(
                call["manifest"], request, manifest_dir=call["manifest_dir"], pulls=call["pulls"]
            )
        finally:
            self.mp.setenv("BAYES_DATA_DIR", self.iso)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    return Env(tmp_path, monkeypatch)


TWO = {"ad_a": (1000, 40, "10.00"), "ad_b": (1000, 50, "20.00")}
JOVANNAH = {
    "ad_1": (900, 12, "10.00"),
    "ad_2": (1100, 20, "10.00"),
    "ad_3": (800, 9, "10.00"),
    "ad_4": (1000, 15, "10.00"),
    "ad_5": (1200, 25, "10.00"),
}


# ------------------------------------------------------------------ U9: the strings


def test_L8_final_strings() -> None:
    """Guard (U9): the skeleton already carries the final strings; passes before the build."""
    assert U.NO_REPLACEMENT_COST == NO_COST_TEXT
    assert U.SURVIVAL_NOT_APPLIED == NOT_APPLIED_TEXT
    assert U.VALUED_AT == VALUED_TEXT
    assert U.SINGULAR == SINGULAR


# ------------------------------------------------------------------ C3: in_money


def test_L8_in_money_passes_money_through() -> None:
    c = B.comparison()
    assert c.unit == "money"
    got = U.in_money(c, B.money("12.34"))
    assert got == B.money("12.34")  # C3: unit money returns the amount


@pytest.mark.parametrize("unit", COUNT_UNITS)
def test_L8_in_money_prices_a_count_at_the_replacement_cost(unit: str) -> None:
    c = count_comparison(unit, cost="1.25")
    got = U.in_money(c, B.money("2.4"))
    assert got is not None
    assert got.currency == "USD"
    assert abs(float(got.amount) - 3.0) < 1e-9  # C3: amount x replacement_cost


def test_L8_in_money_is_in_the_replacement_costs_currency() -> None:
    c = count_comparison("clicks", cost="2", cost_currency="EUR")
    got = U.in_money(c, B.money("3"))
    assert got is not None and got.currency == "EUR"  # C3: "in the replacement cost's currency"
    assert abs(float(got.amount) - 6.0) < 1e-9


@pytest.mark.parametrize("unit", COUNT_UNITS)
def test_L8_in_money_is_none_without_a_replacement_cost(unit: str) -> None:
    assert U.in_money(count_comparison(unit), B.money("2.4")) is None  # C3


# ------------------------------------------------------------------ U3: the validator


@pytest.mark.parametrize(
    ("target", "unit"), [("contribution", "money"), ("clicks", "clicks"), ("orders", "orders")]
)
def test_L8_absent_unit_is_derived_from_the_target(target: str, unit: str) -> None:
    """Guard (U3): the skeleton's validator; passes before the build."""
    c = B.comparison(obj=B.objective(target, HORIZON_OF.get(target, "clicks"), 1000))
    assert c.unit == unit
    stored = json.loads(c.model_dump_json())
    del stored["unit"], stored["replacement_cost"]  # an old snapshot's comparison
    old = C.Comparison.model_validate_json(json.dumps(stored))
    assert old.unit == unit and old.replacement_cost is None


@pytest.mark.parametrize(
    ("target", "unit"),
    [
        ("clicks", "money"),
        ("clicks", "orders"),
        ("clicks", "leads"),
        ("orders", "money"),
        ("orders", "clicks"),
        ("contribution", "clicks"),
        ("contribution", "leads"),
    ],
)
def test_L8_contradicting_unit_is_refused(target: str, unit: str) -> None:
    """Guard (U3): passes before the build."""
    data = B.comparison(obj=B.objective(target, "clicks", 1000)).model_dump()
    data["unit"] = unit
    with pytest.raises(ValidationError):
        C.Comparison(**data)


def test_L8_leads_is_allowed_with_target_orders() -> None:
    """Guard (U3, U9): passes before the build."""
    data = B.comparison(obj=B.objective("orders", "clicks", 1000)).model_dump()
    data["unit"] = "leads"
    assert C.Comparison(**data).unit == "leads"


# ------------------------------------------------------------------ C4, U9: decision feasibility


@pytest.mark.parametrize("unit", COUNT_UNITS)
def test_L8_feasibility_estimable_on_the_priced_loss(unit: str) -> None:
    c = count_comparison(unit, cost="2", el={"ad_a": "0.5", "ad_b": "30"})
    f = decision_feasibility(c, B.economics(loss_tolerance=TOL))
    assert f.status == "estimable"  # 0.5 x 2 = 1 <= 150
    assert abs(f.available - 1.0) < 1e-9  # C4: available is in money
    assert f.target == TOL


@pytest.mark.parametrize("unit", COUNT_UNITS)
def test_L8_feasibility_marginal_on_the_priced_loss(unit: str) -> None:
    c = count_comparison(unit, cost="2", el={"ad_a": "100", "ad_b": "130"})
    f = decision_feasibility(c, B.economics(loss_tolerance=TOL))
    assert f.status == "marginal"  # 100 x 2 = 200, in (150, 2 x 150]; the raw 100 would pass
    assert abs(f.available - 200.0) < 1e-9


@pytest.mark.parametrize("unit", COUNT_UNITS)
def test_L8_feasibility_below_floor_on_the_priced_loss(unit: str) -> None:
    c = count_comparison(unit, cost="1000", el={"ad_a": "0.5", "ad_b": "4"})
    f = decision_feasibility(c, B.economics(loss_tolerance=TOL))
    assert f.status == "below_floor"  # 0.5 x 1000 = 500 > 300; the raw 0.5 would pass
    assert abs(f.available - 500.0) < 1e-9


@pytest.mark.parametrize("unit", COUNT_UNITS)
def test_L8_feasibility_without_a_replacement_cost(unit: str) -> None:
    c = count_comparison(unit, el={"ad_a": "0.5", "ad_b": "4"})
    f = decision_feasibility(c, B.economics(loss_tolerance=TOL))
    assert f.status == "below_floor"  # C4
    assert NO_COST_TEXT.format(singular=SINGULAR[unit]) in f.reasons  # U9 final string
    assert f.available == 0.0  # U9: no money amount


def test_L8_feasibility_no_tolerance_is_checked_first() -> None:
    c = count_comparison("orders", el={"ad_a": "3", "ad_b": "4"})
    f = decision_feasibility(c, B.economics(loss_tolerance=None))
    assert f.status == "below_floor"
    assert f.reasons[0] == NO_TOLERANCE_REASON  # U9: D16 first, then no replacement cost
    assert f.available == 0.0  # U9: no money amount


def test_L8_feasibility_no_tolerance_with_a_cost_reports_the_money_loss() -> None:
    c = count_comparison("clicks", cost="2", el={"ad_a": "3", "ad_b": "4"})
    f = decision_feasibility(c, B.economics(loss_tolerance=None))
    assert f.status == "below_floor"
    assert f.reasons == [NO_TOLERANCE_REASON]  # D16
    assert abs(f.available - 6.0) < 1e-9  # C4: available is in money


# ------------------------------------------------------------------ C5, U7: survival floor


@pytest.mark.parametrize("unit", COUNT_UNITS)
def test_L8_survival_floor_not_applied_to_a_count(unit: str) -> None:
    c = count_comparison(unit, cost="1", q05={"ad_a": "0.1", "ad_b": "0.2"})
    blocked, notices = reallocation.survival_check(c, B.money(1500), list(c.options))
    assert blocked == set()  # C5, U7
    assert notices == [NOT_APPLIED_TEXT.format(unit=unit)]  # once, not once per option


def test_L8_survival_notice_only_when_a_floor_is_set() -> None:
    """Guard (U7): no floor, no notice; the base already returns nothing. Passes before."""
    c = count_comparison("clicks", cost="1", q05={"ad_a": "0.1", "ad_b": "0.2"})
    assert reallocation.survival_check(c, None, list(c.options)) == (set(), [])  # U7


def test_L8_survival_floor_still_applies_to_money() -> None:
    """Guard (§8.2 C3 for unit money): passes before the build."""
    c = count_comparison("money", q05={"ad_a": "100", "ad_b": "2000"})
    blocked, notices = reallocation.survival_check(c, B.money(1500), list(c.options))
    assert blocked == {"ad_a"}
    assert len(notices) == 1 and NOT_APPLIED_TEXT.format(unit="money") not in notices


# ------------------------------------------------------------------ C6: reallocate and hold


def realloc_case(
    iso: Any, *, switching: str, cost: str, floor: Any = None
) -> tuple[C.Recommendation, C.Comparison]:
    def set_cost(d: dict[str, Any]) -> None:
        d["channels"]["meta"]["learning_phase_switching_cost"] = {
            "amount": switching,
            "currency": "USD",
        }

    iso.edit_yaml("channels", set_cost)
    c = count_comparison(
        "clicks",
        cost=cost,
        options=("inc", "cand"),
        ev={"inc": "10", "cand": "30"},
        el={"inc": "20", "cand": "0.5"},
        q05={"inc": "5", "cand": "25"},
    )
    econ = B.economics(loss_tolerance=TOL, survival_floor=floor)
    decision = B.feasibility("estimable", "decision_loss", available=1.0, target=TOL)
    scope = C.Scope(level="ad", ids={"options": "inc,cand"}, window=WINDOW, platform="meta")
    return reallocation.reallocate(c, decision, econ, "run_00000001", scope=scope), c


def test_L8_reallocate_net_benefit_is_priced_benefit_minus_switching_cost(iso: Any) -> None:
    rec, _ = realloc_case(iso, switching="25", cost="2", floor=1500)
    assert rec.action == "reallocate"  # 20 clicks x 2 = 40 > 25; the raw 20 would hold
    assert rec.expected_benefit is not None and rec.expected_benefit.currency == "USD"
    assert abs(float(rec.expected_benefit.amount) - 15.0) < 1e-9  # C6: 40 - 25
    assert rec.expected_loss is not None
    assert abs(float(rec.expected_loss.amount) - 1.0) < 1e-9  # C6: 0.5 clicks x 2
    assert rec.guarantee.slots["expected_loss"] == fmt_money(B.money(1))  # C6: slots in money
    assert rec.params["unit"] == "clicks"  # C6
    assert abs(amount_of(rec.params["replacement_cost"]) - 2.0) < 1e-9
    assert valued_at_matches(rec.guarantee.assumptions, "clicks", 2.0)
    notice = NOT_APPLIED_TEXT.format(unit="clicks")
    assert rec.params["notices"].count(notice) == 1  # U7: once per recommendation


def test_L8_hold_when_the_priced_benefit_does_not_cover_switching(iso: Any) -> None:
    rec, _ = realloc_case(iso, switching="5", cost="0.2")
    assert rec.action == "hold"  # 20 clicks x 0.2 = 4 < 5; the raw 20 would switch
    assert rec.expected_loss is not None
    assert abs(float(rec.expected_loss.amount) - 4.0) < 1e-9  # C6: 20 clicks x 0.2
    assert rec.guarantee.slots["expected_loss"] == fmt_money(B.money(4))


# ------------------------------------------------------------------ U1: stop_or_continue


def stop_data() -> C.FunnelData:
    return B.funnel_data(
        {
            "ad_a": {"impressions": 20000, "clicks": 400, "spend": 500.0, "conv_obs": 8},
            "ad_b": {"impressions": 17000, "clicks": 340, "spend": 500.0, "conv_obs": 18},
        }
    )


def test_L8_stop_test_loss_is_priced() -> None:
    c = count_comparison("orders", cost="100", el={"ad_a": "3", "ad_b": "0.5"})
    decision = B.feasibility("estimable", "decision_loss", available=50.0, target=TOL)
    rec = stop_or_continue(c, decision, stop_data(), B.economics(loss_tolerance=TOL), "run_1")
    assert rec.action == "stop_test"
    assert rec.expected_loss is not None
    assert abs(float(rec.expected_loss.amount) - 50.0) < 1e-9  # U1: 0.5 orders x 100
    assert rec.guarantee.slots["expected_loss"] == fmt_money(B.money(50))  # U1: in money
    assert rec.params["unit"] == "orders"
    assert valued_at_matches(rec.guarantee.assumptions, "orders", 100.0)


def test_L8_stop_projection_uses_the_priced_loss() -> None:
    c = count_comparison("orders", cost="100", el={"ad_a": "3", "ad_b": "2"})
    decision = B.feasibility("marginal", "decision_loss", available=200.0, target=TOL)
    econ = B.economics(loss_tolerance=TOL, test_budget=100000)
    rec = stop_or_continue(c, decision, stop_data(), econ, "run_1")
    # U1: 2 orders x 100 = 200 against 150; the raw 2 would be within tolerance, unprojectable
    assert rec.action == "continue_test"
    want = 740.0 * ((200.0 / 150.0) ** 2 - 1.0)  # n_now = 740 clicks, the horizon's unit
    assert abs(rec.params["remaining_volume"]["amount"] - want) < 1e-6


def test_L8_stop_without_a_replacement_cost_is_not_knowable() -> None:
    c = count_comparison("orders", el={"ad_a": "3", "ad_b": "2"})
    decision = B.feasibility("below_floor", "decision_loss", available=0.0, target=TOL)
    econ = B.economics(loss_tolerance=TOL, test_budget=100000)
    rec = stop_or_continue(c, decision, stop_data(), econ, "run_1")
    assert rec.action == "not_knowable"  # U1
    assert NO_COST_TEXT.format(singular="order") in rec.model_dump_json()  # U1: carried


# ------------------------------------------------------------------ U4, U9: pipeline sets the unit


def test_L8_ctr_run_sets_unit_and_pooled_cost_over_compared_ads(env: Env) -> None:
    write_economics(env.config_root)
    ads = {**TWO, "ad_c": (1000, 10, "90.00")}  # ad_c is in the poll but not compared
    env.run(config(), list(ads), simple_rows(ads))
    ctx = env.rerun(env.tmp / "two", variants=["ad_a", "ad_b"])
    c = ctx.snapshot.comparison
    assert c is not None and sorted(c.options) == ["ad_a", "ad_b"]
    assert c.unit == "clicks"  # C1, U3
    assert c.replacement_cost is not None and c.replacement_cost.currency == "USD"
    want = (7 * 10 + 7 * 20) / (7 * 40 + 7 * 50)  # 210 / 630 = 1/3: pooled, ad_c left out
    assert abs(float(c.replacement_cost.amount) - want) < 1e-12  # U4: stored unrounded
    assert abs(want - pooled_cost(ctx.data, c.options, "clicks")) < 1e-12  # type: ignore[operator]
    # C2: set before decision_feasibility sees it, so the decision's loss is in money
    best = min(float(m.amount) for m in c.expected_loss.values())
    assert ctx.snapshot.decision is not None
    assert abs(ctx.snapshot.decision.available - best * want) < 1e-9


@pytest.mark.parametrize(("event", "unit"), [(None, "orders"), (LEAD_EVENT, "leads")])
def test_L8_cvr_cost_skips_cells_with_no_known_count(
    env: Env, event: str | None, unit: str
) -> None:
    write_economics(env.config_root)

    def row(ad: str, day: int) -> dict[str, Any]:
        imp, clk, spend = TWO[ad]
        conv = None if (ad == "ad_a" and day % 2 == 0) else float(clk // 4)
        return {"impressions": imp, "clicks": clk, "spend": spend, "conv": conv}

    cfg = config(conversion_event={"meta": event}) if event else config()
    env.run(cfg, list(TWO), row)
    ctx = env.rerun(metric="cvr")
    c = ctx.snapshot.comparison
    assert c is not None
    assert c.unit == unit  # U9: a lead cvr run is in leads
    # U4: ad_a's 4 unknown days drop their $40; 3 x $10 + 7 x $20 = 170 over 3 x 10 + 7 x 12
    want = (3 * 10 + 7 * 20) / (3 * 10 + 7 * 12)
    assert c.replacement_cost is not None
    assert abs(float(c.replacement_cost.amount) - want) < 1e-12
    assert abs(want - pooled_cost(ctx.data, c.options, unit)) < 1e-12  # type: ignore[operator]


def test_L8_zero_clicks_gives_no_replacement_cost(env: Env) -> None:
    write_economics(env.config_root)
    env.run(config(), list(TWO), lambda ad, day: {**simple_rows(TWO)(ad, day), "clicks": 0})
    snap = env.contexts[0].snapshot
    c = snap.comparison
    assert c is not None and c.unit == "clicks"
    assert c.replacement_cost is None  # C2, U4: zero units
    assert snap.decision is not None and snap.decision.status == "below_floor"
    assert NO_COST_TEXT.format(singular="click") in snap.decision.reasons  # §4
    alloc = [r for r in snap.recommendations if r.action in ("allocate", "not_knowable")]
    assert alloc and all(r.expected_loss is None for r in alloc)  # U6
    no_cost = NO_COST_TEXT.format(singular="click")
    assert all(no_cost in r.decision_feasibility.reasons for r in alloc)  # U6: the reason


def test_L8_zero_spend_gives_no_replacement_cost(env: Env) -> None:
    write_economics(env.config_root)
    env.run(config(), list(TWO), lambda ad, day: {**simple_rows(TWO)(ad, day), "spend": "0.00"})
    snap = env.contexts[0].snapshot
    c = snap.comparison
    assert c is not None and c.unit == "clicks"
    assert c.replacement_cost is None  # U4: total spend <= 0
    assert snap.decision is not None and snap.decision.status == "below_floor"
    assert NO_COST_TEXT.format(singular="click") in snap.decision.reasons  # C4


def test_L8_lead_ctr_run_is_in_clicks(env: Env) -> None:
    """U9 sets leads only when the target is orders; a lead ctr run stays in clicks."""
    write_economics(env.config_root)
    env.run(config(conversion_event={"meta": LEAD_EVENT}), list(TWO), simple_rows(TWO))
    c = env.contexts[0].snapshot.comparison
    assert c is not None and c.unit == "clicks"
    assert c.replacement_cost is not None
    assert abs(float(c.replacement_cost.amount) - 210 / 630) < 1e-12


# ------------------------------------------------------------------ U6, U7, C6: the Jovannah shape


def test_L8_jovannah_shape_allocates(env: Env) -> None:
    write_economics(env.config_root, survival_floor=1500)
    env.run(config(conversion_event={"meta": LEAD_EVENT}), list(JOVANNAH), simple_rows(JOVANNAH))
    ctx = env.contexts[0]
    snap = ctx.snapshot
    assert snap.metric == "ctr"
    c = snap.comparison
    assert c is not None and c.unit == "clicks" and len(c.options) == 5
    cost = pooled_cost(ctx.data, c.options, "clicks")
    assert cost is not None and abs(cost - 350 / (7 * 81)) < 1e-12
    assert c.replacement_cost is not None
    assert abs(float(c.replacement_cost.amount) - cost) < 1e-12

    recs = [r for r in snap.recommendations if "allocation" in r.params]
    assert len(recs) == 1
    rec = recs[0]
    assert rec.guarantee.slots.get("reason") != allocation.ALL_BLOCKED  # U6, §4
    assert rec.action == "allocate"
    notice = NOT_APPLIED_TEXT.format(unit="clicks")
    assert rec.params["notices"].count(notice) == 1  # U7: once per recommendation
    assert rec.guarantee.assumptions.count(notice) == 1
    assert not any("survival floor 1,500" in n for n in rec.params["notices"])

    shares = rec.params["allocation"]
    share_loss = sum(shares[o] * float(c.expected_loss[o].amount) for o in c.options)
    assert rec.expected_loss is not None and rec.expected_loss.currency == "USD"
    assert abs(float(rec.expected_loss.amount) - share_loss * cost) <= 0.006  # U6, rounded
    assert rec.params["unit"] == "clicks"  # C6
    assert abs(amount_of(rec.params["replacement_cost"]) - cost) < 1e-9
    assert valued_at_matches(rec.guarantee.assumptions, "clicks", cost)


def test_L8_no_survival_notice_without_a_floor(env: Env) -> None:
    """Guard (U7): the notice must not appear without a floor; passes before the build."""
    write_economics(env.config_root)
    env.run(config(conversion_event={"meta": LEAD_EVENT}), list(JOVANNAH), simple_rows(JOVANNAH))
    snap = env.contexts[0].snapshot
    notice = NOT_APPLIED_TEXT.format(unit="clicks")
    for r in snap.recommendations:
        assert notice not in r.params.get("notices", [])  # U7: only when a floor is set
        assert notice not in r.guarantee.assumptions
    assert any(r.action == "allocate" for r in snap.recommendations)


def test_L8_lead_cvr_stop_rec_loss_is_priced(env: Env) -> None:
    """U1 on a lead cvr comparison with immature cohorts.

    Revised by the test writer under fix spec v0.2 S3 (build log B25): a lead run takes no lag
    curve (D53), so no lead cohort is immature and the pipeline no longer reaches the stop path.
    ``stop_or_continue`` is called directly with the run's leads comparison and decision and the
    run's FunnelData with its last day made immature. The U1 assertions are unchanged. Passes
    before the build too.
    """
    write_economics(env.config_root)
    env.run(config(conversion_event={"meta": LEAD_EVENT}), list(TWO), simple_rows(TWO))
    ctx = env.rerun(metric="cvr")
    c = ctx.snapshot.comparison
    assert c is not None and c.unit == "leads"
    cost = pooled_cost(ctx.data, c.options, "leads")
    assert cost is not None and abs(cost - 210 / (7 * 10 + 7 * 12)) < 1e-12
    decision = ctx.snapshot.decision
    assert decision is not None
    immature = [[*row[:-1], 0.5] for row in ctx.data.mature_fraction]  # under min_maturity 0.90
    data = ctx.data.model_copy(update={"mature_fraction": immature})
    econ = C.load_economics(ECON_ID, env.config_root)
    stops = [stop_or_continue(c, decision, data, econ, ctx.snapshot.run_id)]  # S3
    assert stops[0].action in ("stop_test", "continue_test"), stops[0].action
    best = min(float(m.amount) for m in c.expected_loss.values())
    loss = stops[0].expected_loss
    assert loss is not None and loss.currency == "USD"
    assert abs(float(loss.amount) - best * cost) <= 0.006  # U1: loss= passes through in_money
    assert stops[0].params["unit"] == "leads"
    assert valued_at_matches(stops[0].guarantee.assumptions, "leads", cost)


# ------------------------------------------------------------------ U5: contribution unchanged

# Digests of the base code's output (commit f7b2d28), taken as described in the manifest.
BASE_RUN_ID = "run_b2053c7f"
BASE_COMPARISON_SHA = "e9fd4e3dfb3b26cffd5b71391251d6400b8a47d3bb9106a55d1e24859ab7e305"
BASE_DECISION_SHA = "8b761d969c636b86b5c13bb565d4596ea166d07a363c556063b3d769dd421297"
BASE_REC_IDS = ["rec_367ec186", "rec_56105a71"]  # allocate, not_knowable (stop)
PINNED_AT = dt.datetime(2026, 11, 7, 18, 30, tzinfo=UTC)


def digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def test_L8_contribution_run_unchanged(env: Env) -> None:
    """Guard (U5): passes before the build and must keep passing.

    A contribution run (with a survival floor, so the money floor path runs too) at a pinned
    clock into its own data dir. Comparison minus unit and replacement_cost, decision minus
    checked_at, run id and recommendation ids equal the base's pinned digests.
    """
    write_economics(env.config_root, survival_floor=1)
    env.run(config(), list(TWO), simple_rows(TWO))
    env.mp.setattr(pipeline, "utcnow", lambda: PINNED_AT)
    ctx = env.rerun(env.tmp / "contribution", metric="contribution")
    snap = ctx.snapshot
    c, d = snap.comparison, snap.decision
    assert c is not None and d is not None
    assert c.unit == "money"  # U3
    comp = c.model_dump(mode="json", exclude={"unit", "replacement_cost"})
    assert digest(comp) == BASE_COMPARISON_SHA  # U5
    assert digest(d.model_dump(mode="json", exclude={"checked_at"})) == BASE_DECISION_SHA  # U5
    assert snap.run_id == BASE_RUN_ID  # U5
    assert [r.recommendation_id for r in snap.recommendations] == BASE_REC_IDS  # U5
    for r in snap.recommendations:
        assert "unit" not in r.params and "replacement_cost" not in r.params  # U5
        assert not any("valued at their observed cost" in a for a in r.guarantee.assumptions)
        assert not any("survival floor not applied" in a for a in r.guarantee.assumptions)
        payload = {
            "run": r.run_id,
            "action": r.action,
            "options": c.options,
            "params": r.params,
            "g": r.guarantee.statement_math,
        }
        assert r.recommendation_id == C.make_id("rec_", payload)  # the base id formula


# ------------------------------------------------------------------ U10: the socket reply


def test_L8_socket_result_carries_unit_and_cost(env: Env) -> None:
    write_economics(env.config_root)
    env.run(config(), list(TWO), simple_rows(TWO))
    res = sock.result_of(env.contexts[0].snapshot)
    u = res["uncertainty"]
    assert u["unit"] == "clicks"  # U10
    assert abs(amount_of(u["replacement_cost"]) - 210 / 630) < 1e-9  # U10
    assert all(isinstance(v, float) for v in res["expected_loss"].values())  # frozen fields


def test_L8_socket_result_money_unit(env: Env) -> None:
    write_economics(env.config_root)
    env.run(config(), list(TWO), simple_rows(TWO))
    ctx = env.rerun(env.tmp / "contribution", metric="contribution")
    u = sock.result_of(ctx.snapshot)["uncertainty"]
    assert u["unit"] == "money"  # U10
    assert "replacement_cost" in u


# ------------------------------------------------------------------ U2: display


def test_L8_cli_demo_ctr_states_the_money_verdict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli_main(["demo", "--metric", "ctr", "--out", str(tmp_path / "demo")])
    text = capsys.readouterr().out
    assert code == 0, text
    value = next(line for line in text.splitlines() if line.startswith("Expected value:"))
    assert " clicks" in value and "USD" not in value  # U2: comparison amounts in their unit
    loss = next(line for line in text.splitlines() if line.startswith("Expected loss:"))
    assert "no money tolerance applies" not in loss  # U2: the verdict runs the real test
    m = re.search(r"Expected loss:\s+([\d,]+(?:\.\d+)?) USD over the next .*?, (.*)$", loss)
    assert m is not None, loss  # U2: a recommendation amount is money
    amount = float(m.group(1).replace(",", ""))
    verdict = m.group(2)
    t = re.search(r"the ([\d,]+(?:\.\d+)?) USD tolerance", verdict)
    assert t is not None, verdict
    tol = float(t.group(1).replace(",", ""))
    if amount <= tol:
        assert verdict.startswith("within"), verdict
    else:
        assert verdict.startswith("above"), verdict


def test_L8_render_recommendation_money_comparison_counts(tmp_path: Path) -> None:
    comp = count_comparison(
        "clicks",
        cost="1.37",
        ev={"ad_a": "12.5", "ad_b": "14.25"},
        el={"ad_a": "1.75", "ad_b": "0.25"},
        p_best={"ad_a": 0.2, "ad_b": 0.8},
    )
    rec = B.recommendation("allocate")  # expected_benefit 170 USD, expected_loss 5 USD
    b = B.bundle("internal", recommendations=[rec], comparisons=[comp])
    html = Path(render(b, tmp_path).html_path).read_text()
    article = html.split('<article class="rec">')[1].split("</article>")[0]
    five, many = V.fmt_money(B.money(5)), V.fmt_money(B.money(170))
    assert five in article and many in article  # U2: recommendations in money
    assert "5.0 clicks" not in article and "170.0 clicks" not in article
    table = html.split('<h2 id="h-comp">')[1].split("</section>")[0]
    assert "12.5 clicks" in table and "1.8 clicks" in table  # U2: comparisons in their unit


def test_L8_claims_accept_the_replacement_cost(tmp_path: Path) -> None:
    comp = count_comparison(
        "clicks", cost="1.37", ev={"ad_a": "12.5", "ad_b": "14.25"}, el={"ad_a": "2", "ad_b": "0"}
    )
    b = B.bundle("internal", comparisons=[comp])
    said = f"We priced each click at ${V.fmt_amount(Decimal('1.37'))}."  # registry rounding
    block = C.NarrativeBlock(block_id="nb", text=said, author="x")
    res = check_narrative(block, b)
    assert res.passed, res.reasons  # U2: claims/check indexes c.replacement_cost as money
    other = C.NarrativeBlock(block_id="nb", text="We priced each click at $7.", author="x")
    assert not check_narrative(other, b).passed  # only the bundle's own cost
