"""Fakes of neighbouring pieces, built from their interfaces (spec v0.3 §15)."""

from __future__ import annotations

from typing import Any

from bayesian_marketing import core as C
from tests.fakes import builders as B


class FakeSampler:
    """A PosteriorSampler (§7.3) that returns a fixed state and a scripted diagnostics report.

    ``reports`` is consumed one per call; the last one repeats. Calls are recorded.
    """

    def __init__(self, reports: list[C.DiagnosticsReport], state: C.FunnelState | None = None):
        self.reports = list(reports)
        self.state = state or B.funnel_state(route="nuts")
        self.calls: list[tuple[Any, Any, Any]] = []

    def fit(self, model, data, config):
        self.calls.append((model, data, config))
        i = min(len(self.calls) - 1, len(self.reports) - 1)
        rep = self.reports[i].model_copy(update={"report_id": f"dg_{len(self.calls):08d}"})
        st = self.state.model_copy(
            update={"diagnostics_id": rep.report_id, "state_id": f"fs_{len(self.calls):08d}"}
        )
        return st, rep


class FakeCompiler:
    """Stands in for ``model_spec.compile.compile_model``; records each spec it is given."""

    def __init__(self) -> None:
        self.specs: list[C.FunnelSpec] = []

    def __call__(self, spec, priors, data):
        self.specs.append(spec)
        return C.CompiledModel(
            spec_version=f"{spec.version}#{len(self.specs)}",
            model_fn_ref="tests.fakes:model",
            data_shape={"ads": len(data.entities), "days": len(data.dates)},
        )


def failing_report() -> C.DiagnosticsReport:
    return B.diagnostics_report(rhat=1.5, ess_bulk=20.0, ess_tail=15.0, divergences=12)


def passing_report() -> C.DiagnosticsReport:
    return B.diagnostics_report()
