"""Live horizon from the test budget left (D53; spec/Mismatch_Lead_Lag_Horizon_Fix_v0.2.md §3, S8
to S13). Piece L11."""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction

from bayesian_marketing.claims.vocab import fmt_count
from bayesian_marketing.core import Horizon, Money, registries
from bayesian_marketing.decision.units import fmt_unit_cost
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

HORIZON_DEFAULT_REF = "decision_defaults/horizon_default@v1"
_ALL_POLLS = 10**9  # every poll of the client; S12 reads them all each refresh


def spend_to_date(
    store: Store, client_id: str, platform: str, as_of: datetime
) -> tuple[Money | None, date | None]:
    """Total spend in the store for the client and platform as of ``as_of`` (S12): polls with
    status "ok" and ``started_at <= as_of``; per (ad, account-local date) the row of the newest
    such poll wins (ties on ``started_at`` to the greater ``poll_id``). Dates no poll's window
    covered are not counted, an undercount. Returns (total, earliest date), or (None, None) when
    there is no such row or the rows are in more than one currency (S13)."""
    polls = [
        p
        for p in store.polls(client_id, limit=_ALL_POLLS)
        if p.status == "ok" and p.platform == platform and p.started_at <= as_of
    ]
    winner: dict[tuple[str, date], tuple[tuple[datetime, str], LiveRow]] = {}
    for p in polls:
        rank = (p.started_at, p.poll_id)
        for r in store.rows(p.poll_id):
            key = (r.entity_ids.get("ad", ""), r.date)
            held = winner.get(key)
            if held is None or rank > held[0]:
                winner[key] = (rank, r)
    rows = [r for _, r in winner.values()]
    currencies = {r.spend.currency for r in rows}
    if len(currencies) != 1:
        return None, None
    total = sum((r.spend.amount for r in rows), Decimal(0))
    return Money(amount=total, currency=currencies.pop()), min(r.date for r in rows)


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
    if test_budget is None:
        return fallback(unit, WHY_NO_BUDGET)
    if spent is None or since is None:  # S13: both set or both None
        return fallback(unit, WHY_NO_SPEND)
    currency = test_budget.currency
    if spent.currency != currency or any(r.spend.currency != currency for r in window_rows):
        return fallback(unit, WHY_CURRENCY)
    remaining = test_budget.amount - spent.amount
    if remaining <= 0:
        return fallback(unit, WHY_SPENT)
    units = sum(_count(r, unit) for r in window_rows)
    cost = sum((r.spend.amount for r in window_rows), Decimal(0))
    if units <= 0 or cost <= 0:
        return fallback(unit, WHY_NO_UNITS.format(unit=unit))
    # S9: floor(remaining / (cost / units)) from the unrounded cost, exactly
    amount = math.floor(Fraction(remaining) * units / Fraction(cost))
    if amount < 1:
        return fallback(unit, WHY_UNDER_ONE.format(singular=SINGULAR[unit]))
    per_unit = cost / units
    basis = HORIZON_FROM_BUDGET.format(
        amount=fmt_count(amount),
        unit=unit,
        remaining=fmt_unit_cost(Money(amount=remaining, currency=currency)),
        budget=fmt_unit_cost(test_budget),
        since=since.isoformat(),
        per_1000=fmt_unit_cost(Money(amount=per_unit * 1000, currency=currency)),
    )
    return Horizon(unit=unit, amount=Decimal(amount)), basis  # type: ignore[arg-type]


def default_horizon(unit: str) -> Horizon:
    """The registry's default horizon amount in ``unit``, as ``live.refresh._horizon`` built it."""
    h = registries.resolve(HORIZON_DEFAULT_REF)
    return Horizon(unit=unit, amount=Decimal(str(h["amount"])))  # type: ignore[arg-type]


def fallback(unit: str, why: str) -> tuple[Horizon, str]:
    """C6: the default horizon in ``unit`` and ``HORIZON_FALLBACK`` with ``why``."""
    h = default_horizon(unit)
    return h, HORIZON_FALLBACK.format(amount=fmt_count(h.amount), unit=unit, why=why)  # type: ignore[arg-type]


def _count(r: LiveRow, unit: str) -> int:
    if unit == "impressions":
        return r.impressions
    if unit == "clicks":
        return r.clicks
    raise ValueError(f"no horizon unit {unit!r}; impressions or clicks (C5)")
