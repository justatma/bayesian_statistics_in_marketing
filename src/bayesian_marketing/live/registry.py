"""``registries/live.yaml`` (spec v0.2 §3.4), loaded through ``core.registries``."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from bayesian_marketing.core import registries
from bayesian_marketing.core.base import Frozen


class LiveRegistry(Frozen):
    version: str
    freshness_date: str
    interval_seconds: int = Field(gt=0)
    lookback_days: int = Field(ge=1)
    stale_after_seconds: int = Field(gt=0)
    recordings_keep_days: int = Field(ge=1)
    page_refresh_seconds: int = Field(gt=0)
    bind: str
    port: int = Field(ge=0, le=65535)
    account_status: dict[str, str]


def load_live_registry(root: Path | None = None) -> LiveRegistry:
    data = registries.load("live", root)
    data = {**data, "account_status": {str(k): str(v) for k, v in data["account_status"].items()}}
    return LiveRegistry.model_validate({**data, "version": str(data["version"])})
