"""L11 unit checks beyond the frozen tests: points the writer left unpinned (manifest points 9 and
13), the refresh default left as it was, and an unknown unit refused."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from tests.acceptance.test_L11 import T0, D, add_poll, row, usd
from tests.fakes.live import FakeStore

from bayesian_marketing import core as C
from bayesian_marketing.live import horizon as H
from bayesian_marketing.live import refresh as R


def test_superseded_row_in_another_currency_is_not_counted() -> None:
    """Writer point 9: only the winning rows' currencies matter."""
    store = FakeStore()
    add_poll(store, T0, [("ad_a", D[1], 5)], currency="EUR")
    add_poll(store, T0 + dt.timedelta(hours=1), [("ad_a", D[1], 7)])
    spent, since = H.spend_to_date(store, "budget_client", "meta", T0 + dt.timedelta(hours=1))
    assert spent == usd(7)
    assert since == D[1]


def test_spent_without_since_reads_as_no_spend() -> None:
    """Writer point 13: S13 says both set or both None; one without the other is no spend."""
    h, basis = H.budget_horizon(usd(1500), usd(10), None, [row("ad_a", D[7], 10)], "impressions")
    assert (h, basis) == H.fallback("impressions", H.WHY_NO_SPEND)


def test_refresh_default_horizon_unchanged() -> None:
    assert R._horizon() == C.Horizon(unit="impressions", amount=Decimal(1000))
    assert H.default_horizon("clicks") == C.Horizon(unit="clicks", amount=Decimal(1000))


def test_unknown_unit_is_refused() -> None:
    with pytest.raises(ValueError):
        H.budget_horizon(usd(1500), usd(10), D[7], [row("ad_a", D[7], 10)], "orders")


def test_whole_amount_has_no_fraction() -> None:
    """C5: an exact division still gives an integer Decimal (90 left at 0.10 a click)."""
    h, basis = H.budget_horizon(
        usd(100), usd(10), D[7], [row("ad_a", D[7], 5, clicks=50)], "clicks"
    )
    assert str(h.amount) == "900"
    assert basis.startswith("horizon: 900 clicks, the 90.00 USD left of the 100.00 USD")
