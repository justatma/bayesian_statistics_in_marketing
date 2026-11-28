# Bayesian Marketing System — Technical Specification

**Version 0.1 — Build & Assessment Specification**
**Companion to:** *Bayesian Marketing Decision Framework* v0.1 (the "Framework"). The Framework defines *what and why*; this document defines *what to build and how to judge it*.
**Intended reader:** Claude Code (build + assessment), and the human team reviewing its work.

**How to use this document:**
- §§1–4 (stack, layout, core schemas) are **load-bearing** — every module depends on them. Build them first; change them only with an explicit spec revision.
- §§5–9 specify each module's **interface, contracts, failure behavior, and acceptance criteria**. The acceptance criteria are the assessment instrument: code is done when its criteria pass, not when it runs.
- §10 defines the **gate contracts** — the system's enforcement points. §11 defines the **global invariants**. When building or reviewing, check invariants first; an invariant violation outranks any local convenience.
- §12 sequences the build into milestones. **Do not begin a milestone before the previous one's gates pass end-to-end.**

---

## 1. Technology Decisions (fixed unless revised)

| Decision | Choice | Rationale |
|---|---|---|
| Language | Python 3.12 | v1 heritage; ecosystem for inference |
| Schema/validation | **pydantic v2** for every object crossing a module boundary | Gates need machine-checkable contracts |
| Inference backend | `PosteriorSampler` **protocol** (interface), reference implementation **NumPyro (JAX/NUTS)** | Speed + scale; PyMC acceptable as alternate behind the same protocol |
| Posterior storage | **Parquet** files (samples) + metadata JSON | Columnar, portable, diffable metadata |
| Ledgers & registries | **DuckDB/SQLite** (append-only tables) for decision ledger; **versioned YAML** in git for bound/channel/ceiling/prior registries | Registries must change by config, not code (Framework §9.3) |
| Reporting | HTML template → PDF (WeasyPrint or ReportLab) | v1 heritage retained |
| LLM access | Single client module behind `AIService` protocol; model name is **config, never hard-coded** | v1's stale hard-coded model is the cautionary tale |
| Config | Per-client JSON/YAML in `configs/`, credentials via environment or secret store only | Carried over from v1 overview doc |

**Dependency rule:** layers depend downward only (L5 → L4 → L3 → L2 → L1 → core schemas). AI services (§8) may *read* any layer's outputs but may only *write* proposals. No module imports the LLM client except `ai_services/`.

---

## 2. Repository Layout

```
bayesian_marketing/
├── core/                  # §4 schemas: types every layer shares
│   ├── quantities.py      # Quantity, DistributionSpec, Feasibility, Provenance
│   ├── gates.py           # GateResult, Gate protocol, GateRegistry
│   ├── decisions.py       # Recommendation, Guarantee, LedgerEntry
│   └── registries.py      # Registry loader + version resolution
├── data_contract/         # L1 §5.1 — ingestion + validation
│   ├── platforms/         # meta.py, linkedin.py, ga4.py (API clients)
│   ├── schema.py          # PlatformPull validation
│   └── normalize.py       # units, timezones, attribution windows
├── model_spec/            # L1 §5.2 — declarative funnel models
├── prior_registry/        # L1 §5.3 — versioned priors + elicitation records
├── funnel_state/          # L1 §5.4 — posterior persistence & access
├── floors/                # L2 §6 — estimability, detectability, path barriers
├── status_registry/       # L2 §6 — authoritative feasibility statuses
├── inference/             # L3 §7 — router, sampler_pool, crosstab_exact, fallback
├── diagnostics/           # L3 §7 — suite + gates
├── decision/              # L4 §8 — allocation, reallocation, long_run, stopping,
│                          #         guarantees renderer, ledger
├── channels/              # L5 §9 — channel models + ceiling estimator
├── ceilings/              # L5 §9 — optimization cap registry + language
├── ai_services/           # §8 cross-cutting — elicitation, criticism, design,
│                          #   narration, guarantee translation (proposals only)
├── reporting/             # gated rendering: HTML/PDF + dashboards
├── registries/            # VERSIONED YAML: bounds.yaml, channels.yaml,
│                          #   ceilings.yaml, priors/, guarantee_templates.yaml
├── configs/               # per-client configs (gitignored secrets pattern)
├── tests/
│   ├── unit/
│   ├── property/          # hypothesis-based
│   ├── simulation/        # SBC + synthetic-funnel calibration
│   └── gates/             # one test file per gate contract (§10)
└── pipeline.py            # orchestration: the end-to-end run (§10.6)
```

