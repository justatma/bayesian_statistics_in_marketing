"""§11.1 socket functions. Plain dicts across the boundary."""

from __future__ import annotations

from typing import Any


def compare(
    dataset_uri: str,
    *,
    metric: str,
    variants: list[str],
    priors: dict[str, Any],
    window: dict[str, Any],
    segments: dict[str, Any],
) -> dict:
    """BayesianResult-shaped dict (§11.2)."""
    raise NotImplementedError("P11")


def observation_evidence(result: dict, tool_result_id: str) -> dict:
    """Exactly the G3.4 keys."""
    raise NotImplementedError("P11")


def recommendations(run_id: str) -> list[dict]:
    raise NotImplementedError("P11")


def record_approval(
    recommendation_id: str, approval_ref: str, decision: str, decided_by: str, decided_at: str
) -> None:
    """G6."""
    raise NotImplementedError("P11")


def record_outcome(recommendation_id: str, realized: dict) -> None:
    raise NotImplementedError("P11")


def approve_prior(prior_id: str, approver: str) -> dict:
    raise NotImplementedError("P11")


def check_narrative(block: dict, run_id: str) -> dict:
    """G5 result."""
    raise NotImplementedError("P11")


def render_report(run_id: str, kind: str, narrative_blocks: list[dict]) -> str:
    """Path to the rendered PDF or HTML."""
    raise NotImplementedError("P11")
