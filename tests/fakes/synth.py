"""Small seeded data generators for model-recovery tests (P5, P7).

These stand in for the simulator scenarios so the model pieces can be tested before P2 merges.
They use numpy's PCG64 generator, whose stream is stable across numpy versions.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
from scipy.special import expit, logit

from bayesian_marketing import core as C
from tests.fakes import builders as B


def _days(n: int, end: dt.date = B.D_END) -> list[dt.date]:
    return [end - dt.timedelta(days=n - 1 - i) for i in range(n)]


def _split(rng: np.random.Generator, total: int, n: int) -> list[int]:
    return [int(x) for x in rng.multinomial(total, [1.0 / n] * n)]


NEG_DEP_SEED = 1  # realized latent correlation -0.608 (checked in scratch)
NEG_DEP_RHO = -0.6


def negative_dependence(seed: int = NEG_DEP_SEED, n_ads: int = 12, n_days: int = 7):
    """12 ads, latent (logit ctr, logit cvr) bivariate normal with correlation -0.6 (§9.1).

    Returns (FunnelData, realized correlation of the latent pairs).
    """
    rng = np.random.default_rng(seed)
    mu = np.array([logit(0.02), logit(0.03)])
    sd = np.array([0.5, 0.5])
    cov = np.diag(sd) @ np.array([[1, NEG_DEP_RHO], [NEG_DEP_RHO, 1]]) @ np.diag(sd)
    lat = rng.multivariate_normal(mu, cov, size=n_ads)
    ctr, cvr = expit(lat[:, 0]), expit(lat[:, 1])
    ads = {}
    for i in range(n_ads):
        spend_total = 2000.0
        imps = int(rng.poisson(spend_total * 1000 / 10.0))
        clicks = int(rng.binomial(imps, ctr[i]))
        conv = int(rng.binomial(clicks, cvr[i]))
        values = np.round(rng.lognormal(np.log(80) - 0.18, 0.6, size=conv), 2)
        ads[f"ad_{i:02d}"] = {
            "spend": [spend_total / n_days] * n_days,
            "impressions": _split(rng, imps, n_days),
            "clicks": _split(rng, clicks, n_days),
            "conv_obs": _split(rng, conv, n_days),
            "conv_rep": None,
            "order_values": [float(v) for v in values],
        }
    for a in ads.values():  # keep clicks <= impressions and conversions <= clicks per day
        a["clicks"] = [min(c, i) for c, i in zip(a["clicks"], a["impressions"], strict=True)]
        a["conv_obs"] = [min(v, c) for v, c in zip(a["conv_obs"], a["clicks"], strict=True)]
        a["conv_rep"] = [float(v) for v in a["conv_obs"]]
    data = B.funnel_data(ads, dates=_days(n_days))
    return data, float(np.corrcoef(lat[:, 0], lat[:, 1])[0, 1])


A1_SEED = 7


def a1_ads(seed: int = A1_SEED) -> dict[str, dict]:
    """8 ads with wide order-value spread (lognormal sigma 1.2) for the A1 test (§5.2 C2)."""
    rng = np.random.default_rng(seed)
    cvrs = np.linspace(0.015, 0.05, 8)
    ads = {}
    for i, cvr in enumerate(cvrs):
        clicks = 2000
        conv = int(rng.binomial(clicks, cvr))
        values = np.round(rng.lognormal(np.log(80) - 0.72, 1.2, size=conv), 2)
        ads[f"ad_{i}"] = {
            "impressions": 100000,
            "clicks": clicks,
            "spend": 2500.0,
            "conv_obs": conv,
            "conv_rep": float(conv),
            "revenue": float(values.sum()),
            "order_values": [float(v) for v in values],
        }
    return ads


def a1_data() -> C.FunnelData:
    return B.funnel_data(a1_ads())


def fractional_data(n_ads: int = 8, seed: int = 3) -> C.FunnelData:
    """Only platform-reported, fractional conversions (§5.2 C6): no orders file, none observed."""
    rng = np.random.default_rng(seed)
    ads = {}
    for i in range(n_ads):
        clicks = int(rng.integers(800, 1200))
        rep = round(float(clicks * 0.03 + rng.normal(0, 3)), 2) + 0.37
        ads[f"ad_{i}"] = {
            "impressions": clicks * 50,
            "clicks": clicks,
            "spend": clicks * 1.2,
            "conv_obs": None,
            "conv_rep": rep,
            "revenue": rep * 80.0,
        }
    return B.funnel_data(ads, pull_ids=[B.META_PULL])


LAG_SEED = 11
LAG_TRUE_CVR = 0.04
LAG_MEDIAN_DAYS = 4


@dataclass
class LagHeavy:
    dates: list[dt.date]
    clicks: list[int]
    conv_observed: list[int]
    as_of: dt.date
    history: list[C.OrderRow]
    true_cvr: float


def lag_heavy(seed: int = LAG_SEED, n_days: int = 14, clicks_per_day: int = 1000) -> LagHeavy:
    """Geometric lag with median 4 days (§9.1 `lag_heavy`); as_of is the last click day.

    ``history`` is 400 older, fully matured orders with ``first_click_at`` for estimating the lag.
    """
    rng = np.random.default_rng(seed)
    p = 1 - 0.5 ** (1 / (LAG_MEDIAN_DAYS + 1))  # P(lag <= 4) = 0.5
    dates = _days(n_days)
    as_of = dates[-1]
    clicks, observed = [], []
    for d in dates:
        c = int(rng.poisson(clicks_per_day))
        n_conv = int(rng.binomial(c, LAG_TRUE_CVR))
        lags = rng.geometric(p, size=n_conv) - 1
        clicks.append(c)
        observed.append(int(np.sum(lags <= (as_of - d).days)))
    history = []
    base = dt.datetime(2026, 8, 1, 10, 0, tzinfo=dt.UTC)
    for k, lag in enumerate(rng.geometric(p, size=400) - 1):
        first = base + dt.timedelta(hours=int(k))
        history.append(
            B.order_row(
                order_id=f"h{k}",
                first_click_at=first,
                ordered_at=first + dt.timedelta(days=int(lag), hours=1),
            )
        )
    return LagHeavy(dates, clicks, observed, as_of, history, LAG_TRUE_CVR)
