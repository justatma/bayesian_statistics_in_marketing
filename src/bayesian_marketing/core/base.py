"""Shared base model, ids, hashing and errors (spec v0.3 §3)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

Platform = Literal["meta", "google_ads", "linkedin", "ga4", "orders"]
"""§4.14. The five data sources."""

RegistryRef = str
"""A string like ``"bounds/estimability/posterior_width@v1"`` (§3)."""

ID_PREFIXES = ("q_", "rec_", "run_", "fs_", "pull_", "pr_", "econ_", "ds_")


class Frozen(BaseModel):
    """Base for every schema: immutable, no unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Mutable(BaseModel):
    """Base for the few working objects the spec does not freeze (e.g. FunnelData arrays)."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)


class NotInScope(NotImplementedError):
    """Raised by the D13 stubs: VI, crosstab_exact, long_run, detectability, path_barriers,
    the prophet allocation."""


class UncoupledFunnelError(ValueError):
    """§5.2 C1: a joint-route FunnelSpec without CTR/CVR coupling."""


class GateFailure(RuntimeError):
    """A blocking gate failed. Carries the GateResult."""

    def __init__(self, result: Any) -> None:
        super().__init__(f"{result.gate} failed: {'; '.join(result.reasons)}")
        self.result = result


def _default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime | date):
        return obj.isoformat()
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, set | frozenset | tuple):
        return list(obj)
    raise TypeError(f"not canonical-JSON serializable: {type(obj).__name__}")


def canonical_json(obj: Any) -> str:
    """Canonical JSON: sorted keys, compact separators (§3)."""
    if isinstance(obj, BaseModel):
        obj = obj.model_dump(mode="json")
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=_default)


def inputs_hash(obj: Any) -> str:
    """sha256 of canonical JSON (§3)."""
    return hashlib.sha256(canonical_json(obj).encode()).hexdigest()


def make_id(prefix: str, payload: Any) -> str:
    """A prefixed id from the first 8 hex chars of the payload hash, e.g. ``pr_1a2b3c4d``."""
    if prefix not in ID_PREFIXES:
        raise ValueError(f"unknown id prefix {prefix!r}; allowed {ID_PREFIXES}")
    return f"{prefix}{inputs_hash(payload)[:8]}"


def utcnow() -> datetime:
    """Timezone-aware UTC now. All timestamps are UTC (§3)."""
    return datetime.now(UTC)
