"""Blind review of J6 at 9530a4e. A second implementation of rules 1 to 14 and of
bayes-design-c1, written from the spec text alone, held against read_test_design over random and
edge designs; then refusals, purity and the process path."""

from __future__ import annotations

import copy
import decimal
import hashlib
import json
import math
import os
import random
import subprocess
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
from tests.acceptance.j6_fixtures import OpenAudit, design, equal_arms, json_native

from bayesian_marketing.atmaos import socket as sock
from bayesian_marketing.test_design import reading as R
from bayesian_marketing.test_design.voi import sample_size_two_proportions as ss

pytestmark = pytest.mark.piece("J6")
REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- a second implementation (spec only)
def _N(p1, e, dirn, shares, control, alpha, power):
    p2 = p1 * (1 + e) if dirn == "more" else p1 * (1 - e)
    if not (0 < p2 < 1) or p2 == p1:
        return None
    k = len(shares)
    n = math.ceil(ss(p1, p2, alpha / (k - 1), power))
    tot = 0
    for a, s in shares.items():
        if a == control:
            continue
        tot = max(tot, math.ceil(n / min(shares[control], s) - 1e-9))
    return tot


def second(d):
    ratio = 0.4 / 0.2
    sh = {a: d["allocation"][a] for a in d["arms"]}
    c = d["control"]
    p1 = d["baseline_rate"]
    out = dict.fromkeys(R.READING_KEYS)
    out["currency"], out["unit_kind"] = d["currency"], d["unit_kind"]
    if p1 is None or p1 <= 0 or p1 >= 1:
        out["answerable"] = "below_floor"
        return out
    n1 = _N(
        p1, d["smallest_effect"], d["direction"], sh, c, d["false_positive_rate"], d["sensitivity"]
    )
    if n1 is None:
        out["answerable"] = "below_floor"
        return out
    n2 = _N(
        p1,
        d["smallest_effect"] * ratio,
        d["direction"],
        sh,
        c,
        d["false_positive_rate"],
        d["sensitivity"],
    )
    out["units_needed"], out["units_needed_marginal"] = n1, n2
    av = d["units_available"]
    if not d["randomized"]:
        w = "below_floor"
    elif av >= n1:
        w = "estimable"
    elif n2 is not None and av >= n2:
        w = "marginal"
    else:
        w = "below_floor"
    out["answerable"] = w
    flow = d["units_per_period"]
    pd = d["period_days"]
    days = 0 if av >= n1 else (pd * math.ceil((n1 - av) / flow) if flow else None)
    per = None if days is None else max(1, math.ceil((days + d["horizon_days"]) / pd))
    out["periods_needed"] = per
    if per is not None:
        out["stopping_rule"] = {"kind": "fixed_horizon", "max_periods": per, "kill_threshold": None}
    if d["randomized"] and w != "estimable":
        done = False
        others = sorted([a for a in sh if a != c], key=lambda a: (-sh[a], a))
        for m in range(len(sh) - 1, 1, -1):
            keep = [c] + others[: m - 1]
            tot = sum(sh[a] for a in keep)
            ks = {a: sh[a] / tot for a in keep}
            nk = _N(
                p1,
                d["smallest_effect"],
                d["direction"],
                ks,
                c,
                d["false_positive_rate"],
                d["sensitivity"],
            )
            if nk is not None and av >= nk:
                out["remedy"], out["remedy_amount"], done = "coarser_comparison", m, True
                break
        if not done:
            if flow and per is not None and per <= 12:
                out["remedy"], out["remedy_amount"] = "longer_run", per
            else:
                out["remedy"], out["remedy_amount"] = "larger_group", n1
    if d["unit_cost"] is not None:
        ex = math.ceil(n1 * (1 - sh[c]) - 1e-9) if d["holdout"] else n1
        v = (Decimal(repr(d["unit_cost"])) * ex).quantize(Decimal("0.01"), ROUND_HALF_UP)
        out["cost_of_test"] = out["cost_low"] = out["cost_high"] = float(v)
    return out


