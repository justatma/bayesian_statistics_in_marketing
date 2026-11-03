"""§5.3 prior registry functions."""

from __future__ import annotations

from datetime import datetime

from bayesian_marketing.core import PriorRecord


def resolve(parameter_path: str, client_id: str, as_of: datetime) -> PriorRecord:
    """Client, then vertical, then default; every hop recorded (C2). Unapproved fails G8."""
    raise NotImplementedError("P7")


def propose(record: PriorRecord) -> str:
    """Store a pending prior. Returns ``pr_<sha8>``."""
    raise NotImplementedError("P7")


def approve(prior_id: str, approver: str) -> PriorRecord:
    """Approve after the prior predictive check (C6). Called by atmaos.approve_prior only."""
    raise NotImplementedError("P7")


def import_promoted(record: dict, promotion_id: str) -> str:
    """Vertical prior from AtmaOS, carrying its promotion id (C4)."""
    raise NotImplementedError("P7")


def prior_from_cohorts(rates: list[float], discount: float) -> tuple[float, float]:
    """Method of moments with n-1 variance and a disclosed discount (C5). Returns (a, b)."""
    raise NotImplementedError("P7")
