"""§6.2 publish and status_of. Single writer.

The store is an append-only JSON-lines file under ``BAYES_DATA_DIR``. A published status is
immutable (I5): the same quantity id can be republished only with the same status, basis and
bound. New data is a new quantity id, whose feasibility may name the old one in ``supersedes``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from bayesian_marketing.core import (
    Feasibility,
    GateFailure,
    GateResult,
    Quantity,
    inputs_hash,
    registries,
    utcnow,
)

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "generated"
STORE_NAME = "status_registry.jsonl"


class StatusImmutableError(ValueError):
    """A published status cannot be replaced without new data (I5)."""


def _store() -> Path:
    root = Path(os.environ.get("BAYES_DATA_DIR", DEFAULT_DATA_DIR))
    return root / STORE_NAME


def _published() -> dict[str, Feasibility]:
    path = _store()
    out: dict[str, Feasibility] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            out.setdefault(row["quantity_id"], Feasibility.model_validate(row["feasibility"]))
    return out


def _g2_reasons(f: Feasibility, published: dict[str, Feasibility]) -> list[str]:
    reasons: list[str] = []
    try:
        registries.resolve(f.bound_ref)
    except registries.RegistryError as e:
        reasons.append(f"bound_ref does not resolve: {e}")
    if f.status != "estimable" and not f.reasons:
        reasons.append("non-estimable status without reasons")
    if f.supersedes is not None and f.supersedes not in published:
        reasons.append(f"supersedes {f.supersedes!r}, which was never published")
    return reasons


def publish(q: Quantity) -> None:
    """G2: the bound resolves and reasons are recorded; then append. Raises on failure."""
    f = q.feasibility
    published = _published()
    reasons = _g2_reasons(f, published)
    if reasons:
        raise GateFailure(
            GateResult(
                gate="G2",
                passed=False,
                blocking=True,
                reasons=reasons,
                inputs_hash=inputs_hash(q),
                checked_at=utcnow(),
            )
        )
    prior = published.get(q.quantity_id)
    if prior is not None:
        same = (prior.status, prior.basis, prior.bound_ref) == (f.status, f.basis, f.bound_ref)
        if same:
            return
        raise StatusImmutableError(
            f"{q.quantity_id} is published as {prior.status}; a status changes only with new "
            "data, published under a new quantity id with supersedes"
        )
    path = _store()
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"quantity_id": q.quantity_id, "feasibility": f.model_dump(mode="json")}
    with path.open("a") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def status_of(quantity_id: str) -> Feasibility:
    """The published Feasibility. Raises KeyError for an id never published."""
    published = _published()
    if quantity_id not in published:
        raise KeyError(f"no published status for {quantity_id!r}")
    return published[quantity_id]
