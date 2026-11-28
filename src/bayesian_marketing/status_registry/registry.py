"""§6.2 publish and status_of. Single writer.

The store is an append-only JSON-lines file under ``BAYES_DATA_DIR``. A published status is
immutable (I5): the same quantity id can be republished only with the same status, basis, bound
and supersedes. New data is a new quantity id, whose feasibility may name the old one in
``supersedes``. A new id may claim a better status than the latest one published for the same
quantity name and scope, or than the one it supersedes, only if its data pulls strictly extend
that one's.
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
    canonical_json,
    inputs_hash,
    registries,
    utcnow,
)
from bayesian_marketing.core.scope import STATUS_ORDER
from bayesian_marketing.floors.estimability import (
    SIGNED_QUANTITIES,
    quantity_feasibility,
    registry_target,
)

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "generated"
STORE_NAME = "status_registry.jsonl"


class StatusImmutableError(ValueError):
    """A published status cannot be replaced without new data (I5)."""


@dataclass(frozen=True)
class _Entry:
    quantity_id: str
    key: str
    feasibility: Feasibility
    data_pull_ids: frozenset[str]


@dataclass
class _Store:
    by_id: dict[str, _Entry]
    by_key: dict[str, list[_Entry]]  # publication order


def _store() -> Path:
    root = Path(os.environ.get("BAYES_DATA_DIR", DEFAULT_DATA_DIR))
    return root / STORE_NAME


def _key(q: Quantity) -> str:
    """What a status is about: the quantity name and its scope (I5 compares within a key)."""
    return canonical_json({"name": q.name, "scope": q.scope})


def _published() -> _Store:
    path = _store()
    out = _Store({}, {})
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            e = _Entry(
                row["quantity_id"],
                row["key"],
                Feasibility.model_validate(row["feasibility"]),
                frozenset(row["data_pull_ids"]),
            )
            if e.quantity_id not in out.by_id:
                out.by_id[e.quantity_id] = e
                out.by_key.setdefault(e.key, []).append(e)
    return out


def _improves_without_new_data(q: Quantity, old: _Entry) -> str | None:
    f = q.feasibility
    if STATUS_ORDER[f.status] <= STATUS_ORDER[old.feasibility.status]:
        return None
    if frozenset(q.provenance.data_pull_ids) > old.data_pull_ids:
        return None
    return (
        f"status improves on {old.quantity_id!r} ({old.feasibility.status} -> {f.status}) "
        "without new data: data_pull_ids are not a strict superset (I5)"
    )


def _g2_reasons(q: Quantity, store: _Store) -> list[str]:
    f = q.feasibility
    reasons: list[str] = []
    try:
        registries.resolve(f.bound_ref)
    except registries.RegistryError as e:
        reasons.append(f"bound_ref does not resolve: {e}")
        return reasons
    if f.status != "estimable" and not f.reasons:
        reasons.append("non-estimable status without reasons")

    if q.name in SIGNED_QUANTITIES:
        # D10: a signed quantity carries the worst status of its inputs; no floor of its own.
        if f.basis != "inherited":
            reasons.append(f"signed quantity {q.name} must carry basis 'inherited' (D10)")
    else:
        # Whatever basis is claimed, a rate's status is the floor's (D10).
        recomputed = quantity_feasibility(q, registry_target())
        if f.basis != "quantity_precision":
            reasons.append(f"{q.name} must carry basis 'quantity_precision', not {f.basis!r}")
        if recomputed.status != f.status or recomputed.bound_ref != f.bound_ref:
            reasons.append(
                f"claimed status {f.status} ({f.bound_ref}) disagrees with the floor's "
                f"{recomputed.status} ({recomputed.bound_ref})"
            )

    if f.supersedes is not None:
        old = store.by_id.get(f.supersedes)
        if old is None:
            reasons.append(f"supersedes {f.supersedes!r}, which was never published")
        elif (why := _improves_without_new_data(q, old)) is not None:
            reasons.append(why)

    # I5 holds with or without supersedes: compare with the latest other status for this key.
    others = [e for e in store.by_key.get(_key(q), []) if e.quantity_id != q.quantity_id]
    why = _improves_without_new_data(q, others[-1]) if others else None
    if why is not None and why not in reasons:
        reasons.append(why)
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
    prior = published.by_id.get(q.quantity_id)
    if prior is not None:
        p = prior.feasibility
        same = (p.status, p.basis, p.bound_ref, p.supersedes, prior.key, prior.data_pull_ids) == (
            f.status,
            f.basis,
            f.bound_ref,
            f.supersedes,
            _key(q),
            frozenset(q.provenance.data_pull_ids),
        )
        if same:
            return
        raise StatusImmutableError(
            f"{q.quantity_id} is published as {p.status} (supersedes {p.supersedes!r}); a "
            "published status is immutable, new data takes a new quantity id"
        )
    path = _store()
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "quantity_id": q.quantity_id,
        "key": _key(q),
        "feasibility": f.model_dump(mode="json"),
        "data_pull_ids": sorted(q.provenance.data_pull_ids),
    }
    with path.open("a") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def status_of(quantity_id: str) -> Feasibility:
    """The published Feasibility. Raises KeyError for an id never published."""
    published = _published()
    if quantity_id not in published.by_id:
        raise KeyError(f"no published status for {quantity_id!r}")
    return published.by_id[quantity_id].feasibility
