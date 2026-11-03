"""Draw the true world and the daily data from a scenario (§9.1, §5.2 C2 C3, §5.6).

All randomness flows from one ``numpy.random.Generator`` seeded with the recorded seed, drawn in
a fixed order (population, then ads in scenario order, then days), so a seed reproduces bytes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal

import numpy as np

from bayesian_marketing.simulate.scenario import (
    AdSpec,
    Named,
    OrderValue,
    Phase,
    Population,
    Scenario,
    Truth,
)

SECONDS_PER_DAY = 86_400
CENTS = 100


@dataclass(frozen=True)
class WorldAd:
    """One ad with its true parameters."""

    variant: str
    platform: str
    account: Named
    campaign: Named
    ad_set: Named
    ad: Named
    utm_campaign: str
    phases: list[Phase]
    ctr: float
    cvr: float
    cpc: float
    cpm: float
    ov_dist: str
    ov_amount: float | None  # fixed order value
    ov_log_median: float | None  # lognormal
    ov_sigma: float | None

    @property
    def order_value_mean(self) -> float:
        if self.ov_dist == "fixed":
            return float(self.ov_amount)  # type: ignore[arg-type]
        return math.exp(self.ov_log_median + self.ov_sigma**2 / 2)  # type: ignore[operator]


@dataclass
class Conversion:
    ad_index: int
    click_day: int
    click_second: int
    lag_days: int
    order_second: int  # seconds after midnight on day click_day + lag_days
    value: float
    credit: float = 1.0

    @property
    def elapsed_seconds(self) -> int:
        return self.lag_days * SECONDS_PER_DAY + self.order_second - self.click_second


@dataclass
class AdDays:
    spend_cents: list[int]
    impressions: list[int]
    clicks: list[int]
    conversions: list[Conversion] = field(default_factory=list)


@dataclass
class World:
    ads: list[WorldAd]
    days: list[AdDays]
    params: dict[str, object]


def _logit(p: float) -> float:
    return math.log(p / (1 - p))


def _expit(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def _order_value(ov: OrderValue, rng: np.random.Generator) -> tuple[float | None, float | None]:
    """(ad log median, sigma) for a log-normal ad; (None, None) for fixed."""
    if ov.dist == "fixed":
        return None, None
    log_median = math.log(ov.median) + float(rng.normal(0.0, ov.ad_log_sd))  # type: ignore[arg-type]
    return log_median, ov.sigma


def _resolve_cost(truth: Truth, phases: list[Phase]) -> tuple[float, float]:
    """(cpc, cpm) from the truth, or from the fixed spend and clicks totals."""
    if truth.cpc is not None:
        cpc = truth.cpc
    elif truth.cpm is not None:
        cpc = truth.cpm / (1000 * truth.ctr)
    elif all(p.clicks is not None for p in phases):
        spend = sum(_phase_spend(p) for p in phases)
        clicks = sum(p.clicks for p in phases)  # type: ignore[misc]
        cpc = float(spend) / clicks
    else:
        raise ValueError("truth needs cpm or cpc unless every phase fixes clicks")
    cpm = truth.cpm if truth.cpm is not None else cpc * 1000 * truth.ctr
    return cpc, cpm


def _phase_spend(p: Phase) -> Decimal:
    return p.spend if p.spend is not None else p.spend_per_day * p.days  # type: ignore[operator]


def _explicit_ad(a: AdSpec, sc: Scenario, rng: np.random.Generator) -> WorldAd:
    ov = a.order_value or sc.order_value
    log_median, sigma = _order_value(ov, rng)
    cpc, cpm = _resolve_cost(a.truth, a.phases)
    return WorldAd(
        variant=a.variant,
        platform=a.platform,
        account=a.account,
        campaign=a.campaign,
        ad_set=a.ad_set,
        ad=a.ad,
        utm_campaign=a.utm_campaign,
        phases=a.phases,
        ctr=a.truth.ctr,
        cvr=a.truth.cvr,
        cpc=cpc,
        cpm=cpm,
        ov_dist=ov.dist,
        ov_amount=float(ov.amount) if ov.amount is not None else None,
        ov_log_median=log_median,
        ov_sigma=sigma,
    )


def _population(
    pop: Population, sc: Scenario, rng: np.random.Generator
) -> tuple[list[WorldAd], dict[str, object]]:
    mu = np.array([_logit(pop.ctr_median), _logit(pop.cvr_median)])
    sd_ad = np.array(pop.logit_sd.ad)
    corr = np.array([[1.0, pop.ad_rho], [pop.ad_rho, 1.0]])
    cov = np.diag(sd_ad) @ corr @ np.diag(sd_ad)
    ads: list[WorldAd] = []
    ad_latents: list[np.ndarray] = []
    phase = Phase(days=sc.n_days, spend_per_day=pop.spend_per_day)
    p = pop.id_prefix
    names = pop.names
    for i in range(1, pop.accounts + 1):
        acc_off = rng.normal(0.0, pop.logit_sd.account)
        account = Named(id=f"{p}acc{i}", name=names.account.format(i=i))
        for j in range(1, pop.campaigns_per_account + 1):
            camp_off = rng.normal(0.0, pop.logit_sd.campaign)
            cid = f"{account.id}_c{j}"
            campaign = Named(id=cid, name=names.campaign.format(i=i, j=j))
            ad_set = Named(id=f"{cid}_as1", name=names.ad_set.format(i=i, j=j))
            for k in range(1, pop.ads_per_campaign + 1):
                ad_dev = rng.multivariate_normal(np.zeros(2), cov)
                ad_latents.append(ad_dev)
                lat = mu + acc_off + camp_off + ad_dev
                cpm = math.exp(math.log(pop.cpm_median) + float(rng.normal(0.0, pop.cpm_log_sd)))
                ctr = _expit(float(lat[0]))
                log_median, sigma = _order_value(sc.order_value, rng)
                aid = f"{cid}_ad{k:02d}"
                ads.append(
                    WorldAd(
                        variant=aid,
                        platform=pop.platform,
                        account=account,
                        campaign=campaign,
                        ad_set=ad_set,
                        ad=Named(id=aid, name=names.ad.format(i=i, j=j, k=k)),
                        utm_campaign=aid,
                        phases=[phase],
                        ctr=ctr,
                        cvr=_expit(float(lat[1])),
                        cpc=cpm / (1000 * ctr),
                        cpm=cpm,
                        ov_dist=sc.order_value.dist,
                        ov_amount=float(sc.order_value.amount)
                        if sc.order_value.amount is not None
                        else None,
                        ov_log_median=log_median,
                        ov_sigma=sigma,
                    )
                )
    lat_arr = np.array(ad_latents)
    realized = float(np.corrcoef(lat_arr[:, 0], lat_arr[:, 1])[0, 1]) if len(ads) > 2 else None
    return ads, {"realized_ad_rho": realized}


def _split_cents(total_cents: int, days: int) -> list[int]:
    base, rem = divmod(total_cents, days)
    return [base + (1 if d < rem else 0) for d in range(days)]


def _spread(rng: np.random.Generator, total: int, weights: list[int]) -> list[int]:
    w = np.array(weights, dtype=float)
    probs = w / w.sum() if w.sum() > 0 else np.full(len(weights), 1.0 / len(weights))
    return [int(x) for x in rng.multinomial(total, probs)]


def _hyper(rng: np.random.Generator, colors: list[int], n: int) -> list[int]:
    if n == 0:
        return [0] * len(colors)
    return [int(x) for x in rng.multivariate_hypergeometric(colors, n)]


def lag_p(median_days: int) -> float:
    """Geometric success probability on {0, 1, ...} whose median is ``median_days``."""
    return 1.0 - 2.0 ** (-1.0 / (median_days + 0.5))


def _conversion(
    rng: np.random.Generator, ad_index: int, ad: WorldAd, day: int, lag: int | None, p: float
) -> Conversion:
    click_s = int(rng.integers(0, SECONDS_PER_DAY))
    lag_days = int(rng.geometric(p)) - 1 if lag is None else lag
    lo = click_s if lag_days == 0 else 0
    order_s = int(rng.integers(lo, SECONDS_PER_DAY))
    if ad.ov_dist == "fixed":
        value = float(ad.ov_amount)  # type: ignore[arg-type]
    else:
        value = float(rng.lognormal(ad.ov_log_median, ad.ov_sigma))  # type: ignore[arg-type]
    return Conversion(ad_index, day, click_s, lag_days, order_s, round(value, 2))


def _simulate_ad(rng: np.random.Generator, idx: int, ad: WorldAd, lag_prob: float) -> AdDays:
    out = AdDays([], [], [])
    day0 = 0
    for ph in ad.phases:
        spend = _split_cents(int(_phase_spend(ph) * CENTS), ph.days)
        if ph.impressions is not None:
            imps = _spread(rng, ph.impressions, spend)
        elif ph.clicks is not None:
            extra = int(rng.negative_binomial(ph.clicks, ad.ctr)) if ph.clicks > 0 else 0
            imps = _spread(rng, ph.clicks + extra, spend)
        else:
            imps = [int(rng.poisson(s / CENTS * 1000 / ad.cpm)) for s in spend]
        if ph.clicks is not None:
            clicks = _hyper(rng, imps, ph.clicks)
        else:
            clicks = [int(rng.binomial(n, ad.ctr)) for n in imps]
        if ph.conversions is not None:
            convs = _hyper(rng, clicks, ph.conversions)
            lag: int | None = 0  # fixed totals are observed in full (Manuscript counts)
        else:
            convs = [int(rng.binomial(n, ad.cvr)) for n in clicks]
            lag = None
        for d, n in enumerate(convs):
            for _ in range(n):
                out.conversions.append(_conversion(rng, idx, ad, day0 + d, lag, lag_prob))
        out.spend_cents += spend
        out.impressions += imps
        out.clicks += clicks
        day0 += ph.days
    return out


def draw_world(sc: Scenario, rng: np.random.Generator) -> World:
    ads = [_explicit_ad(a, sc, rng) for a in sc.ads]
    params: dict[str, object] = {}
    if sc.population is not None:
        pop_ads, pop_params = _population(sc.population, sc, rng)
        ads += pop_ads
        params.update(pop_params)
    p = lag_p(sc.lag.median_days)
    params["lag_geometric_p"] = p
    days = [_simulate_ad(rng, i, ad, p) for i, ad in enumerate(ads)]
    return World(ads=ads, days=days, params=params)
