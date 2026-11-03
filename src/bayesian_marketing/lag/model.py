"""§5.6 lag_model and mature_fraction."""

from __future__ import annotations

from datetime import date

from bayesian_marketing.core import LagModel, OrderRow, Platform


def lag_model(
    platform: Platform,
    window_code: str,
    history: list[OrderRow] | None,
    lag_report: list[dict] | None,
) -> LagModel:
    """Estimate the lag CDF, or fall back to the registry default with a notice (C1)."""
    raise NotImplementedError("P7")


def mature_fraction(click_date: date, as_of: date, lag: LagModel) -> float:
    """F(as_of - click_date) from the lag CDF."""
    raise NotImplementedError("P7")