---

## 3. Global Types & Conventions

- All timestamps UTC ISO-8601. All money in account currency with explicit `currency` field; no implicit floats-as-dollars.
- Every public function is type-annotated; every object crossing a module boundary is a pydantic model.
- `RegistryRef = str` — a key like `"bounds/estimability/gaussian_regression@v1.2"`. Bounds, ceilings, channels, and guarantee templates are **always referenced through registries, never hard-coded** (Invariant I6).
- Hashing: `inputs_hash = sha256` of the canonical JSON of gate inputs — stored in every `GateResult` so assessments are replayable.

---

## 4. Core Schemas (`core/`)

These are the contracts every gate inspects. Field names and required fields are normative.

### 4.1 `DistributionSpec` — any probability distribution

```python
class DistributionSpec(BaseModel):
    kind: Literal["analytic", "samples"]
    family: str | None              # "beta" | "gamma" | "invgamma" | "lognorm" | ... (analytic only)
    params: dict[str, float] | None # {"alpha": …, "beta": …} (analytic only)
    samples_path: str | None        # parquet path (samples only)
    n_samples: int | None
    summary: dict[str, float]       # REQUIRED always: {"mean", "sd", "q05", "q50", "q95"}
```
**Contract:** `summary` is mandatory regardless of representation, so downstream consumers never branch on `kind` for basic reporting. Analytic and samples representations must agree with each other within Monte Carlo error when both exist (tested, §13).

### 4.2 `Scope` — what a quantity is about

```python
class Scope(BaseModel):
    level: Literal["ad", "ad_set", "campaign", "account", "vertical"]
    ids: dict[str, str]             # {"account": "…", "campaign": "…", "ad": "…"}
    window: tuple[datetime, datetime]
    platform: str | None            # None for cross-platform aggregates
```

### 4.3 `Provenance` — the traceability chain (Invariant I2)

```python
class Provenance(BaseModel):
    funnel_state_id: str            # which posterior produced this
    model_version: str              # model_spec version
    data_pull_ids: list[str]        # validated ingestion batches
    derived_by: str                 # function name in derived_metrics/
    computed_at: datetime
```
**Contract:** a `Quantity` with an empty or dangling `Provenance` is invalid. The reporting layer MUST refuse to render it (gate G7, §10).

### 4.4 `Feasibility` — Layer 2's verdict

```python
class Feasibility(BaseModel):
    status: Literal["estimable", "marginal", "below_floor"]
    bound_ref: RegistryRef          # which bound produced this verdict
    bound_version: str
    available: float                # e.g. conversions observed
    required: float | None          # floor for target precision (None if bound gives none)
    target_precision: float
    assumptions: list[str]          # plain-language, surfaced to clients
    checked_at: datetime
```
**Contract:** statuses may only move *down* (estimable → marginal → below_floor) as data flows downstream (Invariant I5). Nothing may set a status upward without re-running the originating floor check against new data, which produces a **new** `Feasibility` object (immutable update).

### 4.5 `Quantity` — the unit of all reporting

```python
class Quantity(BaseModel):
    name: str                       # "ctr" | "cvr" | "cpa" | "roas" | …
    scope: Scope
    estimate: DistributionSpec
    feasibility: Feasibility
    provenance: Provenance
    diagnostics_ref: str | None     # → DiagnosticsReport id; None only for conjugate fast path
    ceiling_ref: RegistryRef | None # Layer 5 cap, when applicable
```

### 4.6 `GateResult` + the Gate protocol

