"""§7.2 the exact per-ad conjugate route. Piece P3.

The FunnelState's posterior is a ``samples`` DistributionSpec with ``family="conjugate"``:

- ``params`` hold the analytic posteriors and the data totals, flat, keyed
  ``"<ad>.<parameter>.<name>"``: ``ctr.a/b`` and ``cvr.a/b`` (Beta), ``cpa.a/scale`` and
  ``cpm.a/scale`` (InvGamma; CPM in currency per 1,000 impressions), ``aov.a/scale`` (InvGamma,
  compound-gamma route) or ``aov.nig.*`` (log-normal route), ``n.impressions``, ``n.clicks``,
  ``n.conversions``, ``n.orders``, ``spend``, and flags ``flag.lag_adjusted``,
  ``flag.platform_modeled``, ``flag.cpm_reference_prior``, ``flag.aov_source`` (1 orders file,
  2 compound gamma), ``aov.compound_gamma_k``. State-wide: ``route.too_few_ads``,
  ``route.unapproved_priors`` (count; synthetic data only), ``currency.code`` (FunnelData.currency,
  see ``encode_currency``), ``seed``, ``n_draws``.
- CVR trials and CPA spend exposure are both scaled by the mature fraction F(a) (lag-adjusted,
  disclosed by notice); a day's lag-adjusted trials never fall below its conversions.
- ``state_id`` hashes data, prior ids, seed and registry config only, so a refit of the same
  inputs gives the same id and the same draws.
- ``samples_path`` is a parquet of independent seeded draws, one column per
  ``"<ad>.<parameter>"`` (ctr, cvr, cpa, cpm, aov), written under ``BAYES_DATA_DIR``.
- ``summary`` describes the first column.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from bayesian_marketing.core import (
    FunnelData,
    FunnelState,
    GateFailure,
    GateResult,
    PriorRecord,
    PriorSet,
    inputs_hash,
    make_id,
    registries,
    utcnow,
)
from bayesian_marketing.core.money import DistributionSpec
from bayesian_marketing.derived_metrics.dist import PER_MILLE, encode_currency, summary_of_draws
from bayesian_marketing.funnel_state.store import states_dir

REQUIRED_PRIORS = ("ctr", "cvr", "conversions_per_dollar")

CPM_PRIOR = "cpm_impressions_per_dollar"


def _prior(
    priors: PriorSet, path: str, required: bool = True, synthetic: bool = False
) -> PriorRecord | None:
    """The record for ``path``. An unapproved record raises G8 on client data (I10); on synthetic
    data it is allowed and the state carries ``route.unapproved_priors`` so derive discloses it."""
    rec = priors.records.get(path)
    if rec is None:
        if required:
            raise KeyError(f"PriorSet has no record for {path!r}")
        return None
    if not rec.approved and not synthetic:
        res = GateResult(
            gate="G8",
            passed=False,
            blocking=True,
            reasons=[f"prior {rec.prior_id} for {path!r} is not approved (I10)"],
            inputs_hash=inputs_hash(rec),
            checked_at=utcnow(),
        )
        raise GateFailure(res)
    return rec


def _validate(data: FunnelData) -> None:
    """Refuse impossible data rather than clamp it. Errors name the entity and the day."""
    for i, ad in enumerate(data.entities):
        for d, day in enumerate(data.dates):
            where = f"entity {ad!r} on {day.isoformat()}"
            imps, clicks, spend = data.impressions[i][d], data.clicks[i][d], data.spend[i][d]
            if imps < 0 or clicks < 0 or not math.isfinite(spend) or spend < 0:
                raise ValueError(f"{where}: negative or non-finite impressions, clicks or spend")
            if clicks > imps:
                raise ValueError(f"{where}: clicks {clicks} exceed impressions {imps}")
            for kind, c in (
                ("observed", data.conversions_observed[i][d]),
                ("reported", data.conversions_reported[i][d]),
            ):
                if c is None:
                    continue
                if not math.isfinite(c) or c < 0:
                    raise ValueError(f"{where}: {kind} conversions {c} are negative or non-finite")
                if c > clicks:
                    raise ValueError(f"{where}: {kind} conversions {c} exceed clicks {clicks}")
            f = data.mature_fraction[i][d]
            if not (math.isfinite(f) and 0.0 <= f <= 1.0):
                raise ValueError(f"{where}: mature fraction {f} outside [0, 1]")
            r = data.revenue_reported[i][d]
            if r is not None and (not math.isfinite(r) or r < 0):
                raise ValueError(f"{where}: reported revenue {r} is negative or non-finite")
    for ad, values in data.order_values.items():
        for j, v in enumerate(values):
            if not math.isfinite(v) or v <= 0:
                raise ValueError(f"entity {ad!r}, order value #{j}: {v} is not a positive amount")


def _ad_fit(data: FunnelData, i: int, pr: dict[str, PriorRecord | None], k: float) -> dict:
    """Analytic posteriors and totals for entity i. Zero-spend days contribute nothing (§5.2 C4)."""
    ad = data.entities[i]
    days = [d for d in range(len(data.dates)) if data.spend[i][d] > 0]
    imps = float(sum(data.impressions[i][d] for d in days))
    clicks = float(sum(data.clicks[i][d] for d in days))
    spend = float(sum(data.spend[i][d] for d in days))
    p: dict[str, float] = {}

    ctr = pr["ctr"].params  # type: ignore[union-attr]
    p["ctr.a"] = ctr["a"] + clicks
    p["ctr.b"] = ctr["b"] + imps - clicks

    # Conversions per day: observed if present, else platform-reported (platform-modeled).
    conv = 0.0
    trials = 0.0
    exposure = 0.0
    lagged = False
    modeled = False
    conv_days = 0
    for d in days:
        obs = data.conversions_observed[i][d]
        rep = data.conversions_reported[i][d]
        if obs is not None:
            c = float(obs)
        elif rep is not None:
            c = float(rep)
            modeled = True
        else:
            continue
        f = float(data.mature_fraction[i][d])
        conv_days += 1
        conv += c
        # A day cannot have fewer lag-adjusted trials than conversions already seen (both ≤ clicks).
        trials += max(data.clicks[i][d] * f, c)
        exposure += data.spend[i][d] * f  # lag-adjusted spend exposure for CPA (disclosed)
        if f < 1.0 and data.clicks[i][d] > 0:
            lagged = True
    if conv_days:
        cvr = pr["cvr"].params  # type: ignore[union-attr]
        p["cvr.a"] = cvr["a"] + conv
        p["cvr.b"] = cvr["b"] + trials - conv
        cpd = pr["conversions_per_dollar"].params  # type: ignore[union-attr]
        p["cpa.a"] = cpd["shape"] + conv
        p["cpa.scale"] = cpd["rate"] + exposure
        p["n.conversions"] = conv

    # Impressions per dollar, Gamma-Poisson; CPM = PER_MILLE / rate.
    cpm_rec = pr.get(CPM_PRIOR)
    shape0, rate0 = (cpm_rec.params["shape"], cpm_rec.params["rate"]) if cpm_rec else (0.0, 0.0)
    if shape0 + imps > 0 and rate0 + spend > 0:
        p["cpm.a"] = shape0 + imps
        p["cpm.scale"] = PER_MILLE * (rate0 + spend)
        p["flag.cpm_reference_prior"] = 0.0 if cpm_rec else 1.0

    # Order value: conjugate log-normal on the orders file, else compound gamma on daily totals.
    values = list(data.order_values.get(ad, []))  # validated positive
    logs = np.log(np.asarray(values, dtype=float))
    ss = float(((logs - logs.mean()) ** 2).sum()) if len(values) else 0.0
    if len(values) >= 2 and ss > 0:
        n = float(len(values))
        p["aov.nig.mu"] = float(logs.mean())
        p["aov.nig.kappa"] = n
        p["aov.nig.alpha"] = (n - 1.0) / 2.0
        p["aov.nig.beta"] = ss / 2.0
        p["n.orders"] = n
        p["flag.aov_source"] = 1.0
    else:
        n_ord = 0.0
        rev = 0.0
        for d in days:
            r = data.revenue_reported[i][d]
            obs = data.conversions_observed[i][d]
            c = obs if obs is not None else data.conversions_reported[i][d]
            if r is None or c is None or c <= 0:
                continue
            n_ord += float(c)
            rev += float(r)
        if n_ord > 0 and rev > 0:
            p["aov.a"] = k * n_ord
            p["aov.scale"] = k * rev
            p["aov.compound_gamma_k"] = k
            p["n.orders"] = n_ord
            p["flag.aov_source"] = 2.0

    p["n.impressions"] = imps
    p["n.clicks"] = clicks
    p["spend"] = spend
    p["flag.lag_adjusted"] = 1.0 if lagged else 0.0
    p["flag.platform_modeled"] = 1.0 if modeled else 0.0
    return p


def _draw(p: dict[str, float], n: int, rng: np.random.Generator) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    out["ctr"] = rng.beta(p["ctr.a"], p["ctr.b"], n)
    if "cvr.a" in p:
        out["cvr"] = rng.beta(p["cvr.a"], p["cvr.b"], n)
        out["cpa"] = p["cpa.scale"] / rng.gamma(p["cpa.a"], 1.0, n)
    if "cpm.a" in p:
        out["cpm"] = p["cpm.scale"] / rng.gamma(p["cpm.a"], 1.0, n)
    if "aov.nig.mu" in p:
        sigma2 = p["aov.nig.beta"] / rng.gamma(p["aov.nig.alpha"], 1.0, n)
        mu = rng.normal(p["aov.nig.mu"], np.sqrt(sigma2 / p["aov.nig.kappa"]))
        out["aov"] = np.exp(mu + sigma2 / 2.0)
    elif "aov.a" in p:
        out["aov"] = p["aov.scale"] / rng.gamma(p["aov.a"], 1.0, n)
    return out


def fit_conjugate(data: FunnelData, priors: PriorSet, seed: int) -> FunnelState:
    """Per-ad Beta-Binomial CTR and lag-adjusted CVR, Gamma-Poisson conversions per dollar and
    CPM, conjugate order value; analytic parameters plus seeded samples."""
    if not data.entities:
        raise ValueError("FunnelData has no entities")
    _validate(data)
    syn = data.synthetic
    pr: dict[str, Any] = {p: _prior(priors, p, synthetic=syn) for p in REQUIRED_PRIORS}
    pr[CPM_PRIOR] = _prior(priors, CPM_PRIOR, required=False, synthetic=syn)
    unapproved = sorted(p for p, rec in pr.items() if rec is not None and not rec.approved)
    k = float(registries.resolve("bounds/value/compound_gamma_k@v1"))
    min_ads = int(registries.resolve("bounds/coupling/min_ads_for_coupling@v1"))
    n_draws = int(registries.resolve("decision_defaults/joint_draws@v1"))

    params: dict[str, float] = {
        "route.too_few_ads": 1.0 if len(data.entities) < min_ads else 0.0,
        "route.unapproved_priors": float(len(unapproved)),
        "currency.code": encode_currency(data.currency),
        "seed": float(seed),
        "n_draws": float(n_draws),
    }
    rng = np.random.default_rng(seed)
    columns: dict[str, np.ndarray] = {}
    for i, ad in enumerate(data.entities):
        p = _ad_fit(data, i, pr, k)
        params.update({f"{ad}.{key}": float(v) for key, v in p.items()})
        for name, x in _draw(p, n_draws, rng).items():
            columns[f"{ad}.{name}"] = x
    bad = [key for key, v in params.items() if not math.isfinite(v)]
    if bad:
        raise ValueError(f"non-finite posterior parameters: {bad}")

    prior_ids = {path: rec.prior_id for path, rec in pr.items() if rec is not None}
    config = {"compound_gamma_k": k, "min_ads_for_coupling": min_ads, "joint_draws": n_draws}
    state_id = make_id(
        "fs_",
        {"data": data, "priors": prior_ids, "seed": seed, "route": "conjugate", "config": config},
    )
    path = states_dir() / f"{state_id}.samples.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    pd.DataFrame(columns).to_parquet(tmp)
    tmp.replace(path)  # same inputs and seed give the same draws, so a rewrite is identical
    first = next(iter(columns))
    posterior = DistributionSpec(
        kind="samples",
        family="conjugate",
        params=params,
        samples_path=str(path),
        n_samples=n_draws,
        summary=summary_of_draws(columns[first]),
    )
    return FunnelState(
        state_id=state_id,
        spec_version=None,
        route="conjugate",
        prior_ids=prior_ids,
        data_window=(min(data.dates), max(data.dates)),
        posterior=posterior,
        diagnostics_id=None,
        created_at=utcnow(),
        synthetic=data.synthetic,
        data_pull_ids=list(data.pull_ids),
    )
