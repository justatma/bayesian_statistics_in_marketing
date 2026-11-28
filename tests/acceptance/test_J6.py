"""J6: reading a proposed test, ``read_test_design``
(spec/Test_Design_Reading_Specification_v0.2.md, rules 1 to 14, Refused, checks (a) to (n),
and J6.S1 to J6.S4, which govern where they differ).

Goldens: E1 from the spec's AS5 section; E2 and E3 from AtmaOS's AS5 key
(``atmaos/tests/fixtures/arkwright/suggestions_v1/key/exchanges.json`` and ``planted.json``:
two arms at half each, alpha 0.05, power 0.8; E2 a 0.10 baseline ``more`` at 0.2 on 180 units;
E3 a 0.40 baseline ``fewer`` at 0.2 on 850 units). The key's flow and period figures come from
AtmaOS's records, not from the key, so the E2 and E3 tests here state no flow and hold only the
word and the sizes (and the remedy that follows from no flow).

Readings the spec leaves to the test writer, and how they are read here:

* ``remedy_amount`` is null whenever ``remedy`` is null ("Its remedy is a word and a number").
* A field named in a ``ValueError`` means the field's key appears in the message. A duplicate arm
  and too few arms name ``arms``; a control not among the arms names ``control``; any allocation
  fault names ``allocation``; alpha is ``false_positive_rate`` and power ``sensitivity``.
* "NaN or infinity" is refused at any depth, ``outcome`` included: J6.S2 (1) (b) says NaN never
  reaches the hash "because they are refused".
* An int is a wrong type where a bool is wanted (``randomized: 1``). A non-whole float is a wrong
  type where an int is wanted. Whether 1900.0 is accepted as an int is left free and not tested.
* J6.S4's ``<engine_version>`` in ``engine:test_design.reading.MAX_PERIODS@<engine_version>`` is
  held loosely: the prefix exactly, ending in the package version. Either "bayesian-marketing
  0.2.0.dev0" or "0.2.0.dev0" after the ``@`` passes.
* ``read_test_design_rule`` is held to carry at least the seven keys J6.S2 (2) lists.
* Check (c)'s "within 0.22 to 0.30" doesn't hold for the formula over the whole stated grid
  (``fewer`` at effects of 0.25 and up falls to about 0.19, and a 0.5 baseline at 0.35 and 0.4 to
  about 0.215). The test holds the exact equality with the formula over the whole grid, which is
  what an implementation controls, and the 0.22 to 0.30 band only where the formula gives it:
  ``more`` at effects 0.1 to 0.3.
* Check (f)'s 0.7 and 0.3 don't produce float error in ``n / 0.3`` for any n (it divides exactly
  to the integer), so it can't catch a missing 1e-9. A 0.65 and 0.35 split does (714 / 0.35 is
  2040.0000000000002), and so does a holdout cost at a 0.7 control (6940 * (1 - 0.7) is
  2082.0000000000005). Both are added.
* The tie-break by arm key in rule 11 (a) can't be seen in the reading: tied arms have equal
  shares, so either choice gives the same size. A tie is exercised, and only the amount held.
* J6.S4's "``registries.versions()`` unchanged" is held as: no ``test_design`` registry, no
  ``max_periods`` in any registry file, and ``versions()`` and the registry files the same before
  and after J6's calls. It passes at the skeleton by design: it guards against a change.
"""

from __future__ import annotations

import copy
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from bayesian_marketing import __version__
from bayesian_marketing.atmaos import socket as sock
from bayesian_marketing.core import registries
from bayesian_marketing.test_design import reading as R
from tests.acceptance import j6_fixtures as F

pytestmark = pytest.mark.piece("J6")

REPO = Path(__file__).resolve().parents[2]

READING_KEYS = [
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
]
WIDTH = "bounds/estimability/posterior_width@v1"
MAXP_PREFIX = "engine:test_design.reading.MAX_PERIODS@"
ENGINE_VERSION = f"bayesian-marketing {__version__}"

# The base design (E1's second draft): 1,718 needed, 396 at the marginal size.
BASE_NEEDED = 1718
BASE_MARGINAL = 396


def read(**over: Any) -> dict[str, Any]:
    return R.read_test_design(F.design(**over))


def assert_no_outcome(r: dict[str, Any]) -> None:
    assert r["answerable"] == "below_floor"
    for k in (
        "units_needed",
        "units_needed_marginal",
        "periods_needed",
        "stopping_rule",
        "remedy",
        "remedy_amount",
        "cost_of_test",
        "cost_low",
        "cost_high",
    ):
        assert r[k] is None, k


# ------------------------------------------------------------------------ goldens (a), E1 to E3


def test_J6_a_three_against_four_per_cent() -> None:
    r = read(baseline_rate=0.03, direction="more", smallest_effect=0.04 / 0.03 - 1)
    assert r["units_needed"] == 10602


def test_J6_a_point_three_fewer_two_arms() -> None:
    r = read()
    assert r["units_needed"] == 1718
    assert r["answerable"] == "estimable"
    assert r["remedy"] is None and r["remedy_amount"] is None


def test_J6_E1_five_arms() -> None:
    r = read(**F.equal_arms(5), units_available=1900)
    assert r["units_needed"] == 6100
    assert r["units_needed_marginal"] == 1410
    assert r["answerable"] == "marginal"
    assert r["remedy"] == "coarser_comparison"
    assert r["remedy_amount"] == 2


@pytest.mark.parametrize(("k", "needed"), [(4, 4584), (3, 3120), (2, 1718)])
def test_J6_E1_fewer_arms(k: int, needed: int) -> None:
    assert read(**F.equal_arms(k))["units_needed"] == needed


