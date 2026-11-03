"""§7.3 the NUTS sampler. Piece P5."""

from __future__ import annotations

from typing import Protocol

from bayesian_marketing.core import (
    CompiledModel,
    DiagnosticsReport,
    FitConfig,
    FunnelData,
    FunnelState,
)


class PosteriorSampler(Protocol):
    def fit(
        self, model: CompiledModel, data: FunnelData, config: FitConfig
    ) -> tuple[FunnelState, DiagnosticsReport]: ...


class NumpyroSampler:
    """Non-centered NUTS, config from the registry, seeds recorded."""

    def fit(
        self, model: CompiledModel, data: FunnelData, config: FitConfig
    ) -> tuple[FunnelState, DiagnosticsReport]:
        raise NotImplementedError("P5")
