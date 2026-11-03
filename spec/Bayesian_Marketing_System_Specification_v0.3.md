# Bayesian Marketing System: Technical Specification v0.3

**Engine:** ENG-BAYES (AtmaOS inventory §V).
**Status:** build specification. It replaces v0.2 (`spec/reviews/`) after blind review 01 (`spec/reviews/review_blind_01.md`). It is self-contained: every type a builder needs is defined here.
**Date:** 2026-10-30.

**Sources, in order of authority.**

1. Owner decisions, `spec/decisions.md` D1 to D17.
2. AtmaOS inventory, `atma_brain/documents/AtmaOS_Canonical_Architecture_Inventory_v1.0.md`.
3. Framework v0.1, `Bayesian Upgrade Oct. 2026/Bayesian Marketing Decision Framework.md`, as amended by D9 and D11.
4. Manuscript, October 2026, same folder. Its decision math and North Pier numbers are normative.
5. Spec v0.1, same folder. It is kept for lineage and superseded for building.
6. The outside contract: `atma_brain/src/atma_brain/adapters/bayesian/base.py`; `atma_brain/spec/03_agency.md` G3.4 and G8. Proposed changes are in atma_brain `spec/undecided.md` U52 (D12).

A conflict between sources goes to §17 as a question. It is never settled by editing a source.

---

## 0. Changes

### 0.1 From v0.1

| # | Change | Where |
|---|---|---|
| 1 | Client economics in core; every dollar decision needs it | §4.10, G9 |
| 2 | Evidence class and design on every quantity; synthetic flag on provenance | §4.3, §4.6 |
| 3 | Observed whole counts and platform-reported (possibly modeled) conversions kept apart | §5.1, §5.2 C6 |
| 4 | Order value modeled from an orders file, or from daily totals with the wider interval disclosed | §5.2 C2 |
| 5 | Google Ads, GA4 and an orders file added | §5.1 |
| 6 | Conversion-lag model specified | §5.6 |
| 7 | CTR and CVR coupling specified; small accounts take the exact per-ad route | §5.2 C1, §7.1, D11 |
| 8 | Vertical priors only as promoted AtmaOS knowledge | §5.3 C4 |
| 9 | Local run record; AtmaOS holds the ledger and approvals | §8.6, D3 |
| 10 | No model calls; the claim check and prior intake are deterministic | §10, D2 |
| 11 | AtmaOS socket, field by field | §11 |
| 12 | Spend is the input; the cost stage models impressions bought per dollar | §5.2 C3, D8 |
| 13 | Floors computed from the posterior (rates) and from expected loss (decisions) | §6.1, D9, D10 |
| 14 | Research bounds sit in the registry, never shown to clients | §6.1 C3, §8.5, D1, D15 |
| 15 | Simulator with ground truth and the North Pier answer key | §9, D5 |
| 16 | Out of scope: VI, exact cross-tabs, long-run strategy, detectability, path barriers, prophet allocation, optimization ceilings | D13 |

### 0.2 Disposition of review 01

| Finding | Disposition |
|---|---|
| 1.1 socket functions missing | §11 now has eight functions. AtmaOS pushes approvals, outcomes, narrative and prior approvals in; the engine never calls AtmaOS |
| 1.2 `expected_loss` type | Floats in account currency at the socket; currency in `uncertainty["currency"]` (§11.2) |
| 1.3 client, economics, envelope | `DatasetManifest` behind `dataset_uri` (§4.12); envelope fields accepted in the manifest; U52 proposes the proper fix |
| 1.4 oracle route | D11: North Pier routes to the exact per-ad model, and the oracle tests the production route |
| 1.5 floors | D9 and D10 |
| 1.6 provisional rendering | D15 |
| 1.7 dropped modules | D13; `channels/` restored |
| 1.8 undefined types | §4 defines every type |
| 1.9 likelihoods | §5.2 C6 uses a Gamma observation model; §5.6 C2 uses the thinned probability |
| 1.10 oracle precision | §8.1 C2: exact integration for independent analytic posteriors |
| 1.11 economics | D14 |
| 1.12 waves | §15 rebuilt; neighbours across pieces meet through frozen fakes |
| 1.13 evidence mapping | D17, §11.3 complete |
| 2.1 to 2.12 | §5.1 C8, §5.6, §4.11, §14 registry table, §15 test definitions, §13 ownership, §4.13, §4.12, §5.3, §5.2 C8, §14 |

---

## 1. Technology

| Decision | Choice |
|---|---|
| Language | Python, `requires-python >= 3.12` |
| Schemas | pydantic `>= 2.9`; every object crossing a module boundary |
| Numerics | numpy, scipy |
| Sampler | NumPyro on JAX CPU behind `PosteriorSampler` |
| Diagnostics | ArviZ |
| Posterior storage | Parquet (pyarrow) plus metadata JSON |
| Run record | SQLite, append-only by trigger |
| Registries | Versioned YAML in `registries/` |
| Reports | Jinja2 HTML, WeasyPrint PDF |
| HTTP | httpx, in `data_contract/connectors/` only |
| Tests | pytest, hypothesis; `@pytest.mark.piece("P#")` skips until the piece merges; `@pytest.mark.slow` for SBC |
| Lint | ruff, line length 100, rules E F I UP B SIM RUF |
| LLM | none (D2) |

**Dependency rule.** core ← data_contract, channels ← lag, prior_registry, model_spec ← inference, diagnostics, funnel_state ← derived_metrics ← floors, status_registry, test_design ← decision ← claims, reporting ← atmaos, pipeline. A module imports only from its own level or below. `simulate/` imports core and channels only. HTTP clients are imported only by connectors.

---

## 2. Layout

```
spec/                        this spec, decisions.md, facts/, manifests/, reviews/
legacy/                      version 1, untouched
registries/                  bounds.yaml, diagnostics.yaml, channels.yaml, decision_defaults.yaml,
                             guarantee_templates.yaml, phrasing.yaml, priors/
configs/                     per-client YAML (no secrets)
src/bayesian_marketing/
  core/                      §4: money, scope, quantities, feasibility, gates, decisions,
                             economics, provenance, manifest, bundle, registries loader
  channels/                  §5.7
  data_contract/
    readers/                 meta, google_ads, linkedin, ga4, orders
    connectors/              meta, google_ads, linkedin, ga4
  lag/                       §5.6
  prior_registry/            §5.3
  model_spec/                §5.2
  inference/                 router, conjugate, sampler_numpyro, fallback, (vi: stub)
  diagnostics/               §7.4
  funnel_state/              §5.4
  derived_metrics/           §5.5
  floors/                    estimability (detectability, path_barriers: stubs)
  status_registry/           §6.2
  test_design/               §6.3
  decision/                  compare, stopping, reallocation, allocation, guarantees,
                             run_record (long_run: stub)
  claims/                    §10
  reporting/                 §12
  atmaos/                    §11
  simulate/                  §9
  audit/                     §8.7
  pipeline.py                §13.2
tests/ acceptance/ oracle/ property/ simulation/ gates/ fakes/
data/  scenarios/ recordings/ generated/ (gitignored)
```

---

## 3. Conventions