def test_J6_E2_case1_180_members() -> None:
    r = read(
        arms=["no_ask", "host_ask_email"],
        control="no_ask",
        allocation={"no_ask": 0.5, "host_ask_email": 0.5},
        units_available=180,
        baseline_rate=0.1,
        direction="more",
    )
    assert r["answerable"] == "below_floor"
    assert r["units_needed"] == 7682
    assert r["units_needed_marginal"] == 2070
    # Rule 11 with two arms and no flow: (c), the total, not the shortfall.
    assert r["remedy"] == "larger_group"
    assert r["remedy_amount"] == 7682


def test_J6_case1_180_reaching_the_marginal_size() -> None:
    # 0.40 fewer at 0.24: needed 776, marginal 178.
    r = read(units_available=180, baseline_rate=0.4, smallest_effect=0.24)
    assert r["units_needed"] == 776
    assert r["units_needed_marginal"] == 178
    assert r["answerable"] == "marginal"
    assert r["remedy"] == "larger_group" and r["remedy_amount"] == 776


def test_J6_E3_case4_marginal() -> None:
    r = read(
        arms=["notice_as_now", "lend_the_month"],
        control="notice_as_now",
        allocation={"notice_as_now": 0.5, "lend_the_month": 0.5},
        units_available=850,
        baseline_rate=0.4,
    )
    assert r["answerable"] == "marginal"
    assert r["units_needed"] == 1128
    assert r["units_needed_marginal"] == 266
    assert r["remedy"] == "larger_group"
    assert r["remedy_amount"] == 1128


# ---------------------------------------------------------------------------- (b) boundaries


@pytest.mark.parametrize(
    ("units", "word"),
    [
        (BASE_NEEDED, "estimable"),
        (BASE_NEEDED - 1, "marginal"),
        (BASE_MARGINAL, "marginal"),
        (BASE_MARGINAL - 1, "below_floor"),
    ],
)
def test_J6_b_boundaries(units: int, word: str) -> None:
    r = read(units_available=units)
    assert r["units_needed"] == BASE_NEEDED
    assert r["units_needed_marginal"] == BASE_MARGINAL
    assert r["answerable"] == word


# ------------------------------------------------------------------------- (c) the marginal size

GRID_BASELINES = [0.03, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5]
GRID_EFFECTS = [0.1, 0.2, 0.3, 0.4]


@pytest.mark.parametrize("direction", ["more", "fewer"])
def test_J6_c_marginal_from_the_formula(direction: str) -> None:
    alloc = {"usual_welcome": 0.5, "plain_price": 0.5}
    for b in GRID_BASELINES:
        for e in GRID_EFFECTS:
            r = read(baseline_rate=b, smallest_effect=e, direction=direction)
            need = F.units_needed_oracle(b, e, direction, alloc, "usual_welcome")
            marg = F.units_needed_oracle(b, e * 2.0, direction, alloc, "usual_welcome")
            assert r["units_needed"] == need, (b, e)
            assert r["units_needed_marginal"] == marg, (b, e)
            if direction == "more" and e <= 0.3:
                assert 0.22 <= marg / need <= 0.30, (b, e)


@pytest.mark.parametrize("units", [0, 1, 150, 159, 160, 10_000])
def test_J6_c_marginal_null_never_marginal(units: int) -> None:
    # 0.30 fewer at 0.6: p2 = 0.12 at the effect, but negative at 1.2. Needed 160.
    r = read(smallest_effect=0.6, units_available=units)
    assert r["units_needed"] == 160
    assert r["units_needed_marginal"] is None
    assert r["answerable"] == ("estimable" if units >= 160 else "below_floor")


# --------------------------------------------------------------------------- (d) no outcome, rule 6


@pytest.mark.parametrize(
    "over",
    [
        {"baseline_rate": None},
        {"baseline_rate": 0},
        {"baseline_rate": 0.0},
        {"baseline_rate": 1},  # J6.S1 (2)
        {"baseline_rate": 1.0},
        {"baseline_rate": 0.9, "direction": "more", "smallest_effect": 0.2},
        {"smallest_effect": 1},  # fewer at an effect of 1: p2 = 0
        {"smallest_effect": 1.5},  # fewer past 1: p2 < 0
    ],
)
def test_J6_d_no_outcome(over: dict[str, Any]) -> None:
    r = read(**over, unit_cost=1.5, currency="GBP", units_per_period=100)
    assert_no_outcome(r)
    assert r["currency"] == "GBP"
    assert r["value_of_answer"] is None


def test_J6_case3_no_baseline_with_zero_units_is_still_a_reading() -> None:
    assert_no_outcome(read(baseline_rate=None, units_available=0))


# ------------------------------------------------------------------------------ (e) Bonferroni


def test_J6_e_bonferroni() -> None:
    two = read(**F.shares("c", {"c": 0.7, "a": 0.3}))
    three = read(**F.shares("c", {"c": 0.4, "a": 0.3, "b": 0.3}))
    assert two["units_needed"] == F.units_needed_oracle(
        0.3, 0.2, "fewer", {"c": 0.7, "a": 0.3}, "c"
    )
    assert three["units_needed"] == F.units_needed_oracle(
        0.3, 0.2, "fewer", {"c": 0.4, "a": 0.3, "b": 0.3}, "c"
    )
    assert three["units_needed"] > two["units_needed"]


# ------------------------------------------------------------------------------ (f) allocation


def test_J6_f_smaller_arm_sizes_the_comparison() -> None:
    r = read(**F.shares("c", {"c": 0.8, "a": 0.2}))
    assert r["units_needed"] == math.ceil(859 / 0.2) == 4295


