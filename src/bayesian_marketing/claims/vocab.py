"""Display formatting and parsing vocabulary shared by the G5 check and the report renderer.

Rounding comes from ``phrasing.yaml`` (``rounding``), so what the report prints and what G5
accepts are the same strings. The metric labels and aliases below are parser vocabulary and
table labels, not prose; they live here until ``phrasing.yaml`` carries them (manifest P10,
open question 2).
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

from bayesian_marketing.core import Money, Quantity, registries

RATE_NAMES = frozenset({"ctr", "cvr", "lift", "p_exceeds"})
MONEY_NAMES = frozenset({"cpa", "aov", "cpm", "cpc", "contribution_per_click", "contribution"})
RATIO_NAMES = frozenset({"roas"})

METRIC_LABELS: dict[str, str] = {
    "ctr": "click-through rate",
    "cvr": "conversion rate",
    "cpa": "cost per order",
    "roas": "return on ad spend",
    "aov": "average order value",
    "cpm": "cost per thousand impressions",
    "cpc": "cost per click",
    "contribution_per_click": "contribution per click",
    "contribution": "contribution",
    "p_exceeds": "chance of beating break-even",
    "lift": "lift over holdout",
}

METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "ctr": ("click-through rate", "click through rate", "clickthrough rate", "ctr"),
    "cvr": ("conversion rate", "cvr"),
    "cpa": ("cost per order", "cost per acquisition", "cost per conversion", "cpa"),
    "roas": ("return on ad spend", "roas"),
    "aov": ("average order value", "order value", "aov"),
    "cpm": ("cost per thousand impressions", "cost per mille", "cpm"),
    "cpc": ("cost per click", "cpc"),
    "contribution_per_click": ("contribution per click",),
    "contribution": ("contribution",),
    "p_exceeds": ("chance of beating break-even", "break-even"),
    "lift": ("lift",),
}


def phrasing() -> dict[str, Any]:
    return registries.load("phrasing")


def _rounding() -> dict[str, int]:
    return {k: int(v) for k, v in phrasing()["rounding"].items()}


def fmt_percent(x: float) -> str:
    return f"{x * 100:.{_rounding()['percent_decimals']}f}%"


def fmt_amount(x: float | Decimal) -> str:
    """A money amount at registry precision, thousands separated, no currency."""
    return f"{float(x):,.{_rounding()['money_decimals']}f}"


def fmt_money(m: Money) -> str:
    return f"{fmt_amount(m.amount)} {m.currency}"


def fmt_probability(x: float) -> str:
    return f"{x:.{_rounding()['probability_decimals']}f}"


def fmt_ratio(x: float) -> str:
    """ROAS. The registry has no ratio precision; probability_decimals is used (open question)."""
    return f"{x:.{_rounding()['probability_decimals']}f}"


def fmt_count(x: float) -> str:
    return f"{round(x):,d}"


def fmt_value(q: Quantity, x: float) -> str:
    """One summary value of a quantity, as the report prints it."""
    if q.name in RATE_NAMES:
        return fmt_percent(x)
    if q.name in MONEY_NAMES:
        return fmt_amount(x)
    return fmt_ratio(x)


def finite(x: float) -> bool:
    return isinstance(x, int | float) and math.isfinite(x)


def entities_of(q: Quantity) -> set[str]:
    return set(q.scope.ids.values())


def norm_number(s: str) -> str:
    """Strip thousands separators so '1,234' and '1234' compare equal."""
    return s.replace(",", "")
