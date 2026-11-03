"""§7.5 the fallback chain. Piece P6.

Steps, in order, stopping at the first NUTS fit that passes G3:

1. ``nuts_full``: NUTS on the spec as given.
2. ``nuts_static``: NUTS without dynamics.
3. ``nuts_unpooled``: NUTS without pooling above the ad level (hierarchy reduced to ``["ad"]``).
4. ``conjugate``: the exact per-ad conjugate route (P3), stamped as a fallback.

A step whose spec equals the previous step's is not refit. Entering any later step emits one
``DegradationNotice`` naming the step and the G3 reasons that sent the chain there; the step-4
notice carries the registry phrase "joint model failed checks". Every G3-failed NUTS state is
quarantined and saved to the funnel-state store for audit. The step-4 state carries
``route.fallback_conjugate = 1`` in its parameters so downstream code can cap it at ``marginal``
(§7.5; D11's from-the-start conjugate route is not stamped).

``compile_model`` and ``NumpyroSampler`` are looked up through their modules at call time.
"""

from __future__ import annotations

from bayesian_marketing.core import (
    DegradationNotice,
    DiagnosticsReport,
    FitConfig,
    FunnelData,
    FunnelSpec,
    FunnelState,
    GateResult,
    PriorSet,
    inputs_hash,
    make_id,
    registries,
)
from bayesian_marketing.diagnostics.run import g3, run_diagnostics
from bayesian_marketing.funnel_state import store
from bayesian_marketing.inference import conjugate, sampler_numpyro
from bayesian_marketing.model_spec import compile as compile_mod

FALLBACK_FLAG = "route.fallback_conjugate"


def _fit_config(seed: int) -> FitConfig:
    cfg = registries.resolve("diagnostics/sampler@v1")
    return FitConfig(
        chains=int(cfg["chains"]),
        draws=int(cfg["draws"]),
        warmup=int(cfg["warmup"]),
        target_accept=float(cfg["target_accept"]),
        seed=seed,
    )


def _joint_failed() -> str:
    return str(registries.resolve("phrasing/notices/joint_failed@v1"))


def _nuts_steps(spec: FunnelSpec) -> list[tuple[str, FunnelSpec]]:
    static = spec.model_copy(update={"dynamics": "static"})
    unpooled = static.model_copy(update={"hierarchy": ["ad"]})
    steps = [("nuts_full", spec), ("nuts_static", static), ("nuts_unpooled", unpooled)]
    out: list[tuple[str, FunnelSpec]] = []
    for name, s in steps:
        if out and out[-1][1] == s:
            continue  # nothing left to drop at this step
        out.append((name, s))
    return out


def _notice(
    step: str, reason: str, previous: str, gate: GateResult, data: FunnelData
) -> DegradationNotice:
    why = "; ".join(gate.reasons) or "G3 failed"
    text = f"{reason}: {previous} failed G3 ({why})" if reason else f"{previous} failed G3 ({why})"
    return DegradationNotice(
        notice_id=f"dn_{inputs_hash({'step': step, 'gate': gate.inputs_hash})[:8]}",
        step=step,
        reason=text,
        affected=list(data.entities),
    )


def _quarantine(state: FunnelState) -> None:
    store.save(state.model_copy(update={"quarantined": True}))


def _conjugate_step(
    priors: PriorSet, data: FunnelData, seed: int
) -> tuple[FunnelState, DiagnosticsReport]:
    base = conjugate.fit_conjugate(data, priors, seed)
    report = run_diagnostics(base, data)  # PPC on the exact route; passed stays unset (G3 is NUTS)
    params = dict(base.posterior.params or {})
    params[FALLBACK_FLAG] = 1.0
    posterior = base.posterior.model_copy(update={"params": params})
    state = base.model_copy(
        update={
            "state_id": make_id("fs_", {"base": base.state_id, "fallback": "conjugate"}),
            "posterior": posterior,
            "diagnostics_id": report.report_id,
        }
    )
    return state, report


def fit_with_fallback(
    spec: FunnelSpec, priors: PriorSet, data: FunnelData, seed: int
) -> tuple[FunnelState, list[DiagnosticsReport], list[DegradationNotice]]:
    """NUTS full; NUTS static; NUTS unpooled above ad; conjugate per ad (caps at marginal)."""
    config = _fit_config(seed)
    reports: list[DiagnosticsReport] = []
    notices: list[DegradationNotice] = []
    previous: tuple[str, GateResult] | None = None
    for step, step_spec in _nuts_steps(spec):
        if previous is not None:
            notices.append(_notice(step, "", previous[0], previous[1], data))
        model = compile_mod.compile_model(step_spec, priors, data)
        state, raw = sampler_numpyro.NumpyroSampler().fit(model, data, config)
        report, gate = g3(raw)
        reports.append(report)
        if gate.passed:
            return state.model_copy(update={"diagnostics_id": report.report_id}), reports, notices
        _quarantine(state)
        previous = (step, gate)

    if previous is None:  # unreachable: there is always at least one NUTS step
        raise RuntimeError("fallback chain ran no NUTS step")
    notices.append(_notice("conjugate", _joint_failed(), previous[0], previous[1], data))
    state, report = _conjugate_step(priors, data, seed)
    reports.append(report)
    return state, reports, notices