def test_J6_f_point_seven_point_three() -> None:
    r = read(**F.shares("c", {"c": 0.7, "a": 0.3}))
    assert r["units_needed"] == 2864  # 859 / 0.3 = 2863.33


def test_J6_f_float_error_adds_no_unit() -> None:
    # 0.05 more at 0.75: n = 714. 714 / 0.35 is 2040.0000000000002 as floats; the rule gives 2040.
    r = read(**F.shares("c", {"c": 0.65, "a": 0.35}), baseline_rate=0.05, direction="more",
             smallest_effect=0.75)  # fmt: skip
    assert r["units_needed"] == 2040


def test_J6_f_max_over_arms() -> None:
    alloc = {"c": 0.5, "a": 0.3, "b": 0.2}
    r = read(**F.shares("c", alloc))
    assert r["units_needed"] == F.units_needed_oracle(0.3, 0.2, "fewer", alloc, "c")


# -------------------------------------------------------------------- (g) remedy order and amounts


def test_J6_g_three_arms_two_answer() -> None:
    r = read(**F.equal_arms(3), units_available=1900)
    assert r["units_needed"] == 3120
    assert r["remedy"] == "coarser_comparison"
    assert r["remedy_amount"] == 2


def test_J6_g_four_arms_three_answer_by_largest_shares() -> None:
    # Four arms need 11,460. Keeping the control with b and c (the largest) needs 4,680; keeping
    # c and d would need 7,280. m = 3 is tried before m = 2 (which 2,005 would also answer).
    alloc = {"ctrl": 0.4, "d": 0.1, "c": 0.2, "b": 0.3}
    r = read(**F.shares("ctrl", alloc), units_available=5000)
    assert r["units_needed"] == 11460
    assert r["remedy"] == "coarser_comparison"
    assert r["remedy_amount"] == 3


def test_J6_g_four_arms_tie() -> None:
    alloc = {"ctrl": 0.4, "z_arm": 0.2, "a_arm": 0.2, "m_arm": 0.2}
    r = read(**F.shares("ctrl", alloc), units_available=4500)  # three need 4,160; four 5,730
    assert r["remedy"] == "coarser_comparison"
    assert r["remedy_amount"] == 3


def test_J6_g_longer_run_total_periods() -> None:
    r = read(units_available=BASE_NEEDED - 250, units_per_period=100, horizon_days=14)
    assert r["periods_needed"] == 5
    assert r["remedy"] == "longer_run"
    assert r["remedy_amount"] == 5


def test_J6_g_longer_run_at_max_periods() -> None:
    assert R.MAX_PERIODS == 12
    r = read(units_available=BASE_NEEDED - 1200, units_per_period=100, horizon_days=0)
    assert r["periods_needed"] == 12
    assert r["remedy"] == "longer_run" and r["remedy_amount"] == 12


def test_J6_g_larger_group_past_max_periods() -> None:
    r = read(units_available=BASE_NEEDED - 1300, units_per_period=100, horizon_days=0)
    assert r["periods_needed"] == 13
    assert r["remedy"] == "larger_group"
    assert r["remedy_amount"] == BASE_NEEDED


def test_J6_g_larger_group_with_no_flow() -> None:
    for flow in (None, 0):
        r = read(units_available=1000, units_per_period=flow)
        assert r["remedy"] == "larger_group" and r["remedy_amount"] == BASE_NEEDED


def test_J6_g_three_arms_none_answer_falls_through() -> None:
    r = read(**F.equal_arms(3), units_available=1000)  # two arms need 1,718
    assert r["remedy"] == "larger_group" and r["remedy_amount"] == 3120
    r = read(**F.equal_arms(3), units_available=1000, units_per_period=1000, horizon_days=0)
    assert r["remedy"] == "longer_run" and r["remedy_amount"] == r["periods_needed"] == 3


def test_J6_g_marginal_carries_a_remedy() -> None:
    r = read(units_available=1000)
    assert r["answerable"] == "marginal"
    assert r["remedy"] == "larger_group" and r["remedy_amount"] == BASE_NEEDED


def test_J6_rule11_estimable_has_no_remedy() -> None:
    r = read(**F.equal_arms(3), units_available=3120)
    assert r["answerable"] == "estimable"
    assert r["remedy"] is None and r["remedy_amount"] is None


# ------------------------------------------------------------------------- (h) periods, rule 9-10


def test_J6_h_shortfall_250_at_100() -> None:
    # The design is marginal (1,468 >= 396); periods are for units_needed (rule 10).
    r = read(units_available=BASE_NEEDED - 250, units_per_period=100, period_days=7,
             horizon_days=14)  # fmt: skip
    assert r["answerable"] == "marginal"
    assert r["periods_needed"] == 5


@pytest.mark.parametrize("flow", [None, 0])
def test_J6_h_shortfall_with_no_flow(flow: int | None) -> None:
    r = read(units_available=BASE_NEEDED - 250, units_per_period=flow)
    assert r["periods_needed"] is None
    assert r["stopping_rule"] is None  # J6.S1 (3)


def test_J6_h_no_shortfall_horizon_zero() -> None:
    assert read(horizon_days=0)["periods_needed"] == 1


@pytest.mark.parametrize("flow", [None, 0, 50])
def test_J6_h_no_shortfall_horizon_only(flow: int | None) -> None:
    assert read(units_per_period=flow, horizon_days=60, period_days=7)["periods_needed"] == 9


# ----------------------------------------------------------------------- rule 12, stopping rule