All timestamps are UTC ISO-8601. Account-local dates are fixed after normalization, and the timezone is recorded. `Money(amount: Decimal, currency: str)` is used inside the engine; floats appear only at the socket (§11.2). `RegistryRef` is a string like `"bounds/estimability/posterior_width@v1"`. `inputs_hash` is the sha256 of canonical JSON (sorted keys, compact). Every random draw takes a recorded seed. Every public function is annotated and documented. Ids are prefixed strings: `q_`, `rec_`, `run_`, `fs_`, `pull_`, `pr_`, `econ_`, `ds_`.

---

## 4. Core schemas (`core/`)

All are pydantic models and frozen (immutable) unless marked otherwise.

### 4.1 Money and intervals

```python
class Money(BaseModel):          amount: Decimal; currency: str            # ISO 4217
class MoneyInterval(BaseModel):  low: Money; mid: Money; high: Money; level: float = 0.9
```

### 4.2 `DistributionSpec`

```python
class DistributionSpec(BaseModel):
    kind: Literal["analytic", "samples"]
    family: str | None            # beta | gamma | invgamma | lognorm (analytic)
    params: dict[str, float] | None
    samples_path: str | None      # parquet, one column per entity, rows are joint draws
    n_samples: int | None
    summary: dict[str, float]     # required: mean, sd, q05, q50, q95, q025, q975
```

When a quantity has both analytic and sample forms, the two must agree within Monte Carlo error.

### 4.3 `Scope`, `Provenance`

```python
class Scope(BaseModel):
    level: Literal["ad", "ad_set", "campaign", "account"]
    ids: dict[str, str]
    window: tuple[date, date]
    platform: Platform | None     # None only for cross-platform sums (§5.2 C8)

class Provenance(BaseModel):
    funnel_state_id: str | None   # None for deterministic quantities
    model_version: str
    data_pull_ids: list[str]
    derived_by: str
    route: Literal["conjugate", "nuts", "deterministic"]
    synthetic: bool               # True if any input came from simulate/ (D17)
    computed_at: datetime
```

### 4.4 `Feasibility`

```python
class Feasibility(BaseModel):
    status: Literal["estimable", "marginal", "below_floor"]
    basis: Literal["quantity_precision", "decision_loss", "inherited"]
    bound_ref: RegistryRef
    available: float
    required: float | None
    target: float
    reasons: list[str]            # non-empty unless estimable
    supersedes: str | None
    checked_at: datetime
```

Statuses only move down (I5). Signed money quantities get `basis="inherited"` with the worst status of their inputs (D10).

### 4.5 Gates

```python
class GateResult(BaseModel):
    gate: str; passed: bool; blocking: bool; reasons: list[str]
    inputs_hash: str; checked_at: datetime

class Gate(Protocol):
    name: str
    def check(self, obj: BaseModel) -> GateResult: ...
```

Gates are pure functions of their input object plus registries. Every result goes into the run record.

### 4.6 `Quantity`

```python
class Quantity(BaseModel):
    quantity_id: str
    name: Literal["ctr", "cvr", "cpa", "roas", "aov", "cpm", "cpc",
                  "contribution_per_click", "contribution", "p_exceeds", "lift"]
    scope: Scope
    estimate: DistributionSpec
    feasibility: Feasibility
    provenance: Provenance
    evidence_class: Literal["delivery", "platform_attributed", "commercially_realized",
                            "causally_incremental", "deterministic"]
    design: Literal["observational", "randomized", "holdout", "none"]
    diagnostics_ref: str | None   # None only for conjugate and deterministic routes
    notices: list[str]            # degradation and route stamps, e.g. "funnel link not estimated: too few ads"
```

**Validator rules (G10).**

- `causally_incremental` requires `design="holdout"`.
- Any quantity computed from platform conversions is `platform_attributed`.
- `commercially_realized` requires an orders pull among `data_pull_ids`.
- `deterministic` requires `provenance.route="deterministic"`.

### 4.7 `DiagnosticsReport`

```python
class DiagnosticsReport(BaseModel):
    report_id: str; sampler: Literal["numpyro_nuts", "conjugate"]
    rhat_max: float | None; ess_bulk_min: float | None; ess_tail_min: float | None
    n_divergences: int | None; ppc: dict[str, float]; loo: dict[str, float] | None
    seeds: list[int]; thresholds_ref: RegistryRef
    passed: bool | None           # set only by G3
```

### 4.8 `Guarantee`, `Recommendation`

```python
class Guarantee(BaseModel):
    kind: Literal["posterior_probability", "expected_loss", "value_of_information", "none"]
    statement_math: str
    template_id: str              # guarantee_templates.yaml key; prose is rendered, never stored free
    slots: dict[str, str]
    assumptions: list[str]

class Recommendation(BaseModel):
    recommendation_id: str
    action: Literal["allocate", "reallocate", "hold", "stop_test", "continue_test",
                    "collect_more_data", "repair_measurement", "not_knowable"]
    scope: Scope
    params: dict[str, Any]        # e.g. {"allocation": {"ad_b": 0.7, "ad_a": 0.3}}
    basis: list[str]              # quantity_ids
    decision_feasibility: Feasibility   # basis="decision_loss" (D9)
    economics_id: str | None      # None only for not_knowable / repair_measurement
    guarantee: Guarantee
    expected_benefit: Money | None
    expected_loss: Money | None
    horizon: Horizon
    reversibility: Literal["reversible", "costly", "irreversible"]
    requires_human_approval: Literal[True]
    run_id: str
```

There is no status field on the recommendation. Approval lives in AtmaOS and is mirrored by `ApprovalRecord` (§4.11). `constant_factor` and `competitive_ratio` guarantees do not exist in this version (D1, D15).

### 4.9 `Horizon`, `Objective`

```python
class Horizon(BaseModel):
    unit: Literal["clicks", "impressions", "spend", "days"]
    amount: Decimal               # e.g. 1000 clicks; $5000 spend

class Objective(BaseModel):
    target: Literal["contribution", "orders", "clicks"]   # contribution is the default
    horizon: Horizon
```

The loss tolerance applies to the stated horizon (review 2.3).

### 4.10 `ClientEconomics`

```python
class ClientEconomics(BaseModel):
    economics_id: str; client_id: str; currency: str
    variable_cost_per_order: Money           # production, fulfillment, processing, expected returns
    price_source: Literal["modeled_aov", "fixed"]
    fixed_price: Money | None                # required when price_source="fixed"
    repeat_value: DistributionSpec | None
    loss_tolerance: Money | None             # per decision at its horizon; None → G9 fails (D16)
    survival_floor: Money | None             # downside the client cannot absorb
    test_budget: Money | None
    source: str; approved_by: str | None; approved_at: datetime | None
```

Contribution per order is computed per draw as price minus `variable_cost_per_order` (D14). Break-even CPA equals contribution, and break-even ROAS equals price over contribution, both per draw.

### 4.11 Run record objects (append-only)

