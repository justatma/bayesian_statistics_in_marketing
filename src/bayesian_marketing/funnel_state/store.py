"""§5.4 save and load. States are immutable.

A state is one JSON file ``<BAYES_DATA_DIR>/funnel_states/<state_id>.json``. Saving the same state
again is a no-op. A refit of the same inputs has the same state_id and differs only in
``created_at``; that counts as the same state and the first stored copy is kept. Saving a
different state under an existing id raises ``StateExistsError``.
A quarantined state still loads (for audit); ``derived_metrics`` refuses it.
"""

from __future__ import annotations

import os
from pathlib import Path

from bayesian_marketing.core import FunnelState

DEFAULT_DATA_DIR = "data/generated"


class StateExistsError(FileExistsError):
    """A different state is already stored under this state_id."""


def data_dir() -> Path:
    """Root of every persistent store (``BAYES_DATA_DIR``, default ``data/generated/``)."""
    return Path(os.environ.get("BAYES_DATA_DIR", DEFAULT_DATA_DIR))


def states_dir() -> Path:
    return data_dir() / "funnel_states"


def _path(state_id: str) -> Path:
    if not state_id or "/" in state_id or "\\" in state_id or state_id.startswith("."):
        raise ValueError(f"bad state_id {state_id!r}")
    return states_dir() / f"{state_id}.json"


def _same(a: FunnelState, b: FunnelState) -> bool:
    return a.model_dump(exclude={"created_at"}) == b.model_dump(exclude={"created_at"})


def _refuse(state_id: str) -> StateExistsError:
    return StateExistsError(f"state {state_id} exists and states are immutable")


def save(state: FunnelState) -> None:
    path = _path(state.state_id)
    if path.exists():
        if _same(load(state.state_id), state):
            return
        raise _refuse(state.state_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".json.{os.getpid()}.tmp")
    tmp.write_text(state.model_dump_json())
    try:
        os.link(tmp, path)  # fails if another writer got there first
    except FileExistsError:
        if not _same(load(state.state_id), state):
            raise _refuse(state.state_id) from None
    finally:
        tmp.unlink(missing_ok=True)


def load(state_id: str) -> FunnelState:
    path = _path(state_id)
    if not path.exists():
        raise KeyError(f"no funnel state {state_id!r} under {states_dir()}")
    return FunnelState.model_validate_json(path.read_text())