def test_J6_rule12_stopping_rule() -> None:
    r = read(units_available=BASE_NEEDED - 250, units_per_period=100, horizon_days=14)
    assert r["stopping_rule"] == {"kind": "fixed_horizon", "max_periods": 5, "kill_threshold": None}
    assert r["kill_metric_measure_id"] is None
    r = read(kill_candidates=["m_1", "m_2"])
    assert r["stopping_rule"] == {"kind": "fixed_horizon", "max_periods": 9, "kill_threshold": None}
    assert r["kill_metric_measure_id"] is None


# ----------------------------------------------------------------------------- (i) cost, J6.S3


def test_J6_i_cost_and_holdout() -> None:
    r = read(unit_cost=0.25, currency="GBP")
    assert r["cost_of_test"] == r["cost_low"] == r["cost_high"] == 429.5
    assert r["currency"] == "GBP"
    r = read(unit_cost=0.25, currency="GBP", holdout=True)
    assert r["cost_of_test"] == r["cost_low"] == r["cost_high"] == 214.75  # 859 exposed


def test_J6_i_holdout_float_error_adds_no_unit() -> None:
    # 0.30 fewer at 0.13: n = 2,082, N = 6,940 at 0.7 and 0.3. 6,940 x (1 - 0.7) is
    # 2082.0000000000005 as floats; the exposed units are 2,082.
    r = read(**F.shares("c", {"c": 0.7, "a": 0.3}), smallest_effect=0.13, unit_cost=1,
             holdout=True)  # fmt: skip
    assert r["units_needed"] == 6940
    assert r["cost_of_test"] == 2082


def test_J6_i_null_unit_cost_echoes_currency() -> None:
    r = read(unit_cost=None, currency="GBP")
    assert r["cost_of_test"] is None and r["cost_low"] is None and r["cost_high"] is None
    assert r["currency"] == "GBP"
    assert read(unit_cost=None, currency=None)["currency"] is None


def test_J6_i_zero_unit_cost() -> None:
    assert read(unit_cost=0)["cost_of_test"] == 0


# 0.01 more at 98: p2 = 0.99, n = 3 per arm, six units, three exposed under a holdout.
THREE_EXPOSED = {"baseline_rate": 0.01, "direction": "more", "smallest_effect": 98,
                 "holdout": True}  # fmt: skip


@pytest.mark.parametrize(("unit_cost", "cost"), [(0.155, 0.47), (0.015, 0.05)])
def test_J6_S3_half_up_on_the_decimal(unit_cost: float, cost: float) -> None:
    r = read(**THREE_EXPOSED, unit_cost=unit_cost)
    assert r["units_needed"] == 6
    assert r["cost_of_test"] == r["cost_low"] == r["cost_high"] == cost
    assert isinstance(r["cost_of_test"], (int, float)) and not isinstance(r["cost_of_test"], bool)


# ----------------------------------------------------------------------- (j) rules 5 and 8


def test_J6_j_zero_units() -> None:
    r = read(units_available=0)
    assert r["answerable"] == "below_floor"
    assert r["units_needed"] == BASE_NEEDED
    assert r["units_needed_marginal"] == BASE_MARGINAL
    assert r["remedy"] == "larger_group" and r["remedy_amount"] == BASE_NEEDED


@pytest.mark.parametrize("units", [0, 1000, 1900])
def test_J6_j_not_randomized(units: int) -> None:
    r = read(randomized=False, units_available=units, unit_cost=1, horizon_days=60)
    assert r["answerable"] == "below_floor"
    assert r["units_needed"] == BASE_NEEDED
    assert r["units_needed_marginal"] == BASE_MARGINAL
    assert r["remedy"] is None and r["remedy_amount"] is None
    assert r["cost_of_test"] == BASE_NEEDED
    if units >= BASE_NEEDED:
        assert r["periods_needed"] == 9


def test_J6_j_not_randomized_periods_as_if_randomized() -> None:
    kw = {"units_available": BASE_NEEDED - 250, "units_per_period": 100, "horizon_days": 14}
    assert read(randomized=False, **kw)["periods_needed"] == read(**kw)["periods_needed"] == 5


def test_J6_j_not_randomized_many_arms_no_remedy() -> None:
    r = read(**F.equal_arms(5), randomized=False)
    assert r["answerable"] == "below_floor"
    assert r["units_needed"] == 6100
    assert r["remedy"] is None and r["remedy_amount"] is None


# ------------------------------------------------------------------------------ (k) refusals


def refused(field: str | tuple[str, ...], design: dict[str, Any]) -> None:
    """``field`` is the field named; a tuple lists the fields a cascading fault may name."""
    names = (field,) if isinstance(field, str) else field
    with pytest.raises(ValueError) as exc:
        R.read_test_design(design)
    assert any(n in str(exc.value) for n in names), (names, str(exc.value))


@pytest.mark.parametrize("key", R.DESIGN_KEYS)
def test_J6_k_missing_key(key: str) -> None:
    d = F.design()
    del d[key]
    refused(key, d)


def test_J6_k_design_keys_are_the_inputs_table() -> None:
    assert set(R.DESIGN_KEYS) == set(F.design())
    assert len(R.DESIGN_KEYS) == 25


def test_J6_k_unknown_key() -> None:
    refused("budget_cap", F.design(budget_cap=100))


NAN, INF = float("nan"), float("inf")

# A fault in ``arms`` whose design can't be otherwise consistent may be named through the field
# it upsets first; which is checked first is free.
CASCADE = ("arms", "control", "allocation")

