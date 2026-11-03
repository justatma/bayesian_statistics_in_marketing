"""§9.1 generate."""

from __future__ import annotations

from pathlib import Path

from bayesian_marketing.core import GroundTruth


def generate(scenario_path: Path, seed: int, out_dir: Path) -> GroundTruth:
    """Write platform-shaped CSVs (column names from ChannelModel export maps), an orders CSV, a
    synthetic DatasetManifest and ground_truth.json."""
    raise NotImplementedError("P2")
