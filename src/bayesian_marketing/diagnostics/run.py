"""§7.4 run_diagnostics and the G3 gate.

``run_diagnostics`` reads the state's joint draws (one parquet column per ``"<ad>.<parameter>"``,
the layout ``derive`` reads for either route) and computes, per stage, the posterior predictive
p-value of the stage total over all ads (a mid p-value, P(T_rep > T_obs) + ½ P(T_rep = T_obs)):

- delivery: impressions ~ Poisson(spend · 1000 / CPM) on paid days;
- ctr: clicks ~ Binomial(impressions, CTR);
- cvr: conversions ~ Binomial(lag-adjusted trials, CVR), trials as in the conjugate route;
- value: revenue, the sum of the orders file under the log-normal posterior, else the compound
  gamma total Gamma(k · orders, scale = AOV / k).

A stage with no draws or no data is left out. Only parameter columns are read: ``rho`` and names
shaped ``"<entity>.<param>"``; ``chain``, ``draw`` and anything else are ignored.

For a NUTS state the draws must carry a ``chain`` column. R-hat (rank) and bulk and tail ESS come
from ArviZ 1.x, worst over parameter columns. Zero-variance columns are left out and logged (a
constant has no R-hat). ESS is computed on a single chain; R-hat needs two or more. Chains of
unequal length are not truncated: nothing is computed. A metric that cannot be computed is None and
G3 fails it for NUTS; a NaN or infinite result is kept and G3 fails it as not finite. Divergences
come from ``posterior.params["diagnostics.n_divergences"]``; a missing or non-finite count is None.
Conjugate draws are independent, so their R-hat, ESS and divergences are None and G3 skips them.
``passed`` is left unset: only ``g3`` sets it.
"""

from __future__ import annotations

import logging
import math
import re
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
PARAM_COLUMN = re.compile(r"^(rho|[^.]+\.[A-Za-z_][A-Za-z0-9_]*)$")
"""A parameter draw column: ``rho`` or ``"<entity>.<param>"``."""
CHUNK = 256  # orders simulated per block when summing an orders file (memory only)


log = logging.getLogger(__name__)

NON_FINITE = "non-finite draws in "
"""PPC-key prefix marking a parameter column with NaN or infinite draws. The report has no notes
field, so ``run_diagnostics`` records the breach as ``ppc["non-finite draws in <col>"] = 0.0`` and
``g3`` turns that key into the reason "non-finite draws in <col>" (manifest open question 5)."""

NOT_COMPUTED = {
    "rhat": "rhat not computed: needs two or more equal-length chains of a non-constant parameter",
    "ess_bulk": "ess_bulk not computed: needs chain-labelled draws of equal length, non-constant",
    "ess_tail": "ess_tail not computed: needs chain-labelled draws of equal length, non-constant",
    "divergences": "divergences not computed: the sampler recorded no finite divergence count",
}
"""G3 reasons for a NUTS metric that is None. Gate messages, not client phrasing."""


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


def _param_columns(df: pd.DataFrame) -> list[str]:
    return [
        c
        for c in df.columns
        if isinstance(c, str)
        and c != CHAIN_COLUMN
        and PARAM_COLUMN.match(c)
        and pd.api.types.is_numeric_dtype(df[c])
    ]


def _worst(values: list[float], pick: Callable[[list[float]], float]) -> float:
    """Worst value, with any NaN or infinity winning so G3 sees it as not finite."""
    bad = [v for v in values if not math.isfinite(v)]
    return bad[0] if bad else pick(values)


def _chain_stats(df: pd.DataFrame) -> tuple[float | None, float | None, float | None]:
    """Worst R-hat, bulk ESS and tail ESS over parameter columns; None where not computable."""
    if CHAIN_COLUMN not in df.columns:
        log.warning("diagnostics: no %r column; R-hat and ESS not computed", CHAIN_COLUMN)
        return None, None, None
    import arviz as az  # ArviZ 1.x (D19); numpy arrays shaped (chain, draw)

    groups = [g for _, g in df.groupby(CHAIN_COLUMN, sort=True)]
    lengths = {len(g) for g in groups}
    if len(lengths) != 1:
        log.warning("diagnostics: unequal chain lengths %s; not truncated", sorted(lengths))
        return None, None, None
    cols = _param_columns(df)
    constant = [c for c in cols if np.ptp(df[c].to_numpy(dtype=float)) == 0]
    if constant:
        log.warning("diagnostics: zero-variance columns left out of R-hat and ESS: %s", constant)
    cols = [c for c in cols if c not in constant]
    if not cols:
        return None, None, None
    rhats: list[float] = []
    bulks: list[float] = []
    tails: list[float] = []
    for col in cols:
        x = np.stack([g[col].to_numpy(dtype=float) for g in groups])
        if len(groups) >= 2:
            rhats.append(float(az.rhat(x)))
        bulks.append(float(az.ess(x, method="bulk")))
        tails.append(float(az.ess(x, method="tail", prob=TAIL_PROBS)))
    rhat = _worst(rhats, max) if rhats else None
    return rhat, _worst(bulks, min), _worst(tails, min)