BAD: list[tuple[str | tuple[str, ...], dict[str, Any]]] = [
    # wrong types, bools and strings where numbers are wanted
    (CASCADE, {"arms": "usual_welcome,plain_price"}),
    (CASCADE, {"arms": [1, 2]}),
    ("control", {"control": 1}),
    ("allocation", {"allocation": [0.5, 0.5]}),
    ("allocation", {"allocation": {"usual_welcome": "0.5", "plain_price": 0.5}}),
    ("allocation", {"allocation": {"usual_welcome": True, "plain_price": 0.5}}),
    ("unit_kind", {"unit_kind": None}),
    ("unit_kind", {"unit_kind": 3}),
    ("units_available", {"units_available": True}),
    ("units_available", {"units_available": "1900"}),
    ("units_available", {"units_available": 1900.5}),
    ("units_available", {"units_available": None}),
    ("units_per_period", {"units_per_period": True}),
    ("units_per_period", {"units_per_period": "100"}),
    ("units_per_period", {"units_per_period": 2.5}),
    ("outcome", {"outcome": "cancellation_notice"}),
    ("outcome", {"outcome": None}),
    ("outcome", {"outcome": []}),
    ("direction", {"direction": 1}),
    ("horizon_days", {"horizon_days": "60"}),
    ("horizon_days", {"horizon_days": 7.5}),
    ("horizon_days", {"horizon_days": None}),
    ("horizon_days", {"horizon_days": True}),
    ("baseline_rate", {"baseline_rate": "0.3"}),
    ("baseline_rate", {"baseline_rate": True}),
    ("baseline_rate", {"baseline_rate": False}),
    ("smallest_effect", {"smallest_effect": "0.2"}),
    ("smallest_effect", {"smallest_effect": True}),
    ("smallest_effect", {"smallest_effect": None}),
    ("false_positive_rate", {"false_positive_rate": "0.05"}),
    ("false_positive_rate", {"false_positive_rate": None}),
    ("sensitivity", {"sensitivity": True}),
    ("randomized", {"randomized": 1}),
    ("randomized", {"randomized": "true"}),
    ("randomized", {"randomized": None}),
    ("holdout", {"holdout": 0}),
    ("channel", {"channel": None}),
    ("channel", {"channel": 1}),
    ("exposure", {"exposure": 1}),
    ("unit_cost", {"unit_cost": "2"}),
    ("unit_cost", {"unit_cost": True}),
    ("currency", {"currency": 1}),
    ("period_days", {"period_days": 7.5}),
    ("period_days", {"period_days": "7"}),
    ("period_days", {"period_days": True}),
    ("period_days", {"period_days": None}),
    ("kill_candidates", {"kill_candidates": "m_1"}),
    ("kill_candidates", {"kill_candidates": None}),
    ("kill_candidates", {"kill_candidates": ["m_1", 2]}),
    ("economics_ref", {"economics_ref": 1}),
    ("value_per_outcome", {"value_per_outcome": True}),
    ("value_per_outcome", {"value_per_outcome": [1]}),
    ("run_id", {"run_id": 1}),
    ("baseline_measure_id", {"baseline_measure_id": 1}),
    # NaN and infinity
    ("baseline_rate", {"baseline_rate": NAN}),
    ("smallest_effect", {"smallest_effect": INF}),
    ("smallest_effect", {"smallest_effect": NAN}),
    ("false_positive_rate", {"false_positive_rate": NAN}),
    ("sensitivity", {"sensitivity": NAN}),
    ("unit_cost", {"unit_cost": INF}),
    ("unit_cost", {"unit_cost": NAN}),
    ("value_per_outcome", {"value_per_outcome": NAN}),
    ("value_per_outcome", {"value_per_outcome": -INF}),
    ("allocation", {"allocation": {"usual_welcome": NAN, "plain_price": 0.5}}),
    ("outcome", {"outcome": {"name": "x", "where": {"min": NAN}}}),
    # arms and control
    ("arms", {"arms": ["usual_welcome"], "allocation": {"usual_welcome": 1.0}}),
    (CASCADE, {"arms": [], "allocation": {}}),
    (("arms", "allocation"), {"arms": ["usual_welcome", "plain_price", "plain_price"]}),
    ("control", {"control": "someone_else"}),
    # allocation
    ("allocation", {"allocation": {"usual_welcome": 1.0}}),
    ("allocation", {"allocation": {"usual_welcome": 0.5, "plain_price": 0.25, "x": 0.25}}),
    ("allocation", {"allocation": {"usual_welcome": 0.5, "other": 0.5}}),
    ("allocation", {"allocation": {"usual_welcome": 1.0, "plain_price": 0.0}}),
    ("allocation", {"allocation": {"usual_welcome": 1.1, "plain_price": -0.1}}),
    ("allocation", {"allocation": {"usual_welcome": 0.5, "plain_price": 0.4}}),
    ("allocation", {"allocation": {"usual_welcome": 0.5, "plain_price": 0.500001}}),
    # direction, effect, alpha, power, baseline, period
    ("direction", {"direction": "less"}),
    ("direction", {"direction": "More"}),
    ("smallest_effect", {"smallest_effect": 0}),
    ("smallest_effect", {"smallest_effect": -0.1}),
    ("false_positive_rate", {"false_positive_rate": 0}),
    ("false_positive_rate", {"false_positive_rate": 1}),
    ("false_positive_rate", {"false_positive_rate": 1.5}),
    ("sensitivity", {"sensitivity": 0}),
    ("sensitivity", {"sensitivity": 1.0}),
    ("baseline_rate", {"baseline_rate": -0.01}),
    ("baseline_rate", {"baseline_rate": 1.01}),
    ("period_days", {"period_days": 0}),
    ("period_days", {"period_days": -7}),
    # negative counts and cost
    ("units_available", {"units_available": -1}),
    ("units_per_period", {"units_per_period": -1}),
    ("horizon_days", {"horizon_days": -1}),
    ("unit_cost", {"unit_cost": -0.01}),
]


