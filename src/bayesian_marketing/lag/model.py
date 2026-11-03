"""§5.6 lag_model, mature_fraction and lag_notices.

Day convention (D27.1): a lag in whole days is the difference of calendar dates in the account
timezone (UTC when unknown), ``ordered_at.date() - first_click_at.date()`` after converting both to
that zone. A click at 23:30 and an order at 00:30 the next day is a lag of 1. ``mature_fraction``
indexes the CDF by the same date difference, ``(as_of - click_date).days``.

Estimated curve (C1): the empirical CDF of those lags over orders that carry ``first_click_at``
(negative lags dropped), used when at least ``bounds/lag/min_lagged_conversions`` orders qualify.
``cdf[a]`` is the share of lags <= a for a = 0..max observed lag, so ``cdf[-1]`` is 1. When
``as_of`` is given, orders whose click date is fewer than click-window days before ``as_of`` are
dropped first (right-censoring: their late conversions have not arrived yet).

Default curve (§14, D27.2, D27.3): geometric with the median read from
``bounds/lag/default_median_days`` for the code's click window. The registry median is the median of
the untruncated geometric, F(a) = 1 - (1 - p)^(a + 1) with F(median) = 0.5. The curve is then
truncated at the click window and renormalised by F(window), because a platform attributes no
conversion after its window; so the attributed median can sit a day earlier than the registry
median (1-day window: day 0). A default curve carries the "conversion lag assumed" notice, which
callers get from ``lag_notices(lag)`` since ``LagModel`` has no notice field.

A window code must name a click window that is a row of the registry table (``1d_click``,
``7d_click_1d_view``, ``28d_click``...); any other code raises ValueError rather than borrowing a
row.

Platform days-to-conversion reports have no verified format in the facts packs (F3 lists Google's
``segments.days_to_conversion`` as absent). With enough history the report is kept on record under
``<BAYES_DATA_DIR>/lag_reports/`` and the history is used; without it, a non-empty report is
refused.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from bayesian_marketing.core import LagModel, OrderRow, Platform, inputs_hash, registries

DEFAULT_DATA_DIR = "data/generated"
UTC_ZONE = "UTC"

_CLICK_WINDOW = re.compile(r"^(\d+)d_click(?:_|$)")


def _min_lagged() -> int:
    return int(registries.resolve("bounds/lag/min_lagged_conversions@v1"))


def _default_medians() -> dict[int, int]:
    table = registries.resolve("bounds/lag/default_median_days@v1")
    return {int(k): int(v) for k, v in table.items()}


def _click_window_days(window_code: str) -> int:
    m = _CLICK_WINDOW.match(window_code)
    if m is None or int(m.group(1)) <= 0:
        raise ValueError(f"window code {window_code!r} names no click window")
    return int(m.group(1))


def _window_and_median(window_code: str) -> tuple[int, int]:
    days = _click_window_days(window_code)
    table = _default_medians()
    if days not in table:
        raise ValueError(
            f"no default lag median for a {days}-day click window ({window_code!r}); "
            f"registry rows: {sorted(table)}"
        )
    return days, table[days]


def _geometric_cdf(median: int, window: int) -> list[float]:
    """Untruncated median ``median`` (D27.2), truncated at ``window`` and renormalised."""
    q = 0.5 ** (1.0 / (median + 1))  # 1 - p, so that the untruncated F(median) = 0.5
    raw = [1.0 - q ** (a + 1) for a in range(window + 1)]
    top = raw[-1]
    cdf = [min(1.0, v / top) for v in raw]
    cdf[-1] = 1.0
    return cdf


def _local_date(ts: datetime, zone: ZoneInfo, order_id: str, field: str) -> date:
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError(
            f"order {order_id!r}: {field} is a naive datetime; timestamps must carry tz"
        )
    return ts.astimezone(zone).date()


def _lags(history: list[OrderRow] | None, zone: ZoneInfo, cutoff: date | None) -> list[int]:
    """Calendar-date lags (D27.1); clicks after ``cutoff`` are right-censored and dropped."""
    out: list[int] = []
    for row in history or []:
        if row.first_click_at is None:
            continue
        clicked = _local_date(row.first_click_at, zone, row.order_id, "first_click_at")
        ordered = _local_date(row.ordered_at, zone, row.order_id, "ordered_at")
        if cutoff is not None and clicked > cutoff:
            continue
        days = (ordered - clicked).days
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


def _keep_report(platform: Platform, window_code: str, lag_report: list[dict]) -> None:
    payload = {"platform": platform, "window": window_code, "report": lag_report}
    root = Path(os.environ.get("BAYES_DATA_DIR", DEFAULT_DATA_DIR)) / "lag_reports"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{inputs_hash(payload)[:8]}.json"
    if not path.exists():
        path.write_text(json.dumps(payload, sort_keys=True, default=str))


def lag_model(
    platform: Platform,
    window_code: str,
    history: list[OrderRow] | None,
    lag_report: list[dict] | None,
    *,
    timezone: str | None = None,
    as_of: date | None = None,
) -> LagModel:
    """Estimate the lag CDF, or fall back to the registry default with a notice (C1).

    ``timezone`` is the account's IANA zone (UTC when None, D27.1). ``as_of``, when given, drops
    right-censored orders: those clicked fewer than click-window days before it.
    """
    zone = ZoneInfo(timezone or UTC_ZONE)
    cutoff = None
    if as_of is not None:
        cutoff = as_of - timedelta(days=_click_window_days(window_code))
    lags = _lags(history, zone, cutoff)
    if len(lags) >= _min_lagged():
        if lag_report:
            _keep_report(platform, window_code, lag_report)
        return LagModel(
            platform=platform,
            attribution_window=window_code,
            cdf=_empirical_cdf(lags),
            source="orders_history",
            n_lagged_conversions=len(lags),
        )
    if lag_report:
        raise ValueError(
            "too little orders history and platform lag reports have no verified format in the "
            "facts packs; cannot estimate the lag from the report"
        )
    window, median = _window_and_median(window_code)
    return LagModel(
        platform=platform,
        attribution_window=window_code,
        cdf=_geometric_cdf(median, window),
        source="registry_default",
        n_lagged_conversions=len(lags),
    )


def lag_notices(lag: LagModel) -> list[str]:
    """§5.6 C1: a default curve carries "conversion lag assumed" (truncated geometric, D27.2)."""
    if lag.source == "registry_default":
        return [registries.resolve("phrasing/notices/lag_assumed@v1")]
    return []


def mature_fraction(click_date: date, as_of: date, lag: LagModel) -> float:
    """F(as_of - click_date) from the lag CDF; cdf[-1] beyond the curve; 0 for a future click."""
    a = (as_of - click_date).days
    if a < 0:
        return 0.0  # D27.4
    return float(lag.cdf[a]) if a < len(lag.cdf) else float(lag.cdf[-1])