```python
class RunRecord(BaseModel):
    run_id: str; started_at: datetime; engine_version: str; registry_versions: dict[str, str]
    config_hash: str; manifest_id: str; dataset_hashes: list[str]
    gate_results: list[GateResult]; quantity_ids: list[str]; recommendation_ids: list[str]
    route_log: list[str]; seeds: dict[str, int]

class ApprovalRecord(BaseModel):     # written only by atmaos.record_approval
    recommendation_id: str; approval_ref: str; decision: Literal["approved", "rejected"]
    decided_by: str; decided_at: datetime

class OutcomeRecord(BaseModel):      # written by atmaos.record_outcome or by shadow replay
    recommendation_id: str; source: Literal["atmaos", "ground_truth"]
    realized: dict[str, Any]; recorded_at: datetime
```

### 4.12 `DatasetManifest`

This is what `dataset_uri` points to: a `file://` path to a JSON manifest.

```python
class DatasetManifest(BaseModel):
    manifest_id: str; client_id: str; economics_id: str
    files: list[ManifestFile]               # path, platform, sha256, export_kind ("export" | "pull")
    attribution_window: dict[Platform, str]
    entity_map: dict[str, dict[str, str]]   # variant name → platform entity ids
    utm_map: dict[str, dict[str, str]] | None   # utm_campaign/utm_content → entity ids (orders, GA4)
    envelope: dict[str, Any]                # inventory §VIII fields when AtmaOS supplies them; recorded verbatim
    synthetic: bool
```

### 4.13 `ReportBundle`

```python
class ReportBundle(BaseModel):
    kind: Literal["client", "demo", "internal"]
    client_id: str; run_id: str
    quantities: list[Quantity]; recommendations: list[Recommendation]
    gate_results: list[GateResult]; diagnostics: list[DiagnosticsReport]
    knowability: KnowabilitySection          # observed, platform-modeled, attribution windows, not-knowable list
    narrative_blocks: list[NarrativeBlock]   # from AtmaOS; each carries its G5 GateResult
```

A `client` bundle containing any `synthetic` quantity is refused (G10, I13). `demo` and `internal` reports carry the watermark from `phrasing.yaml`.

### 4.14 Other shared types

```python
Platform = Literal["meta", "google_ads", "linkedin", "ga4", "orders"]
class PlatformPull(BaseModel):  pull_id: str; platform: Platform; channel_ref: RegistryRef
    rows: list[PerformanceRow] | list[OrderRow] | list[SiteRow]; quarantined: list[QuarantinedRow]
    partial_truth: bool; measurement_changes: list[str]; pulled_at: datetime; synthetic: bool
class QuarantinedRow(BaseModel): raw: dict[str, Any]; reasons: list[str]
class SiteRow(BaseModel):        date: date; utm: dict[str, str]; sessions: int; purchases: int; revenue: Money
class FunnelData(BaseModel):     per-entity, per-day arrays: spend, impressions, clicks, conversions_observed,
                                 conversions_reported, mature_fraction (§5.6), revenue_reported, order_values
class PrecisionTarget(BaseModel): rel_half_width: float; level: float = 0.9; caveat_rel_half_width: float
class DegradationNotice(BaseModel): notice_id: str; step: str; reason: str; affected: list[str]
```

The model types (`FunnelSpec`, `StageSpec`, `PriorSet`, `CompiledModel`, `FitConfig`, `FunnelState`) are in §5.2 to §5.4. The decision types (`Comparison`, `DecisionProblem`, `TestDesign`, `DesignAssessment`) are in §6.3 and §8.1. `LagModel` is in §5.6, and `ChannelModel` is in §5.7.

---

## 5. Layer 1: the generative model

### 5.1 `data_contract/`

```python
def read_export(platform: Platform, path: Path, manifest: DatasetManifest) -> PlatformPull
def pull(platform: Platform, config: ClientConfig, window: tuple[date, date]) -> PlatformPull   # connectors

class PerformanceRow(BaseModel):
    entity_ids: dict[str, str]; date: date
    impressions: int; clicks: int; spend: Money
    conversions_observed: int | None
    conversions_reported: float | None
    conversions_modeled_share: float | None
    attribution_window: str
    revenue_reported: Money | None

class OrderRow(BaseModel):
    order_id: str; ordered_at: datetime; value: Money; refunded: Money
    utm: dict[str, str] | None; click_id: str | None; first_click_at: datetime | None
```

**Contracts.**

- C1. Malformed rows are quarantined with reasons and never coerced. This includes clicks above impressions, negative values, conversions above clicks, unknown currency, and a duplicate `order_id`.
- C2. Timezone normalization happens here and nowhere else.
- C3. Each column mapping comes from that platform's `ChannelModel` export map (§5.7), never from code.
- C4. Pulls are idempotent per (platform, account, window, attribution window). A re-pull gets a new `pull_id`.
- C5. A change of attribution window inside a window splits the series and appends to `measurement_changes`.
- C6. Connectors record redacted exchanges when `RECORD=1`. Tests replay recordings and never touch the network. An empty account returns an empty pull flagged `empty_account`, not an error.
- C7. Orders join to entities through `utm_map` or click id only. GA4 site rows join at campaign and day through `utm_map`. There is no user-level join.
- C8. **Conversion typing** (review 2.1). A platform's headline conversion figure always goes to `conversions_reported`. It is copied to `conversions_observed` only when the channel model marks that field `may_be_modeled: false` and every value in the pull is an integer. Orders-file counts are always observed. `partial_truth = (conversions_observed is None for any row) and (conversions_modeled_share is None)`.

### 5.2 `model_spec/`

```python
class StageSpec(BaseModel):
    name: Literal["delivery", "ctr", "cvr", "value"]
    likelihood: Literal["poisson", "binomial", "beta_binomial", "gamma_obs", "lognormal", "compound_gamma"]
    pooled: bool

class FunnelSpec(BaseModel):
    version: str; stages: list[StageSpec]
    hierarchy: list[Literal["ad", "campaign", "account"]]    # within one platform (C8)
    coupling: Literal["lkj_bivariate"]                      # required (I9)
    dynamics: Literal["static", "random_walk"]

class PriorSet(BaseModel):     records: dict[str, PriorRecord]    # parameter_path → approved record
class CompiledModel(BaseModel): spec_version: str; model_fn_ref: str; data_shape: dict[str, int]
def compile_model(spec: FunnelSpec, priors: PriorSet, data: FunnelData) -> CompiledModel
```

**Contracts.**

- C1. **Coupling.** Ad-level `(logit ctr, logit cvr)` is bivariate normal around campaign means, with an LKJ(η) prior on the correlation and half-normal scales. A spec without coupling raises `UncoupledFunnelError`. This model is used only at or above `min_ads_for_coupling` (D11).
- C2. **Value.** With an orders file, order value is log-normal per ad and partially pooled. Without one, daily revenue given n > 0 conversions is Gamma(shape n·k, rate k/μ), the sum of n i.i.d. Gamma(k, k/μ) order values. Any ROAS computed from a fixed revenue per conversion fails A1.
- C3. **Delivery.** Impressions on day d are Poisson(spend_d × 1000 / CPM_ad), with log CPM partially pooled. Spend is an input (D8).
- C4. Structural zeros (paused ads, zero spend) are explicit inputs. Days with zero spend contribute no likelihood terms, and are never filtered silently.
- C5. `compile_model` is backend-agnostic.
- C6. **Fractional conversions** (review 1.9). When only `conversions_reported` exists and is fractional, the cvr stage observes it through `gamma_obs`: reported ~ Gamma(mean = clicks·mature_fraction·cvr, shape = φ·mean), with φ ~ half-normal. Every quantity downstream is capped at `marginal` with the notice "platform-modeled conversions". Fractional counts never enter a binomial or Poisson likelihood.
- C7. `dynamics="static"` by default. `random_walk` (daily Gaussian walk on logit scale) is allowed only when the window has at least `min_days_for_dynamics` days.
- C8. **Platforms.** Hierarchy is within one platform. Platforms are never pooled with each other, because their measurement differs. Cross-platform totals are sums of per-platform derived quantities. Such a total has `platform=None`, takes the lowest evidence class of its inputs (order: deterministic, commercially_realized, causally_incremental, platform_attributed, delivery), and takes the worst feasibility status.

