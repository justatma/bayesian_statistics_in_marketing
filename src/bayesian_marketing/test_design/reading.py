"""Reading a proposed test, ``read_test_design`` (J6; spec/Test_Design_Reading_Specification_v0.2.md
with J6.S1 to J6.S5, which govern where they differ from the text above them). A pure function of
the design and the registries: it reads no store, run, notebook or file under ``data_dir()``,
never mutates its input, and gives no free text."""

from __future__ import annotations

import hashlib
import json
import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from bayesian_marketing import __version__
from bayesian_marketing.core import registries
from bayesian_marketing.test_design.voi import sample_size_two_proportions

MAX_PERIODS = 12
"""J6.S4, rule 11 (b): the longest run the ``longer_run`` remedy offers. An engineering choice."""

HASH_FORM = "bayes-design-c1"
"""J6.S2 (1)."""

WIDTH_REF = "bounds/estimability/posterior_width@v1"

ANSWERABLE = ("estimable", "marginal", "below_floor")
REMEDIES = ("coarser_comparison", "longer_run", "larger_group")

READING_KEYS = (
    "answerable",
    "units_needed",
    "units_needed_marginal",
    "periods_needed",
    "kill_metric_measure_id",
    "stopping_rule",
    "remedy",
    "remedy_amount",
    "value_of_answer",
    "cost_of_test",
    "cost_low",
    "cost_high",
    "currency",
    "unit_kind",
    "rule_ref",
    "engine_version",
    "inputs_hash",
)
"""The reading's exact keys (spec, "The reading")."""

DESIGN_KEYS = (
    "arms",
    "control",
    "allocation",
    "unit_kind",
    "units_available",
    "units_per_period",
    "outcome",
    "direction",
    "horizon_days",
    "baseline_rate",
    "baseline_measure_id",
    "smallest_effect",
    "false_positive_rate",
    "sensitivity",
    "randomized",
    "holdout",
    "channel",
    "exposure",
    "unit_cost",
    "currency",
    "period_days",
    "kill_candidates",
    "economics_ref",
    "value_per_outcome",
    "run_id",
)
"""Every key a design must carry, and no others (spec, Inputs; J6.S1 (1))."""


# ------------------------------------------------------------------------------------ references


def rule_ref() -> list[str]:
    """J6.S4 and J6.S5 (3): the references a reading cites."""
    return [WIDTH_REF, f"engine:test_design.reading.MAX_PERIODS@{__version__}"]


def _engine_version() -> str:
    return f"bayesian-marketing {__version__}"


def _width() -> tuple[float, float]:
    """``rel_half_width`` and ``caveat_rel_half_width``, read from the registry at call time."""
    pw = registries.resolve(WIDTH_REF)
    return float(pw["rel_half_width"]), float(pw["caveat_rel_half_width"])


# ------------------------------------------------------------------------------------------ hash


def _normalise(v: Any) -> Any:
    """J6.S2 (1) (b): a whole number as an integer, a bool never as a number."""
    if v is None or isinstance(v, (bool, str)):
        return v
    if isinstance(v, int):
        return int(v)
    if isinstance(v, float):
        return int(v) if v == int(v) else v
    if isinstance(v, list):
        return [_normalise(x) for x in v]
    if isinstance(v, dict):
        return {k: _normalise(x) for k, x in v.items()}
    raise ValueError(f"not JSON-native: {type(v).__name__}")


