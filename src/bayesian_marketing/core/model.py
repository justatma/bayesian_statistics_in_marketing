"""Model, prior, state, lag, channel and route types: §5.2 to §5.7, §7.1.

In core so every layer can name them without importing upward (D18). Their modules re-export.
"""

from __future__ import annotations

import itertools
from datetime import date, datetime
from typing import Literal

from pydantic import Field, model_validator

from bayesian_marketing.core.base import Frozen, Platform, UncoupledFunnelError
from bayesian_marketing.core.money import DistributionSpec, Money


class StageSpec(Frozen):
    name: Literal["delivery", "ctr", "cvr", "value"]
    likelihood: Literal[
        "poisson",
        "binomial",
        "beta_binomial",
        "gamma_obs",
        "lognormal",
        "compound_gamma",
    ]
    pooled: bool


class FunnelSpec(Frozen):
    version: str
    stages: list[StageSpec]
    hierarchy: list[Literal["ad", "campaign", "account"]]  # within one platform (§5.2 C8)
    coupling: Literal["lkj_bivariate"] | None = "lkj_bivariate"  # required (I9)
    dynamics: Literal["static", "random_walk"] = "static"

    @model_validator(mode="after")
    def _i9(self) -> FunnelSpec:
        if self.coupling != "lkj_bivariate":
            raise UncoupledFunnelError("a joint-route FunnelSpec needs lkj_bivariate coupling (I9)")
        if "value" not in {s.name for s in self.stages}:
            raise ValueError("order value is always a modeled stage (I9)")
        return self


class ElicitationRecord(Frozen):
    source: Literal["ai_proposal", "human", "historical_fit", "promoted"]
    rationale: str
    evidence_refs: list[str]
    author: str
    created_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None
    promotion_id: str | None = None


class PriorRecord(Frozen):
    prior_id: str  # "pr_<sha8>"
    parameter_path: str
    family: str
    params: dict[str, float]
    elicitation: ElicitationRecord
    version: str
    resolution_path: list[str]
    predictive_check: dict[str, float] | None = None

    @property
    def approved(self) -> bool:
        return self.elicitation.approved_by is not None


class PriorSet(Frozen):
    records: dict[str, PriorRecord]  # parameter_path -> approved record


class CompiledModel(Frozen):
    spec_version: str
    model_fn_ref: str
    data_shape: dict[str, int]


class FitConfig(Frozen):
    chains: int
    draws: int
    warmup: int
    target_accept: float
    seed: int


class FunnelState(Frozen):
    state_id: str  # "fs_<sha8>"
    spec_version: str | None
    route: Literal["conjugate", "nuts"]
    prior_ids: dict[str, str]
    data_window: tuple[date, date]
    posterior: DistributionSpec
    diagnostics_id: str | None
    supersedes: str | None = None
    quarantined: bool = False
    created_at: datetime
    synthetic: bool
    data_pull_ids: list[str] = Field(default_factory=list)  # D22: derive fills Provenance from it


class LagModel(Frozen):
    platform: Platform
    attribution_window: str
    cdf: list[float]  # F(a) for a = 0..max_days
    source: Literal["orders_history", "platform_lag_report", "registry_default"]
    n_lagged_conversions: int

    @model_validator(mode="after")
    def _cdf(self) -> LagModel:
        c = self.cdf
        decreasing = any(b < a for a, b in itertools.pairwise(c))
        if not c or decreasing or not 0 <= c[0] <= c[-1] <= 1:
            raise ValueError("cdf must be non-decreasing within [0, 1]")
        return self


class ChannelModel(Frozen):
    platform: Platform
    version: str
    export_map: dict[str, str]  # platform column -> PerformanceRow field
    conversion_field_may_be_modeled: bool
    default_attribution_window: str
    learning_phase_switching_cost: Money | None  # None = unknown, disclosed
    freshness_date: date
    max_age_days: int

    def is_stale(self, as_of: date) -> bool:
        return (as_of - self.freshness_date).days > self.max_age_days


class Route(Frozen):
    kind: Literal["conjugate", "nuts"]
    reason: str
    notices: list[str]
