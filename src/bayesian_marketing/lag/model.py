"""§5.6 lag_model and mature_fraction.

Estimated curve (C1): the empirical CDF of whole-day lags ``(ordered_at - first_click_at).days``
over the orders that carry ``first_click_at`` (negative lags are dropped), used when at least
``bounds/lag/min_lagged_conversions`` orders qualify. ``cdf[a]`` is the share of lags <= a, for
a = 0..max observed lag, so ``cdf[-1]`` is 1.

Default curve (§14 "default lag curves"): geometric with median 1 day for 1-day click windows, 2
for 7-day, 4 for 28-day, in the convention F(a) = 1 - (1 - p)^(a + 1) with F(median) = 0.5. The
curve runs over a = 0..window days and is normalised by F(window), because the platform reports
only conversions inside its click window, so a cohort is complete once the window has passed. The
medians are read from ``bounds/lag/default_median_days`` when the registry carries that key (open
question: it does not yet), else from the §14 table below. ``notices(lag)`` gives the
"conversion lag assumed" notice for a default curve.

Platform days-to-conversion reports have no verified format in the facts packs (F3 lists Google's
``segments.days_to_conversion`` as absent), so a non-empty ``lag_report`` is refused.
"""

from __future__ import annotations

import re
from datetime import date

from bayesian_marketing.core import LagModel, OrderRow, Platform, registries

# §14 registry-defaults table: click-window days -> geometric median days. Used only while the
# bounds registry lacks lag.default_median_days (open question for the integrator).
SPEC_DEFAULT_MEDIANS: dict[int, int] = {1: 1, 7: 2, 28: 4}

_CLICK_WINDOW = re.compile(r"^(\d+)d_click")


def _min_lagged() -> int:
    return int(registries.resolve("bounds/lag/min_lagged_conversions@v1"))


def _default_medians() -> dict[int, int]:
    lag = registries.load("bounds").get("lag", {})
    table = lag.get("default_median_days") if isinstance(lag, dict) else None
    if isinstance(table, dict) and table:
        return {int(k): int(v) for k, v in table.items()}
    return dict(SPEC_DEFAULT_MEDIANS)


def _window_and_median(window_code: str) -> tuple[int, int]:
    """Click-window days and default median for a window code.

    A window between table rows takes the next longer row's median; a window past the table, or a
    code with no click window ("none", "property_setting", "per_conversion_action"), takes the
    longest row (slowest lag, so the lowest mature fractions).
    """
    table = _default_medians()
    longest = max(table)
    m = _CLICK_WINDOW.match(window_code)
    if m is None:
        return longest, table[longest]
    days = int(m.group(1))
    for w in sorted(table):
        if days <= w:
            return days, table[w]
    return days, table[longest]


def _geometric_cdf(median: int, window: int) -> list[float]:
    q = 0.5 ** (1.0 / (median + 1))  # 1 - p, so that F(median) = 0.5
    raw = [1.0 - q ** (a + 1) for a in range(window + 1)]
    top = raw[-1]
    cdf = [min(1.0, v / top) for v in raw]
    cdf[-1] = 1.0
    return cdf


def _lags(history: list[OrderRow] | None) -> list[int]:
    out: list[int] = []
    for row in history or []:
        if row.first_click_at is None:
            continue
        days = (row.ordered_at - row.first_click_at).days
        if days >= 0:
            out.append(days)
    return out


def _empirical_cdf(lags: list[int]) -> list[float]:
    n = len(lags)
    counts = [0] * (max(lags) + 1)
    for v in lags:
        counts[v] += 1
    cdf, run = [], 0
    for c in counts:
        run += c
        cdf.append(run / n)
    cdf[-1] = 1.0
    return cdf


def lag_model(
    platform: Platform,
    window_code: str,
    history: list[OrderRow] | None,
    lag_report: list[dict] | None,
) -> LagModel:
    """Estimate the lag CDF, or fall back to the registry default with a notice (C1)."""
    if lag_report:
        raise ValueError(
            "platform lag reports have no verified format in the facts packs; pass orders history"
        )
    lags = _lags(history)
    if len(lags) >= _min_lagged():
        return LagModel(
            platform=platform,
            attribution_window=window_code,
            cdf=_empirical_cdf(lags),
            source="orders_history",
            n_lagged_conversions=len(lags),
        )
    window, median = _window_and_median(window_code)
    return LagModel(
        platform=platform,
        attribution_window=window_code,
        cdf=_geometric_cdf(median, window),
        source="registry_default",
        n_lagged_conversions=len(lags),
    )


def notices(lag: LagModel) -> list[str]:
    """§5.6 C1: a default curve carries "conversion lag assumed"."""
    if lag.source == "registry_default":
        return [registries.resolve("phrasing/notices/lag_assumed@v1")]
    return []


def mature_fraction(click_date: date, as_of: date, lag: LagModel) -> float:
    """F(as_of - click_date) from the lag CDF; cdf[-1] beyond the curve."""
    a = (as_of - click_date).days
    if a < 0:
        raise ValueError(f"click date {click_date} is after as_of {as_of}")
    return float(lag.cdf[a]) if a < len(lag.cdf) else float(lag.cdf[-1])