@pytest.mark.parametrize(
    ("field", "over"),
    BAD,
    ids=[f"{f if isinstance(f, str) else f[0]}-{i}" for i, (f, _) in enumerate(BAD)],
)
def test_J6_k_refused(field: str | tuple[str, ...], over: dict[str, Any]) -> None:
    refused(field, F.design(**over))


@pytest.mark.parametrize(
    "over",
    [
        {"units_per_period": None},
        {"units_per_period": 0},
        {"units_available": 0},
        {"horizon_days": 0},
        {"unit_cost": 0},
        {"unit_cost": 3},
        {"currency": None},
        {"baseline_rate": None},
        {"baseline_rate": 0},
        {"baseline_rate": 1},
        {"baseline_measure_id": "m_base"},
        {"value_per_outcome": "unknown"},
        {"value_per_outcome": 12.5},
        {"economics_ref": "econ_1", "run_id": "run_1"},
        {"smallest_effect": 1, "direction": "more"},
        {"false_positive_rate": 0.1, "sensitivity": 0.9},
        {"kill_candidates": ["m_1"]},
        {"outcome": {}},
        F.equal_arms(3),
    ],
)
def test_J6_k_accepted(over: dict[str, Any]) -> None:
    r = read(**over)
    assert r["answerable"] in R.ANSWERABLE


# ---------------------------------------------------------------------------------- (l) shape


def test_J6_l_reading_keys_exact() -> None:
    assert list(R.READING_KEYS) == READING_KEYS
    for over in ({}, {"baseline_rate": None}, {"randomized": False}, F.equal_arms(5)):
        r = read(**over)
        assert set(r) == set(READING_KEYS)
        assert len(r) == len(READING_KEYS)


@pytest.mark.parametrize(
    "over",
    [
        {},
        {"units_available": 0},
        {"baseline_rate": None},
        {"randomized": False, "unit_cost": 0.155, "currency": "EUR"},
        {"units_available": 1468, "units_per_period": 100, "horizon_days": 14},
        {"unit_kind": "członek", "currency": "złoty"},
        F.equal_arms(5),
    ],
)
def test_J6_l_json_native_and_closed_strings(over: dict[str, Any]) -> None:
    d = F.design(**over)
    r = R.read_test_design(d)
    assert F.json_native(r)
    assert json.loads(json.dumps(r, allow_nan=False)) == r
    assert R.ANSWERABLE == ("estimable", "marginal", "below_floor")
    assert r["answerable"] in R.ANSWERABLE
    assert r["remedy"] is None or r["remedy"] in R.REMEDIES
    assert set(R.REMEDIES) == {"coarser_comparison", "longer_run", "larger_group"}
    assert r["unit_kind"] == d["unit_kind"]
    assert r["currency"] == d["currency"]
    assert r["engine_version"] == ENGINE_VERSION
    assert isinstance(r["inputs_hash"], str) and len(r["inputs_hash"]) == 64
    assert all(c in "0123456789abcdef" for c in r["inputs_hash"])
    allowed = (
        set(R.ANSWERABLE)
        | set(R.REMEDIES)
        | {"fixed_horizon", d["unit_kind"], ENGINE_VERSION, r["inputs_hash"]}
        | set(r["rule_ref"])
        | ({d["currency"]} if d["currency"] is not None else set())
    )
    assert set(F.strings_in(r)) <= allowed
    for k in ("units_needed", "units_needed_marginal", "periods_needed", "remedy_amount"):
        assert r[k] is None or (isinstance(r[k], int) and not isinstance(r[k], bool)), k
    assert r["value_of_answer"] is None  # rule 14


def test_J6_l_rule_ref() -> None:
    r = read()
    assert isinstance(r["rule_ref"], list) and len(r["rule_ref"]) == 2
    assert r["rule_ref"][0] == WIDTH
    assert r["rule_ref"][1].startswith(MAXP_PREFIX)
    assert r["rule_ref"][1].endswith(__version__)
    assert r["rule_ref"] == R.rule_ref()


def test_J6_l_not_mutated() -> None:
    d = F.design(**F.equal_arms(4), unit_cost=0.155, currency="GBP", units_per_period=100)
    before = copy.deepcopy(d)
    R.read_test_design(d)
    assert d == before
    assert list(d) == list(before)
    assert list(d["allocation"]) == list(before["allocation"])


def test_J6_l_equal_designs_equal_readings_and_key_order() -> None:
    d = F.design(unit_cost=2, currency="GBP")
    shuffled = {k: d[k] for k in reversed(list(d))}
    shuffled["outcome"] = {k: d["outcome"][k] for k in reversed(list(d["outcome"]))}
    shuffled["allocation"] = {k: d["allocation"][k] for k in reversed(list(d["allocation"]))}
    a = R.read_test_design(d)
    b = R.read_test_design(copy.deepcopy(d))
    c = R.read_test_design(shuffled)
    assert a == b == c


def test_J6_l_int_against_equal_float() -> None:
    a = read(unit_cost=2, value_per_outcome=5, smallest_effect=1, direction="more",
             outcome={"window_days": 30})  # fmt: skip
    b = read(unit_cost=2.0, value_per_outcome=5.0, smallest_effect=1.0, direction="more",
             outcome={"window_days": 30.0})  # fmt: skip
    assert a == b


def test_J6_l_inputs_hash_moves_with_the_design() -> None:
    assert read()["inputs_hash"] != read(units_available=1901)["inputs_hash"]
    assert read()["inputs_hash"] != read(outcome={"name": "other"})["inputs_hash"]


# -------------------------------------------------------------------------- J6.S2 (1) the hash

