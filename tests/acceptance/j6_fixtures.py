"""Shared fixtures for the J6 acceptance set (spec/Test_Design_Reading_Specification_v0.2.md with
J6.S1 to J6.S4).

* ``design(**over)`` is a well-formed design: E1's second draft (two arms at half each, 1,900
  accounts, a 0.30 baseline wanted ``fewer`` at an effect of 0.2, alpha 0.05, power 0.8), with no
  flow, no unit cost and a 60-day horizon in 7-day periods. Any field can be stated.
* ``units_needed_oracle`` is rules 1 and 2 written out literally over the engine's
  ``test_design.voi.sample_size_two_proportions``, for checks that hold a size against the
  formula rather than a stated golden.
* ``c1_hash`` is a second implementation of the ``bayes-design-c1`` hash written from J6.S2 (1)'s
  text alone. It does not call ``design_hash`` or ``json.dumps`` on the whole value: it walks the
  value and writes each piece itself.
* ``OpenAudit`` records, through an audit hook, every file opened and every SQLite connection made
  while it is active (check (n)).
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import sys
from typing import Any

from bayesian_marketing.test_design.voi import sample_size_two_proportions

ARMS2 = ["usual_welcome", "plain_price"]


def design(**over: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "arms": list(ARMS2),
        "control": "usual_welcome",
        "allocation": {"usual_welcome": 0.5, "plain_price": 0.5},
        "unit_kind": "account",
        "units_available": 1900,
        "units_per_period": None,
        "outcome": {
            "name": "cancellation_notice",
            "record_kinds": ["event"],
            "where": {"event": ["cancellation_notice"]},
        },
        "direction": "fewer",
        "horizon_days": 60,
        "baseline_rate": 0.30,
        "baseline_measure_id": None,
        "smallest_effect": 0.2,
        "false_positive_rate": 0.05,
        "sensitivity": 0.8,
        "randomized": True,
        "holdout": False,
        "channel": "email",
        "exposure": "repeated",
        "unit_cost": None,
        "currency": None,
        "period_days": 7,
        "kill_candidates": [],
        "economics_ref": None,
        "value_per_outcome": None,
        "run_id": None,
    }
    d.update(copy.deepcopy(over))
    return d


def equal_arms(k: int, control: str = "arm0") -> dict[str, Any]:
    """Arms, control and allocation for ``k`` arms at 1/k each, the control first."""
    arms = [control] + [f"arm{i}" for i in range(1, k)]
    return {"arms": arms, "control": control, "allocation": {a: 1 / k for a in arms}}


def shares(control: str, alloc: dict[str, float]) -> dict[str, Any]:
    """Arms, control and allocation from a stated allocation (insertion order)."""
    return {"arms": list(alloc), "control": control, "allocation": dict(alloc)}


def p2_of(p1: float, e: float, direction: str) -> float:
    return p1 * (1 + e) if direction == "more" else p1 * (1 - e)


def units_needed_oracle(
    p1: float,
    e: float,
    direction: str,
    allocation: dict[str, float],
    control: str,
    alpha: float = 0.05,
    power: float = 0.8,
) -> int | None:
    """Rules 1 and 2: N(e), or None when p2 is outside (0, 1)."""
    p2 = p2_of(p1, e, direction)
    if not 0 < p2 < 1:
        return None
    k = len(allocation)
    n = math.ceil(sample_size_two_proportions(p1, p2, alpha / (k - 1), power))
    sc = allocation[control]
    return max(math.ceil(n / min(sc, sa) - 1e-9) for a, sa in allocation.items() if a != control)


# ------------------------------------------------------------------- bayes-design-c1, a second hand


def _c1_write(v: Any) -> str:
    """J6.S2 (1) (b) and (c), written piece by piece."""
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            raise ValueError("NaN and infinity never occur")
        if v == int(v):
            return str(int(v))
        return repr(v)
    if isinstance(v, str):
        # A JSON string with non-ASCII left as it is.
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return "[" + ",".join(_c1_write(x) for x in v) + "]"
    if isinstance(v, dict):
        keys = sorted(v, key=lambda s: [ord(c) for c in s])
        return "{" + ",".join(_c1_write(k) + ":" + _c1_write(v[k]) for k in keys) + "}"
    raise TypeError(f"not JSON-native: {type(v).__name__}")


def c1_hash(v: dict[str, Any]) -> str:
    """J6.S2 (1) (d): lowercase hex SHA-256 of the UTF-8 bytes."""
    return hashlib.sha256(_c1_write(v).encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------------- check (n)

_ACTIVE: list[OpenAudit] = []
_HOOKED = False


def _hook(event: str, args: tuple[Any, ...]) -> None:
    if not _ACTIVE:
        return
    if event == "open":
        path = args[0]
        if isinstance(path, (str, bytes)) or hasattr(path, "__fspath__"):
            for a in _ACTIVE:
                a.opened.append(str(path if not isinstance(path, bytes) else path.decode()))
    elif event == "sqlite3.connect":
        for a in _ACTIVE:
            a.sqlite.append(str(args[0]) if args else "")


class OpenAudit:
    """``with OpenAudit() as a:`` records ``a.opened`` (paths) and ``a.sqlite`` (connections)."""

    def __init__(self) -> None:
        self.opened: list[str] = []
        self.sqlite: list[str] = []

    def __enter__(self) -> OpenAudit:
        global _HOOKED
        if not _HOOKED:
            sys.addaudithook(_hook)
            _HOOKED = True
        _ACTIVE.append(self)
        return self

    def __exit__(self, *exc: object) -> None:
        _ACTIVE.remove(self)


def json_native(v: Any) -> bool:
    if v is None or isinstance(v, (bool, int, str)):
        return True
    if isinstance(v, float):
        return math.isfinite(v)
    if isinstance(v, list):
        return all(json_native(x) for x in v)
    if isinstance(v, dict):
        return all(isinstance(k, str) and json_native(x) for k, x in v.items())
    return False


def strings_in(v: Any) -> list[str]:
    """Every string value at any depth (dict keys left out)."""
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        return [s for x in v for s in strings_in(x)]
    if isinstance(v, dict):
        return [s for x in v.values() for s in strings_in(x)]
    return []
