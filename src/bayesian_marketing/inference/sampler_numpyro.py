"""§7.3 the NUTS sampler. Piece P5.

The joint model (§5.2 C1-C7), non-centered throughout:

- ad-level ``(logit ctr, logit cvr) = mu + Σ_levels tau_l·z_l[group] + z_ad @ (diag(sigma)·L)ᵀ``
  with ``L ~ LKJCholesky(2, eta)``; ``rho = L[1, 0]`` is the CTR/CVR correlation;
- ``random_walk`` adds one daily Gaussian walk per stage on the logit scale, shared by the ads and
  pinned at 0 on the first day; per-ad CTR and CVR are reported at the last day of the window;
- delivery: impressions on a day ~ Poisson(spend · PER_MILLE / CPM), log CPM partially pooled;
- clicks ~ Binomial(impressions, ctr); conversions ~ Binomial(clicks, cvr · F) exactly (§5.6 C2);
- gamma_obs (C6): an ad's fractional reported conversions summed over days ~ Gamma(shape φ·m,
  rate φ) with m = Σ clicks·F·cvr (the per-day terms share rate φ, so their sum is exact);
- value: log-normal order values per ad through their sufficient statistics, ad log means
  partially pooled; or compound gamma on summed daily revenue, Gamma(k·N, k/μ) (C2).

The state's parquet has one column per ``<ad>.<parameter>`` (ctr, cvr, cpm, aov), ``rho`` and
``chain`` (chain index per row; rows are chain-major). ``posterior.params`` carries P3's per-ad
keys (``n.*``, ``spend``, ``flag.*``), ``currency.code``, ``route.*``, ``seed``,
``sampler.chains``, ``sampler.draws`` and ``diagnostics.n_divergences``. The state is not saved
here: diagnostics and G3 decide (P6).
"""

from __future__ import annotations

import math
from typing import Any, Protocol

import jax
import jax.numpy as jnp
import numpy as np
import numpyro
import numpyro.distributions as dist
import pandas as pd
from jax.scipy.special import expit
from numpyro.infer import MCMC, NUTS, Predictive

from bayesian_marketing.core import (
    CompiledModel,
    DiagnosticsReport,
    FitConfig,
    FunnelData,
    FunnelSpec,
    FunnelState,
    PriorSet,
    inputs_hash,
    make_id,
    registries,
    utcnow,
)
from bayesian_marketing.core.money import DistributionSpec
from bayesian_marketing.derived_metrics.dist import PER_MILLE, encode_currency, summary_of_draws
from bayesian_marketing.funnel_state.store import states_dir
from bayesian_marketing.model_spec.compile import load_plan
from bayesian_marketing.model_spec.plan import (
    ModelArrays,
    ModelPlan,
    build_arrays,
    resolve_plan_priors,
)

jax.config.update("jax_enable_x64", True)  # counts reach 1e6+; float32 Poisson/Binomial lose it

PARAMS = ("ctr", "cvr", "cpm", "aov")
THRESHOLDS_REF = "diagnostics/thresholds@v1"
PROB_CEILING_GAP = 1e-7
"""Numeric guard: a binomial probability is kept at most 1 - this, so its log(1 - p) stays finite.
Not a modelling bound (a CVR times maturity this close to 1 is refused by no data)."""
TAIL_PROBS = (0.05, 0.95)
"""Tail-ESS quantiles, the ArviZ convention."""


class PosteriorSampler(Protocol):
    def fit(
        self, model: CompiledModel, data: FunnelData, config: FitConfig
    ) -> tuple[FunnelState, DiagnosticsReport]: ...


def default_config(seed: int) -> FitConfig:
    """Sampler settings from ``diagnostics.yaml``."""
    s = registries.resolve("diagnostics/sampler@v1")
    return FitConfig(
        chains=int(s["chains"]),
        draws=int(s["draws"]),
        warmup=int(s["warmup"]),
        target_accept=float(s["target_accept"]),
        seed=seed,
    )


# ----------------------------------------------------------------------------------------- model


