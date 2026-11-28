"""§7.5 the fallback chain. Piece P6.

Steps, in order, stopping at the first NUTS fit that passes G3:

1. ``nuts_full``: NUTS on the spec as given.
2. ``nuts_static``: NUTS without dynamics.
3. ``nuts_unpooled``: NUTS without pooling above the ad level (hierarchy reduced to ``["ad"]``).
4. ``conjugate``: the exact per-ad conjugate route (P3), stamped as a fallback.

A step whose spec equals the previous step's is not refit. Entering any later step emits one
``DegradationNotice`` naming the step and the G3 reasons that sent the chain there; the step-4
notice carries the registry phrase "joint model failed checks". A step whose compile or fit raises
counts as failed: its notice records the exception type and message, and no state is quarantined
because none exists. Every G3-failed NUTS state is quarantined and saved to the funnel-state
store for audit. The step-4 state carries
``route.fallback_conjugate = 1`` in its parameters so downstream code can cap it at ``marginal``
(§7.5; D11's from-the-start conjugate route is not stamped).

J8 (10) to (12), S40, S44: within a NUTS step, a try whose G3 fails on divergences alone is retried
up to ``RETRIES`` times at seeds from ``retry_seed``; try 1 keeps the run's seed, so a first-try
pass is what it was before J8. Every try is recorded as an attempt, and a retried step adds one
notice.

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
    PriorSet,
    inputs_hash,
    make_id,
    registries,
)
from bayesian_marketing.diagnostics.run import divergences_only, g3, run_diagnostics
from bayesian_marketing.funnel_state import store
from bayesian_marketing.inference import conjugate, sampler_numpyro
from bayesian_marketing.model_spec import compile as compile_mod

FALLBACK_FLAG = "route.fallback_conjugate"

RETRIES = 2
"""J8 (10), S40: a NUTS step whose G3 fails on divergences alone is tried at most 1 + RETRIES
times before the chain moves on."""

ATTEMPT_FIELDS = ("step", "try", "seed", "divergences", "passed")
"""J8 (11): one record per try, in ``RunSnapshot.fit_attempts``."""


def retry_seed(seed: int, step: str, n: int, taken: set[int]) -> int:
    """S40 (2): try 1 is ``seed``; try n (2 or 3) is
    ``int(inputs_hash({"seed": seed, "step": step, "try": n})[:8], 16)``, salted with a counter
    until it is not ``seed`` and not in ``taken`` (the seeds already used)."""
    if n == 1:
        return seed
    key: dict[str, object] = {"seed": seed, "step": step, "try": n}
    out = int(inputs_hash(key)[:8], 16)
    salt = 0
    while out == seed or out in taken:
        salt += 1
        out = int(inputs_hash({**key, "salt": salt})[:8], 16)
    return out


# Notice wording, held here until the integrator adds phrasing keys (manifest open question 1).
STEP_FAILED_G3 = "{step} failed G3 ({why})"
STEP_RAISED = "{step} raised {exc_type}: {message}"
JOINT_FAILED = "{phrase}: {cause}"  # phrase is phrasing/notices/joint_failed@v1
STEP_RETRIED = "{step} retried on divergences: {tries}; {outcome}"  # J8 (11), one per step


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


def _notice(step: str, cause: str, data: FunnelData) -> DegradationNotice:
    return DegradationNotice(
        notice_id=f"dn_{inputs_hash({'step': step, 'cause': cause})[:8]}",
        step=step,
        reason=cause,
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


def _attempt(step: str, n: int, seed: int, divergences: int | None, passed: bool) -> dict:
    return dict(zip(ATTEMPT_FIELDS, (step, n, seed, divergences, passed), strict=True))


def _retry_notice(step: str, tried: list[dict], data: FunnelData) -> DegradationNotice:
    tries = ", ".join(
        f"try {a['try']} seed {a['seed']} "
        + ("raised" if a["divergences"] is None else f"{a['divergences']} divergences")
        for a in tried
    )
    last = tried[-1]
    outcome = f"try {last['try']} accepted" if last["passed"] else "no try passed"
    return _notice(step, STEP_RETRIED.format(step=step, tries=tries, outcome=outcome), data)


def fit_with_fallback(
    spec: FunnelSpec, priors: PriorSet, data: FunnelData, seed: int
) -> tuple[FunnelState, list[DiagnosticsReport], list[DegradationNotice], list[dict]]:
    """NUTS full; NUTS static; NUTS unpooled above ad; conjugate per ad (caps at marginal).

    J8 (10), S40, S44: a NUTS try whose G3 fails on divergences alone (``divergences_only``) is
    retried at a new seed (``retry_seed``), up to ``RETRIES`` times; any other failure, a raise
    included, moves the chain to the next step. Every try is an attempt (``ATTEMPT_FIELDS``),
    returned in order as the fourth value; every G3-failed try's state is quarantined and its
    report kept. A step that was retried adds one notice, after its tries.
    """
    reports: list[DiagnosticsReport] = []
    notices: list[DegradationNotice] = []
    attempts: list[dict] = []
    taken: set[int] = {seed}
    cause: str | None = None  # why the previous step failed, carried into the next notice
    for step, step_spec in _nuts_steps(spec):
        if cause is not None:
            notices.append(_notice(step, cause, data))
        tried: list[dict] = []
        accepted: FunnelState | None = None
        for n in range(1, RETRIES + 2):
            try_seed = retry_seed(seed, step, n, taken)
            taken.add(try_seed)
            try:
                if n == 1:
                    model = compile_mod.compile_model(step_spec, priors, data)
                state, raw = sampler_numpyro.NumpyroSampler().fit(
                    model, data, _fit_config(try_seed)
                )
            except Exception as exc:  # integrator ruling, S44 (2): a raising try is a failed try
                cause = STEP_RAISED.format(step=step, exc_type=type(exc).__name__, message=exc)
                tried.append(_attempt(step, n, try_seed, None, False))
                break
            report, gate = g3(raw)
            reports.append(report)
            tried.append(_attempt(step, n, try_seed, report.n_divergences, bool(gate.passed)))
            if gate.passed:
                accepted = state.model_copy(update={"diagnostics_id": report.report_id})
                break
            _quarantine(state)
            cause = STEP_FAILED_G3.format(step=step, why="; ".join(gate.reasons))
            if not divergences_only(report):  # S40 (1), S44 (3)
                break
        attempts += tried
        if len(tried) > 1:
            notices.append(_retry_notice(step, tried, data))
        if accepted is not None:
            return accepted, reports, notices, attempts

    if cause is None:  # unreachable: there is always at least one NUTS step
        raise RuntimeError("fallback chain ran no NUTS step")
    notices.append(
        _notice("conjugate", JOINT_FAILED.format(phrase=_joint_failed(), cause=cause), data)
    )
    state, report = _conjugate_step(priors, data, seed)
    reports.append(report)
    return state, reports, notices, attempts
