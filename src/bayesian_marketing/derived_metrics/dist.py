"""DistributionSpec helpers shared by derive, compare and test_design (P3).

Analytic families map to scipy frozen distributions. ``params`` may carry ``loc`` and ``scale``
on top of the shape parameters, so an affine map of a posterior (e.g. contribution per click =
contribution per order x CVR - CPC) stays analytic and exact.
"""

from __future__ import annotations

import math
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import integrate, stats

from bayesian_marketing.core import DistributionSpec

TAIL = 1e-15
"""Tail mass cut from each end of an unbounded support before quadrature. Registry key requested:
decision_defaults.yaml quadrature_tail_mass: 1.0e-15."""

PER_MILLE = 1000.0
"""CPM is currency per 1,000 impressions (a unit definition, not a tunable)."""


def encode_currency(code: str) -> float:
    """ISO 4217 letters as a base-26 number, so the code fits in ``posterior.params`` (floats)."""
    if len(code) != 3 or not code.isalpha() or not code.isupper():
        raise ValueError(f"not an ISO 4217 code: {code!r}")
    return float(sum((ord(ch) - 65) * 26 ** (2 - i) for i, ch in enumerate(code)))


def decode_currency(value: float) -> str:
    n = int(value)
    return "".join(chr(65 + (n // 26 ** (2 - i)) % 26) for i in range(3))


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


class QuadratureError(ArithmeticError):
    """Exact integration did not meet its tolerance; the caller falls back to joint draws."""


BREAK_QUANTILES = (1e-9, 1e-6, 1e-3, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 1 - 1e-3, 1 - 1e-6)
"""Quantiles of every other arm where the integrand in the quantile domain may turn sharply."""

BREAK_MARGIN = 1e-9
"""Breakpoints this close to a quantile-domain end are dropped; the sliver left is noise."""


def _u_bounds(d: Any) -> tuple[float, float]:
    """Quantile-domain limits: 0 and 1 for a finite support end, TAIL inside for an infinite one."""
    lo, hi = (float(v) for v in d.support())
    return (0.0 if math.isfinite(lo) else TAIL, 1.0 if math.isfinite(hi) else 1.0 - TAIL)


def exact_max_moments(dists: list[Any], abs_tol: float) -> tuple[list[float], list[float]]:
    """For independent X_j: P(X_j is the largest) and E[max_k X_k - X_j] for each j.

    Integrated in the quantile domain of each arm, u = F_j(x), so no integrand has a peak:
    P(best=j) = ∫_0^1 Π_{k≠j} F_k(F_j^{-1}(u)) du and
    E[max] = Σ_j ∫_0^1 F_j^{-1}(u) Π_{k≠j} F_k(F_j^{-1}(u)) du.
    Breakpoints sit at F_j(F_k^{-1}(q)) for the other arms' quantiles q. Any IntegrationWarning,
    a p_best sum off 1 by more than ``abs_tol``, or an expected loss below ``-abs_tol`` raises
    QuadratureError.
    """
    means = [float(d.mean()) for d in dists]
    if not all(math.isfinite(m) for m in means):
        raise QuadratureError("an option has no finite mean")
    k = len(dists)
    each = abs_tol / (4 * k)
    p_best: list[float] = []
    e_max = 0.0
    with warnings.catch_warnings():
        warnings.simplefilter("error", integrate.IntegrationWarning)
        for j, dj in enumerate(dists):
            others = [d for i, d in enumerate(dists) if i != j]
            u_lo, u_hi = _u_bounds(dj)
            pts: set[float] = set()
            for d in others:
                xs = np.asarray(d.ppf(BREAK_QUANTILES), dtype=float)
                pts |= {float(u) for u in np.asarray(dj.cdf(xs[np.isfinite(xs)]))}
            inner = sorted(u for u in pts if u_lo + BREAK_MARGIN < u < u_hi - BREAK_MARGIN)

            def prod(u: float, dj: Any = dj, others: list[Any] = others) -> float:
                return math.prod(float(d.cdf(float(dj.ppf(u)))) for d in others)

            def xprod(u: float, dj: Any = dj, others: list[Any] = others) -> float:
                x = float(dj.ppf(u))
                return x * math.prod(float(d.cdf(x)) for d in others)

            kw: dict[str, Any] = {"epsabs": each, "epsrel": 0.0, "limit": 2000}
            if inner:
                kw["points"] = inner
            try:
                p, _ = integrate.quad(prod, u_lo, u_hi, **kw)
                e, _ = integrate.quad(xprod, u_lo, u_hi, **kw)
            except integrate.IntegrationWarning as w:
                raise QuadratureError(f"quadrature did not converge: {w}") from None
            p_best.append(float(p))
            e_max += float(e)
    if abs(sum(p_best) - 1.0) > abs_tol:
        raise QuadratureError(f"p_best sums to {sum(p_best)!r}, off 1 by more than {abs_tol}")
    loss = [e_max - m for m in means]
    if min(loss) < -abs_tol:
        raise QuadratureError(f"negative expected loss {min(loss)!r}")
    return [min(max(p, 0.0), 1.0) for p in p_best], [max(v, 0.0) for v in loss]