def make_model(plan: ModelPlan, n_ads: int, n_days: int, n_groups: dict[str, int]):
    """The NumPyro model for a plan. Shapes are fixed; data arrays are arguments."""
    h = plan.hyper
    stages = plan.stages
    eps = float(jnp.finfo(jnp.float64).tiny)

    def model(d: dict[str, Any]) -> None:
        mu = numpyro.sample(
            "mu",
            dist.Normal(
                jnp.array([h["ctr.mu_loc"], h["cvr.mu_loc"]]),
                jnp.array([h["ctr.mu_scale"], h["cvr.mu_scale"]]),
            ),
        )
        scales = jnp.array([h["ctr.scale"], h["cvr.scale"]])
        sigma = numpyro.sample("sigma", dist.HalfNormal(scales))
        corr_l = numpyro.sample("L_corr", dist.LKJCholesky(2, h["lkj_eta"]))
        numpyro.deterministic("rho", corr_l[1, 0])
        lat = jnp.broadcast_to(mu, (n_ads, 2))
        for level in plan.levels:
            tau = numpyro.sample(f"tau_{level}", dist.HalfNormal(scales))
            z_l = numpyro.sample(f"z_{level}", dist.Normal(0.0, 1.0).expand([n_groups[level], 2]))
            lat = lat + (tau * z_l)[d[f"group.{level}"]]
        z_ad = numpyro.sample("z_ad", dist.Normal(0.0, 1.0).expand([n_ads, 2]))
        lat = lat + z_ad @ (jnp.diag(sigma) @ corr_l).T
        if plan.spec.dynamics == "random_walk":
            tau_rw = numpyro.sample("tau_rw", dist.HalfNormal(scales))
            z_rw = numpyro.sample("z_rw", dist.Normal(0.0, 1.0).expand([n_days - 1, 2]))
            walk = jnp.concatenate([jnp.zeros((1, 2)), jnp.cumsum(tau_rw * z_rw, axis=0)])
        else:
            walk = jnp.zeros((n_days, 2))
        lat_day = lat[:, None, :] + walk[None, :, :]
        numpyro.deterministic("ctr", expit(lat_day[:, -1, 0]))
        cvr_day = expit(lat_day[..., 1])
        numpyro.deterministic("cvr", cvr_day[:, -1])

        # Delivery (C3): impressions per day ~ Poisson(spend * PER_MILLE / CPM).
        m_cpm = numpyro.sample("cpm_mu", dist.Normal(h["cpm.mu_loc"], h["cpm.mu_scale"]))
        z_cpm = numpyro.sample("z_cpm", dist.Normal(0.0, 1.0).expand([n_ads]))
        if h["cpm.scale"] > 0:
            s_cpm = numpyro.sample("cpm_scale", dist.HalfNormal(h["cpm.scale"]))
            log_cpm = m_cpm + s_cpm * z_cpm
        else:  # unpooled: each ad's log CPM from the prior directly
            log_cpm = h["cpm.mu_loc"] + h["cpm.mu_scale"] * z_cpm + 0.0 * m_cpm
        numpyro.deterministic("cpm", jnp.exp(log_cpm))
        mask = d["day_mask"] > 0
        rate = jnp.where(mask, d["spend"] * PER_MILLE * jnp.exp(-log_cpm)[:, None], 1.0)
        numpyro.sample("impressions", dist.Poisson(rate).mask(mask), obs=d["impressions"])
        numpyro.sample(
            "clicks",
            dist.Binomial(total_count=d["impressions"], logits=lat_day[..., 0]).mask(mask),
            obs=d["clicks"],
        )

        # CVR with the exact lag likelihood (§5.6 C2).
        cmask = d["conv_mask"] > 0
        p = jnp.clip(cvr_day * d["mature"], eps, 1.0 - PROB_CEILING_GAP)
        numpyro.sample(
            "conversions",
            dist.Binomial(total_count=d["clicks"], probs=jnp.where(cmask, p, 0.5)).mask(cmask),
            obs=d["conv"],
        )
        if stages["cvr"] == "gamma_obs":
            phi = numpyro.sample("phi", dist.HalfNormal(h["phi.scale"]))
            m = jnp.sum(d["clicks"] * d["mature"] * cvr_day * d["gobs_mask"], axis=1)
            gmask = d["gobs_ad"] > 0
            m = jnp.where(gmask, jnp.maximum(m, eps), 1.0)
            y = jnp.where(gmask, d["gobs_y"], 1.0)
            numpyro.sample("reported", dist.Gamma(phi * m, phi).mask(gmask), obs=y)

        # Value (C2).
        m_v = numpyro.sample("value_mu", dist.Normal(h["value.mu_loc"], h["value.mu_scale"]))
        z_v = numpyro.sample("z_value", dist.Normal(0.0, 1.0).expand([n_ads]))
        if h["value.scale"] > 0:
            s_v = numpyro.sample("value_scale", dist.HalfNormal(h["value.scale"]))
            mu_v = m_v + s_v * z_v
        else:
            mu_v = h["value.mu_loc"] + h["value.mu_scale"] * z_v + 0.0 * m_v
        vmask = d["value_mask"]
        if stages["value"] == "lognormal":
            # D36 item 2: half-normal truncated below at min_log_sd, so one price point (all
            # orders the same value) does not drive the sd to zero.
            sd_v = numpyro.sample(
                "value_sd",
                dist.TruncatedNormal(0.0, h["value.sd_scale"], low=h["value.min_log_sd"]),
            )
            n = d["value_n"]
            ll = (
                -n * jnp.log(sd_v)
                - 0.5 * n * math.log(2 * math.pi)
                - (d["value_ss"] + n * (d["value_mean"] - mu_v) ** 2) / (2 * sd_v**2)
            )
            numpyro.factor("order_values", jnp.sum(vmask * ll))
            numpyro.deterministic("aov", jnp.exp(mu_v + 0.5 * sd_v**2))
        else:
            k = h["value.k"]
            aov = jnp.exp(mu_v)
            gm = vmask > 0
            shape = jnp.where(gm, k * d["value_n"], 1.0)
            numpyro.sample(
                "revenue",
                dist.Gamma(shape, k / aov).mask(gm),
                obs=jnp.where(gm, d["value_rev"], 1.0),
            )
            numpyro.deterministic("aov", aov)

    return model


