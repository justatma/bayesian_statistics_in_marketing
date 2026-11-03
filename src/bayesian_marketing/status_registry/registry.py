"""§6.2 publish and status_of. Single writer."""

from __future__ import annotations

from bayesian_marketing.core import Feasibility, Quantity


def publish(q: Quantity) -> None:
    raise NotImplementedError("P4")


def status_of(quantity_id: str) -> Feasibility:
    raise NotImplementedError("P4")
