"""§8.7 guarantee_report."""

from __future__ import annotations

from datetime import date

from bayesian_marketing.core import AuditReport


def guarantee_report(since: date) -> AuditReport:
    raise NotImplementedError("P9")
