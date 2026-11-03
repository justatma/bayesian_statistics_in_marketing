"""§8.4 allocation. Piece P9. The prophet rule is a stub (D13)."""

from __future__ import annotations

from bayesian_marketing.core import Comparison, NotInScope, Recommendation


def allocate(c: Comparison, run_id: str) -> Recommendation:
    """Split in proportion to p_best, floored at min_arm_share, capped per arm."""
    raise NotImplementedError("P9")


def prophet_allocation(*args: object, **kwargs: object) -> None:
    raise NotInScope("the one-sample prophet allocation is out of scope (D13)")
