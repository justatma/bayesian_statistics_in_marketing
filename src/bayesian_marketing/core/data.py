"""Row, pull and model-input types: §4.14, §5.1.

These sit in core so the simulator, readers and connectors share one definition (D18).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import Field, model_validator

from bayesian_marketing.core.base import Frozen, Platform, RegistryRef
from bayesian_marketing.core.money import Money


class PerformanceRow(Frozen):
    entity_ids: dict[str, str]  # keys among account, campaign, ad_set, ad
    entity_names: dict[str, str] = Field(
        default_factory=dict
    )  # same keys; names change, ids don't (D34)
    objective: str | None = (
        None  # campaign objective / optimization event as the source states it (D34)
    )
    date: date
    impressions: int
    clicks: int
    spend: Money
    conversions_observed: int | None = None
    conversions_reported: float | None = None
    conversions_modeled_share: float | None = None
    attribution_window: str
    revenue_reported: Money | None = None


class OrderRow(Frozen):
    order_id: str
    ordered_at: datetime
    value: Money
    refunded: Money
    utm: dict[str, str] | None = None
    click_id: str | None = None
    first_click_at: datetime | None = None


class SiteRow(Frozen):
    date: date
    utm: dict[str, str]
    sessions: int
    purchases: int
    revenue: Money


class QuarantinedRow(Frozen):
    raw: dict[str, Any]
    reasons: list[str]

    @model_validator(mode="after")
    def _has_reason(self) -> QuarantinedRow:
        if not self.reasons:
            raise ValueError("a quarantined row needs at least one reason (§5.1 C1)")
        return self


class PlatformPull(Frozen):
    pull_id: str  # "pull_<platform>_<sha8>" (D18)
    platform: Platform
    channel_ref: RegistryRef
    account_id: str | None = None
    window: tuple[date, date] | None = None
    rows: list[PerformanceRow] | list[OrderRow] | list[SiteRow]
    quarantined: list[QuarantinedRow]
    partial_truth: bool
    measurement_changes: list[str]  # attribution/measurement changes in window only (§5.1 C5)
    notes: list[str] = Field(default_factory=list)  # reader disclosures that are not C5 (D24)
    empty_account: bool = False  # §5.1 C6
    timezone: str | None = None  # account timezone the dates were normalized from (§5.1 C2)
    account: dict[str, str] = Field(default_factory=dict)  # live view §3.3 (D43): raw, as text
    pulled_at: datetime
    synthetic: bool

    @model_validator(mode="after")
    def _id_names_platform(self) -> PlatformPull:
        if not self.pull_id.startswith(f"pull_{self.platform}_"):
            raise ValueError(f"pull_id must start with 'pull_{self.platform}_' (D18)")
        return self


class FunnelData(Frozen):
    """Per-entity, per-day arrays for one platform. Index order: ``[entity][day]``.

    Zero spend marks a structural zero (§5.2 C4); such days contribute no likelihood terms.
    """

    platform: Platform
    currency: str
    entities: list[str]  # ad ids
    parents: dict[str, dict[str, str]]  # ad id -> {"campaign": ..., "account": ...}
    dates: list[date]
    spend: list[list[float]]
    impressions: list[list[int]]
    clicks: list[list[int]]
    conversions_observed: list[list[int | None]]
    conversions_reported: list[list[float | None]]
    mature_fraction: list[list[float]]  # F(as_of - d), §5.6
    revenue_reported: list[list[float | None]]
    order_values: dict[str, list[float]] = Field(default_factory=dict)  # ad id -> order values
    pull_ids: list[str]
    synthetic: bool

    @model_validator(mode="after")
    def _shapes(self) -> FunnelData:
        n_e, n_d = len(self.entities), len(self.dates)
        for name in (
            "spend",
            "impressions",
            "clicks",
            "conversions_observed",
            "conversions_reported",
            "mature_fraction",
            "revenue_reported",
        ):
            arr = getattr(self, name)
            if len(arr) != n_e or any(len(row) != n_d for row in arr):
                raise ValueError(f"{name} must be [{n_e} entities][{n_d} days]")
        return self


class PrecisionTarget(Frozen):
    rel_half_width: float
    level: float = 0.9
    caveat_rel_half_width: float


class DegradationNotice(Frozen):
    notice_id: str
    step: str
    reason: str
    affected: list[str]
