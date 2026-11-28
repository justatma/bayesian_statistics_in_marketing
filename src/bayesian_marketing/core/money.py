"""§4.1 Money and intervals, §4.2 DistributionSpec."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import field_validator, model_validator

from bayesian_marketing.core.base import Frozen

ISO_4217_PATTERN = r"^[A-Z]{3}$"
REQUIRED_SUMMARY_KEYS = ("mean", "sd", "q05", "q50", "q95", "q025", "q975")


class Money(Frozen):
    amount: Decimal
    currency: str

    @field_validator("currency")
    @classmethod
    def _iso(cls, v: str) -> str:
        if len(v) != 3 or not v.isalpha() or not v.isupper():
            raise ValueError(f"currency must be an ISO 4217 code, got {v!r}")
        return v


class MoneyInterval(Frozen):
    low: Money
    mid: Money
    high: Money
    level: float = 0.9

    @model_validator(mode="after")
    def _same_currency(self) -> MoneyInterval:
        if len({self.low.currency, self.mid.currency, self.high.currency}) != 1:
            raise ValueError("interval mixes currencies")
        return self


class DistributionSpec(Frozen):
    kind: Literal["analytic", "samples"]
    family: str | None = None  # beta | gamma | invgamma | lognorm (analytic)
    params: dict[str, float] | None = None
    samples_path: str | None = None  # parquet, one column per entity, rows are joint draws
    n_samples: int | None = None
    summary: dict[str, float]

    @model_validator(mode="after")
    def _shape(self) -> DistributionSpec:
        missing = [k for k in REQUIRED_SUMMARY_KEYS if k not in self.summary]
        if missing:
            raise ValueError(f"summary missing {missing}")
        if self.kind == "analytic" and (self.family is None or self.params is None):
            raise ValueError("analytic distribution needs family and params")
        if self.kind == "samples" and (self.samples_path is None or not self.n_samples):
            raise ValueError("samples distribution needs samples_path and n_samples")
        return self