def _jnp(arrays: ModelArrays) -> dict[str, Any]:
    return {
        k: jnp.asarray(v, dtype=jnp.int32 if k.startswith("group.") else jnp.float64)
        for k, v in arrays.as_dict().items()
    }


def _mcmc(model, config: FitConfig, num_samples: int | None = None) -> MCMC:
    return MCMC(
        NUTS(model, target_accept_prob=config.target_accept),
        num_warmup=config.warmup,
        num_samples=num_samples or config.draws,
        num_chains=config.chains,
        chain_method="sequential",
        progress_bar=False,
        jit_model_args=True,
    )


# ------------------------------------------------------------------------------------------- fit


def _diagnostics(
    grouped: dict[str, np.ndarray], n_div: int, seed: int, payload: Any
) -> DiagnosticsReport:
    import arviz as az

    rhats, bulk, tail = [], [], []
    for x in grouped.values():
        x = np.asarray(x, dtype=float)
        x = x.reshape(x.shape[0], x.shape[1], -1)
        for j in range(x.shape[2]):
            v = x[:, :, j]
            if np.ptp(v) == 0:
                continue  # a fixed quantity (e.g. L[0,0] = 1) has no mixing to measure
            rhats.append(float(az.rhat(v)))
            bulk.append(float(az.ess(v)))
            tail.append(float(az.ess(v, method="tail", prob=TAIL_PROBS)))
    report_id = "dg_" + inputs_hash(payload)[:8]
    return DiagnosticsReport(
        report_id=report_id,
        sampler="numpyro_nuts",
        rhat_max=max(rhats) if rhats else None,
        ess_bulk_min=min(bulk) if bulk else None,
        ess_tail_min=min(tail) if tail else None,
        n_divergences=n_div,
        ppc={},
        loo=None,
        seeds=[seed],
        thresholds_ref=THRESHOLDS_REF,
    )


