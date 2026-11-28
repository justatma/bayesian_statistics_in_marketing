"""Scenario files (``data/scenarios/<name>.yaml``, §9.1) parsed into typed objects.

Every number the simulator uses comes from the scenario file or from ``registries/channels.yaml``;
the code holds none of its own (I6).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

AdPlatform = Literal["meta", "google_ads", "linkedin"]


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Named(_Strict):
    id: str
    name: str


class OrderValue(_Strict):
    """Order value per ad: a fixed amount, or log-normal with an ad-level spread of log median."""

    dist: Literal["fixed", "lognormal"]
    amount: Decimal | None = None  # fixed
    median: float | None = None  # lognormal: population median
    sigma: float | None = None  # lognormal: within-ad log sd
    ad_log_sd: float = 0.0  # lognormal: sd of ad log medians around the population (C2 pooling)

    @model_validator(mode="after")
    def _complete(self) -> OrderValue:
        if self.dist == "fixed" and self.amount is None:
            raise ValueError("fixed order value needs amount")
        if self.dist == "lognormal" and (self.median is None or self.sigma is None):
            raise ValueError("lognormal order value needs median and sigma")
        return self


class Lag(_Strict):
    """Geometric lag in whole days from click to order, with the stated median (§5.6)."""

    median_days: int = 0


class FractionalCredit(_Strict):
    """Per-conversion credit share ~ Beta(a, b), as a data-driven attribution model reports."""

    beta_a: float
    beta_b: float
    decimals: int


class WindowChange(_Strict):
    from_day: int  # 0-based day index from which the new window applies
    window: str
    click_window_days: int | None = None


class PlatformSpec(_Strict):
    attribution_window: str | None = None  # default: the channel's default_attribution_window
    click_window_days: int | None = None  # default: parsed from "<n>d_click"
    utm_source: str
    utm_medium: str
    orders_joinable: bool = True  # False: orders carry no utm, so only the platform column counts
    fractional_credit: FractionalCredit | None = None
    window_changes: list[WindowChange] = Field(default_factory=list)


class Phase(_Strict):
    """A run of days with its spend and any totals the scenario fixes exactly."""

    days: int
    spend: Decimal | None = None  # total over the phase
    spend_per_day: Decimal | None = None
    impressions: int | None = None
    clicks: int | None = None
    conversions: int | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Phase:
        if (self.spend is None) == (self.spend_per_day is None):
            raise ValueError("a phase needs exactly one of spend, spend_per_day")
        if self.conversions is not None and self.clicks is None:
            raise ValueError("fixed conversions need fixed clicks")
        if self.impressions is not None and self.clicks is None:
            raise ValueError("fixed impressions need fixed clicks")
        if self.impressions is not None and self.impressions < self.clicks:  # type: ignore[operator]
            raise ValueError("fixed clicks exceed fixed impressions")
        if self.conversions is not None and self.conversions > self.clicks:  # type: ignore[operator]
            raise ValueError("fixed conversions exceed fixed clicks")
        return self


class Truth(_Strict):
    ctr: float
    cvr: float
    cpm: float | None = None
    cpc: float | None = None  # default: cpm / (1000 ctr), or spend / clicks when clicks are fixed


class AdSpec(_Strict):
    variant: str
    platform: AdPlatform
    account: Named
    campaign: Named
    ad_set: Named
    ad: Named
    utm_campaign: str
    truth: Truth
    phases: list[Phase]
    order_value: OrderValue | None = None  # default: the scenario's order_value


class LogitSd(_Strict):
    account: tuple[float, float]
    campaign: tuple[float, float]
    ad: tuple[float, float]


class PopulationNames(_Strict):
    """Name templates; ``{i}``, ``{j}``, ``{k}`` are the account, campaign and ad numbers."""

    account: str
    campaign: str
    ad_set: str
    ad: str


class Population(_Strict):
    """Ads drawn from a hierarchy: account and campaign offsets, then ad-level (logit ctr,
    logit cvr) bivariate normal with correlation ``ad_rho`` (§5.2 C1, §9.1)."""

    platform: AdPlatform
    accounts: int
    campaigns_per_account: int
    ads_per_campaign: int
    ctr_median: float
    cvr_median: float
    logit_sd: LogitSd
    ad_rho: float
    cpm_median: float
    cpm_log_sd: float
    spend_per_day: Decimal
    id_prefix: str
    names: PopulationNames


class EconomicsSpec(_Strict):
    variable_cost_per_order: Decimal
    price_source: Literal["modeled_aov", "fixed"]
    fixed_price: Decimal | None = None
    loss_tolerance: Decimal | None = None
    survival_floor: Decimal | None = None
    test_budget: Decimal | None = None
    source: str
    approved_by: str | None = None
    approved_at: str | None = None


class Scenario(_Strict):
    scenario: str
    description: str
    client_id: str
    currency: str
    utc_offset: str
    start_date: date
    n_days: int
    platforms: dict[AdPlatform, PlatformSpec]
    lag: Lag = Lag()
    order_value: OrderValue
    economics: EconomicsSpec
    ads: list[AdSpec] = Field(default_factory=list)
    population: Population | None = None
    notes: dict[str, object] = Field(default_factory=dict)  # recorded into GroundTruth.params

    @model_validator(mode="after")
    def _consistent(self) -> Scenario:
        if not self.ads and self.population is None:
            raise ValueError("a scenario needs ads or a population")
        for a in self.ads:
            if a.platform not in self.platforms:
                raise ValueError(f"ad {a.variant} is on undeclared platform {a.platform}")
            if sum(p.days for p in a.phases) != self.n_days:
                raise ValueError(f"ad {a.variant}: phases cover {sum(p.days for p in a.phases)}")
        if self.population and self.population.platform not in self.platforms:
            raise ValueError("population platform is not declared")
        variants = [a.variant for a in self.ads]
        if len(variants) != len(set(variants)):
            raise ValueError("duplicate variant names")
        return self


def load_scenario(path: Path) -> tuple[Scenario, dict[str, object]]:
    """The parsed scenario and its raw mapping (recorded in GroundTruth.params)."""
    raw = yaml.safe_load(Path(path).read_text())
    return Scenario.model_validate(raw), raw
