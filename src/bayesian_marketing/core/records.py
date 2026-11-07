"""§4.11 run record objects, §4.12 DatasetManifest, §4.13 ReportBundle with G10, §9.1
GroundTruth, §10 NarrativeBlock, §13.2 pipeline request and result.

Types the spec names but does not define (ManifestFile, ClientConfig, KnowabilitySection,
RenderedReport, AuditReport, CompareRequest, RunResult) are defined here (D18).
"""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from bayesian_marketing.core.base import Frozen, Platform
from bayesian_marketing.core.decisions import ClientEconomics, Comparison, Horizon, Recommendation
from bayesian_marketing.core.quantity import Quantity
from bayesian_marketing.core.scope import DiagnosticsReport, GateResult


class RunRecord(Frozen):
    run_id: str
    started_at: datetime
    engine_version: str
    registry_versions: dict[str, str]
    config_hash: str
    manifest_id: str
    dataset_hashes: list[str]
    gate_results: list[GateResult]
    quantity_ids: list[str]
    recommendation_ids: list[str]
    route_log: list[str]
    seeds: dict[str, int]


class ApprovalRecord(Frozen):  # written only by atmaos.record_approval
    recommendation_id: str
    approval_ref: str
    decision: Literal["approved", "rejected"]
    decided_by: str
    decided_at: datetime


class OutcomeRecord(Frozen):  # written by atmaos.record_outcome or by shadow replay
    recommendation_id: str
    source: Literal["atmaos", "ground_truth"]
    realized: dict[str, Any]
    recorded_at: datetime


class ManifestFile(Frozen):
    path: str  # relative to the manifest's directory
    platform: Platform
    sha256: str
    export_kind: Literal["export", "pull"]


class DatasetManifest(Frozen):
    manifest_id: str  # "ds_<sha8>"
    client_id: str
    economics_id: str
    files: list[ManifestFile]
    attribution_window: dict[Platform, str]
    entity_map: dict[str, dict[str, str]]  # variant name -> platform entity ids
    utm_map: dict[str, dict[str, str]] | None = None
    envelope: dict[str, Any] = Field(
        default_factory=dict
    )  # inventory §VIII fields from AtmaOS, recorded verbatim
    synthetic: bool
    public: bool = False  # §9.3 public datasets
    currency: str | None = None  # D22: for exports that carry none (GA4)

    @classmethod
    def load(cls, uri_or_path: str | Path) -> DatasetManifest:
        """Resolve a ``file://`` URI or a path to a manifest (§4.12)."""
        s = str(uri_or_path)
        path = Path(s.removeprefix("file://"))
        return cls.model_validate_json(path.read_text())


class ClientConfig(Frozen):
    """Per-client YAML in ``configs/`` (no secrets). Connectors read credentials from env."""

    client_id: str
    timezone: str
    currency: str
    accounts: dict[Platform, str]  # platform -> account id
    economics_path: str | None = None
    # Live view §3.2 (D41, D43). conversion_event: platform -> action_type the connector counts.
    # conversion_event_confirmed: False or absent means provisional. priors: path -> prior id (L4).
    conversion_event: dict[Platform, str] = Field(default_factory=dict)
    conversion_event_confirmed: dict[Platform, bool] = Field(default_factory=dict)
    priors: dict[str, str] = Field(default_factory=dict)


class NarrativeBlock(Frozen):
    block_id: str
    text: str
    author: str
    gate: GateResult | None = None


class KnowabilitySection(Frozen):
    observed: list[str]
    platform_modeled: list[str]
    attribution_windows: dict[str, str]
    not_knowable: list[str]  # quantity ids rendered as "not knowable yet"


class ReportBundle(Frozen):
    kind: Literal["client", "demo", "internal"]
    client_id: str
    run_id: str
    quantities: list[Quantity]
    recommendations: list[Recommendation]
    comparisons: list[Comparison] = Field(default_factory=list)
    gate_results: list[GateResult]
    diagnostics: list[DiagnosticsReport]
    knowability: KnowabilitySection
    narrative_blocks: list[NarrativeBlock]

    @model_validator(mode="after")
    def _g10_no_synthetic_in_client(self) -> ReportBundle:
        if self.kind == "client" and any(q.provenance.synthetic for q in self.quantities):
            raise ValueError("G10: a client bundle cannot contain synthetic quantities (I13)")
        return self


class RenderedReport(Frozen):
    html_path: str
    pdf_path: str | None
    inputs_hash: str
    watermark: str | None


class AuditReport(Frozen):
    since: date
    n_recommendations: int
    by_source: dict[str, dict[str, float]]  # "atmaos" | "ground_truth" -> metric -> value
    coverage_90: dict[str, float]
    regret: dict[str, float]
    not_knowable_correct_share: float | None


class CompareRequest(Frozen):
    metric: Literal["ctr", "cvr", "cpa", "roas", "contribution_per_click", "contribution"]
    variants: list[str]
    priors: dict[str, str]  # parameter path -> approved prior_id
    window: tuple[date, date]
    horizon: Horizon
    segments: dict[str, Any] = Field(default_factory=dict)


class RunResult(Frozen):
    run: RunRecord
    quantities: list[Quantity]
    comparison: Comparison | None
    recommendations: list[Recommendation]
    diagnostics: list[DiagnosticsReport]


class GroundTruth(Frozen):
    scenario: str
    seed: int
    params: dict[str, Any]
    true_quantities: dict[str, float]  # keyed "<variant>.<quantity>"
    true_best: dict[str, str]  # objective -> variant


def load_economics(economics_id: str, manifest_dir: Path | None = None) -> ClientEconomics:
    """Resolve an economics id (D22): ``<manifest_dir>/economics/<id>.json`` first, then
    ``<BAYES_CONFIG_DIR or configs>/economics/<id>.json``."""
    candidates = []
    if manifest_dir is not None:
        candidates.append(Path(manifest_dir) / "economics" / f"{economics_id}.json")
    root = Path(os.environ.get("BAYES_CONFIG_DIR", Path(__file__).resolve().parents[3] / "configs"))
    candidates.append(root / "economics" / f"{economics_id}.json")
    for c in candidates:
        if c.exists():
            return ClientEconomics.model_validate_json(c.read_text())
    raise FileNotFoundError(
        f"economics {economics_id!r} not found in {[str(c) for c in candidates]}"
    )
