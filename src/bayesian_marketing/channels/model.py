"""§5.7 channel_model."""

from __future__ import annotations

from datetime import date

from bayesian_marketing.core import ChannelModel, Platform


def channel_model(platform: Platform, as_of: date) -> ChannelModel:
    """Read the platform's ChannelModel from ``registries/channels.yaml``. A stale one fails G1."""
    raise NotImplementedError("P1")
