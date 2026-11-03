"""DistributionSpec helpers shared by derive, compare and test_design (P3).

Analytic families map to scipy frozen distributions. ``params`` may carry ``loc`` and ``scale``
on top of the shape parameters, so an affine map of a posterior (e.g. contribution per click =
contribution per order x CVR - CPC) stays analytic and exact.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import integrate, stats

from bayesian_marketing.core import DistributionSpec

TAIL = 1e-15
"""Tail mass cut from each end of an unbounded support before quadrature."""


def frozen(spec: DistributionSpec) -> Any:
    """The scipy frozen distribution of an analytic spec."""
    if spec.kind != "analytic" or spec.params is None:
        raise ValueError("not an analytic distribution")
    p = dict(spec.params)
    loc = p.pop("loc", 0.0)
    scale = p.pop("scale", 1.0)
    fam = spec.family
    if fam == "beta":
        return stats.beta(p["a"], p["b"], loc=loc, scale=scale)
    if fam == "gamma":
        return stats.gamma(p["a"], loc=loc, scale=scale)
    if fam == "invgamma":
        return stats.invgamma(p["a"], loc=loc, scale=scale)
    if fam == "lognorm":
        return stats.lognorm(p["s"], loc=loc, scale=scale)
    raise ValueError(f"unknown analytic family {fam!r}")


def summary_of_dist(d: Any) -> dict[str, float]:
    q = d.ppf([0.05, 0.5, 0.95, 0.025, 0.975])
    return {
        "mean": float(d.mean()),
        "sd": float(d.std()),
        "q05": float(q[0]),
        "q50": float(q[1]),
        "q95": float(q[2]),
        "q025": float(q[3]),
        "q975": float(q[4]),
    }


def summary_of_draws(x: Any) -> dict[str, float]:
    x = np.asarray(x, dtype=float)
    q = np.quantile(x, [0.05, 0.5, 0.95, 0.025, 0.975])
    return {
        "mean": float(x.mean()),
        "sd": float(x.std(ddof=1)) if x.size > 1 else 0.0,
        "q05": float(q[0]),
        "q50": float(q[1]),
        "q95": float(q[2]),
        "q025": float(q[3]),
        "q975": float(q[4]),
    }


def analytic(family: str, params: dict[str, float]) -> DistributionSpec:
    spec = DistributionSpec(kind="analytic", family=family, params=params, summary=_PLACEHOLDER)
    return spec.model_copy(update={"summary": summary_of_dist(frozen(spec))})


_PLACEHOLDER = dict.fromkeys(("mean", "sd", "q05", "q50", "q95", "q025", "q975"), 0.0)


def write_draws(path: Path, column: str, draws: Any) -> DistributionSpec:
    """A one-column samples spec (contract assumption 16)."""
    x = np.asarray(draws, dtype=float)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({column: x}).to_parquet(path)
    return DistributionSpec(
        kind="samples", samples_path=str(path), n_samples=int(x.size), summary=summary_of_draws(x)
    )


def read_draws(spec: DistributionSpec, column: str | None = None) -> np.ndarray:
    """Draws of a samples spec: the named column, else the single (first) column."""
    if spec.kind != "samples" or spec.samples_path is None:
        raise ValueError("not a samples distribution")
    df = pd.read_parquet(spec.samples_path)
    col = column if column is not None else df.columns[0]
    if col not in df.columns:
        raise KeyError(f"{spec.samples_path} has no column {col!r}")
    return df[col].to_numpy(dtype=float)


def draws_of(spec: DistributionSpec, n: int, rng: np.random.Generator) -> np.ndarray:
    """Draws of any spec: read for samples, seeded rvs for analytic."""
    if spec.kind == "samples":
        return read_draws(spec)
    return np.asarray(frozen(spec).rvs(size=n, random_state=rng), dtype=float)


def _support(d: Any) -> tuple[float, float]:
    lo, hi = (float(v) for v in d.support())
    if not math.isfinite(lo):
        lo = float(d.ppf(TAIL))
    if not math.isfinite(hi):
        hi = float(d.isf(TAIL))
    return lo, hi


def exact_max_moments(dists: list[Any], abs_tol: float) -> tuple[list[float], float]:
    """For independent X_j: P(X_j is the largest) for each j, and E[max_j X_j], by quadrature.

    P(best=j) = ∫ f_j(x) Π_{k≠j} F_k(x) dx and E[max] = Σ_j ∫ x f_j(x) Π_{k≠j} F_k(x) dx.
    """
    p_best: list[float] = []
    e_max = 0.0
    for j, dj in enumerate(dists):
        others = [d for k, d in enumerate(dists) if k != j]
        lo, hi = _support(dj)
        pts = sorted({float(v) for v in dj.ppf([0.001, 0.05, 0.5, 0.95, 0.999])} | _peaks(others))
        pts = [p for p in pts if lo < p < hi]

        def cdf_others(x: float, others: list[Any] = others) -> float:
            out = 1.0
            for d in others:
                out *= float(d.cdf(x))
            return out

        def f_p(x: float, dj: Any = dj, c: Any = cdf_others) -> float:
            return float(dj.pdf(x)) * c(x)

        def f_e(x: float, dj: Any = dj, c: Any = cdf_others) -> float:
            return x * float(dj.pdf(x)) * c(x)

        kw = {"epsabs": abs_tol, "epsrel": 0.0, "limit": 1000, "points": pts or None}
        p, _ = integrate.quad(f_p, lo, hi, **kw)
        e, _ = integrate.quad(f_e, lo, hi, **kw)
        p_best.append(float(p))
        e_max += float(e)
    return p_best, e_max


def _peaks(dists: list[Any]) -> set[float]:
    out: set[float] = set()
    for d in dists:
        out |= {float(v) for v in d.ppf([0.05, 0.5, 0.95])}
    return out