def _divergences(params: dict[str, float]) -> int | None:
    div = params.get(DIVERGENCES_PARAM)
    if div is None:
        return None
    if not math.isfinite(div):
        log.warning("diagnostics: divergence count %r is not finite", div)
        return None
    return int(div)


def run_diagnostics(state: FunnelState, data: FunnelData) -> DiagnosticsReport:
    """R-hat, ESS bulk and tail, divergences, per-stage PPC p-values. Does not set ``passed``."""
    spec = state.posterior
    if spec.kind != "samples" or spec.samples_path is None:
        raise ValueError(f"state {state.state_id} has no joint draws to check")
    df = pd.read_parquet(spec.samples_path)
    seed = _seed(state)
    params = spec.params or {}
    sampler = "conjugate" if state.route == "conjugate" else "numpyro_nuts"
    cols = _param_columns(df)
    bad = [c for c in cols if not np.isfinite(df[c].to_numpy(dtype=float)).all()]
    rhat = bulk = tail = None
    div = None
    if bad:
        # Checked before any metric or PPC: ArviZ ranks an infinity as an ordinary value and the
        # PPC draws cannot take NaN. Nothing else is computed; G3 fails on the marker keys.
        log.warning("diagnostics: non-finite draws in %s; metrics and PPC skipped", bad)
        ppc = {f"{NON_FINITE}{c}": 0.0 for c in bad}
    else:
        if sampler == "numpyro_nuts":
            rhat, bulk, tail = _chain_stats(df)
            div = _divergences(params)
        ppc = _ppc(state, data, df[cols], seed)
    payload = {"state": state.state_id, "ppc": ppc, "rhat": rhat, "seed": seed}
    return DiagnosticsReport(
        report_id=_report_id(payload),
        sampler=sampler,
        rhat_max=rhat,
        ess_bulk_min=bulk,
        ess_tail_min=tail,
        n_divergences=div,
        ppc=ppc,
        loo=None,
        seeds=[seed],
        thresholds_ref=THRESHOLDS_REF,
    )


def g3(report: DiagnosticsReport) -> tuple[DiagnosticsReport, GateResult]:
    """The only setter of ``passed``. A fail quarantines the state and triggers fallback.

    One reason per breached threshold, naming the metric or the PPC stage. A None metric fails on
    a NUTS report (not computed) and is skipped on a conjugate one; NaN or infinity fails as not
    finite. A ``non-finite draws in <col>`` PPC key is a breach with that reason. Never raises on
    a report.
    """
    reasons: list[str] = []
    rhat_max = float(_threshold("rhat_max"))  # type: ignore[arg-type]
    ess_bulk_min = float(_threshold("ess_bulk_min"))  # type: ignore[arg-type]
    ess_tail_min = float(_threshold("ess_tail_min"))  # type: ignore[arg-type]
    div_max = int(_threshold("divergences_max"))  # type: ignore[call-overload]
    lo, hi = (float(x) for x in _threshold("ppc_band"))  # type: ignore[attr-defined]

    nuts = report.sampler == "numpyro_nuts"

    def check(metric: str, x: float | None, fails: Callable[[float], bool], text: str) -> None:
        if x is None:
            if nuts:
                reasons.append(NOT_COMPUTED[metric])
        elif not math.isfinite(x):
            reasons.append(f"{metric} {x} is not finite")
        elif fails(x):
            reasons.append(f"{metric} {x} {text}")

    check("rhat", report.rhat_max, lambda x: x > rhat_max, f"above rhat_max {rhat_max}")
    check(
        "ess_bulk",
        report.ess_bulk_min,
        lambda x: x < ess_bulk_min,
        f"below ess_bulk_min {ess_bulk_min}",
    )
    check(
        "ess_tail",
        report.ess_tail_min,
        lambda x: x < ess_tail_min,
        f"below ess_tail_min {ess_tail_min}",
    )
    div = None if report.n_divergences is None else float(report.n_divergences)
    check("divergences", div, lambda x: x > div_max, f"above divergences_max {div_max}")
    for stage, p in sorted(report.ppc.items()):
        if stage.startswith(NON_FINITE):
            reasons.append(stage)
        elif not math.isfinite(p) or p < lo or p > hi:
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
