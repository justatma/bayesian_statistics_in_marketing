"""§5.2 compile_model."""

from __future__ import annotations

from bayesian_marketing.core import CompiledModel, FunnelData, FunnelSpec, PriorSet


def compile_model(spec: FunnelSpec, priors: PriorSet, data: FunnelData) -> CompiledModel:
    """Backend-agnostic compiled model (C5). Coupling required (C1, I9)."""
    raise NotImplementedError("P5")