def design_hash(design: dict[str, Any]) -> str:
    """J6.S2 (1): the design's hash under ``bayes-design-c1``."""
    text = json.dumps(
        _normalise(design),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------------ validation


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


COUNT_MAX = 10**12
"""J6.S6: the largest count or unit cost read; anything above is refused, naming the field."""
RATE_EDGE = 1e-9
"""J6.S6: alpha and power lie in [RATE_EDGE, 1 - RATE_EDGE]."""


def _utf8(key: str, s: str) -> None:
    """J6.S6: a string must encode as UTF-8 (no lone surrogate)."""
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(f"{key}: not valid Unicode text") from None


def _num(d: dict[str, Any], key: str, *, null: bool = False) -> Any:
    v = d[key]
    if v is None and null:
        return None
    if not _is_num(v):
        raise ValueError(f"{key}: a number is wanted, not {type(v).__name__}")
    if isinstance(v, int) and abs(v) > COUNT_MAX:  # J6.S6: before any float conversion
        raise ValueError(f"{key}: must be at most {COUNT_MAX} in size")
    if not math.isfinite(v):
        raise ValueError(f"{key}: NaN or infinity")
    return v


def _count(d: dict[str, Any], key: str, *, low: int = 0, null: bool = False) -> int | None:
    v = d[key]
    if v is None and null:
        return None
    if _is_num(v) and isinstance(v, int) and v > COUNT_MAX:  # J6.S6: before any float use
        raise ValueError(f"{key}: must be at most {COUNT_MAX}")
    if not _is_num(v) or not math.isfinite(v) or v != int(v):
        raise ValueError(f"{key}: an integer is wanted")
    if v < low:
        raise ValueError(f"{key}: must be at least {low}")
    if v > COUNT_MAX:
        raise ValueError(f"{key}: must be at most {COUNT_MAX}")
    return int(v)


def _str(d: dict[str, Any], key: str, *, null: bool = False) -> str | None:
    v = d[key]
    if v is None and null:
        return None
    if not isinstance(v, str):
        raise ValueError(f"{key}: a string is wanted")
    _utf8(key, v)
    return v


def _bool(d: dict[str, Any], key: str) -> bool:
    v = d[key]
    if not isinstance(v, bool):
        raise ValueError(f"{key}: a bool is wanted")
    return v


def _json_native(key: str, v: Any) -> None:
    """Refuse NaN, infinity and non-JSON values at any depth (J6.S2 (1) (b))."""
    if isinstance(v, str):
        _utf8(key, v)
        return
    if v is None or isinstance(v, (bool, int)):
        return
    if isinstance(v, float):
        if not math.isfinite(v):
            raise ValueError(f"{key}: NaN or infinity")
        return
    if isinstance(v, list):
        for x in v:
            _json_native(key, x)
        return
    if isinstance(v, dict):
        for k, x in v.items():
            if not isinstance(k, str):
                raise ValueError(f"{key}: object keys must be strings")
            _utf8(key, k)
            _json_native(key, x)
        return
    raise ValueError(f"{key}: not a JSON value ({type(v).__name__})")


def _validate(design: Any) -> None:
    """Spec, Inputs and Refused. Raises ``ValueError`` naming the field."""
    if not isinstance(design, dict):
        raise ValueError("design: a JSON object is wanted")
    for key in DESIGN_KEYS:
        if key not in design:
            raise ValueError(f"{key}: missing")
    unknown = sorted(str(k) for k in design if k not in DESIGN_KEYS)
    if unknown:
        raise ValueError(f"{unknown[0]}: unknown key")

    arms = design["arms"]
    if not isinstance(arms, list) or not all(isinstance(a, str) for a in arms):
        raise ValueError("arms: a list of strings is wanted")
    if len(arms) < 2:
        raise ValueError("arms: two or more are wanted")
    if len(set(arms)) != len(arms):
        raise ValueError("arms: a duplicate arm")
    if _str(design, "control") not in arms:
        raise ValueError("control: not among the arms")

    alloc = design["allocation"]
    if not isinstance(alloc, dict):
        raise ValueError("allocation: an object is wanted")
    for a, s in alloc.items():
        if not _is_num(s) or not math.isfinite(s):
            raise ValueError(f"allocation: the share of {a!r} is not a finite number")
    if set(alloc) != set(arms):
        raise ValueError("allocation: its keys must equal the arms")
    if any(s <= 0 for s in alloc.values()):
        raise ValueError("allocation: every share must be above 0")
    if abs(math.fsum(alloc.values()) - 1) > 1e-9:
        raise ValueError("allocation: the shares must sum to 1")

    _str(design, "unit_kind")
    _count(design, "units_available")
    _count(design, "units_per_period", null=True)
    if not isinstance(design["outcome"], dict):
        raise ValueError("outcome: an object is wanted")
    _json_native("outcome", design["outcome"])
    if design["direction"] not in ("more", "fewer"):
        raise ValueError("direction: 'more' or 'fewer' is wanted")
    _count(design, "horizon_days")
    b = _num(design, "baseline_rate", null=True)
    if b is not None and not 0 <= b <= 1:
        raise ValueError("baseline_rate: must lie in [0, 1]")
    _str(design, "baseline_measure_id", null=True)
    if _num(design, "smallest_effect") <= 0:
        raise ValueError("smallest_effect: must be above 0")
    for key in ("false_positive_rate", "sensitivity"):
        if not RATE_EDGE <= _num(design, key) <= 1 - RATE_EDGE:
            raise ValueError(f"{key}: must lie in [{RATE_EDGE:g}, 1 - {RATE_EDGE:g}]")
    _bool(design, "randomized")
    _bool(design, "holdout")
    _str(design, "channel")
    _str(design, "exposure")
    c = _num(design, "unit_cost", null=True)
    if c is not None and c < 0:
        raise ValueError("unit_cost: must be 0 or more")
    if c is not None and c > COUNT_MAX:
        raise ValueError(f"unit_cost: must be at most {COUNT_MAX}")
    _str(design, "currency", null=True)
    _count(design, "period_days", low=1)
    kc = design["kill_candidates"]
    if not isinstance(kc, list) or not all(isinstance(x, str) for x in kc):
        raise ValueError("kill_candidates: a list of strings is wanted")
    _str(design, "economics_ref", null=True)
    if not isinstance(design["value_per_outcome"], str):
        _num(design, "value_per_outcome", null=True)
    _str(design, "run_id", null=True)


# -------------------------------------------------------------------------------------- the rule


def _size(
    p1: float,
    e: float,
    direction: str,
    alloc: dict[str, float],
    control: str,
    alpha_total: float,
    power: float,
) -> int | None:
    """Rules 1 and 2: N(e) over ``alloc`` (the control and the arms compared with it), or None
    when p2 is not strictly inside (0, 1)."""
    p2 = p1 * (1 + e) if direction == "more" else p1 * (1 - e)
    if not 0 < p2 < 1 or p2 == p1:
        return None
    alpha = alpha_total / (len(alloc) - 1)
    n = math.ceil(sample_size_two_proportions(p1, p2, alpha, power))
    sc = alloc[control]
    return max(math.ceil(n / min(sc, sa) - 1e-9) for a, sa in alloc.items() if a != control)


def _kept(alloc: dict[str, float], control: str, m: int) -> dict[str, float]:
    """Rule 11 (a): the control and the m - 1 largest non-control arms (ties by key in
    code-point order), shares renormalised over the kept arms."""
    others = sorted((a for a in alloc if a != control), key=lambda a: (-alloc[a], a))
    keep = [control, *others[: m - 1]]
    total = math.fsum(alloc[a] for a in keep)
    return {a: alloc[a] / total for a in keep}


def _cost(unit_cost: float, exposed: int) -> float:
    """J6.S3: half up to cents, on the decimal the unit cost's double stands for."""
    dec = Decimal(unit_cost) if isinstance(unit_cost, int) else Decimal(repr(unit_cost))
    return float((dec * exposed).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def read_test_design(design: dict[str, Any]) -> dict[str, Any]:
    """J6: the reading of a proposed test. Raises ``ValueError`` naming the field on a malformed
    design; a well-formed design that can't answer is a reading."""
    _validate(design)
    inputs_hash = design_hash(design)
    rel, caveat = _width()
    ratio = caveat / rel

    alloc = {a: design["allocation"][a] for a in design["arms"]}
    control = design["control"]
    direction = design["direction"]
    e = design["smallest_effect"]
    alpha = design["false_positive_rate"]
    power = design["sensitivity"]
    randomized = design["randomized"]
    available = int(design["units_available"])
    flow = None if design["units_per_period"] is None else int(design["units_per_period"])
    period_days = int(design["period_days"])
    horizon = int(design["horizon_days"])
    p1 = design["baseline_rate"]

    needed = marginal = periods = remedy = amount = cost = stopping = None
    if p1 is not None and 0 < p1 < 1:
        needed = _size(p1, e, direction, alloc, control, alpha, power)
    if needed is None:
        answerable = "below_floor"  # rule 6
    else:
        marginal = _size(p1, e * ratio, direction, alloc, control, alpha, power)
        if not randomized:
            answerable = "below_floor"  # rule 8
        elif available >= needed:
            answerable = "estimable"
        elif marginal is not None and available >= marginal:
            answerable = "marginal"
        else:
            answerable = "below_floor"

        # Rules 9, 10 and 12.
        enrol: int | None
        if available >= needed:
            enrol = 0
        elif flow:
            enrol = period_days * math.ceil((needed - available) / flow)
        else:
            enrol = None
        if enrol is not None:
            periods = max(1, math.ceil((enrol + horizon) / period_days))
            stopping = {"kind": "fixed_horizon", "max_periods": periods, "kill_threshold": None}

        # Rule 11.
        if answerable != "estimable" and randomized:
            for m in range(len(alloc) - 1, 1, -1):
                n_kept = _size(p1, e, direction, _kept(alloc, control, m), control, alpha, power)
                if n_kept is not None and available >= n_kept:
                    remedy, amount = "coarser_comparison", m
                    break
            else:
                if flow and periods is not None and periods <= MAX_PERIODS:
                    remedy, amount = "longer_run", periods
                else:
                    remedy, amount = "larger_group", needed

        # Rule 13 and J6.S3.
        if design["unit_cost"] is not None:
            exposed = needed
            if design["holdout"]:
                exposed = math.ceil(needed * (1 - alloc[control]) - 1e-9)
            cost = _cost(design["unit_cost"], exposed)

    reading = {
        "answerable": answerable,
        "units_needed": needed,
        "units_needed_marginal": marginal,
        "periods_needed": periods,
        "kill_metric_measure_id": None,
        "stopping_rule": stopping,
        "remedy": remedy,
        "remedy_amount": amount,
        "value_of_answer": None,  # rule 14
        "cost_of_test": cost,
        "cost_low": cost,
        "cost_high": cost,
        "currency": design["currency"],
        "unit_kind": design["unit_kind"],
        "rule_ref": rule_ref(),
        "engine_version": _engine_version(),
        "inputs_hash": inputs_hash,
    }
    return {k: reading[k] for k in READING_KEYS}


def read_test_design_rule() -> dict[str, Any]:
    """J6.S2 (2): ``rel_half_width``, ``caveat_rel_half_width``, ``ratio``, ``max_periods``,
    ``rule_ref``, ``hash_form`` and ``engine_version``."""
    rel, caveat = _width()
    return {
        "rel_half_width": rel,
        "caveat_rel_half_width": caveat,
        "ratio": caveat / rel,
        "max_periods": MAX_PERIODS,
        "rule_ref": rule_ref(),
        "hash_form": HASH_FORM,
        "engine_version": _engine_version(),
    }
