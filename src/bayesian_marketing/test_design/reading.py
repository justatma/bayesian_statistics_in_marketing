"""Reading a proposed test, ``read_test_design`` (J6; spec/Test_Design_Reading_Specification_v0.2.md
with J6.S1 to J6.S4). A pure function of the design and the registries: it reads no store, run,
notebook or file under ``data_dir()``, never mutates its input, and gives no free text."""

from __future__ import annotations

from typing import Any

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


def rule_ref() -> list[str]:
    """J6.S4: the references a reading cites."""
    raise NotImplementedError


def design_hash(design: dict[str, Any]) -> str:
    """J6.S2 (1): the design's hash under ``bayes-design-c1``."""
    raise NotImplementedError


def read_test_design(design: dict[str, Any]) -> dict[str, Any]:
    """J6: the reading of a proposed test. Raises ``ValueError`` naming the field on a malformed
    design; a well-formed design that can't answer is a reading."""
    raise NotImplementedError


def read_test_design_rule() -> dict[str, Any]:
    """J6.S2 (2): ``rel_half_width``, ``caveat_rel_half_width``, ``ratio``, ``max_periods``,
    ``rule_ref``, ``hash_form`` and ``engine_version``."""
    raise NotImplementedError
