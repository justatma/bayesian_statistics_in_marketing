"""§5.2 compile_model.

The CompiledModel names its plan by ``model_fn_ref = "model_spec.joint:<plan_id>"``. The plan is
kept in process and written as JSON to ``<BAYES_DATA_DIR>/models/<plan_id>.json`` so a sampler in
another process can load it (:func:`load_plan`).
"""

from __future__ import annotations

import json

from bayesian_marketing.core import (
    CompiledModel,
    FunnelData,
    FunnelSpec,
    PriorSet,
    UncoupledFunnelError,
    registries,
)
from bayesian_marketing.funnel_state.store import data_dir
from bayesian_marketing.inference.conjugate import _validate
from bayesian_marketing.model_spec.plan import ModelPlan, build_arrays, build_plan

REF_PREFIX = "model_spec.joint:"
_PLANS: dict[str, ModelPlan] = {}


def _plan_path(plan_id: str):
    return data_dir() / "models" / f"{plan_id}.json"


def compile_model(spec: FunnelSpec, priors: PriorSet, data: FunnelData) -> CompiledModel:
    """Backend-agnostic compiled model (C5). Coupling required (C1, I9)."""
    # A spec built with model_construct skips FunnelSpec's validator, so check again here.
    if spec.coupling != "lkj_bivariate":
        raise UncoupledFunnelError("a joint-route FunnelSpec needs lkj_bivariate coupling (I9)")
    if "value" not in {s.name for s in spec.stages}:
        raise ValueError("order value is always a modeled stage (I9)")
    if spec.dynamics == "random_walk":
        min_days = int(registries.resolve("bounds/dynamics/min_days_for_dynamics@v1"))
        if len(data.dates) < min_days:
            raise ValueError(
                f"random_walk dynamics need at least {min_days} days; the window has "
                f"{len(data.dates)} (C7)"
            )
    if not data.entities:
        raise ValueError("FunnelData has no entities")
    _validate(data)
    plan = build_plan(spec, priors, data)
    arrays = build_arrays(plan, data)  # raises on fractional counts in a binomial (C6)
    _PLANS[plan.plan_id] = plan
    path = _plan_path(plan.plan_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(plan.to_json(), sort_keys=True))
    tmp.replace(path)
    shape = {"n_ads": arrays.n_ads, "n_days": arrays.n_days}
    shape.update({f"n_{level}": n for level, n in arrays.n_groups.items()})
    return CompiledModel(
        spec_version=spec.version, model_fn_ref=f"{REF_PREFIX}{plan.plan_id}", data_shape=shape
    )


def load_plan(model: CompiledModel) -> ModelPlan:
    if not model.model_fn_ref.startswith(REF_PREFIX):
        raise ValueError(f"not a joint model reference: {model.model_fn_ref!r}")
    plan_id = model.model_fn_ref.removeprefix(REF_PREFIX)
    if plan_id in _PLANS:
        return _PLANS[plan_id]
    path = _plan_path(plan_id)
    if not path.exists():
        raise LookupError(f"no compiled plan {plan_id}; compile the model first")
    plan = ModelPlan.from_json(json.loads(path.read_text()))
    _PLANS[plan_id] = plan
    return plan