### 5.3 `prior_registry/`

```python
class ElicitationRecord(BaseModel):
    source: Literal["ai_proposal", "human", "historical_fit", "promoted"]
    rationale: str; evidence_refs: list[str]; author: str; created_at: datetime
    approved_by: str | None; approved_at: datetime | None; promotion_id: str | None
class PriorRecord(BaseModel):
    prior_id: str; parameter_path: str; family: str; params: dict[str, float]
    elicitation: ElicitationRecord; version: str; resolution_path: list[str]
    predictive_check: dict[str, float] | None

def resolve(parameter_path: str, client_id: str, as_of: datetime) -> PriorRecord
def propose(record: PriorRecord) -> str                     # returns prior_id "pr_<sha8>", status pending
def approve(prior_id: str, approver: str) -> PriorRecord    # called by atmaos.approve_prior only
def import_promoted(record: dict, promotion_id: str) -> str # vertical priors from AtmaOS (C4)
def prior_from_cohorts(rates: list[float], discount: float) -> tuple[float, float]
```

**Contracts.**

- C1. Fitting is blocked for any parameter path whose prior is unapproved (G8).
- C2. Resolution order is client, then vertical, then default. Every hop is recorded.
- C3. A prior is immutable once used.
- C4. Vertical priors arrive only through `import_promoted`, carrying an AtmaOS promotion id. The engine never computes a prior from another client's data.
- C5. `prior_from_cohorts` uses method of moments with the n−1 variance and a disclosed discount (Manuscript ch. 5; oracle row "prior from cohorts").
- C6. `approve` runs a prior predictive check first and refuses when the 99th percentile of simulated rates exceeds the plausibility ceiling.
- C7. The framework default priors are shipped in `registries/priors/default.yaml`, pre-approved by the owner, with `source: human`.

### 5.4 `funnel_state/`

```python
class FitConfig(BaseModel):  chains: int; draws: int; warmup: int; target_accept: float; seed: int
class FunnelState(BaseModel):
    state_id: str; spec_version: str | None; route: Literal["conjugate", "nuts"]
    prior_ids: dict[str, str]; data_window: tuple[date, date]
    posterior: DistributionSpec; diagnostics_id: str | None
    supersedes: str | None; quarantined: bool; created_at: datetime; synthetic: bool
def save(state: FunnelState) -> None; def load(state_id: str) -> FunnelState
```

States are immutable. A quarantined state can be loaded for audit, but `derived_metrics` refuses it.

### 5.5 `derived_metrics/`

```python
def derive(name: str, state: FunnelState, scope: Scope, econ: ClientEconomics | None) -> Quantity
```

These are pure functions with no I/O beyond reading the state. Comparisons between sampled posteriors use joint draws. Comparisons between independent analytic posteriors use the exact integration of §8.1 C2.

### 5.6 `lag/`

```python
class LagModel(BaseModel):
    platform: Platform; attribution_window: str
    cdf: list[float]              # F(a) for a = 0..max_days
    source: Literal["orders_history", "platform_lag_report", "registry_default"]
    n_lagged_conversions: int
def lag_model(platform: Platform, window_code: str, history: list[OrderRow] | None,
              lag_report: list[dict] | None) -> LagModel
def mature_fraction(click_date: date, as_of: date, lag: LagModel) -> float
```

**Contracts.**

- C1. The lag curve is estimated from orders with `first_click_at`, or from a platform's days-to-conversion report, when there are at least `min_lagged_conversions`. Otherwise the registry default is used, and the notice "conversion lag assumed" is attached.
- C2. **Likelihood** (review 1.9). Conversions from clicks on day d, observed at as_of, are Binomial(clicks_d, cvr · F(as_of − d)). The NUTS route uses this likelihood exactly. The conjugate route uses effective trials Σ clicks_d·F(a_d) as an approximation, stamped "lag-adjusted approximation".
- C3. A stop decision may not rest on a cohort with F(a) < `min_maturity`.

### 5.7 `channels/`

```python
class ChannelModel(BaseModel):
    platform: Platform; version: str
    export_map: dict[str, str]                 # platform column → PerformanceRow field
    conversion_field_may_be_modeled: bool
    default_attribution_window: str
    learning_phase_switching_cost: Money | None   # None = unknown, disclosed
    freshness_date: date; max_age_days: int
def channel_model(platform: Platform, as_of: date) -> ChannelModel
```

Channel models are read from `registries/channels.yaml`. One that is stale fails G1 for its platform.

---

## 6. Layer 2: the information budget

### 6.1 `floors/estimability`

```python
def quantity_feasibility(q: Quantity, target: PrecisionTarget) -> Feasibility
def decision_feasibility(c: Comparison, econ: ClientEconomics) -> Feasibility
```

**Rate basis (D10).** This applies to strictly positive quantities only. Let w be the 90% relative half-width (q95 − q05) / (2 × q50). The quantity is `estimable` if w ≤ 0.20, `marginal` if w ≤ 0.40, and otherwise `below_floor`. `required` is the event count at which w would reach 0.20, from w ∝ n^−½ scaled from the current w and event count. That projection is an approximation and is labeled as one. Regime mismatches downgrade the status one level, each with a reason: lag-adjusted approximation, attribution change in window, funnel link not estimated.

**Decision basis (D9).** Let L be the expected opportunity loss of the best option at the objective's horizon. The decision is `estimable` if L ≤ tolerance, `marginal` if L ≤ 2 × tolerance, and otherwise `below_floor`. `required` is the additional volume at which the projected L falls under tolerance, found by preposterior simulation (conjugate route) or by variance scaling (NUTS route, labeled as approximate). With no tolerance, G9 fails and the decision is `not_knowable` (D16).

**Contracts.**

- C1. Every number comes from the registry.
- C2. The decision basis governs recommending. The rate basis governs quoting (D9).
- C3. Research-result entries in `bounds.yaml` carry `verified`, `regime_validated` and `client_visible: false`. `floors/` never reads them (D1).
- C4. `detectability` and `path_barriers` raise `NotInScope`.

### 6.2 `status_registry/`

```python
def publish(q: Quantity) -> None          # G2; single writer
def status_of(quantity_id: str) -> Feasibility
```

A published status is immutable. New data produces a new status with a `supersedes` link.

### 6.3 `test_design/`

