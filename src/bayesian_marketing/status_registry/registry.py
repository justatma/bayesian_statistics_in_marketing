"""§6.2 publish and status_of. Single writer.

The store is an append-only JSON-lines file under ``BAYES_DATA_DIR``. A published status is
immutable (I5): the same quantity id can be republished only with the same status, basis and
bound. New data is a new quantity id, whose feasibility may name the old one in ``supersedes``;
it may claim a better status only if its data pulls strictly extend the old one's.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
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
from bayesian_marketing.core.scope import STATUS_ORDER
from bayesian_marketing.floors.estimability import quantity_feasibility, registry_target

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "generated"
STORE_NAME = "status_registry.jsonl"


class StatusImmutableError(ValueError):
    """A published status cannot be replaced without new data (I5)."""


@dataclass(frozen=True)
class _Entry:
    feasibility: Feasibility
    data_pull_ids: frozenset[str]


def _store() -> Path:
    root = Path(os.environ.get("BAYES_DATA_DIR", DEFAULT_DATA_DIR))
    return root / STORE_NAME


def _published() -> dict[str, _Entry]:
    path = _store()
    out: dict[str, _Entry] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            out.setdefault(
                row["quantity_id"],
                _Entry(
                    Feasibility.model_validate(row["feasibility"]),
                    frozenset(row["data_pull_ids"]),
                ),
            )
    return out


def _g2_reasons(q: Quantity, published: dict[str, _Entry]) -> list[str]:
    f = q.feasibility
    reasons: list[str] = []
    try:
        registries.resolve(f.bound_ref)
    except registries.RegistryError as e:
        reasons.append(f"bound_ref does not resolve: {e}")
        return reasons
    if f.status != "estimable" and not f.reasons:
        reasons.append("non-estimable status without reasons")

    if f.basis == "decision_loss":
        reasons.append("a quantity's feasibility cannot have basis 'decision_loss' (D9)")
    elif f.basis == "quantity_precision":
        recomputed = quantity_feasibility(q, registry_target())
        if recomputed.status != f.status or recomputed.bound_ref != f.bound_ref:
            reasons.append(
                f"claimed status {f.status} ({f.bound_ref}) disagrees with the floor's "
                f"{recomputed.status} ({recomputed.bound_ref})"
            )
    # basis 'inherited' (signed quantities, D10) has no rate floor of its own to recompute.

    if f.supersedes is not None:
        old = published.get(f.supersedes)
        if old is None:
            reasons.append(f"supersedes {f.supersedes!r}, which was never published")
        elif STATUS_ORDER[f.status] > STATUS_ORDER[old.feasibility.status]:
            pulls = frozenset(q.provenance.data_pull_ids)
            if not pulls > old.data_pull_ids:
                reasons.append(
                    f"status improves on {f.supersedes!r} ({old.feasibility.status} -> "
                    f"{f.status}) without new data: data_pull_ids are not a strict superset (I5)"
                )
    return reasons


def publish(q: Quantity) -> None:
    """G2: bound resolves, reasons recorded, status matches the floor, no improvement without
    new data; then append. Raises GateFailure("G2") or StatusImmutableError."""
    f = q.feasibility
    published = _published()
    reasons = _g2_reasons(q, published)
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
        p = prior.feasibility
        if (p.status, p.basis, p.bound_ref) == (f.status, f.basis, f.bound_ref):
            return
        raise StatusImmutableError(
            f"{q.quantity_id} is published as {p.status}; a status changes only with new "
            "data, published under a new quantity id with supersedes"
        )
    path = _store()
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "quantity_id": q.quantity_id,
        "feasibility": f.model_dump(mode="json"),
        "data_pull_ids": sorted(q.provenance.data_pull_ids),
    }
    with path.open("a") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def status_of(quantity_id: str) -> Feasibility:
    """The published Feasibility. Raises KeyError for an id never published."""
    published = _published()
    if quantity_id not in published:
        raise KeyError(f"no published status for {quantity_id!r}")
    return published[quantity_id].feasibility