class NumpyroSampler:
    """Non-centered NUTS, config from the registry (:func:`default_config`), seeds recorded."""

    def fit(
        self, model: CompiledModel, data: FunnelData, config: FitConfig
    ) -> tuple[FunnelState, DiagnosticsReport]:
        plan = load_plan(model)
        arrays = build_arrays(plan, data)
        fn = make_model(plan, arrays.n_ads, arrays.n_days, arrays.n_groups)
        mcmc = _mcmc(fn, config)
        mcmc.run(jax.random.PRNGKey(config.seed), _jnp(arrays), extra_fields=("diverging",))
        grouped = {k: np.asarray(v) for k, v in mcmc.get_samples(group_by_chain=True).items()}
        n_div = int(np.asarray(mcmc.get_extra_fields()["diverging"]).sum())

        n_chains, n_draws = grouped["rho"].shape[:2]
        columns: dict[str, np.ndarray] = {}
        for name in PARAMS:
            x = grouped[name].reshape(n_chains * n_draws, arrays.n_ads)
            for i, ad in enumerate(data.entities):
                columns[f"{ad}.{name}"] = x[:, i].astype(float)
        columns["rho"] = grouped["rho"].reshape(-1).astype(float)
        columns["chain"] = np.repeat(np.arange(n_chains), n_draws).astype(np.int64)
        bad = [k for k, v in columns.items() if not np.all(np.isfinite(v))]
        if bad:
            raise ValueError(f"non-finite posterior draws in {bad}")

        params: dict[str, float] = dict(arrays.params)
        params.update(
            {
                "route.too_few_ads": 0.0,  # NUTS estimates the funnel link (D11 does not apply)
                "route.unapproved_priors": float(len(plan.unapproved)),
                "currency.code": encode_currency(data.currency),
                "seed": float(config.seed),
                "n_draws": float(n_chains * n_draws),
                "sampler.chains": float(n_chains),
                "sampler.draws": float(n_draws),
                "diagnostics.n_divergences": float(n_div),
            }
        )
        payload = {
            "data": plan.data_hash,
            "plan": plan.plan_id,
            "priors": plan.prior_ids,
            "config": config,
            "route": "nuts",
        }
        state_id = make_id("fs_", payload)
        sample_keys = {k: v for k, v in grouped.items() if not k.startswith("z_")}
        report = _diagnostics(sample_keys, n_div, config.seed, {"state": state_id, **payload})

        path = states_dir() / f"{state_id}.samples.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".parquet.tmp")
        pd.DataFrame(columns).to_parquet(tmp)
        tmp.replace(path)
        first = next(iter(columns))
        posterior = DistributionSpec(
            kind="samples",
            family="nuts",
            params=params,
            samples_path=str(path),
            n_samples=n_chains * n_draws,
            summary=summary_of_draws(columns[first]),
        )
        state = FunnelState(
            state_id=state_id,
            spec_version=plan.spec.version,
            route="nuts",
            prior_ids=plan.prior_ids,
            data_window=(min(data.dates), max(data.dates)),
            posterior=posterior,
            diagnostics_id=report.report_id,
            created_at=utcnow(),
            synthetic=data.synthetic,
            data_pull_ids=list(data.pull_ids),
        )
        return state, report


# ------------------------------------------------------------------------------------------- SBC


SBC_SPEND_PER_AD = 100.0
"""SBC design input (not a decision bound): one day's spend per simulated ad."""


def _sbc_plan(spec: FunnelSpec, priors: PriorSet) -> ModelPlan:
    terms, hyper = resolve_plan_priors(spec, priors, synthetic=True)  # SBC data is synthetic
    return ModelPlan(
        plan_id="sbc",
        spec=spec,
        terms=terms,
        hyper=hyper,
        levels=[],
        data_hash="",
        synthetic=True,
        n_days=1,
    )


def _sbc_arrays(n_ads: int, spend: float) -> dict[str, np.ndarray]:
    one = np.ones((n_ads, 1))
    zero = np.zeros(n_ads)
    return {
        "spend": spend * one,
        "impressions": one,
        "clicks": one,
        "day_mask": one,
        "conv": 0 * one,
        "conv_mask": one,
        "mature": one,
        "gobs_y": zero,
        "gobs_mask": 0 * one,
        "gobs_ad": zero,
        "value_n": zero,
        "value_mean": zero,
        "value_ss": zero,
        "value_rev": zero,
        "value_mask": zero,
    }