```python
class DecisionProblem(BaseModel):
    options: list[str]; payoffs: dict[str, DistributionSpec]   # per option, at horizon
    objective: Objective
class TestDesign(BaseModel):
    arms: list[str]; allocation: dict[str, float]; volume: Horizon
    randomized: bool; holdout: bool
    sensitivity: float | None; false_positive_rate: float | None   # for signal-type tests (Manuscript ch. 6)
class DesignAssessment(BaseModel):
    evpi: Money; evsi: Money; cost: MoneyInterval; net_value: Money
    verdict: Literal["buy", "do_not_buy", "redesign"]; redesign: TestDesign | None
    design_label: Literal["observational", "randomized", "holdout"]
def evpi(p: DecisionProblem) -> Money
def evsi(p: DecisionProblem, d: TestDesign) -> Money
def assess(p: DecisionProblem, d: TestDesign, econ: ClientEconomics, state: FunnelState) -> DesignAssessment
```

**Contracts.**

- C1. EVSI follows the preposterior method of Manuscript ch. 6.
- C2. Cost is an interval taken from the CPC and CPM posteriors.
- C3. When cost exceeds EVSI, the verdict is `do_not_buy`, with the cheapest redesign found that clears its own cost, if one exists.
- C4. A design without randomization is labeled observational.

---

## 7. Layer 3: inference

### 7.1 `inference/router`

```python
class Route(BaseModel): kind: Literal["conjugate", "nuts"]; reason: str; notices: list[str]
def route(spec: FunnelSpec, data: FunnelData) -> Route
```

- C1. If fewer than `min_ads_for_coupling` ads are in the comparison, the route is `conjugate`, with the notice "funnel link not estimated: too few ads" (D11). Otherwise it is `nuts`.
- C2. Every route decision and its reason goes to the run record.
- C3. VI is a stub that raises `NotInScope` (D13).

### 7.2 `inference/conjugate`

There is one model per ad:

- CTR is Beta-Binomial.
- CVR is Beta-Binomial on lag-adjusted trials.
- Conversions per dollar are Gamma-Poisson, so CPA ~ InvGamma(α + n, β + spend), as in v1's `legacy/modules/cpa_model.py`.
- CPM is Gamma-Poisson on impressions per dollar.
- Order value is the conjugate log-normal (normal-inverse-gamma on log values) when an orders file exists. Otherwise it is the Gamma-Gamma fit to daily totals, using `compound_gamma` (§5.2 C2) with k fixed at the registry default and disclosed.
- ROAS and contribution are computed from joint draws of these independent posteriors.

The result is a `FunnelState` with `route="conjugate"`, holding analytic parameters plus a sample representation with a recorded seed.

### 7.3 `inference/sampler_numpyro`

```python
class PosteriorSampler(Protocol):
    def fit(self, model: CompiledModel, data: FunnelData, config: FitConfig) -> tuple[FunnelState, DiagnosticsReport]
```

The sampler uses non-centered parameterization, takes its config from the registry, and records its seeds.

### 7.4 `diagnostics/`

```python
def run_diagnostics(state: FunnelState, data: FunnelData) -> DiagnosticsReport
```

The thresholds live in the registry (§14). PPC computes, per stage, the posterior predictive p-value of the stage total. A misfit names its stage. Only G3 sets `passed`.

### 7.5 `inference/fallback`

The chain runs in order:

1. NUTS, full spec.
2. NUTS without dynamics.
3. NUTS without pooling above the ad level.
4. Conjugate per ad.

Each step emits a `DegradationNotice`. Reaching step 4 caps every quantity at `marginal` and adds the notice "joint model failed checks". This step-4 cap does not apply to D11's conjugate route, which is a choice made from the start, not a fallback.

---

## 8. Layer 4: decisions

### 8.1 `decision/compare`

```python
class Comparison(BaseModel):
    options: list[str]; objective: Objective; economics_id: str
    p_best: dict[str, float]
    expected_value: dict[str, Money]           # at horizon
    expected_loss: dict[str, Money]            # expected opportunity loss of choosing each
    p_exceeds_break_even: dict[str, float]
    method: Literal["exact_integration", "joint_draws"]
def compare(options: list[Quantity], objective: Objective, econ: ClientEconomics) -> Comparison
```

**Contracts.**

- C1. `compare` requires approved economics. Without them, G9 fails.
- C2. **Exact integration.** When every option is an independent analytic posterior (conjugate route), p_best, expected loss and break-even probabilities are computed by numerical quadrature to absolute tolerance 1e-10. Otherwise they come from joint draws, with the Monte Carlo standard error reported.
- C3. A comparison does not compute feasibility. `floors.decision_feasibility` does that afterwards (review 1.12).

### 8.2 `decision/reallocation`

- C1. The switching cost comes from `ChannelModel.learning_phase_switching_cost`. When it is unknown, the recommendation states this, sets `reversibility="costly"`, and computes the hold test with a cost of zero, also stated.
- C2. The decision is `hold` when expected benefit minus switching cost ≤ 0, or when the decision basis is `below_floor`. The oracle case is $1,170 − $250 = $920 < $1,000, which gives hold.
- C3. An option whose 5th-percentile contribution at the horizon breaches `survival_floor` is never recommended.

### 8.3 `decision/stopping`

- C1. `stop_test` requires the decision basis to be `estimable` and every cited cohort to be mature (§5.6 C3).
- C2. A stop rejected only because cohorts are immature gives `continue_test` with the notice "waiting for late conversions".
- C3. Below floor gives `continue_test` with the remaining cost from `test_design`. If the required cost exceeds `test_budget`, the result is `not_knowable`.

### 8.4 `decision/allocation`

The split is in proportion to p_best, floored at `min_arm_share` and capped per arm by config. The guarantee kind is `posterior_probability`. The prophet rule is a stub raising `NotInScope` (D13).

### 8.5 `decision/guarantees`

```python
def render_guarantee(g: Guarantee, locale: str = "en") -> str
```

Rendering uses `guarantee_templates.yaml` only (I8). Every template states the model route, the evidence class in plain words, the horizon, and the main assumption. Templates exist only for the four guarantee kinds of §4.8. No provisional entry is reachable (D15).

### 8.6 `decision/run_record`

```python
def append(obj: RunRecord | Recommendation | ApprovalRecord | OutcomeRecord) -> None
def read(kind: str, **filters) -> list[BaseModel]
```

The store is SQLite, with triggers that reject UPDATE and DELETE (A7).

### 8.7 `audit/`

```python
def guarantee_report(since: date) -> AuditReport
```

For each recommendation with an `OutcomeRecord`, the report compares stated expected benefit and loss with what was realized, and checks interval coverage. Ground-truth outcomes from shadow runs are reported separately from AtmaOS outcomes.

---

## 9. Test data (D5)

### 9.1 `simulate/`

```python
class GroundTruth(BaseModel):
    scenario: str; seed: int; params: dict[str, Any]
    true_quantities: dict[str, float]          # keyed "<variant>.<quantity>"
    true_best: dict[str, str]                  # objective → variant
def generate(scenario_path: Path, seed: int, out_dir: Path) -> GroundTruth
```

