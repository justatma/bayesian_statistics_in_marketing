"""§10 check_narrative and intake_prior_proposal."""

from __future__ import annotations

from bayesian_marketing.core import GateResult, NarrativeBlock, ReportBundle


def check_narrative(block: NarrativeBlock, bundle: ReportBundle) -> GateResult:
    """G5 (§10 C1)."""
    raise NotImplementedError("P10")


def intake_prior_proposal(proposal: dict) -> str:
    """Validate an AtmaOS prior proposal and hand it to prior_registry.propose."""
    raise NotImplementedError("P10")