HASH_DESIGN = F.design(
    unit_kind="członek_会员",
    outcome={
        "name": "notice",
        "where": {
            "event": ["cancellation_notice"],
            "window_days": 30,
            "weight": 30.0,
            "tolerance": 1e-05,
            "Zeta": True,
            "é": None,
            "alpha": [1, 1.0, 0.1],
        },
    },
    unit_cost=2,
    value_per_outcome=2.0,
    currency="EUR",
)
# Computed with j6_fixtures.c1_hash, written from J6.S2 (1)'s text, and cross-checked against
# json.dumps(normalised, sort_keys=True, separators=(",", ":"), ensure_ascii=False).
HASH_DESIGN_C1 = "7dcd7f5952a00670f094ee65d27a0514bbc68d5544e10f5a6df6ede23de0dab1"


def test_J6_S2_stated_hash() -> None:
    assert R.HASH_FORM == "bayes-design-c1"
    assert F.c1_hash(HASH_DESIGN) == HASH_DESIGN_C1
    assert R.design_hash(copy.deepcopy(HASH_DESIGN)) == HASH_DESIGN_C1
    assert R.read_test_design(copy.deepcopy(HASH_DESIGN))["inputs_hash"] == HASH_DESIGN_C1


@pytest.mark.parametrize(
    "over",
    [
        {},
        {"baseline_rate": None},
        {"unit_cost": 0.155, "currency": "€"},
        {"smallest_effect": 1e-05},
        {"value_per_outcome": 1e300},
        F.equal_arms(5),
    ],
)
def test_J6_S2_second_implementation_agrees(over: dict[str, Any]) -> None:
    d = F.design(**over)
    assert R.design_hash(d) == F.c1_hash(d)
    assert R.read_test_design(d)["inputs_hash"] == F.c1_hash(d)


def test_J6_S2_key_order_and_int_float() -> None:
    d = copy.deepcopy(HASH_DESIGN)
    rev = {k: d[k] for k in reversed(list(d))}
    rev["outcome"]["where"] = {
        k: d["outcome"]["where"][k] for k in reversed(list(d["outcome"]["where"]))
    }
    floats = copy.deepcopy(d)
    floats["unit_cost"] = 2.0
    floats["value_per_outcome"] = 2
    floats["outcome"]["where"]["window_days"] = 30.0
    floats["outcome"]["where"]["alpha"] = [1.0, 1, 0.1]
    assert R.design_hash(rev) == R.design_hash(floats) == HASH_DESIGN_C1


def test_J6_S2_bool_is_not_a_number() -> None:
    a = F.design(outcome={"flag": True})
    b = F.design(outcome={"flag": 1})
    assert R.design_hash(a) != R.design_hash(b)
    assert R.design_hash(a) == F.c1_hash(a)
    assert R.design_hash(b) == F.c1_hash(b)


# ------------------------------------------------------------------- J6.S2 (2) the rule's values


def test_J6_S2_rule_values() -> None:
    rule = R.read_test_design_rule()
    want = {
        "rel_half_width",
        "caveat_rel_half_width",
        "ratio",
        "max_periods",
        "rule_ref",
        "hash_form",
        "engine_version",
    }
    assert want <= set(rule)
    width = registries.resolve(WIDTH)
    assert rule["rel_half_width"] == width["rel_half_width"] == 0.20
    assert rule["caveat_rel_half_width"] == width["caveat_rel_half_width"] == 0.40
    assert rule["ratio"] == width["caveat_rel_half_width"] / width["rel_half_width"]
    assert rule["max_periods"] == R.MAX_PERIODS == 12
    assert rule["hash_form"] == "bayes-design-c1"
    assert rule["engine_version"] == ENGINE_VERSION == read()["engine_version"]
    assert rule["rule_ref"] == read()["rule_ref"] == R.rule_ref()
    assert F.json_native(rule)


def test_J6_socket_pass_throughs() -> None:
    d = F.design(**F.equal_arms(3), unit_cost=0.155)
    assert sock.read_test_design(copy.deepcopy(d)) == R.read_test_design(copy.deepcopy(d))
    assert sock.read_test_design_rule() == R.read_test_design_rule()


_CALL = (
    "import json, sys\n"
    "from bayesian_marketing.atmaos import socket as s\n"
    "req = json.load(sys.stdin)\n"
    "out = getattr(s, req['call'])(*req['args'])\n"
    "sys.stdout.write(json.dumps(out))\n"
)


def test_J6_S2_call_path_isolated_interpreter(iso: Any) -> None:
    """``python -I``, JSON on stdin and stdout, an environment of BAYES_DATA_DIR, HOME and PATH;
    the registries found from the package."""
    env = {
        "BAYES_DATA_DIR": str(iso.store),
        "HOME": os.environ.get("HOME", str(iso.root)),
        "PATH": os.environ.get("PATH", ""),
    }
    d = F.design(**F.equal_arms(5), unit_cost=0.155, currency="GBP")

    def call(name: str, *args: Any) -> Any:
        done = subprocess.run(
            [sys.executable, "-I", "-c", _CALL],
            input=json.dumps({"call": name, "args": list(args)}),
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
            cwd=iso.root,
            check=False,
        )
        assert done.returncode == 0, done.stderr[-2000:]
        return json.loads(done.stdout)

    assert call("read_test_design", d) == R.read_test_design(copy.deepcopy(d))
    assert call("read_test_design_rule") == R.read_test_design_rule()
    assert not any(iso.store.iterdir())


# --------------------------------------------------------------------------- (m) the registry


