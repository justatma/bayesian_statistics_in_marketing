"""``registries/live.yaml`` (spec v0.2 §3.4), loaded through ``core.registries``."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, model_validator

from bayesian_marketing.core import registries
from bayesian_marketing.core.base import Frozen


class LiveRegistry(Frozen):
    version: str
    freshness_date: str
    interval_seconds: int = Field(gt=0)
    lookback_days: int = Field(ge=1)
    # L12 (D55): the engine's analysis window, the last analysis_days of the poll; <= lookback_days
    analysis_days: int = Field(default=7, ge=1)
    stale_after_seconds: int = Field(gt=0)
    recordings_keep_days: int = Field(ge=1)
    page_refresh_seconds: int = Field(gt=0)
    bind: str
    port: int = Field(ge=0, le=65535)
    account_status: dict[str, str]

    @model_validator(mode="after")
    def _analysis_within_lookback(self) -> LiveRegistry:
        """L12 item 1: ``1 <= analysis_days <= lookback_days``; a registry that breaks it fails
        to load."""
        if not 1 <= self.analysis_days <= self.lookback_days:
            raise ValueError(
                f"analysis_days ({self.analysis_days}) must be between 1 and lookback_days "
                f"({self.lookback_days})"
            )
        return self


def load_live_registry(root: Path | None = None) -> LiveRegistry:
    data = registries.load("live", root)
    data = {**data, "account_status": {str(k): str(v) for k, v in data["account_status"].items()}}
    return LiveRegistry.model_validate({**data, "version": str(data["version"])})
