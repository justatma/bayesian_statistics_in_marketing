"""§5.7 channel_model."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from bayesian_marketing.core import (
    ChannelModel,
    GateFailure,
    GateResult,
    Money,
    Platform,
    inputs_hash,
    registries,
    utcnow,
)

__all__ = ["ChannelModel", "channel_entry", "channel_model", "channel_ref", "load_channel_model"]

REGISTRY = "channels"


def channel_entry(platform: Platform) -> dict[str, Any]:
    """The raw registry entry for one platform."""
    channels = registries.load(REGISTRY)["channels"]
    if platform not in channels:
        raise ValueError(f"no channel model for platform {platform!r} in registries/channels.yaml")
    return channels[platform]


def channel_ref(platform: Platform) -> str:
    """RegistryRef of the platform's channel entry, e.g. ``channels/channels/meta@v1``."""
    version = registries.load(REGISTRY)["version"]
    return f"{REGISTRY}/channels/{platform}@{version}"


def _as_date(v: Any) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def _switching_cost(v: Any) -> Money | None:
    if v is None:
        return None
    return Money(amount=Decimal(str(v["amount"])), currency=str(v["currency"]))


def load_channel_model(platform: Platform) -> ChannelModel:
    """Build the ChannelModel from the registry without judging freshness."""
    e = channel_entry(platform)
    return ChannelModel(
        platform=platform,
        version=str(e["version"]),
        export_map=dict(e["export_map"]),
        conversion_field_may_be_modeled=bool(e["conversion_field_may_be_modeled"]),
        default_attribution_window=str(e["default_attribution_window"]),
        learning_phase_switching_cost=_switching_cost(e.get("learning_phase_switching_cost")),
        freshness_date=_as_date(e["freshness_date"]),
        max_age_days=int(e["max_age_days"]),
    )


def stale_result(cm: ChannelModel, as_of: date) -> GateResult:
    """The failing G1 result for a stale channel model."""
    age = (as_of - cm.freshness_date).days
    return GateResult(
        gate="G1",
        passed=False,
        blocking=True,
        reasons=[
            f"channel model for {cm.platform} is stale: freshness_date "
            f"{cm.freshness_date.isoformat()} is {age} days before {as_of.isoformat()}, "
            f"max_age_days {cm.max_age_days}"
        ],
        inputs_hash=inputs_hash(
            {"platform": cm.platform, "version": cm.version, "as_of": as_of.isoformat()}
        ),
        checked_at=utcnow(),
    )


def channel_model(platform: Platform, as_of: date) -> ChannelModel:
    """Read the platform's ChannelModel from ``registries/channels.yaml``. A stale one fails G1.

    Raises ``GateFailure`` (gate ``G1``) when the model is stale at ``as_of``; only that
    platform is blocked.
    """
    cm = load_channel_model(platform)
    if cm.is_stale(as_of):
        raise GateFailure(stale_result(cm, as_of))
    return cm
