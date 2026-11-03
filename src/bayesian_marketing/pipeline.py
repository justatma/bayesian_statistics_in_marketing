"""§13.2 the pipeline. Piece P11."""

from __future__ import annotations

from datetime import date

from bayesian_marketing.core import (
    CompareRequest,
    DatasetManifest,
    FunnelData,
    LagModel,
    PlatformPull,
    RunResult,
)


def run(manifest: DatasetManifest, request: CompareRequest) -> RunResult:
    """read (G1) -> lag -> route -> fit -> save -> derive (G10) -> feasibility -> publish (G2)
    -> compare (G9) -> decision feasibility -> recommend -> run_record.append."""
    raise NotImplementedError("P11")


def assemble_funnel_data(pulls: list[PlatformPull], lag: LagModel, as_of: date) -> FunnelData:
    """One platform's pulls (and its orders pull, if any) into FunnelData (D22)."""
    raise NotImplementedError("P11")
