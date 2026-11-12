"""Live horizon from the test budget left (D53; spec/Mismatch_Lead_Lag_Horizon_Fix_v0.2.md §3, S8
to S13). Piece L11."""

from __future__ import annotations

from datetime import date, datetime

from bayesian_marketing.core import Horizon, Money
from bayesian_marketing.live.contracts import LiveRow, Store

HORIZON_FROM_BUDGET = (
    "horizon: {amount} {unit}, the {remaining} left of the {budget} test budget "
    "(spend counted since {since}) at {per_1000} per 1,000 {unit}"
)
HORIZON_FALLBACK = "horizon: the default {amount} {unit}, because {why}"

WHY_NO_BUDGET = "no test budget is set in the economics file"
WHY_NO_SPEND = (
    "no spend to date could be read from the store (none recorded, or in more than one currency)"
)
WHY_CURRENCY = "the budget and the spend are in different currencies"
WHY_SPENT = "the test budget is spent"
WHY_NO_UNITS = "no {unit} in the window to price the budget"
WHY_UNDER_ONE = "less than one {singular} of budget is left"
WHY_NO_ECONOMICS = "the economics file could not be read"

SINGULAR = {"impressions": "impression", "clicks": "click"}  # S11


def spend_to_date(
    store: Store, client_id: str, platform: str, as_of: datetime
) -> tuple[Money | None, date | None]:
    """Total spend in the store for the client and platform as of ``as_of`` (S12): polls with
    status "ok" and ``started_at <= as_of``; per (ad, account-local date) the row of the newest
    such poll wins (ties on ``started_at`` to the greater ``poll_id``). Dates no poll's window
    covered are not counted, an undercount. Returns (total, earliest date), or (None, None) when
    there is no such row or the rows are in more than one currency (S13)."""
    raise NotImplementedError


def budget_horizon(
    test_budget: Money | None,
    spent: Money | None,
    since: date | None,
    window_rows: list[LiveRow],
    unit: str,
) -> tuple[Horizon, str]:
    """D53: the budget left, converted to ``unit`` at the observed cost per unit pooled over
    ``window_rows`` (§3 C5); the registry default with ``HORIZON_FALLBACK`` otherwise (C6).
    Returns the horizon and its basis sentence."""
    raise NotImplementedError
