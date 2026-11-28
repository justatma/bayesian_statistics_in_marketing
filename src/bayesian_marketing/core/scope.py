"""§4.3 Scope and Provenance, §4.4 Feasibility, §4.5 Gates, §4.7 DiagnosticsReport."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, model_validator

from bayesian_marketing.core.base import Frozen, Platform, RegistryRef


class Scope(Frozen):
    level: Literal["ad", "ad_set", "campaign", "account"]
    ids: dict[str, str]
    window: tuple[date, date]
    platform: Platform | None  # None only for cross-platform sums (§5.2 C8)


class Provenance(Frozen):
    funnel_state_id: str | None  # None for deterministic quantities
    model_version: str
    data_pull_ids: list[str]
    derived_by: str
    route: Literal["conjugate", "nuts", "deterministic"]
    synthetic: bool  # True if any input came from simulate/ (D17)
    computed_at: datetime


FeasibilityStatus = Literal["estimable", "marginal", "below_floor"]
STATUS_ORDER: dict[str, int] = {"below_floor": 0, "marginal": 1, "estimable": 2}
"""Higher is better. Statuses only move down without new data (I5)."""


class Feasibility(Frozen):
    status: FeasibilityStatus
    basis: Literal["quantity_precision", "decision_loss", "inherited"]
    bound_ref: RegistryRef
    available: float
    required: float | None
    target: float
    reasons: list[str]  # non-empty unless estimable
    supersedes: str | None = None
    checked_at: datetime

    @model_validator(mode="after")
    def _reasons(self) -> Feasibility:
        if self.status != "estimable" and not self.reasons:
            raise ValueError("a non-estimable feasibility needs at least one reason")
        return self


def worst_status(statuses: list[str]) -> str:
    """The lowest of the given statuses (§5.2 C8, D10 'inherited')."""
    return min(statuses, key=lambda s: STATUS_ORDER[s])


class GateResult(Frozen):
    gate: str
    passed: bool
    blocking: bool
    reasons: list[str]
    inputs_hash: str
    checked_at: datetime


class Gate(Protocol):
    name: str

    def check(self, obj: BaseModel) -> GateResult: ...


class DiagnosticsReport(Frozen):
    report_id: str
    sampler: Literal["numpyro_nuts", "conjugate"]
    rhat_max: float | None
    ess_bulk_min: float | None
    ess_tail_min: float | None
    n_divergences: int | None
    ppc: dict[str, float]
    loo: dict[str, float] | None
    seeds: list[int]
    thresholds_ref: RegistryRef
    passed: bool | None = None  # set only by G3
