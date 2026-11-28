"""§4.6 Quantity, with the G10 evidence validator (§13.1, owner S0)."""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from bayesian_marketing.core.base import Frozen
from bayesian_marketing.core.money import DistributionSpec
from bayesian_marketing.core.scope import Feasibility, Provenance, Scope

QuantityName = Literal[
    "ctr",
    "cvr",
    "cpa",
    "roas",
    "aov",
    "cpm",
    "cpc",
    "contribution_per_click",
    "contribution",
    "p_exceeds",
    "lift",
]
EvidenceClass = Literal[
    "delivery",
    "platform_attributed",
    "commercially_realized",
    "causally_incremental",
    "deterministic",
]
Design = Literal["observational", "randomized", "holdout", "none"]

EVIDENCE_ORDER: tuple[str, ...] = (
    "deterministic",
    "commercially_realized",
    "causally_incremental",
    "platform_attributed",
    "delivery",
)
"""§5.2 C8 order, strongest first. A cross-platform total takes the lowest (last) of its inputs."""

DELIVERY_ONLY: frozenset[str] = frozenset({"ctr", "cpm", "cpc"})
"""Quantities that need no conversion data and may carry evidence class ``delivery``."""

AD_PLATFORMS: frozenset[str] = frozenset({"meta", "google_ads", "linkedin"})


def pull_platform(pull_id: str) -> str | None:
    """Platform encoded in a pull id ``pull_<platform>_<sha8>`` (D18). None if not encoded."""
    if not pull_id.startswith("pull_"):
        return None
    body = pull_id[len("pull_") :]
    for p in ("google_ads", "meta", "linkedin", "ga4", "orders"):
        if body.startswith(p + "_"):
            return p
    return None


def lowest_evidence(classes: list[str]) -> str:
    """The weakest evidence class among inputs (§5.2 C8)."""
    return max(classes, key=EVIDENCE_ORDER.index)


class Quantity(Frozen):
    quantity_id: str
    name: QuantityName
    scope: Scope
    estimate: DistributionSpec
    feasibility: Feasibility
    provenance: Provenance
    evidence_class: EvidenceClass
    design: Design
    diagnostics_ref: str | None  # None only for conjugate and deterministic routes
    notices: list[str]
    n_events: float | None = None  # D22: events behind the estimate (D10 available/required)

    @model_validator(mode="after")
    def _g10(self) -> Quantity:
        reasons = g10_reasons(self)
        if reasons:
            raise ValueError("G10: " + "; ".join(reasons))
        return self


def g10_reasons(q: Quantity) -> list[str]:
    """Every G10 rule the quantity breaks (§4.6). Empty means it passes."""
    reasons: list[str] = []
    pulls = q.provenance.data_pull_ids
    platforms = {pull_platform(p) for p in pulls}
    has_orders = "orders" in platforms

    if q.evidence_class == "causally_incremental" and q.design != "holdout":
        reasons.append("causally_incremental requires design='holdout'")
    if q.evidence_class == "commercially_realized" and not has_orders:
        reasons.append("commercially_realized requires an orders pull among data_pull_ids")
    if (q.evidence_class == "deterministic") != (q.provenance.route == "deterministic"):
        reasons.append("evidence_class 'deterministic' and route 'deterministic' go together")
    if q.evidence_class == "delivery" and q.name not in DELIVERY_ONLY:
        reasons.append(f"{q.name} uses conversions and cannot be evidence class 'delivery'")
    uses_platform_conversions = (
        q.name not in DELIVERY_ONLY and not has_orders and platforms & AD_PLATFORMS
    )
    if uses_platform_conversions and q.evidence_class not in (
        "platform_attributed",
        "deterministic",
        "causally_incremental",
    ):
        reasons.append("a quantity computed from platform conversions is platform_attributed")
    if q.provenance.route == "nuts" and q.diagnostics_ref is None:
        reasons.append("a sampled quantity needs diagnostics_ref")
    return reasons