def _rand_design(rng):
    k = rng.choice([2, 2, 3, 4, 5, 6])
    arms = [f"a{i}" for i in range(k)]
    mode = rng.choice(["eq", "rand", "tenth"])
    if mode == "eq":
        w = [1] * k
    elif mode == "tenth":
        w = [rng.randint(1, 5) for _ in range(k)]
    else:
        w = [rng.random() + 0.05 for _ in range(k)]
    t = sum(w)
    sh = [x / t for x in w]
    if mode == "tenth":
        sh = [round(x, 2) for x in sh]
        sh[-1] = round(1 - sum(sh[:-1]), 2)
        if sh[-1] <= 0 or abs(sum(sh) - 1) > 1e-9:
            sh = [1 / k] * k
    ctrl = rng.choice(arms)
    dirn = rng.choice(["more", "fewer"])
    return design(
        arms=arms,
        control=ctrl,
        allocation=dict(zip(arms, sh)),
        units_available=rng.choice([0, 50, 180, 850, 1900, 5000, 20000, 10**6]),
        units_per_period=rng.choice([None, 0, 10, 100, 2500]),
        direction=dirn,
        horizon_days=rng.choice([0, 7, 14, 60]),
        baseline_rate=rng.choice([None, 0, 1, 0.9, 0.5, 0.3, 0.1, 0.03, rng.random()]),
        smallest_effect=rng.choice(
            [0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 1.0, 1.5, rng.random() * 1.2 + 0.01]
        ),
        false_positive_rate=rng.choice([0.05, 0.1, 0.01]),
        sensitivity=rng.choice([0.8, 0.9, 0.95]),
        randomized=rng.random() < 0.85,
        holdout=rng.random() < 0.4,
        unit_cost=rng.choice([None, 0, 0.155, 0.015, 0.25, 2, 1.1, 0.333, 12.5]),
        currency=rng.choice([None, "GBP"]),
        period_days=rng.choice([1, 7, 14, 30]),
    )


def test_second_implementation_agrees_on_random_designs():
    rng = random.Random(61)
    seen = set()
    for _ in range(4000):
        d = _rand_design(rng)
        got = R.read_test_design(copy.deepcopy(d))
        want = second(d)
        for key, v in want.items():
            if key in ("rule_ref", "engine_version", "inputs_hash"):
                continue
            assert got[key] == v, (key, got[key], v, d)
        seen.add((got["answerable"], got["remedy"]))
    assert len(seen) >= 8, seen


def test_boundaries_both_sides_for_many_designs():
    rng = random.Random(7)
    n = 0
    for _ in range(300):
        d = _rand_design(rng)
        d["randomized"] = True
        r = R.read_test_design(d)
        if r["units_needed"] is None:
            continue
        for av, word in [
            (r["units_needed"], "estimable"),
            (r["units_needed"] - 1, None),
        ]:
            d2 = {**d, "units_available": av}
            got = R.read_test_design(d2)["answerable"]
            if word:
                assert got == word
            else:
                assert got != "estimable"
        m = r["units_needed_marginal"]
        if m is not None and m < r["units_needed"]:
            assert R.read_test_design({**d, "units_available": m})["answerable"] == "marginal"
            assert (
                R.read_test_design({**d, "units_available": m - 1})["answerable"] == "below_floor"
            )
            n += 1
    assert n > 20


