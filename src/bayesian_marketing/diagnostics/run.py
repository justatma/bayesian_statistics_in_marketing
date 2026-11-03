"""§7.4 run_diagnostics and the G3 gate.

``run_diagnostics`` reads the state's joint draws (one parquet column per ``"<ad>.<parameter>"``,
the layout ``derive`` reads for either route) and computes, per stage, the posterior predictive
p-value of the stage total over all ads (a mid p-value, P(T_rep > T_obs) + ½ P(T_rep = T_obs)):

- delivery: impressions ~ Poisson(spend · 1000 / CPM) on paid days;
- ctr: clicks ~ Binomial(impressions, CTR);
- cvr: conversions ~ Binomial(lag-adjusted trials, CVR), trials as in the conjugate route;
- value: revenue, the sum of the orders file under the log-normal posterior, else the compound
  gamma total Gamma(k · orders, scale = AOV / k).

A stage with no draws or no data is left out. When the parquet carries a ``chain`` column the
draws are split by chain and R-hat (rank) and bulk and tail ESS come from ArviZ 1.x, worst over
columns; without chains (independent conjugate draws) they are None. Divergences come from the
state parameter ``diagnostics.n_divergences`` when present. ``passed`` is left unset: only ``g3``
sets it.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import pandas as pd

from bayesian_marketing.core import (
    DiagnosticsReport,
    FunnelData,
    FunnelState,
    GateResult,
    inputs_hash,
    registries,
    utcnow,
)
from bayesian_marketing.derived_metrics.dist import PER_MILLE

THRESHOLDS_REF = "diagnostics/thresholds@v1"
CHAIN_COLUMN = "chain"
DIVERGENCES_PARAM = "diagnostics.n_divergences"
TAIL_PROBS = (0.05, 0.95)
"""The definition of tail ESS (Vehtari et al. 2021, ArviZ default), not a tunable threshold."""
CHUNK = 256  # orders simulated per block when summing an orders file (memory only)


def _threshold(key: str) -> object:
    return registries.resolve(f"diagnostics/thresholds/{key}@v1")


def _report_id(payload: object) -> str:
    return f"dg_{inputs_hash(payload)[:8]}"


def _seed(state: FunnelState) -> int:
    params = state.posterior.params or {}
    if "seed" in params:
        return int(params["seed"])
    return int(inputs_hash(state.state_id)[:8], 16)


def _paid_days(data: FunnelData, i: int) -> list[int]:
    return [d for d in range(len(data.dates)) if data.spend[i][d] > 0]


def _conversions(data: FunnelData, i: int, d: int) -> float | None:
    obs = data.conversions_observed[i][d]
    if obs is not None:
        return float(obs)
    rep = data.conversions_reported[i][d]
    return None if rep is None else float(rep)


def _mid_p(rep: np.ndarray, obs: float) -> float:
    return float(np.mean(rep > obs) + 0.5 * np.mean(rep == obs))


class _Draws:
    def __init__(self, df: pd.DataFrame) -> None:
        self.df = df

    def get(self, column: str) -> np.ndarray | None:
        if column not in self.df.columns:
            return None
        return self.df[column].to_numpy(dtype=float)


def _ppc_delivery(data: FunnelData, draws: _Draws, rng: np.random.Generator) -> float | None:
    obs, rep, used = 0.0, None, False
    for i, ad in enumerate(data.entities):
        cpm = draws.get(f"{ad}.cpm")
        days = _paid_days(data, i)
        if cpm is None or not days:
            continue
        spend = sum(data.spend[i][d] for d in days)
        obs += sum(data.impressions[i][d] for d in days)
        r = rng.poisson(spend * PER_MILLE / cpm)
        rep = r if rep is None else rep + r
        used = True
    return _mid_p(rep, obs) if used and rep is not None else None


def _ppc_ctr(data: FunnelData, draws: _Draws, rng: np.random.Generator) -> float | None:
    obs, rep = 0.0, None
    for i, ad in enumerate(data.entities):
        ctr = draws.get(f"{ad}.ctr")
        days = _paid_days(data, i)
        if ctr is None or not days:
            continue
        imps = int(sum(data.impressions[i][d] for d in days))
        obs += sum(data.clicks[i][d] for d in days)
        r = rng.binomial(imps, np.clip(ctr, 0.0, 1.0))
        rep = r if rep is None else rep + r
    return None if rep is None else _mid_p(rep, obs)


def _ppc_cvr(data: FunnelData, draws: _Draws, rng: np.random.Generator) -> float | None:
    obs, rep = 0.0, None
    for i, ad in enumerate(data.entities):
        cvr = draws.get(f"{ad}.cvr")
        if cvr is None:
            continue
        conv, trials, seen = 0.0, 0.0, False
        for d in _paid_days(data, i):
            c = _conversions(data, i, d)
            if c is None:
                continue
            seen = True
            conv += c
            trials += max(data.clicks[i][d] * float(data.mature_fraction[i][d]), c)
        if not seen:
            continue
        obs += round(conv)
        r = rng.binomial(round(trials), np.clip(cvr, 0.0, 1.0))
        rep = r if rep is None else rep + r
    return None if rep is None else _mid_p(rep, obs)


def _lognormal_total(
    params: dict[str, float], ad: str, n: int, n_draws: int, rng: np.random.Generator
) -> np.ndarray:
    """Sum of ``n`` new orders under the normal-inverse-gamma posterior on log order value."""
    alpha, beta = params[f"{ad}.aov.nig.alpha"], params[f"{ad}.aov.nig.beta"]
    mu0, kappa = params[f"{ad}.aov.nig.mu"], params[f"{ad}.aov.nig.kappa"]
    sigma2 = beta / rng.gamma(alpha, 1.0, n_draws)
    mu = rng.normal(mu0, np.sqrt(sigma2 / kappa))
    sd = np.sqrt(sigma2)
    total = np.zeros(n_draws)
    for start in range(0, n, CHUNK):
        m = min(CHUNK, n - start)
        z = rng.standard_normal((n_draws, m))
        total += np.exp(mu[:, None] + sd[:, None] * z).sum(axis=1)
    return total


def _ppc_value(
    data: FunnelData, draws: _Draws, params: dict[str, float], rng: np.random.Generator
) -> float | None:
    obs, rep = 0.0, None
    default_k = float(registries.resolve("bounds/value/compound_gamma_k@v1"))
    for i, ad in enumerate(data.entities):
        values = list(data.order_values.get(ad, []))
        if len(values) >= 2 and f"{ad}.aov.nig.alpha" in params:
            n_draws = len(draws.df)
            r = _lognormal_total(params, ad, len(values), n_draws, rng)
            obs += float(sum(values))
        else:
            aov = draws.get(f"{ad}.aov")
            if aov is None:
                continue
            n_ord, rev = 0.0, 0.0
            for d in _paid_days(data, i):
                rv, c = data.revenue_reported[i][d], _conversions(data, i, d)
                if rv is None or c is None or c <= 0:
                    continue
                n_ord += c
                rev += float(rv)
            if n_ord <= 0 or rev <= 0:
                continue
            k = float(params.get(f"{ad}.aov.compound_gamma_k", default_k))
            r = rng.gamma(k * n_ord, aov / k)
            obs += rev
        rep = r if rep is None else rep + r
    return None if rep is None else _mid_p(rep, obs)


def _ppc(state: FunnelState, data: FunnelData, df: pd.DataFrame, seed: int) -> dict[str, float]:
    draws = _Draws(df)
    params = dict(state.posterior.params or {})
    rng = np.random.default_rng(seed)
    stages: list[tuple[str, Callable[[], float | None]]] = [
        ("delivery", lambda: _ppc_delivery(data, draws, rng)),
        ("ctr", lambda: _ppc_ctr(data, draws, rng)),
        ("cvr", lambda: _ppc_cvr(data, draws, rng)),
        ("value", lambda: _ppc_value(data, draws, params, rng)),
    ]
    out: dict[str, float] = {}
    for name, fn in stages:
        p = fn()
        if p is not None and math.isfinite(p):
            out[name] = p
    return out


def _chain_stats(df: pd.DataFrame) -> tuple[float | None, float | None, float | None]:
    """Worst R-hat, bulk ESS and tail ESS over draw columns, or None without a chain column."""
    if CHAIN_COLUMN not in df.columns:
        return None, None, None
    import arviz as az  # ArviZ 1.x (D19); numpy arrays shaped (chain, draw)

    groups = [g.drop(columns=[CHAIN_COLUMN]) for _, g in df.groupby(CHAIN_COLUMN, sort=True)]
    n = min(len(g) for g in groups)
    if len(groups) < 2 or n < 4:
        return None, None, None
    rhat, bulk, tail = -math.inf, math.inf, math.inf
    for col in groups[0].columns:
        x = np.stack([g[col].to_numpy(dtype=float)[:n] for g in groups])
        rhat = max(rhat, float(az.rhat(x)))
        bulk = min(bulk, float(az.ess(x, method="bulk")))
        tail = min(tail, float(az.ess(x, method="tail", prob=TAIL_PROBS)))
    return rhat, bulk, tail


def run_diagnostics(state: FunnelState, data: FunnelData) -> DiagnosticsReport:
    """R-hat, ESS bulk and tail, divergences, per-stage PPC p-values. Does not set ``passed``."""
    spec = state.posterior
    if spec.kind != "samples" or spec.samples_path is None:
        raise ValueError(f"state {state.state_id} has no joint draws to check")
    df = pd.read_parquet(spec.samples_path)
    seed = _seed(state)
    rhat, bulk, tail = _chain_stats(df)
    params = spec.params or {}
    div = params.get(DIVERGENCES_PARAM)
    draw_cols = df.drop(columns=[CHAIN_COLUMN], errors="ignore")
    ppc = _ppc(state, data, draw_cols, seed)
    sampler = "conjugate" if state.route == "conjugate" else "numpyro_nuts"
    payload = {"state": state.state_id, "ppc": ppc, "rhat": rhat, "seed": seed}
    return DiagnosticsReport(
        report_id=_report_id(payload),
        sampler=sampler,
        rhat_max=rhat,
        ess_bulk_min=bulk,
        ess_tail_min=tail,
        n_divergences=None if div is None else int(div),
        ppc=ppc,
        loo=None,
        seeds=[seed],
        thresholds_ref=THRESHOLDS_REF,
    )


def g3(report: DiagnosticsReport) -> tuple[DiagnosticsReport, GateResult]:
    """The only setter of ``passed``. A fail quarantines the state and triggers fallback.

    One reason per breached threshold, naming the metric or the PPC stage. A metric that is None
    (not computed, e.g. independent conjugate draws) is not checked. Never raises on a report.
    """
    reasons: list[str] = []
    rhat_max = float(_threshold("rhat_max"))  # type: ignore[arg-type]
    ess_bulk_min = float(_threshold("ess_bulk_min"))  # type: ignore[arg-type]
    ess_tail_min = float(_threshold("ess_tail_min"))  # type: ignore[arg-type]
    div_max = int(_threshold("divergences_max"))  # type: ignore[call-overload]
    lo, hi = (float(x) for x in _threshold("ppc_band"))  # type: ignore[attr-defined]

    def bad(x: float | None, fails: Callable[[float], bool]) -> bool:
        return x is not None and (not math.isfinite(x) or fails(x))

    if bad(report.rhat_max, lambda x: x > rhat_max):
        reasons.append(f"rhat {report.rhat_max} above rhat_max {rhat_max}")
    if bad(report.ess_bulk_min, lambda x: x < ess_bulk_min):
        reasons.append(f"ess_bulk {report.ess_bulk_min} below ess_bulk_min {ess_bulk_min}")
    if bad(report.ess_tail_min, lambda x: x < ess_tail_min):
        reasons.append(f"ess_tail {report.ess_tail_min} below ess_tail_min {ess_tail_min}")
    if report.n_divergences is not None and report.n_divergences > div_max:
        reasons.append(f"divergences {report.n_divergences} above divergences_max {div_max}")
    for stage, p in sorted(report.ppc.items()):
        if not math.isfinite(p) or p < lo or p > hi:
            reasons.append(f"PPC misfit in stage {stage}: p-value {p} outside [{lo}, {hi}]")

    passed = not reasons
    out = report.model_copy(update={"passed": passed})
    res = GateResult(
        gate="G3",
        passed=passed,
        blocking=True,
        reasons=reasons,
        inputs_hash=inputs_hash(report.model_copy(update={"passed": None})),
        checked_at=utcnow(),
    )
    return out, res