def test_J6_m_ratio_from_the_registry(iso: Any) -> None:
    def three(data: dict[str, Any]) -> None:
        pw = data["estimability"]["posterior_width"]
        pw["rel_half_width"] = 0.25
        pw["caveat_rel_half_width"] = 0.75

    iso.edit_yaml("bounds", three)
    r = read()
    alloc = {"usual_welcome": 0.5, "plain_price": 0.5}
    assert r["units_needed"] == BASE_NEEDED
    assert r["units_needed_marginal"] == F.units_needed_oracle(
        0.3, 0.2 * 3.0, "fewer", alloc, "usual_welcome"
    )
    assert r["units_needed_marginal"] == 160 != BASE_MARGINAL
    assert read(units_available=160)["answerable"] == "marginal"
    assert read(units_available=159)["answerable"] == "below_floor"
    rule = R.read_test_design_rule()
    assert rule["rel_half_width"] == 0.25 and rule["caveat_rel_half_width"] == 0.75
    assert rule["ratio"] == 3.0


def test_J6_m_ratio_pushing_p2_out(iso: Any) -> None:
    def five(data: dict[str, Any]) -> None:
        pw = data["estimability"]["posterior_width"]
        pw["rel_half_width"] = 0.1
        pw["caveat_rel_half_width"] = 0.5

    iso.edit_yaml("bounds", five)
    r = read(units_available=1000)
    assert r["units_needed"] == BASE_NEEDED
    assert r["units_needed_marginal"] is None
    assert r["answerable"] == "below_floor"


def test_J6_m_max_periods_moves_the_edge(monkeypatch: pytest.MonkeyPatch) -> None:
    kw = {"units_available": BASE_NEEDED - 250, "units_per_period": 100, "horizon_days": 14}
    monkeypatch.setattr(R, "MAX_PERIODS", 4)
    r = read(**kw)
    assert r["periods_needed"] == 5
    assert r["remedy"] == "larger_group" and r["remedy_amount"] == BASE_NEEDED
    monkeypatch.setattr(R, "MAX_PERIODS", 5)
    r = read(**kw)
    assert r["remedy"] == "longer_run" and r["remedy_amount"] == 5


# ------------------------------------------------------------------------- (n) reads nothing else


def test_J6_n_reads_no_store_no_notebook(iso: Any) -> None:
    from bayesian_marketing.funnel_state import store

    R.read_test_design(F.design())  # imports warmed
    data = Path(store.data_dir()).resolve()
    designs = [
        F.design(),
        F.design(**F.equal_arms(5), units_per_period=100),
        F.design(baseline_rate=None),
        F.design(randomized=False, unit_cost=0.155, holdout=True),
    ]
    with F.OpenAudit() as audit:
        for d in designs:
            R.read_test_design(d)
        R.read_test_design_rule()
        sock.read_test_design(F.design())
        sock.read_test_design_rule()
    assert audit.sqlite == []
    reg = iso.registry.resolve()
    allowed_repo = [REPO / "src", REPO / ".venv"]
    for raw in audit.opened:
        p = Path(raw).resolve()
        assert not p.is_relative_to(data), raw
        assert not p.is_relative_to(REPO / "notebook"), raw
        assert not p.is_relative_to(REPO / "data"), raw
        if p.is_relative_to(REPO):
            assert any(p.is_relative_to(a) for a in allowed_repo), raw
        if p.is_relative_to(iso.root.resolve()):
            assert p.is_relative_to(reg), raw
    assert not any(iso.store.iterdir())


# --------------------------------------------------------------- J6.S4, registries.versions()


def test_J6_S4_no_registry_file_and_versions_unchanged() -> None:
    root = REPO / "registries"
    before = registries.versions(root)
    files_before = {p: p.read_bytes() for p in sorted(root.rglob("*.yaml"))}
    assert not any("test_design" in name for name in before)
    for p, body in files_before.items():
        assert b"max_periods" not in body, p
    R.read_test_design(F.design())
    R.read_test_design_rule()
    registries.clear_cache()
    assert registries.versions(root) == before
    assert {p: p.read_bytes() for p in sorted(root.rglob("*.yaml"))} == files_before
    assert registries.versions() == registries.versions(root)


def test_J6_S4_max_periods_in_code() -> None:
    assert R.MAX_PERIODS == 12
    assert R.rule_ref()[1].startswith(MAXP_PREFIX)
    assert R.rule_ref()[0] == WIDTH


# --------------------------------------------------------------- request cases 2 and 6, Not in J6


def test_J6_case2_not_ad_spend() -> None:
    r = read(units_available=BASE_NEEDED - 250, units_per_period=100, horizon_days=14,
             unit_cost=0.25, currency="GBP", value_per_outcome=40.0)  # fmt: skip
    assert r["answerable"] == "marginal"
    assert r["units_needed"] == BASE_NEEDED and r["units_needed_marginal"] == BASE_MARGINAL
    assert r["periods_needed"] == 5
    assert r["cost_of_test"] == 429.5
    assert r["value_of_answer"] is None


def test_J6_case6_paid_media_reads_as_case2() -> None:
    plain = F.design(units_per_period=100, unit_cost=0.25, currency="GBP")
    paid = F.design(
        units_per_period=100,
        unit_cost=0.25,
        currency="GBP",
        channel="meta",
        exposure="impression",
        economics_ref="econ/meta@v1",
        value_per_outcome=40.0,
        run_id="run_122248b8",
        baseline_measure_id="m_base",
        kill_candidates=["m_cpa"],
        outcome={"name": "purchase"},
    )
    a, b = R.read_test_design(plain), R.read_test_design(paid)
    assert a["inputs_hash"] != b["inputs_hash"]
    a.pop("inputs_hash")
    b.pop("inputs_hash")
    assert a == b
    assert b["value_of_answer"] is None
    assert b["stopping_rule"]["kind"] == "fixed_horizon"
