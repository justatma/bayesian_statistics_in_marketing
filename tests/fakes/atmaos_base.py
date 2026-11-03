"""Local copy of AtmaOS's ``BayesianResult`` (facts pack F7). The engine must not import atmaos.

``Record`` is ``pydantic.BaseModel`` with ``frozen=True, extra="forbid", use_enum_values=False``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=False)


class BayesianResult(Record):
    posterior: dict[str, Any]
    probability_best: dict[str, float]
    expected_loss: dict[str, float]
    uncertainty: dict[str, Any] = Field(default_factory=dict)
    config_hash: str
    tool_version: str


G3_4_KEYS = frozenset(
    {
        "tool_version",
        "dataset_snapshot_hash",
        "window",
        "metric",
        "priors",
        "configuration",
        "segments",
        "result",
        "uncertainty",
        "tool_result_id",
    }
)
