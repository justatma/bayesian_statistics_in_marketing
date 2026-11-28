"""J9.1, J9.2, S49 (1), (2): whether a measure applies to an ad on a run.

A lead is counted and never valued (D33), so a valued name (``pipeline.VALUED``) on a lead run
applies only when the run holds a quantity of that name for the ad. Every other name, and every
name on a purchase run, applies. The rule reads the snapshot's quantities alone, never its
``not_estimable`` lines, so a lead run saved before D46 gives the same answer.

This module imports neither ``claims.slots`` nor ``atmaos.socket``: both call it.
"""

from __future__ import annotations

from typing import Any


def applies(snap: Any, kind: str | None, ad: str | None, name: str) -> bool:
    """False exactly when ``kind`` is "lead", ``name`` is in ``pipeline.VALUED`` and ``snap``
    holds no quantity of ``name`` whose scope names ``ad``."""
    from bayesian_marketing import pipeline

    if kind != "lead" or name not in pipeline.VALUED:
        return True
    return any(q.name == name and q.scope.ids.get("ad") == ad for q in snap.quantities)