`generate` writes a `DatasetManifest` with `synthetic: true`. Per platform, it writes CSVs using that platform's export column names (taken from the `ChannelModel` export maps, so P1 and P2 share one source). It also writes an orders CSV, plus `ground_truth.json`.

**Scenarios** (`data/scenarios/*.yaml`):

| Scenario | Tests |
|---|---|
| `north_pier_day2`, `north_pier_day14` | Manuscript totals, two ads, conjugate route |
| `tiny_campaign` | Rates and decision below floor; renders "not knowable yet" |
| `negative_dependence` | 12 ads, true CTR/CVR correlation −0.6; joint model recovers the sign; independent-pairing ROAS is visibly wrong |
| `delivery_mix_shift` | Ch. 10: 42 → 22 orders per 1,000 clicks |
| `attribution_window_change` | C5 split |
| `lag_heavy` | median lag 4 days; premature stop refused |
| `fractional_conversions` | §5.2 C6 cap |
| `switching_cost_hold` | Reallocation returns hold |
| `many_accounts` | 3 accounts × 4 campaigns × 10 ads; SBC load |

### 9.2 North Pier answer key (`tests/oracle/`)

These values were recomputed on 2026-10-30 by integration with scipy 1.18.1, and every one matches the Manuscript. The tolerance is 4 significant figures unless stated. They are produced by the production conjugate route with exact integration (D11, §8.1 C2).

| Case | Input | Expected |
|---|---|---|
| CTR day two | Beta(2,98); A 40/2,000, B 34/2,000 | Beta(42,2058), Beta(36,2064); means 2.000%, 1.714%; 95% CI A 1.446%–2.641%, B 1.204%–2.311%; P(A>B) 0.7548 |
| CVR day fourteen | Beta(1,49); A 8/400, B 18/340 | Beta(9,441), Beta(19,371); means 2.000%, 4.872%; 95% CI A 0.9206%–3.480%, B 2.966%–7.215%; P(B>A) 0.9907 |
| Floors at D10 | same | 90% rel half-width CTR A 0.251, B 0.271 (marginal); CVR A 0.536 (below floor), B 0.366 (marginal) |
| Expected contribution, 1,000 clicks | $32 per order; CPC $1.25, $500/340 | A −$610.00, B +$88.39; P(B higher) 0.9624 |
| Expected opportunity loss | same | A $704.21, B $5.82 (±$0.01) |
| Break-even | same | thresholds 3.906%, 4.596%; P(A clears) 0.008265, P(B clears) 0.5741 |
| EVPI, EVSI | 40%, +$2,000 / −$1,000; 75% / 25% signal | EV now $200; EVPI $600; P(pos) 0.45; posteriors 0.6667, 0.1818; EVSI $250 |
| Sample size | 3% vs 4%, α 0.05 two-sided, power 0.8 | 5,300.74 per arm |
| Prior from cohorts | .013 .017 .019 .021 .023 .027; discount 0.25; then 10/200 | κ 829.51; Beta(16.59, 812.92); Beta(4.148, 203.23); mean 3.473% |
| Dependence | (4%, 1%) or (1%, 5%); 10,000 imps, $200, $80 | paired 1.6, 2.0, mean 1.8; independent 0.4, 1.6, 2.0, 8.0, mean 3.0 |
| Delivery mix | 800/200 → 300/700 clicks at 5% / 1% | 42 → 22 |
| Economics | $80, $48 → $56 | break-even CPA $32, ROAS 2.5 → 3.333 |
| Hold | keep $1,000; switch 0.7×$1,500 + 0.3×$400; cost $250 | $920 < $1,000 → hold |

### 9.3 Public data

The candidate is `bigquery-public-data.ga4_obfuscated_sample_ecommerce` (2020-11-01 to 2021-01-31), used for real order-value spread and purchase lag. It is used only after facts pack F5 records its terms and schema. It never appears as client evidence. The manifest is marked `synthetic: false, public: true`, and reports label it.

### 9.4 Shadow replay

```python
def replay(scenario_path: Path, seed: int, start: date, end: date) -> AuditReport
```

The replay feeds the pipeline one day at a time and writes each recommendation. It then writes `OutcomeRecord(source="ground_truth")` from `GroundTruth`, and scores:

- regret against the true best option,
- coverage of the 90% intervals,
- the share of "not knowable" verdicts that were correct, meaning the truth could not be resolved at the tolerance with the data seen.

---

## 10. Claims (`claims/`) (D2)

```python
class NarrativeBlock(BaseModel): block_id: str; text: str; author: str; gate: GateResult | None
def check_narrative(block: NarrativeBlock, bundle: ReportBundle) -> GateResult     # G5
def intake_prior_proposal(proposal: dict) -> str                                   # → prior_registry.propose
```

**C1. `check_narrative` rules.** It tokenizes every number, percent, money amount, comparative and causal verb. It then checks each one:

- **Numbers.** Each must equal a bundle quantity's summary value at its displayed precision, using the rounding rules in `phrasing.yaml`.
- **Rate findings.** A quoted rate must not have `below_floor` quantity status. A `marginal` rate needs the caveat phrase from `phrasing.yaml` in the same sentence.
- **Comparatives.** Each must match a `Comparison` in the bundle. The statement "B is better" requires a decision basis of `marginal` or `estimable`.
- **Causal verbs.** Lexicon: caused, drove, generated, lifted, incremental. Plain causal verbs require `randomized`. The word "incremental" requires `holdout` (D17).
- **Not-knowable items.** These may appear only in the `phrasing.yaml` "not knowable yet" form.

**C2. No model client in the repo.** No module may import these packages: anthropic, openai, google.generativeai, google.genai, mistralai, cohere, litellm, langchain, llama_index. A test checks both the import graph and the installed dependency tree.

---

## 11. AtmaOS socket (`atmaos/`)

### 11.1 Functions

AtmaOS calls the engine, and the engine never calls AtmaOS.

```python
def compare(dataset_uri: str, *, metric: str, variants: list[str], priors: dict[str, Any],
            window: dict[str, Any], segments: dict[str, Any]) -> dict              # BayesianResult-shaped
def observation_evidence(result: dict, tool_result_id: str) -> dict               # G3.4 payload
def recommendations(run_id: str) -> list[dict]                                    # proposed, with guarantees rendered
def record_approval(recommendation_id: str, approval_ref: str, decision: str,
                    decided_by: str, decided_at: str) -> None                     # G6
def record_outcome(recommendation_id: str, realized: dict) -> None
def approve_prior(prior_id: str, approver: str) -> dict
def check_narrative(block: dict, run_id: str) -> dict                             # G5 result
def render_report(run_id: str, kind: str, narrative_blocks: list[dict]) -> str    # path to PDF/HTML
```

`compare` runs `pipeline.run`. Its arguments are mapped as follows:

- `dataset_uri` resolves to a `DatasetManifest`, which supplies the client and the economics.
- `metric` must be one of ctr, cvr, cpa, roas, contribution_per_click, contribution. The objective is contribution unless the metric names a rate.
- `variants` are keys of `entity_map`.
- `priors` maps parameter paths to approved `prior_id`s. Unknown or unapproved ids fail G8.
- `window` is `{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "horizon": {"unit": ..., "amount": ...}}`.
- `segments` filters `Scope.ids`.

