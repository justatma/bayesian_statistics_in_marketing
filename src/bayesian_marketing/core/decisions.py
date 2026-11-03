"""§4.8 Guarantee and Recommendation, §4.9 Horizon and Objective, §4.10 ClientEconomics,
§8.1 Comparison, §6.3 decision-problem types.

Comparison and the test-design types live in core because floors (a lower layer) reads them
(D18).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import model_validator

from bayesian_marketing.core.base import Frozen
from bayesian_marketing.core.money import DistributionSpec, Money, MoneyInterval
from bayesian_marketing.core.scope import Feasibility, Scope


class Horizon(Frozen):
    unit: Literal["clicks", "impressions", "spend", "days"]
    amount: Decimal  # e.g. 1000 clicks; $5000 spend


class Objective(Frozen):
    target: Literal["contribution", "orders", "clicks"] = "contribution"
    horizon: Horizon


class ClientEconomics(Frozen):
    economics_id: str
    client_id: str
    currency: str
    variable_cost_per_order: Money  # production, fulfillment, processing, expected returns
    price_source: Literal["modeled_aov", "fixed"]
    fixed_price: Money | None = None  # required when price_source="fixed"
    repeat_value: DistributionSpec | None = None
    loss_tolerance: Money | None = None  # per decision at its horizon; None → G9 fails (D16)
    survival_floor: Money | None = None
    test_budget: Money | None = None
    source: str
    approved_by: str | None = None
    approved_at: datetime | None = None

    @model_validator(mode="after")
    def _consistent(self) -> ClientEconomics:
        if self.price_source == "fixed" and self.fixed_price is None:
            raise ValueError("price_source='fixed' requires fixed_price")
        for name in (
            "variable_cost_per_order",
            "fixed_price",
            "loss_tolerance",
            "survival_floor",
            "test_budget",
        ):
            m = getattr(self, name)
            if m is not None and m.currency != self.currency:
                raise ValueError(f"{name} is in {m.currency}, economics are in {self.currency}")
        return self

    @property
    def approved(self) -> bool:
        return self.approved_by is not None and self.approved_at is not None


class Guarantee(Frozen):
    kind: Literal["posterior_probability", "expected_loss", "value_of_information", "none"]
    statement_math: str
    template_id: str  # guarantee_templates.yaml key; prose is rendered, never stored free
    slots: dict[str, str]
    assumptions: list[str]


RecommendationAction = Literal[
    "allocate",
    "reallocate",
    "hold",
    "stop_test",
    "continue_test",
    "collect_more_data",
    "repair_measurement",
    "not_knowable",
]


class Recommendation(Frozen):
    recommendation_id: str
    action: RecommendationAction
    scope: Scope
    params: dict[str, Any]  # e.g. {"allocation": {"ad_b": 0.7, "ad_a": 0.3}}
    basis: list[str]  # quantity_ids
    decision_feasibility: Feasibility  # basis="decision_loss" (D9)
    economics_id: str | None  # None only for not_knowable / repair_measurement
    guarantee: Guarantee
    expected_benefit: Money | None
    expected_loss: Money | None
    horizon: Horizon
    reversibility: Literal["reversible", "costly", "irreversible"]
    requires_human_approval: Literal[True] = True
    run_id: str

    @model_validator(mode="after")
    def _rules(self) -> Recommendation:
        if self.decision_feasibility.basis != "decision_loss":
            raise ValueError("decision_feasibility.basis must be 'decision_loss' (D9)")
        if self.economics_id is None and self.action not in ("not_knowable", "repair_measurement"):
            raise ValueError("economics_id may be None only for not_knowable/repair_measurement")
        return self


class Comparison(Frozen):
    options: list[str]
    objective: Objective
    economics_id: str
    p_best: dict[str, float]
    expected_value: dict[str, Money]  # at horizon
    expected_loss: dict[str, Money]  # expected opportunity loss of choosing each
    p_exceeds_break_even: dict[str, float]
    method: Literal["exact_integration", "joint_draws"]
    mc_standard_error: dict[str, float] | None = None  # joint_draws only (§8.1 C2)
    value_q05: dict[str, Money] | None = None  # D22: 5th pct of value at horizon (§8.2 C3)


class DecisionProblem(Frozen):
    options: list[str]
    payoffs: dict[str, DistributionSpec]  # per option, at horizon
    objective: Objective


class TestDesign(Frozen):
    __test__ = False  # not a pytest class

    arms: list[str]
    allocation: dict[str, float]
    volume: Horizon
    randomized: bool
    holdout: bool
    sensitivity: float | None = None  # signal-type tests (Manuscript ch. 6)
    false_positive_rate: float | None = None


class DesignAssessment(Frozen):
    evpi: Money
    evsi: Money
    cost: MoneyInterval
    net_value: Money
    verdict: Literal["buy", "do_not_buy", "redesign"]
    redesign: TestDesign | None
    design_label: Literal["observational", "randomized", "holdout"]
