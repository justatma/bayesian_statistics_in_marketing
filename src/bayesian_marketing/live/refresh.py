"""Engine refresh after a good poll (spec v0.2 §5 L4). Piece L4."""

from __future__ import annotations

from pathlib import Path

from bayesian_marketing.core.records import ClientConfig
from bayesian_marketing.live.contracts import Clock, PollRecord, RefreshRecord, Store

ONE_AD = "one ad, nothing to compare"
NO_ECONOMICS_PATH = "no economics file in the client config"


def refresh(
    config: ClientConfig,
    poll_rec: PollRecord,
    store: Store,
    clock: Clock,
    *,
    data_dir: Path,
    config_root: Path,
) -> RefreshRecord:
    """Runs ``ctr`` through ``pipeline.execute`` with the poll's rows; stores and returns the
    record. Never raises (C2)."""
    raise NotImplementedError("L4")