### 11.2 `BayesianResult` mapping

| Field (type in `base.py`) | Filled from |
|---|---|
| `posterior: dict[str, Any]` | per variant: summary, quantity status, evidence class, design, quantity_id, notices |
| `probability_best: dict[str, float]` | `Comparison.p_best` |
| `expected_loss: dict[str, float]` | `Comparison.expected_loss`, as float amounts in account currency |
| `uncertainty: dict[str, Any]` | currency, horizon, decision feasibility, intervals, diagnostics summary, route, degradation notices, `run_id`, `recommendation_ids` |
| `config_hash: str` | `RunRecord.config_hash` |
| `tool_version: str` | package version + registry versions |

`observation_evidence` returns exactly the keys from G3.4: tool version, dataset snapshot hash, window, metric, priors, configuration, segments, result, uncertainty, and `tool_result_id`.

### 11.3 Evidence-class mapping (inventory §VIII)

| Engine | Inventory class |
|---|---|
| raw `PerformanceRow`, `SiteRow` | observed metric |
| raw `OrderRow` | observed metric (commercially realized) |
| `deterministic` quantity | deterministic derived quantity |
| posterior quantity, design `observational` or `none` | model inference / prediction |
| posterior quantity, design `randomized` | experimental estimate (between variants; not incrementality) |
| posterior quantity, design `holdout`, class `causally_incremental` | experimental estimate (incremental) |
| any object with `synthetic: true` | simulation |
| `commercially_realized` posterior quantity | model inference / prediction, over commercially realized data |

### 11.4 Proposed contract changes

The proposed changes are recorded in atma_brain `spec/undecided.md` U52 (D12):

- typed fields for feasibility, evidence class and recommendations;
- currency-bearing loss amounts;
- a client and economics reference;
- the inventory envelope.

---

## 12. Reporting (`reporting/`)

```python
def render(bundle: ReportBundle, out_dir: Path) -> RenderedReport   # HTML and PDF paths, inputs_hash
```

**Contracts.**

- C1. **G7.** Every rendered number comes from a bundle quantity with valid provenance. Sampler-produced quantities also need a passing G3 diagnostics report. Otherwise render is blocked and the missing links are listed.
- C2. **Below-floor quantities** render as the "not knowable yet" block, showing required data against available data and the cost of knowing.
- C3. **Knowability section.** It lists what was observed, what was platform-modeled, the attribution windows, and the not-knowable list.
- C4. **Plain-words labels.** Every number carries its evidence class in plain words, from `phrasing.yaml`.
- C5. **Diagnostics appendix.** It holds real R̂, ESS, divergence and PPC values for each fitted state, or the phrase "exact conjugate model; no sampler ran".
- C6. **Narrative.** Narrative blocks render only with a passing G5. A bundle with no narrative renders template sentences only.
- C7. **Report kinds.** `kind="client"` is refused if any quantity is synthetic. `demo` and `internal` reports carry the watermark.

---

## 13. Gates and pipeline

### 13.1 Gates

| Gate | Owner piece | Fires at | Pass criteria | On fail |
|---|---|---|---|---|
| G1 ingestion | P1 | `read_export`, `pull` | rows validate; timezone normalized; attribution window present; channel fresh | quarantine rows; stale channel blocks its platform |
| G2 feasibility | P4 | `status_registry.publish` | bound resolvable; reasons recorded | quantity not published |
| G3 diagnostics | P6 | after each NUTS fit | §14 thresholds | state quarantined; fallback |
| G4 ceiling | none (dormant, D13) | n/a | n/a | n/a |
| G5 narration | P10 | before a narrative block renders | §10 C1 | block rejected with failing claims listed |
| G6 approval | P11 | `record_approval` | approval names a person; recommendation exists | approval refused |
| G7 provenance | P10 | `reporting.render` | §12 C1 | render blocked |
| G8 prior approval | P7 | `prior_registry.resolve` | approved; predictive check passed | fit blocked for that path |
| G9 economics | P3 | `compare` | approved economics with loss tolerance | `not_knowable` |
| G10 evidence | S0 | `Quantity` and `ReportBundle` construction | §4.6 rules; no synthetic in client bundle | object rejected |

### 13.2 Pipeline

```python
def run(manifest: DatasetManifest, request: CompareRequest) -> RunResult
```

```
read (G1) → lag → route → [conjugate | compile + priors (G8) → NUTS (G3, fallback)]
  → funnel_state.save → derive (G10) → quantity feasibility → publish (G2)
  → compare (G9) → decision feasibility → recommend (guarantee templates)
  → run_record.append → return
```

Narrative, approval and rendering are separate socket calls. They happen after AtmaOS has acted.

---

## 14. Invariants and registry defaults

**Invariants.**

- I1. No independent per-metric models, except the D11 small-account route (stamped) and the fallback's last step (stamped).
- I2. Every rendered number traces to a quantity, then to a funnel state or deterministic inputs, then to a validated pull.
- I3. No execution path exists.
- I4. No model client is imported (D2).
- I5. Statuses never move up without new data. Degradation is never silent.
- I6. Bounds, thresholds, templates and phrasing come from registries.
- I7. The run record is append-only.
- I8. Guarantee prose comes from templates only.
- I9. CTR/CVR coupling is present in every joint-route spec. Order value is always a modeled stage.
- I10. A prior requires approval before use.
- I11. Causal verbs require a randomized design. "Incremental" requires a holdout.
- I12. No dollar decision runs without approved economics and a loss tolerance.
- I13. Synthetic data never reaches a client report.

**Registry defaults** (written by S0; changing any of them is a registry version bump, never a code change):

| Key | Default | Source |
|---|---|---|
| rate target / caveat edge | 0.20 / 0.40 relative half-width at 90% | D10 |
| decision marginal multiplier | 2 × tolerance | engineering choice; to calibrate on shadow runs |
| `min_ads_for_coupling` | 8 | D11; SBC may lower it |
| LKJ η | 2.0 | weakly regularizing convention |
| `min_days_for_dynamics` | 21 | engineering choice |
| plausibility ceiling (99th pct) | CTR 0.20, CVR 0.50 | engineering choice |
| R̂ / ESS bulk, tail / divergences | ≤ 1.01 / ≥ 400 / 0 | Stan and ArviZ guidance (Manuscript n. 9, 17) |
| PPC band | [0.05, 0.95] per stage | convention, disclosed as such |
| chains / draws / warmup / target_accept | 4 / 1000 / 1000 / 0.9 | NumPyro common practice |
| `min_lagged_conversions` | 50 | engineering choice |
| `min_maturity` | 0.90 | engineering choice |
| default lag curves | geometric, median 1 day (1-day windows), 2 days (7-day), 4 days (28-day) | placeholder, disclosed as "conversion lag assumed" |
| compound-gamma k (no orders file) | 2.0 | placeholder, disclosed |
| `max_age_days` (channel) | 90 | engineering choice |
| learning-phase switching cost | unknown (None) for all platforms | D13; disclosed per §8.2 C1 |
| `min_arm_share` | 0.10 | engineering choice |
| G5 rounding | match at the displayed precision of the bundle's formatter | §10 |
| default priors | Beta(1,49) CVR, Beta(2,98) CTR, Gamma(1, 1) per $ conversions | Manuscript ch. 2 and 4 teaching priors, approved as framework defaults |