```python
class GateResult(BaseModel):
    gate: str                       # "G2_feasibility", …
    passed: bool
    blocking: bool                  # if True and passed=False → pipeline halts for this object
    reasons: list[str]              # machine + human readable
    inputs_hash: str
    checked_at: datetime

class Gate(Protocol):
    name: str
    def check(self, obj: BaseModel) -> GateResult: ...
```
**Contract:** every gate is a pure function of its input object + registries. Gates never mutate. Gate outcomes are logged to the run record. A `blocking=True` failure must leave an auditable trace (Invariant I4's enforcement mechanism).

### 4.7 `DiagnosticsReport`

```python
class DiagnosticsReport(BaseModel):
    sampler: str                    # "numpyro_nuts" | "vi" | "conjugate"
    rhat_max: float | None
    ess_bulk_min: float | None
    ess_tail_min: float | None
    n_divergences: int | None
    ppc_summary: dict[str, float]   # e.g. Bayesian p-values per stage
    loo: dict[str, float] | None    # elpd, se, vs. candidate models
    passed: bool                    # computed by diagnostics gate G3, not by the sampler
    thresholds_ref: RegistryRef     # thresholds are config, not constants in code
```

### 4.8 `Recommendation` + `Guarantee`

```python
class Guarantee(BaseModel):
    kind: Literal["constant_factor", "competitive_ratio", "posterior_probability", "none"]
    statement_math: str             # precise form, e.g. "E[value] ≥ c · OPT, c from bounds/…@v…"
    statement_plain: str            # MUST be rendered from guarantee_templates registry (Invariant I8)
    assumptions: list[str]
    bound_ref: RegistryRef | None
    bound_verified: bool            # mirrors [verified]/[provisional] — surfaced in UI

class Recommendation(BaseModel):
    action: Literal["allocate", "reallocate", "hold", "stop_test", "continue_test", "collect_more_data"]
    scope: Scope
    params: dict                    # e.g. {"allocation": {"ad_a": 0.7, "ad_b": 0.3}}
    basis: list[str]                # Quantity ids the decision rests on
    guarantee: Guarantee
    rationale: str                  # AI-drafted, template-validated
    requires_human_approval: Literal[True]   # v2.0: ALWAYS True (Invariant I3)
    status: Literal["proposed", "approved", "rejected", "executed", "expired"]
```

### 4.9 `LedgerEntry` (append-only)

```python
class LedgerEntry(BaseModel):
    recommendation_id: str
    posterior_state_id: str
    gate_results: list[GateResult]
    decided_by: str | None          # human approver; None while proposed
    decided_at: datetime | None
    realized_outcome: dict | None   # filled by later reconciliation jobs
```
**Contract:** the ledger store exposes **append and read only**. Any update/delete attempt raises (acceptance test A7).

### 4.10 `ChannelModel` / `CeilingEntry` / `PriorRecord` / `ElicitationRecord`

```python
class ChannelModel(BaseModel):
    platform: str
    signal_losses: list[Literal["aggregation", "modeled_conversions",
                                "attribution_window", "privacy_noise", "api_lag"]]
    loss_params: dict[str, float]   # e.g. {"deletion_rate_hat": 0.31}
    info_ceiling: float | None      # max recoverable information (units documented per bound)
    ceiling_ref: RegistryRef | None
    freshness_date: date            # stale → review task (Framework §7.6)

class CeilingEntry(BaseModel):
    problem_class: str              # "kernel_clustering" | "k_median" | "maxcut_allocation"
    cap: float
    algorithm_used: str
    current_gap: float | None       # None until measured
    bound_ref: RegistryRef
    verified: bool

class ElicitationRecord(BaseModel):
    source: Literal["ai_proposal", "human", "historical_fit"]
    rationale: str
    evidence_refs: list[str]        # past campaigns, vertical data, doc links
    author: str                     # person or ai_services/prior_elicitation
    created_at: datetime
    approved_by: str | None         # REQUIRED before use (gate G8)

class PriorRecord(BaseModel):
    parameter_path: str             # e.g. "cvr.logit_intercept.campaign[retail]"
    family: str
    params: dict[str, float]
    elicitation: ElicitationRecord
    version: str
```

---

## 5. Layer 1 Modules — Generative Model

### 5.1 `data_contract/` — ingestion that distrusts its sources

**Interface:**

```python
def pull(platform: str, account_config: ClientConfig,
         window: tuple[datetime, datetime]) -> PlatformPull: ...

class PlatformPull(BaseModel):
    pull_id: str                    # content hash of raw payload
    platform: str
    channel_model_ref: RegistryRef  # MUST resolve to a fresh ChannelModel (gate G1)
    rows: list[PerformanceRow]
    pulled_at: datetime

class PerformanceRow(BaseModel):
    entity_ids: dict[str, str]      # campaign/ad_set/ad
    date: date
    impressions: int
    clicks: int
    conversions: float              # float: platforms report modeled/fractional conversions
    conversions_modeled_share: float  # 0–1; platform-modeled fraction (drives Layer 5)
    spend: Money
    revenue: Money | None           # None = not measured on this platform
```

**Contracts:**
- C1: Every row validates against `PerformanceRow`; malformed rows quarantine (rejected + logged), never silently coerced.
- C2: Timezone normalization to account currency timezone happens here and only here; downstream modules assume UTC dates.
- C3: `conversions_modeled_share` is mandatory; if a platform API cannot provide it, the pull is flagged `partial_truth=True` and Layer 5's channel model must reflect the unknown share.
- C4: Pulls are idempotent per `(platform, account, window)`; re-pulls create new `pull_id`s, never overwrite (provenance integrity).

**Failures:** API failure → typed `IngestionError` with retry policy; stale `ChannelModel` (freshness_date exceeded) → G1 blocks with a review task.

**Acceptance (A-data):** fuzzed payloads (bad types, negative counts, timezone chaos, missing revenue) must be quarantined with reasons; no uncaught exceptions; no silent repairs.

### 5.2 `model_spec/` — the funnel, declared

**Interface:**

```python
class FunnelSpec(BaseModel):
    version: str
    stages: list[StageSpec]         # ctr, cvr, cost, value — see below
    hierarchy: list[Literal["ad", "ad_set", "campaign", "account", "vertical"]]
    dynamics: Literal["static", "random_walk", "state_space"]
    overdispersion: dict[str, bool] # per-stage Beta-Binomial switch

class StageSpec(BaseModel):
    name: Literal["ctr", "cvr", "cost", "value"]
    likelihood: str                 # "binomial" | "beta_binomial" | "gamma" | "lognormal" | …
    link: str | None
    covariates: list[str]           # e.g. placement, device, creative_cluster

def compile_model(spec: FunnelSpec, priors: PriorSet) -> CompiledModel: ...
```

**Contracts:**
- C1: **CTR and CVR are jointly modeled** — the compiled model must contain a coupling term (e.g., correlated random effects); a spec without one fails validation with `UncoupledFunnelError`. This encodes Framework Commitment 1.
- C2: `value` (revenue per conversion) is a modeled stage with its own likelihood; **any code path computing ROAS from a point-estimate value fails review** (acceptance test A1 is the enforcement).
- C3: `compile_model` is backend-agnostic; it emits a `CompiledModel` consumable by any `PosteriorSampler` implementation.
- C4: Structural zeros (paused ads, zero-delivery days) are explicit model inputs, not filtered rows.

**Acceptance (A-model):** compile the reference specs; verify (a) joint coupling present, (b) ROAS derived quantity carries value-stage uncertainty — regression test: posterior SD of ROAS under modeled value > SD under frozen value, on a fixture with revenue variance > 0.

### 5.3 `prior_registry/` — elicited, versioned, approved

**Interface:**

```python
def resolve(parameter_path: str, client: str, as_of: datetime) -> PriorRecord: ...
def propose(record: PriorRecord) -> str: ...        # AI or human proposal → pending
def approve(prior_id: str, approver: str) -> None: ...  # gate G8
```

**Contracts:**
- C1: A prior without an approved `ElicitationRecord` is unusable in production runs (gate G8 blocks).
- C2: Resolution order: client → vertical → framework default. Every hop is recorded in the returned record (`resolution_path` field).
- C3: Priors are immutable once used in a fitted `FunnelState`; revisions create new versions.

### 5.4 `funnel_state/` — the single source of truth

**Interface:**

```python
class FunnelState(BaseModel):
    state_id: str
    spec_version: str
    prior_versions: dict[str, str]
    data_window: tuple[datetime, datetime]
    posterior: DistributionSpec     # samples representation, parquet-backed
    diagnostics_id: str
    created_at: datetime

def load(state_id: str) -> FunnelState: ...
def latest(scope: Scope) -> FunnelState: ...
```

**Contracts:**
- C1: `FunnelState` is the **only** object `derived_metrics` may read. No module may recompute posteriors ad hoc.
- C2: States are immutable; new data → new state, linked by `supersedes` field.
- C3: Every state carries its `diagnostics_id`; states whose diagnostics failed gate G3 are quarantined — loadable for audit, blocked from `derived_metrics`.

### 5.5 `derived_metrics/`

**Interface:**

```python
def derive(name: str, state: FunnelState, scope: Scope) -> Quantity: ...
# registry of pure functions: ctr, cvr, cpa, roas, marginal_roas, p_superiority(a, b), expected_loss(...)
```

**Contracts:**
- C1: Pure functions of posterior samples — no I/O, no platform calls.
- C2: Comparisons (e.g., `p_superiority`) operate on **joint** samples of the two entities — never on independently drawn marginals (preserves funnel correlation; Framework Commitment 1).

---

## 6. Layer 2 Modules — Information Budget

### 6.1 `floors/estimability`

**Interface:**

```python
def estimability_check(quantity_kind: str, target_precision: float,
                       available: float, regime: RegimeInfo) -> Feasibility: ...
```

**Contracts:**
- C1: Bound parameters come from `registries/bounds.yaml` via `bound_ref` — never literals in code (I6). Registry entries carry: formula identifier, assumptions list, verification flag, source citation.
- C2: Conservative use policy (Framework §4.6): each bound entry declares its regime assumptions; `regime` mismatch → status downgraded one level with reason recorded.
- C3: Output feeds `status_registry`; no other module computes floors independently.

### 6.2 `floors/detectability`

```python
def detectability_check(segmentation: SegmentationProposal,
                        audience_graph_stats: GraphStats) -> Feasibility: ...
```
**Contracts:** segment-level quantities inherit the *worst* status of (segment floor, constituent quantities' floors). Below-threshold segmentations return `below_floor` with the threshold parameters recorded.

### 6.3 `floors/path_barriers`

```python
def path_feasibility(loss_rate_hat: float, path_length: int,
                     volume: int) -> Feasibility: ...
```
**Contracts:** gates any journey/path-level report. `loss_rate_hat` comes from the platform's `ChannelModel` (Layer 5) — Layer 2 never estimates loss itself; it consumes Layer 5's channel estimate. This is the L5→L2 dependency edge and the only one permitted.

### 6.4 `test_design/`

```python
def validate_design(design: TestDesign) -> DesignAssessment: ...
# DesignAssessment: per-question Feasibility + cost_of_knowing (Money) + recommended redesign
```
**Contracts:** runs **pre-spend**. `cost_of_knowing` uses current account CPA posterior medians; uncertainty in CPA → cost interval, not point.

### 6.5 `status_registry/`

```python
def publish(quantity: Quantity) -> None: ...    # writes authoritative status
def status_of(quantity_id: str) -> Feasibility: ...
```
**Contracts:**
- C1: Single writer (Layer 2). All other layers read.
- C2: Statuses are immutable once published; new data → new status object with `supersedes` link (mirrors §4.4 immutability rule).

**Layer 2 acceptance (A-floor):** (a) registry-swap test — bump a bound's version in YAML; outputs change with zero code edits; (b) monotonicity test — less data never improves a status; (c) below-floor quantities are physically unrenderable end-to-end (integration test with reporting, §9.3).

---

## 7. Layer 3 Modules — Inference

### 7.1 `inference/router`

```python
class PosteriorSampler(Protocol):
    def fit(self, model: CompiledModel, data: FunnelData,
            config: FitConfig) -> tuple[FunnelState, DiagnosticsReport]: ...

def route(spec: FunnelSpec, data: FunnelData) -> Route: ...
# Route = conjugate | nuts | vi — with recorded reason
```

**Contracts:**
- C1: `conjugate` route only when the *entire* fitted submodel is honestly conjugate AND hierarchy is absent (single isolated rate). Any hierarchy → NUTS/VI.
- C2: Route choice + reason logged to the run record.
- C3: VI route requires posterior-vs-NUTS agreement check on a burn-in subset before production use (documented tolerance in registries).

### 7.2 `inference/sampler_pool`

**Contracts:** non-centered parameterization default for hierarchical specs; deterministic seeds recorded in `DiagnosticsReport`; sampling config (chains, draws, target_accept) from config, versioned with the run.

### 7.3 `inference/crosstab_exact`

```python
def exact_crosstab_inference(table: ContingencyTable,
                             margins: MarginSpec,
                             query: CrossTabQuery) -> DistributionSpec: ...
```
**Contracts:** classical enumeration fallback for small tables; method (exact/enumeration) recorded in the result's `Provenance.derived_by`.

### 7.4 `diagnostics/suite` + gate

**Interface:**

```python
def run_diagnostics(state: FunnelState) -> DiagnosticsReport: ...
def compare_models(states: list[FunnelState]) -> ModelComparison: ...  # LOO-based
```

**Contracts:**
- C1: Thresholds (`rhat_max ≤ 1.01`, `ess_* ≥ 400`, `divergences = 0` as **defaults**) live in `registries/diagnostics.yaml`; per-client override allowed, logged.
- C2: `DiagnosticsReport.passed` is computed **only** by gate G3 (§10), never by the sampler — the sampler proposes evidence; the gate decides.
- C3: Posterior predictive checks run per funnel stage; stage-level misfit names the stage in `reasons`.

### 7.5 `inference/fallback`

**Contracts:** documented degradation chain: `nuts → vi → conjugate_isolated`. Each step emits a `DegradationNotice` attached to all affected Quantities; degraded quantities render with the notice in reports. Silent degradation is an invariant violation (I5-adjacent).

**Layer 3 acceptance (A-inf):** (a) **SBC** — simulation-based calibration on the reference funnel: posterior rank statistics uniform within tolerance across ≥ 100 synthetic fits; (b) gate-fixture test — a fixture with R̂ = 1.2 fails G3 and its Quantities cannot reach `decision/`; (c) VI agreement check enforced on first use per client.

---

## 8. Layer 4 Modules — Decision

### 8.1 `decision/early_allocation`

```python
def early_allocation(candidates: list[CandidateArm],
                     budget: Money,
                     constraints: MatroidSpec,
                     samples: SamplesPool) -> Recommendation: ...
```

**Contracts:**
- C1: Implements the one-sample allocation rule family; the bound (constant factor) is loaded from `bounds/allocation/one_sample@…` with its `verified` flag propagated into `Guarantee.bound_verified`.
- C2: Every output `Recommendation.params.allocation` sums to ≤ budget; constraint violations raise before a Recommendation is formed.
- C3: If any candidate's basis Quantities are `below_floor`, the rule may still run (that is the *point* of one-sample rules) but the Recommendation MUST say so in `rationale` and mark `guarantee.kind` accordingly — guarantees hold distributionally, not per-instance; the plain-language template (§10, G6) enforces this phrasing.

### 8.2 `decision/reallocation`

```python
def reallocation(current: AllocationState, proposed: AllocationState,
                 switching_costs: SwitchingCostModel) -> Recommendation: ...
```

**Contracts:**
- C1: `SwitchingCostModel` must include platform learning-phase reset cost per channel (from `channels/registry`) — a reallocation that ignores switching cost fails review.
- C2: The module computes the competitive benchmark from the registry bound and MUST be able to emit `action="hold"` when switching cost dominates guaranteed gain. "Hold" recommendations carry the same guarantee apparatus as active ones.
- C3: Every reallocation logs the computed regret-equivalent estimate into the ledger for later audit.

### 8.3 `decision/long_run`

**Contracts:** mean-payoff strategy computation behind `StrategySolver` protocol; solver version + bound version recorded. Out of scope for milestone M2 — interface only, implementation M3.

### 8.4 `decision/stopping`

```python
def stopping_rule(test: TestState) -> Recommendation: ...
# actions: stop_test | continue_test — gated by Layer 2 feasibility on the decision's own precision requirement
```

**Contracts:**
- C1: A `stop_test` recommendation requires the decisive Quantity to be `estimable` at the target precision *after* conversion-lag correction (Layer 1 input); marginal → `continue_test` with expected remaining cost.
- C2: Stopping thresholds (probability-of-superiority, expected-loss caps) are per-client config with framework defaults; logged per decision.

### 8.5 `decision/guarantees` — the renderer that may not improvise

```python
def render_guarantee(g: Guarantee, locale: str = "en") -> str: ...
```

**Contracts:**
- C1: `statement_plain` is produced **only** from `registries/guarantee_templates.yaml` (Invariant I8). Free-form guarantee prose is an invariant violation.
- C2: Templates carry slots for `bound_ref`, `verified` status, and assumptions; if `bound_verified=False`, the template must render the provisional marker (client-facing honesty, Framework §6.6).

### 8.6 `decision/log` — the ledger

**Contracts:** append-only store (§4.9); reconciliation jobs fill `realized_outcome`; quarterly audit report compares guarantees vs. outcomes (Framework §9.4) — `audit/guarantee_report.py` produces it.

**Layer 4 acceptance (A-dec):** (a) allocation sums/constraint fuzzing; (b) hold-recommendation fixture — engineered scenario where switching cost dominates must yield `hold`; (c) stopping gate — below-floor decisive quantity forces `continue_test`/`collect_more_data`; (d) every Recommendation in a simulation run has template-rendered guarantee and `requires_human_approval=True`.

---

## 9. Layer 5 + AI Services + Reporting

### 9.1 `channels/`

```python
def channel_model(platform: str, account: str, as_of: date) -> ChannelModel: ...
def estimate_ceiling(model: ChannelModel) -> float: ...   # info ceiling from registry bound
```

**Contracts:**
- C1: `freshness_date` older than registry's `max_age_days` → gate G1 blocks ingestion for that platform until a human reviews the channel entry.
- C2: `loss_params` feed Layer 2's path barriers and tighten estimability floors (the L5→L2 edge, §6.3).
- C3: Platform-modeled conversions share flows from `PerformanceRow.conversions_modeled_share` into the channel's effective noise estimate.

### 9.2 `ceilings/`

```python
def cap_for(problem_class: str) -> CeilingEntry: ...
def at_cap_language(entry: CeilingEntry) -> str: ...   # client-facing phrasing from language registry
```

**Contracts:** caps from `ceilings.yaml` only; `verified=True` caps may be stated as fact client-facing; `verified=False` caps render with provisional phrasing. `current_gap` is measured by benchmark jobs, never asserted.

### 9.3 `reporting/` — gated rendering

```python
def render_report(bundle: ReportBundle, config: ClientConfig) -> RenderedReport: ...
```

**Contracts:**
- C1: **Gate G7 enforces**: every rendered number traces to a `Quantity` with valid provenance + feasibility + (if sampler-produced) passing diagnostics. The renderer takes `ReportBundle` (Quantities + statuses + gate results), not raw dataframes — it *cannot* reach around the gates (this is structural, not policy).
- C2: Below-floor quantities render as the standard "not knowable yet" block with `required` vs `available` data and the cost-of-knowing link to test design.
- C3: Ceiling context renders alongside any segmentation/allocation quality claim ("at the provable cap" or gap statement).
- C4: Diagnostics appendix contains **real** sampler diagnostics for every fitted state — R̂, ESS, divergence counts, PPC summaries — or an explicit "conjugate fast path (exact)" note.

### 9.4 `ai_services/` — five roles, one leash

```python
class AIService(Protocol):
    def propose(self, request: AIRequest) -> AIProposal: ...

# Roles:
#  prior_elicitation   → proposes PriorRecord (needs G8 approval before use)
#  model_criticism     → interprets DiagnosticsReport → proposes ModelRevision
#  experiment_design   → proposes TestDesign scored by info-gain vs cost_of_knowing
#  narration           → proposes NarrativeBlock from Quantities + statuses
#  guarantee_rendering → MAY NOT free-style; fills templates only (I8)
```

**Contracts:**
- C1: **Proposals only.** No `AIService` output reaches a persisted artifact without passing its role's gate: elicitation→G8, criticism→diagnostics re-run must confirm improvement, design→Layer 2 floor validation, narration→G5 claim check.
- C2: **Narration claim check (gate G5):** extract every numeric/comparative claim from the draft; each must match a `Quantity` in the bundle within stated rounding; each claim's quantity must be `estimable` or `marginal` (marginal ⇒ caveat sentence mandatory); below-floor ⇒ claim must be the standard not-knowable phrasing. Unmatched or mislabeled claims → gate fails → draft rejected, logged, regenerated once, then human escalation.
- C3: LLM model name, temperature, and prompts are versioned config; prompt versions recorded in the run record.
- C4: `ai_services` never receives raw credentials; it reads sanitized bundles (client name/token redaction list from config).

**Acceptance (A-ai):** property test — for 100+ synthetic bundles including adversarial below-floor quantities, no rendered narrative contains a numeric claim absent from the bundle or a finding about a below-floor quantity.

---

## 10. Gate Contracts

Gates are the system's constitution. Each lists: **where** it fires, **input**, **pass criteria**, **on-fail behavior**. All gates emit `GateResult` (§4.6) to the run record.

| Gate | Fires at | Pass criteria (defaults; registry-configurable) | On fail |
|---|---|---|---|
| **G1 ingestion** | `data_contract.pull` | Channel model fresh; rows validate; timezone normalized | Quarantine rows; review task; pull blocked |
| **G2 feasibility** | `status_registry.publish` | Bound resolvable + regime match recorded | Quantity cannot be published; pipeline continues for others |
| **G3 diagnostics** | after every `fit` | R̂ ≤ 1.01; ESS_bulk/tail ≥ 400; divergences = 0; PPC stage checks within bands | `FunnelState` quarantined; fallback chain (§7.5) |
| **G4 ceiling** | segmentation/allocation quality claims | `CeilingEntry` exists and gap measured | Claim rendered without cap language → blocked until registry entry |
| **G5 narration** | every AI narrative block | All claims match bundle Quantities; statuses respected; templates used | Draft rejected → one regeneration → human escalation |
| **G6 decision approval** | before any `Recommendation` leaves the system | `status="approved"` by named human | v2.0: no execution path exists at all (I3) |
| **G7 provenance** | `reporting.render_report` | Every number ← valid `Quantity` chain | Render blocked; missing links enumerated |
| **G8 prior approval** | `prior_registry` resolution | `ElicitationRecord.approved_by` set | Fit blocked for that parameter path |

### 10.6 Pipeline orchestration (`pipeline.py`)

```
pull (G1) → compile model + resolve priors (G8) → fit (G3, fallback chain)
  → derive Quantities → feasibility (G2) → decision proposals (guarantee render, G6 pending)
  → narration draft (G5) → report render (G7, G4) → ledger append
```
**Contract:** the orchestrator treats gates as the only coordination mechanism — modules never call each other across layers except through the documented edges (§6.3 is the sole L5→L2 edge).

---

## 11. Global Invariants (assess these first)

- **I1** No independent per-metric models in production paths. Conjugate fast path exists only as §7.1-C1 subset or logged fallback.
- **I2** Every rendered number traces: Quantity ← FunnelState ← validated pull. (G7)
- **I3** v2.0 ships zero automated execution; every Recommendation requires named human approval.
- **I4** AI output never bypasses a gate; no module outside `ai_services/` imports the LLM client.
- **I5** Feasibility statuses never move upward without a new floor check on new data; degradations are always logged, never silent.
- **I6** Bounds, caps, thresholds, templates come from versioned registries. A hard-coded bound constant in module code is a build failure.
- **I7** Ledger is append-only.
- **I8** Guarantee plain language comes from templates only.
- **I9** CTR/CVR coupling present in every compiled funnel spec; revenue-per-conversion always a modeled stage.
- **I10** Every AI-elicited prior requires named human approval before use (G8).

---

## 12. Build Milestones

| Milestone | Contents | Exit gate |
|---|---|---|
| **M0 — honest minimal loop** | core schemas; conjugate path; estimability floors; G1,G2,G5,G7; single-metric report with below-floor rendering | A-floor integration test passes: a tiny campaign renders "not knowable yet" correctly |
| **M1 — joint model** | model_spec, prior_registry, NumPyro NUTS path, real diagnostics suite + G3, derived_metrics incl. joint comparisons | SBC passes; A1 (plug-in regression) passes |
| **M2 — decision layer** | early_allocation, reallocation (with hold), stopping, guarantees renderer, ledger, G6 | A-dec suite passes; guarantee audit report generates |
| **M3 — measurement reality + full AI** | channels, ceilings, path barriers, crosstab_exact, model_criticism + experiment_design roles | A-ai property test passes; ceiling language renders per registry |

## 13. Definition of Done (per module)

1. Interface implemented exactly as specified (signatures + pydantic models).
2. Its contracts have **tests named after them** (`test_C1_…`), including fuzz/property tests where listed.
3. Its gates emit `GateResult` and demonstrably block on failure (test in `tests/gates/`).
4. Registry-driven parameters proven swappable by a no-code-change test.
5. Docstring on every public function; a one-paragraph "what this module may never do" in its README section.

## 14. Explicit Non-Goals (v2.0)

- No automated execution of budget changes into ad platforms.
- No real-time/intraday bidding logic.
- No creative generation.
- No cross-client data pooling without explicit per-client consent flags in config (vertical-level pooling is aggregate-only).
- No new probability theory: bounds are consumed from registries, not re-derived in code.

---

*End of specification. Assessment workflow for Claude Code: build milestone → run its acceptance suite → verify invariants §11 → proceed.*
