"""D26: a §7.5 step-4 (fallback conjugate) state is never better than marginal."""

from __future__ import annotations

from tests.fakes import builders as B

from bayesian_marketing.core import registries
from bayesian_marketing.derived_metrics.derive import derive
from bayesian_marketing import core as C
from bayesian_marketing.floors.estimability import quantity_feasibility, registry_target
from bayesian_marketing.inference.conjugate import fit_conjugate

phr = registries.load("phrasing")


def test_fallback_state_carries_joint_failed_and_caps_at_marginal() -> None:
    data = B.north_pier_day14()
    state = fit_conjugate(data, B.default_prior_set(), seed=7)
    params = dict(state.posterior.params or {})
    params["route.fallback_conjugate"] = 1.0
    post = state.posterior.model_copy(update={"params": params})
    state = state.model_copy(update={"posterior": post})
    ad = data.entities[0]
    scope = C.Scope(
        level="ad", ids={"ad": ad}, window=(data.dates[0], data.dates[-1]), platform=data.platform
    )
    q = derive("ctr", state, scope, None)
    assert any("joint model failed checks" in n for n in q.notices)
    f = quantity_feasibility(q, registry_target())
    assert f.status in ("marginal", "below_floor")