# ---------------------------------------------------------------------------------------- the hash
def _c1(v):
    """From J6.S2 (1) alone, a third hand: normalise then dumps."""

    def norm(x):
        if isinstance(x, bool) or x is None or isinstance(x, str):
            return x
        if isinstance(x, (int, float)):
            return int(x) if float(x) == int(x) else x
        if isinstance(x, list):
            return [norm(y) for y in x]
        return {k: norm(y) for k, y in x.items()}

    s = json.dumps(
        norm(v), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def test_hash_nested_whole_floats_bools_and_non_ascii():
    d = design(
        unit_kind="compte été \U0001f600",
        outcome={
            "z": [
                1.0,
                True,
                1,
                False,
                0.0,
                -0.0,
                1e0,
                2.5,
                1e-5,
                1e16,
                123456789012345678,
                [1.0, {"\U0001f600": 1.0, "￿": 2, "b": None}],
            ],
            "é": {"x": 3.0, "a": 0.1 + 0.2},
            "A": "́",
        },
        value_per_outcome=40.0,
    )
    got = R.read_test_design(d)["inputs_hash"]
    assert got == _c1(d) == R.design_hash(d)
    text = json.dumps(R._normalise(d), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert '"z":[1,true,1,false,0,0,1,2.5,1e-05,10000000000000000,123456789012345678' in text
    assert "0.30000000000000004" in text
    # sorted by code point: U+FFFF before U+1F600 (not by UTF-16 unit)
    assert text.index("￿") < text.index("\U0001f600", text.index("￿"))
    d2 = copy.deepcopy(d)
    d2["outcome"]["z"][0] = 1
    d2["outcome"]["z"][2] = 1.0
    d2["unit_cost"] = None
    assert R.design_hash(d2) == R.design_hash(d)
    # a bool is not a number: True and 1 differ
    d3 = copy.deepcopy(d)
    d3["outcome"]["z"][1] = 1
    assert R.design_hash(d3) != R.design_hash(d)


def test_hash_key_order_and_int_float_in_counts():
    d = design(units_available=1900, period_days=7, horizon_days=60)
    rev = dict(reversed(list(d.items())))
    rev["allocation"] = dict(reversed(list(d["allocation"].items())))
    assert R.design_hash(rev) == R.design_hash(d)
    assert R.design_hash({**d, "units_available": 1900.0}) == R.design_hash(d)


# ------------------------------------------------------------------------------------- refusals
BAD = {
    "arms": [
        None,
        5,
        "x",
        [],
        ["usual_welcome"],
        ["a", "a"],
        ["usual_welcome", 3],
        ("usual_welcome", "plain_price"),
    ],
    "control": [None, 3, "nobody"],
    "allocation": [
        None,
        [],
        {"usual_welcome": 0.5},
        {"usual_welcome": 0.5, "plain_price": 0.6},
        {"usual_welcome": 1.0, "plain_price": 0.0},
        {"usual_welcome": 1.5, "plain_price": -0.5},
        {"usual_welcome": "0.5", "plain_price": 0.5},
        {"usual_welcome": True, "plain_price": 0.0},
        {"usual_welcome": float("nan"), "plain_price": 0.5},
        {"usual_welcome": 0.5, "plain_price": 0.5, "extra": 0.1},
    ],
    "unit_kind": [None, 3, True],
    "units_available": [None, -1, "5", True, 1.5, float("nan"), float("inf")],
    "units_per_period": ["5", -1, True, 2.5, float("inf")],
    "outcome": [
        None,
        [],
        "x",
        {"a": float("nan")},
        {"a": {"b": [float("inf")]}},
        {"a": object()},
        {1: 2},
    ],
    "direction": [None, "More", "up", 1, ["more"]],
    "horizon_days": [None, -1, "7", True, 1.5],
    "baseline_rate": ["0.3", True, -0.01, 1.01, float("nan"), float("inf"), [0.3]],
    "baseline_measure_id": [3, True],
    "smallest_effect": [None, 0, -0.1, "0.2", True, float("nan"), float("inf")],
    "false_positive_rate": [None, 0, 1, -0.1, 1.5, "0.05", True, float("nan")],
    "sensitivity": [None, 0, 1, "0.8", True, float("nan")],
    "randomized": [None, 1, "true", 0],
    "holdout": [None, 1, "false", 0],
    "channel": [None, 3],
    "exposure": [None, 3],
    "unit_cost": ["1", -0.01, True, float("nan"), float("inf")],
    "currency": [3, True],
    "period_days": [None, 0, -7, "7", True, 0.5, float("nan")],
    "kill_candidates": [None, "x", [1], ["a", None], ("a",)],
    "economics_ref": [3, True],
    "value_per_outcome": [True, float("nan"), float("inf"), [1], {}],
    "run_id": [3, True],
}


@pytest.mark.parametrize("key", sorted(BAD))
def test_each_bad_value_raises_valueerror_naming_the_field(key):
    for bad in BAD[key]:
        d = design()
        d[key] = bad
        with pytest.raises(ValueError) as ei:
            R.read_test_design(d)
        field = "allocation" if key in ("allocation",) else key
        assert field in str(ei.value), (key, bad, str(ei.value))
        assert not isinstance(ei.value, (OverflowError, decimal.DecimalException))


def test_missing_and_unknown_keys_and_non_dict():
    for k in R.DESIGN_KEYS:
        d = design()
        del d[k]
        with pytest.raises(ValueError, match=k):
            R.read_test_design(d)
    with pytest.raises(ValueError, match="zzz"):
        R.read_test_design({**design(), "zzz": 1})
    for bad in (None, [], "x", 3):
        with pytest.raises(ValueError):
            R.read_test_design(bad)


def test_allocation_sum_tolerance_edges():
    ok = design(allocation={"usual_welcome": 0.5 + 5e-10, "plain_price": 0.5})
    R.read_test_design(ok)
    with pytest.raises(ValueError, match="allocation"):
        R.read_test_design(design(allocation={"usual_welcome": 0.5 + 2e-9, "plain_price": 0.5}))


def _reads(**over):
    return R.read_test_design(design(**over))


def test_F1_large_unit_cost_is_refused_naming_the_field():
    """Finding 1 (minor), settled by J6.S6: a unit cost above COUNT_MAX is refused, naming it,
    so the Decimal product to cents can always be held."""
    for c in (1e25, 10**30):
        with pytest.raises(ValueError, match="unit_cost"):
            _reads(unit_cost=c)
    assert _reads(unit_cost=10**12)["cost_of_test"] is not None


def test_F2_extreme_alpha_is_refused_naming_the_field():
    """Finding 2 (minor), settled by J6.S6: alpha and power lie in [1e-9, 1 - 1e-9]."""
    for k in (2, 3):
        with pytest.raises(ValueError, match="false_positive_rate"):
            _reads(false_positive_rate=5e-324, **equal_arms(k))
    _reads(false_positive_rate=1e-9, **equal_arms(3))


def test_F3_huge_counts_are_refused_naming_the_field():
    """Finding 3 (minor), settled by J6.S6: a count above COUNT_MAX is refused, naming it."""
    with pytest.raises(ValueError, match="units_available"):
        _reads(units_available=10**400)
    with pytest.raises(ValueError, match="horizon_days"):
        _reads(units_available=0, units_per_period=1, horizon_days=10**400)


def test_F4_lone_surrogate_is_refused_naming_a_field():
    """Finding 4 (minor): a string that can't be UTF-8 encoded passes validation and raises
    UnicodeEncodeError (a ValueError) from the hash, naming no field."""
    with pytest.raises(ValueError, match="unit_kind"):
        _reads(unit_kind="\ud800")


def test_effect_too_small_to_move_p2_reads_as_below_floor_not_error():
    r = R.read_test_design(design(smallest_effect=1e-17))
    assert r["answerable"] == "below_floor" and r["units_needed"] is None and r["remedy"] is None
    # one step up the size is finite, so rule 6 as written ("p2 outside (0, 1)") is not what
    # decides it: the discontinuity is the builder's reading, recorded here.
    r2 = R.read_test_design(design(smallest_effect=1e-12))
    assert r2["units_needed"] is not None


def test_whole_floats_as_counts_are_accepted_and_read_as_ints():
    a = R.read_test_design(design(units_available=1900.0, period_days=7.0, horizon_days=60.0))
    b = R.read_test_design(design())
    assert a == b
    assert all(type(a[k]) is int for k in ("units_needed",))


def test_value_per_outcome_any_string_accepted():
    for s in ("", "40", "abc", "NaN"):
        R.read_test_design(design(value_per_outcome=s))


def test_integer_unit_cost_equals_decimal_of_repr():
    for c in (0, 1, 3, 10**12):  # J6.S6: COUNT_MAX
        a = R.read_test_design(design(unit_cost=c))["cost_of_test"]
        b = R.read_test_design(design(unit_cost=float(c)))["cost_of_test"]
        assert a == b


def test_cost_half_cent_edges_and_holdout_float_traps():
    d = design(unit_cost=0.155, units_available=0)
    n = R.read_test_design(d)["units_needed"]
    assert R.read_test_design(d)["cost_of_test"] == float(
        (Decimal("0.155") * n).quantize(Decimal("0.01"), ROUND_HALF_UP)
    )
    # (1 - 0.7) trap: 6940 * (1 - 0.7) = 2082.0000000000005 in doubles
    assert math.ceil(6940 * (1 - 0.7)) == 2083
    assert math.ceil(6940 * (1 - 0.7) - 1e-9) == 2082
    for sc in (0.7, 0.3, 0.35, 0.1, 0.9):
        al = {"usual_welcome": sc, "plain_price": 1 - sc}
        d = design(allocation=al, unit_cost=1, holdout=True)
        r = R.read_test_design(d)
        ex = math.ceil(r["units_needed"] * (1 - sc) - 1e-9)
        assert r["cost_of_test"] == float(ex)


# ---------------------------------------------------------------------------------------- purity
def test_not_mutated_and_no_state_between_calls():
    rng = random.Random(3)
    for _ in range(40):
        d = _rand_design(rng)
        before = copy.deepcopy(d)
        r1 = R.read_test_design(d)
        assert d == before and list(d["allocation"]) == list(before["allocation"])
        r1["rule_ref"].append("x")
        r1["stopping_rule"] = r1["stopping_rule"] and {"x": 1}
        r2 = R.read_test_design(d)
        assert r2["rule_ref"] == R.rule_ref() and len(r2["rule_ref"]) == 2
        assert R.read_test_design(d)["inputs_hash"] == r2["inputs_hash"]
    a = R.read_test_design(design(units_available=0))
    R.read_test_design(design(units_available=10**6, baseline_rate=None))
    assert R.read_test_design(design(units_available=0)) == a


def test_reading_shape_and_closed_strings():
    rng = random.Random(5)
    words = {
        "estimable",
        "marginal",
        "below_floor",
        "coarser_comparison",
        "longer_run",
        "larger_group",
        "fixed_horizon",
    }
    for _ in range(300):
        d = _rand_design(rng)
        r = R.read_test_design(d)
        assert tuple(r) == R.READING_KEYS and json_native(r)
        json.dumps(r, allow_nan=False)
        allowed = (
            words
            | {d["unit_kind"], d["currency"]}
            | set(r["rule_ref"])
            | {r["engine_version"], r["inputs_hash"]}
        )
        for key, v in r.items():
            if isinstance(v, str):
                assert v in allowed, (key, v)
        assert (r["remedy"] is None) == (r["remedy_amount"] is None)
        if r["units_needed"] is None:
            assert (
                r["periods_needed"] is None and r["stopping_rule"] is None and r["remedy"] is None
            )


def test_reads_nothing_beyond_registries():
    with OpenAudit() as a:
        R.read_test_design(design(unit_cost=0.1))
        R.read_test_design_rule()
    bad = [p for p in a.opened if "registries" not in p and not p.endswith((".pyc", ".so"))]
    assert a.sqlite == [] and bad == [], bad


def test_socket_passthroughs_equal_module():
    d = design()
    assert sock.read_test_design(d) == R.read_test_design(d)
    assert sock.read_test_design_rule() == R.read_test_design_rule()


def test_rule_values_and_isolated_process():
    from bayesian_marketing import __version__
    from bayesian_marketing.core import registries

    pw = registries.resolve("bounds/estimability/posterior_width@v1")
    want = R.read_test_design_rule()
    assert want["ratio"] == pw["caveat_rel_half_width"] / pw["rel_half_width"]
    assert want["max_periods"] == 12 and want["hash_form"] == "bayes-design-c1"
    assert want["rule_ref"][1] == f"engine:test_design.reading.MAX_PERIODS@{__version__}"
    assert registries.versions() == registries.versions()
    code = (
        "import json,sys\n"
        "from bayesian_marketing.atmaos import socket as s\n"
        "req=json.load(sys.stdin)\n"
        "print(json.dumps({'rule':s.read_test_design_rule(),'read':s.read_test_design(req)},ensure_ascii=False))\n"
    )
    import tempfile

    with tempfile.TemporaryDirectory() as dd:
        env = {"BAYES_DATA_DIR": dd, "HOME": dd, "PATH": os.environ["PATH"]}
        d = design(unit_kind="compte été", unit_cost=0.155)
        p = subprocess.run(
            [sys.executable, "-I", "-c", code], input=json.dumps(d, ensure_ascii=False),
            capture_output=True, text=True, env=env, cwd=dd, timeout=120,
        )  # fmt: skip
        assert p.returncode == 0, p.stderr[-800:]
        out = json.loads(p.stdout)
        assert out["rule"] == want
        assert out["read"] == R.read_test_design(d)
        assert os.listdir(dd) == [] or all(
            not f.endswith((".db", ".sqlite")) for f in os.listdir(dd)
        )
