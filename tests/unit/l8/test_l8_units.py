"""L8 builder checks beyond the frozen test: the U4 helper's edges, the currency guard, the
paths with no replacement cost, and the D30 no-economics split (D51)."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from tests.fakes import builders as B

from bayesian_marketing import core as C
from bayesian_marketing.decision import allocation, reallocation
from bayesian_marketing.decision import units as U
from bayesian_marketing.decision.stopping import stop_or_continue

WINDOW = (dt.date(2026, 11, 1), dt.date(2026, 11, 7))


def count_comparison(unit: str, cost: Any = None, currency: str = "USD", **kw: Any) -> C.Comparison:
    target = {"clicks": "clicks", "orders": "orders", "leads": "orders"}[unit]
    data = B.comparison(obj=B.objective(target, "clicks", 1000), **kw).model_dump()
    data["unit"] = unit
    data["replacement_cost"] = None if cost is None else B.money(cost, currency)
    return C.Comparison(**data)


def data_two_days() -> C.FunnelData:
    a = {"clicks": [10, 0], "spend": [5.0, 3.0], "conv_obs": [None, 2], "conv_rep": [4.0, 9.0]}
    b = {"clicks": [20, 10], "spend": [7.0, 0.0], "conv_obs": [None, None], "conv_rep": [None, 1.0]}
    return B.funnel_data({"a": a, "b": b}, dates=list(WINDOW))


def test_replacement_cost_clicks_pools_every_cell() -> None:
    got = U.replacement_cost(data_two_days(), ["a", "b"], "clicks", "USD")
    assert got is not None and got.currency == "USD"
    assert float(got.amount) == pytest.approx(15.0 / 40.0)


def test_replacement_cost_orders_observed_before_reported_and_skips_unknown() -> None:
    # a: day 1 reported 4 ($5), day 2 observed 2 ($3); b: day 1 unknown (its $7 dropped), day 2
    # reported 1 ($0). Spend 8 over 7 orders.
    got = U.replacement_cost(data_two_days(), ["a", "b"], "orders", "USD")
    assert got is not None
    assert float(got.amount) == pytest.approx(8.0 / 7.0)
    assert U.replacement_cost(data_two_days(), ["a", "b"], "leads", "USD") == got


def test_replacement_cost_none_for_money_other_currency_and_compared_subset() -> None:
    d = data_two_days()
    assert U.replacement_cost(d, ["a", "b"], "money", "USD") is None
    assert U.replacement_cost(d, ["a", "b"], "clicks", "EUR") is None
    only_b = U.replacement_cost(d, ["b"], "clicks", "USD")
    assert only_b is not None and float(only_b.amount) == pytest.approx(7.0 / 30.0)


def test_unit_params_and_assumptions_are_empty_for_money() -> None:
    c = B.comparison()
    assert U.unit_params(c) == {} and U.unit_assumptions(c) == []


def test_valued_at_quotes_the_cost_to_the_cent() -> None:
    c = count_comparison("clicks", cost="0.6189")
    (text,) = U.unit_assumptions(c)
    assert text == U.VALUED_AT.format(unit="clicks", cost="0.62 USD", singular="click")
    assert U.unit_params(c) == {
        "unit": "clicks",
        "replacement_cost": {"amount": "0.6189", "currency": "USD"},
    }


def test_replacement_cost_in_another_currency_is_refused() -> None:
    c = count_comparison("clicks", cost="1", currency="EUR")
    with pytest.raises(ValueError, match="replacement_cost"):
        reallocation.check_currency(c, "USD")


def test_reallocate_without_a_cost_is_not_knowable() -> None:
    c = count_comparison(
        "clicks",
        options=("inc", "cand"),
        expected_value={"inc": 1, "cand": 3},
        expected_loss={"inc": 2, "cand": 0.1},
    )
    decision = B.feasibility("estimable", "decision_loss", available=1.0, target=150)
    scope = C.Scope(level="ad", ids={"options": "inc,cand"}, window=WINDOW, platform="meta")
    econ = B.economics(loss_tolerance=150)
    rec = reallocation.reallocate(c, decision, econ, "run_1", scope=scope)
    assert rec.action == "not_knowable"
    assert rec.guarantee.slots["reason"] == U.NO_REPLACEMENT_COST.format(singular="click")
    assert rec.expected_loss is None and rec.params["unit"] == "clicks"


def test_stop_estimable_without_a_cost_is_not_knowable() -> None:
    c = count_comparison("orders", expected_loss={"ad_a": 3, "ad_b": 0.5})
    decision = B.feasibility("estimable", "decision_loss", available=1.0, target=150)
    data = B.funnel_data(
        {
            "ad_a": {"impressions": 2000, "clicks": 40, "spend": 50.0, "conv_obs": 2},
            "ad_b": {"impressions": 2000, "clicks": 40, "spend": 50.0, "conv_obs": 3},
        }
    )
    rec = stop_or_continue(c, decision, data, B.economics(loss_tolerance=150), "run_1")
    assert rec.action == "not_knowable" and rec.expected_loss is None
    assert U.NO_REPLACEMENT_COST.format(singular="order") in rec.guarantee.slots["reason"]


def test_allocate_without_economics_keeps_the_count_loss() -> None:
    """D30 branch unchanged (U6): no economics file, so nothing is priced."""
    c = count_comparison("clicks", cost="2", expected_loss={"ad_a": 1, "ad_b": 3})
    rec = allocation.allocate(c, "run_1")
    assert rec.action == "allocate"
    shares = rec.params["allocation"]
    want = shares["ad_a"] * 1 + shares["ad_b"] * 3
    assert rec.expected_loss is not None
    assert float(rec.expected_loss.amount) == pytest.approx(round(want, 2))
