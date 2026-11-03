"""§5.1 read_export."""

from __future__ import annotations

from pathlib import Path

from bayesian_marketing.core import DatasetManifest, Platform, PlatformPull


def read_export(platform: Platform, path: Path, manifest: DatasetManifest) -> PlatformPull:
    """Read one export file into a PlatformPull (§5.1 C1 to C5, C7, C8; G1)."""
    raise NotImplementedError("P1")
