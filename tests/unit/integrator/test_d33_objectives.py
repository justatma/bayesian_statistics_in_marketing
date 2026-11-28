"""D33: leads and subscription objectives are representable but refused by compare."""

from __future__ import annotations

import pytest
from tests.fakes import builders as B

from bayesian_marketing import core as C
from bayesian_marketing.decision.compare import compare


@pytest.mark.parametrize("target", ["leads", "subscription_contribution"])
def test_planned_objectives_refused(target: str) -> None:
    obj = C.Objective(target=target, horizon=C.Horizon(unit="clicks", amount=1000))
    q = B.quantity("cvr", estimate=B.beta_spec(10, 990))
    with pytest.raises(C.NotInScope):
        compare([q, q], obj, B.economics())
