"""The backend-agnostic joint model plan (§5.2 C1-C8, §5.6 C2).

``compile_model`` turns a FunnelSpec, a PriorSet and FunnelData into a :class:`ModelPlan`: the
stage choices, every hyperprior as a number with the prior record it came from, and the data hash.
:func:`build_arrays` turns FunnelData into the plain numpy arrays the likelihood needs. Neither
names a sampling backend (C5); ``inference.sampler_numpyro`` reads both.

Prior resolution, per parameter path the spec needs:

1. the PriorSet record. An unapproved record raises G8 on client data (I10); on synthetic data it
   is allowed and counted in ``unapproved`` (D23 item 2).
2. else the registry's ``priors/default`` ``pending_records`` placeholder (D22 item 4). These are
   unapproved, so they are always counted in ``unapproved`` and disclosed downstream
   (``route.unapproved_priors``). See the P5 manifest, open question 1.

The LKJ concentration falls back to ``bounds/coupling/lkj_eta`` (an approved §14 default) when the
PriorSet has no ``lkj_concentration`` record.

Hyperpriors are read off the records:

- population logit means: Normal with the exact mean and sd of logit(p) for p ~ the Beta record;
- population log CPM: Normal with the exact mean and sd of log(PER_MILLE / r) for r ~ the Gamma
  record on impressions per dollar; the CPM pooling scale is half-normal with that sd;
- order value: ``order_value_log_mean`` for the population log mean, ``order_value_log_sd`` for the
  within-ad sd of log order value and for the between-ad pooling scale;
- ``logit_scale_ctr`` / ``logit_scale_cvr`` for the ad-level scales, the scales of levels above the
  ad, and the random-walk innovation scales;
- ``gamma_obs_shape`` for φ (C6).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.special import digamma, polygamma

from bayesian_marketing.core import (
    FunnelData,
    FunnelSpec,
    GateFailure,
    GateResult,
    PriorSet,
    inputs_hash,
    make_id,
    registries,
    utcnow,
)
from bayesian_marketing.derived_metrics.dist import PER_MILLE

PENDING = "priors/default/pending_records"
LEVEL_ORDER = ("campaign", "account")
SUPPORTED = {
    "delivery": ("poisson",),
    "ctr": ("binomial",),
    "cvr": ("binomial", "gamma_obs"),
    "value": ("lognormal", "compound_gamma"),
}
INTEGRAL_TOL = 1e-9
"""A reported conversion count within this of an integer is a count (binomial), else fractional."""


@dataclass(frozen=True)
class PriorTerm:
    path: str
    family: str
    params: dict[str, float]
    prior_id: str
    approved: bool
    source: str  # "prior_set" | "registry_pending" | "registry_bound"


@dataclass(frozen=True)
class ModelPlan:
    plan_id: str
    spec: FunnelSpec
    terms: dict[str, PriorTerm]  # parameter path -> term
    hyper: dict[str, float]
    levels: list[str]  # hierarchy levels above the ad that have more than one group
    data_hash: str
    synthetic: bool
    n_days: int

    @property
    def stages(self) -> dict[str, str]:
        return {s.name: s.likelihood for s in self.spec.stages}

    @property
    def pooled(self) -> dict[str, bool]:
        return {s.name: s.pooled for s in self.spec.stages}

    @property
    def unapproved(self) -> list[str]:
        return sorted(p for p, t in self.terms.items() if not t.approved)

    @property
    def prior_ids(self) -> dict[str, str]:
        return {p: t.prior_id for p, t in self.terms.items()}

    def to_json(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "spec": self.spec.model_dump(mode="json"),
            "terms": {p: t.__dict__ for p, t in self.terms.items()},
            "hyper": self.hyper,
            "levels": self.levels,
            "data_hash": self.data_hash,
            "synthetic": self.synthetic,
            "n_days": self.n_days,
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> ModelPlan:
        return cls(
            plan_id=d["plan_id"],
            spec=FunnelSpec.model_validate(d["spec"]),
            terms={p: PriorTerm(**t) for p, t in d["terms"].items()},
            hyper={k: float(v) for k, v in d["hyper"].items()},
            levels=list(d["levels"]),
            data_hash=d["data_hash"],
            synthetic=bool(d["synthetic"]),
            n_days=int(d["n_days"]),
        )


# ---------------------------------------------------------------------------------------- priors


def _g8(path: str, prior_id: str, params: Any) -> GateFailure:
    res = GateResult(
        gate="G8",
        passed=False,
        blocking=True,
        reasons=[f"prior {prior_id} for {path!r} is not approved (I10)"],
        inputs_hash=inputs_hash(params),
        checked_at=utcnow(),
    )
    return GateFailure(res)


def resolve_term(priors: PriorSet, path: str, synthetic: bool) -> PriorTerm:
    rec = priors.records.get(path)
    if rec is not None:
        if not rec.approved and not synthetic:
            raise _g8(path, rec.prior_id, rec.params)
        return PriorTerm(
            path=path,
            family=rec.family,
            params={k: float(v) for k, v in rec.params.items()},
            prior_id=rec.prior_id,
            approved=rec.approved,
            source="prior_set",
        )
    pending = registries.load("priors/default").get("pending_records", {})
    if path not in pending:
        raise KeyError(f"PriorSet has no record for {path!r} and the registry no placeholder")
    rec_d = pending[path]
    params = {k: float(v) for k, v in rec_d["params"].items()}
    return PriorTerm(
        path=path,
        family=str(rec_d["family"]),
        params=params,
        prior_id=make_id("pr_", {"pending": path, "params": params}),
        approved=False,
        source="registry_pending",
    )


def _need(term: PriorTerm, family: str, *keys: str) -> None:
    if term.family != family or any(k not in term.params for k in keys):
        raise ValueError(
            f"prior {term.path!r} must be {family} with {keys}, got {term.family} {term.params}"
        )


def logit_beta_moments(a: float, b: float) -> tuple[float, float]:
    """Exact mean and sd of logit(p) for p ~ Beta(a, b)."""
    return float(digamma(a) - digamma(b)), float(math.sqrt(polygamma(1, a) + polygamma(1, b)))


def log_cpm_moments(shape: float, rate: float) -> tuple[float, float]:
    """Exact mean and sd of log(PER_MILLE / r) for impressions per dollar r ~ Gamma(shape, rate)."""
    return (
        float(math.log(PER_MILLE) - (digamma(shape) - math.log(rate))),
        float(math.sqrt(polygamma(1, shape))),
    )


def resolve_plan_priors(
    spec: FunnelSpec, priors: PriorSet, synthetic: bool
) -> tuple[dict[str, PriorTerm], dict[str, float]]:
    stages = {s.name: s.likelihood for s in spec.stages}
    pooled = {s.name: s.pooled for s in spec.stages}
    terms: dict[str, PriorTerm] = {}
    hyper: dict[str, float] = {}

    def term(path: str) -> PriorTerm:
        t = resolve_term(priors, path, synthetic)
        terms[path] = t
        return t

    for stage in ("ctr", "cvr"):
        t = term(stage)
        _need(t, "beta", "a", "b")
        hyper[f"{stage}.mu_loc"], hyper[f"{stage}.mu_scale"] = logit_beta_moments(
            t.params["a"], t.params["b"]
        )
        s = term(f"logit_scale_{stage}")
        _need(s, "halfnormal", "scale")
        hyper[f"{stage}.scale"] = s.params["scale"]

    if "lkj_concentration" in priors.records:
        t = term("lkj_concentration")
        _need(t, "fixed", "value")
        hyper["lkj_eta"] = t.params["value"]
    else:
        hyper["lkj_eta"] = float(registries.resolve("bounds/coupling/lkj_eta@v1"))

    t = term("cpm_impressions_per_dollar")
    _need(t, "gamma", "shape", "rate")
    loc, sd = log_cpm_moments(t.params["shape"], t.params["rate"])
    hyper["cpm.mu_loc"], hyper["cpm.mu_scale"] = loc, sd
    hyper["cpm.scale"] = sd if pooled["delivery"] else 0.0

    t = term("order_value_log_mean")
    _need(t, "normal", "loc", "scale")
    hyper["value.mu_loc"], hyper["value.mu_scale"] = t.params["loc"], t.params["scale"]
    s = term("order_value_log_sd")
    _need(s, "halfnormal", "scale")
    hyper["value.sd_scale"] = s.params["scale"]
    hyper["value.scale"] = s.params["scale"] if pooled["value"] else 0.0
    if stages["value"] == "compound_gamma":
        hyper["value.k"] = float(registries.resolve("bounds/value/compound_gamma_k@v1"))

    if stages["cvr"] == "gamma_obs":
        t = term("gamma_obs_shape")
        _need(t, "halfnormal", "scale")
        hyper["phi.scale"] = t.params["scale"]
    return terms, hyper


# ----------------------------------------------------------------------------------- validation


def check_spec(spec: FunnelSpec) -> None:
    """Stage set and likelihoods the joint model implements. Coupling is checked by the caller."""
    names = [s.name for s in spec.stages]
    if sorted(names) != sorted(SUPPORTED) or len(set(names)) != len(names):
        raise ValueError(f"the joint model needs each of the stages {sorted(SUPPORTED)} once")
    for s in spec.stages:
        if s.likelihood not in SUPPORTED[s.name]:
            raise ValueError(
                f"stage {s.name!r} likelihood {s.likelihood!r} is not implemented by the joint "
                f"model; supported: {SUPPORTED[s.name]}"
            )
        if s.name in ("ctr", "cvr") and not s.pooled:
            raise ValueError("CTR/CVR coupling (C1) needs pooled ctr and cvr stages")
    if "ad" not in spec.hierarchy:
        raise ValueError("the joint model's hierarchy must include the ad level")


def _levels(spec: FunnelSpec, data: FunnelData) -> list[str]:
    out = []
    for level in LEVEL_ORDER:
        if level not in spec.hierarchy:
            continue
        groups = {data.parents.get(ad, {}).get(level) for ad in data.entities}
        if None in groups:
            raise ValueError(f"hierarchy level {level!r} is missing from FunnelData.parents")
        if len(groups) > 1:
            out.append(level)
    return out


def build_plan(spec: FunnelSpec, priors: PriorSet, data: FunnelData) -> ModelPlan:
    check_spec(spec)
    terms, hyper = resolve_plan_priors(spec, priors, data.synthetic)
    levels = _levels(spec, data)
    data_hash = inputs_hash(data)
    plan_id = inputs_hash(
        {"spec": spec, "terms": {p: t.__dict__ for p, t in terms.items()}, "data": data_hash}
    )[:16]
    return ModelPlan(
        plan_id=plan_id,
        spec=spec,
        terms=terms,
        hyper=hyper,
        levels=levels,
        data_hash=data_hash,
        synthetic=data.synthetic,
        n_days=len(data.dates),
    )


# --------------------------------------------------------------------------------------- arrays


@dataclass
class ModelArrays:
    """Likelihood inputs, ``[ad]`` or ``[ad, day]``. Days with zero spend carry mask 0 (C4)."""

    n_ads: int
    n_days: int
    spend: np.ndarray  # [ad, day]
    impressions: np.ndarray
    clicks: np.ndarray
    day_mask: np.ndarray  # 1 where spend > 0
    conv: np.ndarray  # [ad, day] integer conversions observed by the binomial (0 elsewhere)
    conv_mask: np.ndarray  # 1 where the binomial observes the day
    mature: np.ndarray  # [ad, day] F(as_of - d)
    gobs_y: np.ndarray  # [ad] summed fractional reported conversions
    gobs_mask: np.ndarray  # [ad, day] days whose reported conversions gamma_obs observes
    gobs_ad: np.ndarray  # [ad] 1 where gamma_obs observes a positive total
    value_n: np.ndarray  # [ad] lognormal: order count; compound gamma: conversions
    value_mean: np.ndarray  # [ad] lognormal: mean log order value
    value_ss: np.ndarray  # [ad] lognormal: sum of squared deviations of log order value
    value_rev: np.ndarray  # [ad] compound gamma: summed revenue
    value_mask: np.ndarray  # [ad] 1 where the value stage observes the ad
    groups: dict[str, np.ndarray] = field(default_factory=dict)  # level -> [ad] group index
    n_groups: dict[str, int] = field(default_factory=dict)
    params: dict[str, float] = field(default_factory=dict)  # per-ad counts and flags for derive

    def as_dict(self) -> dict[str, np.ndarray]:
        out = {
            k: np.asarray(getattr(self, k), dtype=float)
            for k in (
                "spend",
                "impressions",
                "clicks",
                "day_mask",
                "conv",
                "conv_mask",
                "mature",
                "gobs_y",
                "gobs_mask",
                "gobs_ad",
                "value_n",
                "value_mean",
                "value_ss",
                "value_rev",
                "value_mask",
            )
        }
        for level, idx in self.groups.items():
            out[f"group.{level}"] = np.asarray(idx, dtype=np.int32)
        return out


def _integral(x: float) -> bool:
    return abs(x - round(x)) <= INTEGRAL_TOL


def build_arrays(plan: ModelPlan, data: FunnelData) -> ModelArrays:
    """Arrays for the likelihood plus the per-ad counts and flags derive reads (P3 keys)."""
    if inputs_hash(data) != plan.data_hash:
        raise ValueError("FunnelData differs from the data this model was compiled for")
    stages = plan.stages
    n_a, n_d = len(data.entities), len(data.dates)
    spend = np.asarray(data.spend, dtype=float).reshape(n_a, n_d)
    imps = np.asarray(data.impressions, dtype=float).reshape(n_a, n_d)
    clicks = np.asarray(data.clicks, dtype=float).reshape(n_a, n_d)
    mature = np.asarray(data.mature_fraction, dtype=float).reshape(n_a, n_d)
    day_mask = (spend > 0).astype(float)
    conv = np.zeros((n_a, n_d))
    conv_mask = np.zeros((n_a, n_d))
    gobs_mask = np.zeros((n_a, n_d))
    gobs_y = np.zeros(n_a)
    value_n = np.zeros(n_a)
    value_mean = np.zeros(n_a)
    value_ss = np.zeros(n_a)
    value_rev = np.zeros(n_a)
    params: dict[str, float] = {}
    for i, ad in enumerate(data.entities):
        modeled = False
        lag = False
        n_conv = 0.0
        cg_n = 0.0
        cg_r = 0.0
        for d in range(n_d):
            if not day_mask[i, d]:
                continue  # structural zero: no likelihood term (C4)
            obs = data.conversions_observed[i][d]
            rep = data.conversions_reported[i][d]
            c: float | None = None
            if obs is not None:
                c = float(obs)
                conv[i, d], conv_mask[i, d] = c, 1.0
            elif rep is not None:
                c = float(rep)
                modeled = True
                if stages["cvr"] == "gamma_obs" and not _integral(c):
                    gobs_y[i] += c
                    gobs_mask[i, d] = 1.0
                elif _integral(c):
                    conv[i, d], conv_mask[i, d] = round(c), 1.0
                else:
                    raise ValueError(
                        f"entity {ad!r} on {data.dates[d].isoformat()}: fractional reported "
                        f"conversions {c} cannot enter a binomial; use the gamma_obs cvr stage (C6)"
                    )
            if c is None:
                continue
            n_conv += c
            if mature[i, d] < 1.0 and clicks[i, d] > 0:
                lag = True
            r = data.revenue_reported[i][d]
            if r is not None and c > 0:
                cg_n += c
                cg_r += float(r)
        values = np.asarray(data.order_values.get(ad, []), dtype=float)
        if stages["value"] == "lognormal":
            if values.size:
                logs = np.log(values)
                value_n[i] = float(values.size)
                value_mean[i] = float(logs.mean())
                value_ss[i] = float(((logs - logs.mean()) ** 2).sum())
            orders = float(values.size)
        else:
            if cg_n > 0 and cg_r > 0:
                value_n[i], value_rev[i] = cg_n, cg_r
            orders = float(value_n[i])
        params.update(
            {
                f"{ad}.n.impressions": float((imps[i] * day_mask[i]).sum()),
                f"{ad}.n.clicks": float((clicks[i] * day_mask[i]).sum()),
                f"{ad}.n.conversions": n_conv,
                f"{ad}.n.orders": orders,
                f"{ad}.spend": float((spend[i] * day_mask[i]).sum()),
                # The NUTS likelihood uses lag exactly (§5.6 C2): no approximation to disclose.
                f"{ad}.flag.lag_adjusted": 0.0,
                f"{ad}.flag.lag_exact": 1.0 if lag else 0.0,
                f"{ad}.flag.platform_modeled": 1.0 if modeled else 0.0,
                f"{ad}.flag.aov_orders_file": 1.0 if stages["value"] == "lognormal" else 0.0,
            }
        )
        if stages["value"] == "compound_gamma":
            params[f"{ad}.flag.aov_source"] = 2.0  # placeholder k disclosed by derive
            params[f"{ad}.aov.compound_gamma_k"] = plan.hyper["value.k"]
    groups: dict[str, np.ndarray] = {}
    n_groups: dict[str, int] = {}
    for level in plan.levels:
        names = sorted({data.parents[ad][level] for ad in data.entities})
        groups[level] = np.asarray([names.index(data.parents[ad][level]) for ad in data.entities])
        n_groups[level] = len(names)
    gobs_ad = (gobs_y > 0).astype(float)
    return ModelArrays(
        n_ads=n_a,
        n_days=n_d,
        spend=spend,
        impressions=imps,
        clicks=clicks,
        day_mask=day_mask,
        conv=conv,
        conv_mask=conv_mask,
        mature=mature,
        gobs_y=gobs_y,
        gobs_mask=gobs_mask * gobs_ad[:, None],
        gobs_ad=gobs_ad,
        value_n=value_n,
        value_mean=value_mean,
        value_ss=value_ss,
        value_rev=value_rev,
        value_mask=(value_n > 0).astype(float)
        if stages["value"] == "lognormal"
        else (value_rev > 0).astype(float),
        groups=groups,
        n_groups=n_groups,
        params=params,
    )
