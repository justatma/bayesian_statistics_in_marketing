"""§5.4 save and load. States are immutable.

A state is one JSON file ``<BAYES_DATA_DIR>/funnel_states/<state_id>.json``. Saving the same state
again is a no-op; saving a different state under an existing id raises ``StateExistsError``.
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


def save(state: FunnelState) -> None:
    path = _path(state.state_id)
    if path.exists():
        if load(state.state_id) == state:
            return
        raise StateExistsError(f"state {state.state_id} exists and states are immutable")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(state.model_dump_json())
    try:
        os.link(tmp, path)  # fails if another writer got there first
    except FileExistsError:
        tmp.unlink(missing_ok=True)
        if load(state.state_id) != state:
            raise StateExistsError(
                f"state {state.state_id} exists and states are immutable"
            ) from None
        return
    tmp.unlink(missing_ok=True)


def load(state_id: str) -> FunnelState:
    path = _path(state_id)
    if not path.exists():
        raise KeyError(f"no funnel state {state_id!r} under {states_dir()}")
    return FunnelState.model_validate_json(path.read_text())