def _simulate(
    truth: dict[str, np.ndarray], base: dict[str, np.ndarray], rng: np.random.Generator
) -> dict[str, np.ndarray]:
    d = {k: v.copy() for k, v in base.items()}
    rate = d["spend"][:, 0] * PER_MILLE / truth["cpm"]
    imps = rng.poisson(rate)
    clicks = rng.binomial(imps, truth["ctr"])
    conv = rng.binomial(clicks, truth["cvr"])
    d["impressions"][:, 0] = imps
    d["clicks"][:, 0] = clicks
    d["conv"][:, 0] = conv
    n = conv.astype(float)
    mu_v = np.log(truth["aov"]) - 0.5 * truth["value_sd"] ** 2
    sd = float(truth["value_sd"])
    has = n > 0
    mean = np.where(has, rng.normal(mu_v, sd / np.sqrt(np.maximum(n, 1.0))), 0.0)
    ss = np.where(n > 1, sd**2 * rng.chisquare(np.maximum(n - 1, 1.0)), 0.0)
    d["value_n"], d["value_mean"], d["value_ss"] = n, mean, ss
    d["value_mask"] = has.astype(float)
    return d


def _flat(samples: dict[str, np.ndarray], n_ads: int) -> dict[str, np.ndarray]:
    """Parameters ranked by SBC, each as a 1-D draw vector (last axis = draws)."""
    out: dict[str, np.ndarray] = {}
    for name in ("mu", "sigma"):
        for j, stage in enumerate(("ctr", "cvr")):
            out[f"{name}.{stage}"] = samples[name][:, j]
    for name in ("rho", "cpm_mu", "cpm_scale", "value_mu", "value_scale", "value_sd"):
        if name in samples:
            out[name] = samples[name].reshape(-1)
    for name in PARAMS:
        for i in range(n_ads):
            out[f"ad_{i}.{name}"] = samples[name][:, i]
    return out


def sbc_ranks(
    spec: FunnelSpec, priors: PriorSet, n_ads: int, n_fits: int, n_draws: int, seed: int
) -> dict[str, list[int]]:
    """Simulation-based calibration (Talts et al. 2018) of the static log-normal-value model.

    Each fit draws the parameters from the prior, simulates one day of data for ``n_ads`` ads,
    fits one chain with the registry's warmup and draws, thins to ``n_draws`` draws and records
    the rank (0..n_draws) of each true value among them.
    """
    plan = _sbc_plan(spec, priors)
    if plan.stages["value"] != "lognormal" or plan.stages["cvr"] != "binomial":
        raise ValueError("sbc_ranks simulates the binomial-cvr, log-normal-value model")
    if spec.dynamics != "static":
        raise ValueError("sbc_ranks simulates the static model")
    base_cfg = default_config(seed)
    thin = max(1, base_cfg.draws // n_draws)
    cfg = base_cfg.model_copy(update={"chains": 1, "draws": n_draws * thin})
    model = make_model(plan, n_ads, 1, {})
    base = _sbc_arrays(n_ads, SBC_SPEND_PER_AD)
    prior = Predictive(model, num_samples=n_fits)
    key = jax.random.PRNGKey(seed)
    key, k_prior = jax.random.split(key)
    truths = {
        k: np.asarray(v)
        for k, v in prior(k_prior, {k: jnp.asarray(v) for k, v in base.items()}).items()
    }
    rng = np.random.default_rng(seed)
    mcmc = _mcmc(model, cfg)
    ranks: dict[str, list[int]] = {}
    for f in range(n_fits):
        truth = {k: v[f] for k, v in truths.items()}
        d = _simulate(truth, base, rng)
        key, k_fit = jax.random.split(key)
        mcmc.run(k_fit, {k: jnp.asarray(v, dtype=jnp.float64) for k, v in d.items()})
        post = {k: np.asarray(v)[::thin][:n_draws] for k, v in mcmc.get_samples().items()}
        true_flat = _flat({k: np.asarray(v)[None] for k, v in truth.items()}, n_ads)
        for name, draws in _flat(post, n_ads).items():
            ranks.setdefault(name, []).append(int(np.sum(draws < true_flat[name][0])))
    return ranks