---

## 15. Pieces, waves and checks

Neighbours across pieces meet only through interfaces. The acceptance writer generates fakes from those interfaces in `tests/fakes/`. A piece passes against fakes, and the integration test runs when its neighbour merges.

| Wave | Piece | Files | Frozen acceptance tests |
|---|---|---|---|
| 0 | S0 skeleton (integrator) | `pyproject.toml`; `core/` complete with G10 validators; all registries with the §14 defaults and every channel export map; every module as typed stubs; `tests/fakes/` | `test_S0_schema_examples_validate`, `test_S0_registry_swap_needs_no_code`, `test_S0_G10_rejects_bad_evidence_combos`, `test_S0_no_model_client_importable` |
| 1 | P1 data contract and channels | `data_contract/readers/`, `channels/` | `test_P1_quarantine_fuzz` (hypothesis, 500 cases: every invalid row quarantined with a reason, valid rows unchanged), `test_P1_reads_each_platform_export`, `test_P1_attribution_change_splits`, `test_P1_conversion_typing_C8`, `test_P1_stale_channel_blocks` |
| 1 | P2 simulator | `simulate/`, `data/scenarios/` | `test_P2_ground_truth_matches_totals`, `test_P2_exports_read_by_channel_maps`, `test_P2_seed_reproducible`, `test_P2_manifest_marked_synthetic` |
| 1 | P3 conjugate path and decision math | `inference/conjugate.py`, `funnel_state/`, `derived_metrics/`, `decision/compare.py`, `test_design/` | `test_P3_oracle_<case>` for every §9.2 row except floors, `test_P3_exact_and_sampled_agree`, `test_P3_G9_without_economics` |
| 1 | P4 floors, status, run record, guarantees | `floors/`, `status_registry/`, `decision/run_record.py`, `decision/guarantees.py` | `test_P4_oracle_floors`, `test_P4_less_data_never_improves_status` (property), `test_P4_decision_basis_governs_D9`, `test_P4_run_record_rejects_update_delete`, `test_P4_no_provisional_template_reachable` |
| 2 | P5 joint model and router | `model_spec/`, `inference/router.py`, `inference/sampler_numpyro.py` | `test_P5_uncoupled_spec_rejected`, `test_P5_small_account_routes_conjugate`, `test_P5_A1_roas_wider_with_modeled_value` (frozen-value reference lives in `tests/`), `test_P5_recovers_negative_dependence` (posterior P(ρ<0) > 0.9 on `negative_dependence`), `test_P5_fractional_uses_gamma_obs`, `test_P5_sbc` (slow: 100 fits of a reduced 6-ad spec, 20-bin rank histograms, χ² p > 0.01 per parameter after Bonferroni) |
| 2 | P6 diagnostics and fallback | `diagnostics/`, `inference/fallback.py` | `test_P6_rhat_fixture_fails_G3`, `test_P6_each_fallback_step_emits_notice`, `test_P6_quarantined_state_refused_by_derive` |
| 2 | P7 priors and lag | `prior_registry/`, `lag/` | `test_P7_unapproved_prior_blocks_fit`, `test_P7_predictive_check_refuses_implausible`, `test_P7_cohort_prior_oracle`, `test_P7_import_promoted_requires_id`, `test_P7_lag_thinned_likelihood_recovers_cvr` (on `lag_heavy`, true CVR in 90% interval) |
| 2 | P8 connectors | `data_contract/connectors/`, `data/recordings/` | `test_P8_<platform>_replay_parses` ×4, `test_P8_empty_account_flagged`, `test_P8_recordings_contain_no_secrets`, `test_P8_fields_in_facts_pack` |
| 3 | P9 decisions and audit | `decision/stopping.py`, `decision/reallocation.py`, `decision/allocation.py`, `audit/` | `test_P9_hold_oracle`, `test_P9_premature_stop_refused`, `test_P9_below_floor_continues_or_not_knowable`, `test_P9_survival_floor_respected`, `test_P9_every_recommendation_templated_and_approval_required` |
| 3 | P10 claims and reporting | `claims/`, `reporting/` | `test_P10_A_ai_property` (generator below), `test_P10_tiny_campaign_not_knowable_block`, `test_P10_G7_blocks_untraced`, `test_P10_client_report_refuses_synthetic`, `test_P10_diagnostics_appendix_real` |
| 4 | P11 pipeline, socket, smoke | `pipeline.py`, `atmaos/` | `test_P11_result_fits_BayesianResult` (validates against a copy of `base.py`'s model), `test_P11_evidence_matches_G3_4`, `test_P11_record_approval_G6`, `test_P11_smoke_every_scenario`, `test_P11_shadow_replay_writes_scores` |

**`test_P10_A_ai_property` generator.** For each of 120 bundles built from simulator scenarios (40 of them `tiny_campaign` or `fractional_conversions`):

1. Render a clean draft from templates. The checker must accept it.
2. Make five corrupted copies, each injecting one violation: a wrong number, a below-floor rate stated as a finding, a causal verb without randomization, a missing marginal caveat, or a comparative with no comparison.
3. The checker must reject every corrupted copy, naming the injected claim.

The ground truth is the injection list.

**Merge gate per piece.** The piece's frozen tests pass, the full suite passes, ruff is clean, and the diff stays inside its file list. The slow SBC test runs at P5's merge and nightly, not on every commit.

---

## 16. Facts packs (`spec/facts/`)

| Pack | Contents | For |
|---|---|---|
| F1 | Export column names per platform (Meta Ads Manager, Google Ads report, LinkedIn Campaign Manager, GA4), attribution window encoding, currency and timezone, which conversion fields may be modeled | S0 (channel maps), P1, P2 |
| F2 | Meta Marketing API: insights endpoint, fields, breakdowns, attribution settings, pagination, rate limits, version on build day; recorded sandbox probe | P8 |
| F3 | Google Ads API: GAQL resources and metrics, days-to-conversion segment, test accounts (serving metrics empty), developer token levels, login-customer-id | P8, P7 |
| F4 | LinkedIn Marketing API: adAnalytics finder and pivots, fields, versioned header, tiers, recorded test-account probe | P8 |
| F5 | GA4 Data API runReport; BigQuery sample dataset schema and terms | P1, P8, §9.3 |
| F6 | NumPyro, JAX, ArviZ versions pinned on build day; LKJ and non-centered patterns; ArviZ signatures | P5, P6 |
| F7 | AtmaOS: `base.py`, G3.4, G8 text, `Record` base, frozen test names | P11 |

Every endpoint and field named in connector code must appear in its pack.

---

## 17. Open for the owner

1. A small owner-funded campaign, or an existing ad account of your own with past campaigns, as the one real-data shadow account before a client exists.
2. GA4 credentials: a Google Cloud service account, separate from the three ad-platform keys.
3. The registry defaults marked "engineering choice" or "placeholder" in §14. They ship disclosed and get calibrated on shadow runs, unless you want different starting values.
