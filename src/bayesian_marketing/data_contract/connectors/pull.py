"""§5.1 pull."""

from __future__ import annotations

from datetime import date

from bayesian_marketing.core import ClientConfig, Platform, PlatformPull


def pull(platform: Platform, config: ClientConfig, window: tuple[date, date]) -> PlatformPull:
    """Pull one platform's rows for the window. Records redacted exchanges when RECORD=1 (C6)."""
    raise NotImplementedError("P8")
