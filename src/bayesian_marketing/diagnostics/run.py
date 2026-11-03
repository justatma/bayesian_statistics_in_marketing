"""§7.4 run_diagnostics and the G3 gate."""

from __future__ import annotations

from bayesian_marketing.core import DiagnosticsReport, FunnelData, FunnelState, GateResult


def run_diagnostics(state: FunnelState, data: FunnelData) -> DiagnosticsReport:
    """R-hat, ESS bulk and tail, divergences, per-stage PPC p-values. Does not set ``passed``."""
    raise NotImplementedError("P6")


def g3(report: DiagnosticsReport) -> tuple[DiagnosticsReport, GateResult]:
    """The only setter of ``passed``. A fail quarantines the state and triggers fallback."""
    raise NotImplementedError("P6")
