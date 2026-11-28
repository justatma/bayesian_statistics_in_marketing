# Bayesian Marketing System: Technical Specification v0.2

**Engine:** ENG-BAYES in the AtmaOS inventory (`atma_brain/documents/AtmaOS_Canonical_Architecture_Inventory_v1.0.md` §V).
**Status:** draft for blind spec review. Nothing is built from it until the review's undecided list is answered.
**Date:** 2026-10-30.

**Sources, in order of authority for this engine.**

1. Owner decisions in `spec/decisions.md` (D1 to D8).
2. The AtmaOS inventory (architecture, boundaries, evidence classes).
3. *Bayesian Marketing Decision Framework* v0.1 (`Bayesian Upgrade Oct. 2026/`), the "Framework".
4. *How to Make Better Marketing Decisions with Statistics and AI*, manuscript of October 2026 (same folder), the "Manuscript". Its decision math and its North Pier numbers are normative here (D1).
5. *Bayesian Marketing System Specification* v0.1 (same folder), "v0.1". This document replaces it for building; v0.1 is kept unedited (D7).
6. The AtmaOS contract this engine must satisfy from outside: `atma_brain/src/atma_brain/adapters/bayesian/base.py` and `atma_brain/spec/03_agency.md` G3.4 and G8.

Where two sources conflict, the conflict goes in §17 as a question. It is never resolved by editing a source.

---

## 0. What changed from v0.1

| # | v0.1 | v0.2 | Why |
|---|---|---|---|
| 1 | No business economics | `ClientEconomics` in core; every decision in dollars needs it (§4.9) | Expected loss and break-even are impossible without contribution per order (Manuscript ch. 4, 7) |
| 2 | Quantities carry no evidence type | Every `Quantity` carries `evidence_class` and `design` (§4.5) | Inventory §VIII: delivery, platform-attributed, commercially realized and causally incremental must stay distinct |
| 3 | `conversions: float` feeds a binomial likelihood | Integer observed conversions and fractional platform-modeled conversions are separate fields with separate treatment (§5.1, §5.2 C6) | Manuscript ch. 9: a fractional count is not a binomial count |
| 4 | Revenue per conversion modeled with no data to identify its spread | Optional order-level file; compound model on daily totals when absent, with the wider interval disclosed (§5.2 C2) | Platforms report daily revenue totals |
| 5 | Google Ads missing | Added, with GA4 and an orders file (§5.1) | D6 |
| 6 | Stopping needs a lag correction nobody specifies | `lag/` module with interface and checks (§5.6) | v0.1 §8.4 C1 depends on it |
| 7 | CTR/CVR coupling unspecified | Correlated ad-level effects with an LKJ prior; disclosure when the prior dominates (§5.2 C1) | A two-ad test cannot estimate a correlation |
| 8 | Vertical pooling across clients | Vertical priors arrive only as approved, de-identified AtmaOS knowledge (§5.3 C4) | Inventory §VIII cross-client limits |
| 9 | Own DuckDB decision ledger and own approval gate | Local append-only run record; AtmaOS holds the ledger and approval of record (§8.6) | D3 |
| 10 | `ai_services/` with its own LLM client | No model calls. Claim check and prior intake are deterministic functions (§10) | D2 |
| 11 | Layout omits `derived_metrics/`, `test_design/`, `audit/` | Added (§2) | Consistency |
| 12 | No mapping to AtmaOS's `BayesianResult` | `atmaos/` socket with a field-by-field mapping (§11) | The frozen atma_brain test waits on it |
| 13 | Cost stage is "spend given conversions" | Spend is the control; the cost stage models impressions bought per dollar (§5.2 C3) | D8 |
| 14 | Floors, guarantees and ceilings rest on numbered research results | Floors computed from the posterior and the decision; guarantees are posterior probabilities and expected loss; research bounds sit in the registry as provisional and client-invisible (§6, §8.5) | D1 |
| 15 | No test data plan | `simulate/` writes platform-shaped exports with known truth; North Pier answer key (§9) | D5 |
| 16 | `Recommendation.status` includes `executed` while I3 forbids execution | `executed` removed; status mirrors the AtmaOS approval record | Internal contradiction |

---

## 1. Technology

| Decision | Choice | Note |
|---|---|---|
| Language | Python, `requires-python >= 3.12` | Matches atma_brain |
| Schemas | pydantic `>= 2.9` for every object crossing a module boundary | Matches atma_brain |
| Numerics | numpy, scipy | Conjugate path and decision math |
| Sampler | NumPyro on JAX (CPU), behind the `PosteriorSampler` protocol | v0.1 choice kept |
| Diagnostics | ArviZ | R̂ (rank-normalized split), ESS bulk and tail, LOO, PPC |
| Posterior storage | Parquet (pyarrow) plus metadata JSON | v0.1 choice kept |
| Run record | SQLite, append-only by trigger | Local only (D3) |
| Registries | Versioned YAML under `registries/` | v0.1 choice kept |
| Reports | Jinja2 HTML, WeasyPrint PDF | v1 used ReportLab; HTML first lets the same template serve a dashboard |
| HTTP | httpx | Connectors only |
| Property tests | hypothesis | |
| Lint and test | ruff (line length 100, rules E F I UP B SIM RUF), pytest, `@pytest.mark.piece("P#")` markers that skip until the piece merges | Matches atma_brain conventions |
| LLM | none | D2 |

**Dependency rule.** Layers depend downward only: decision → inference → model → data contract → core. `floors/` reads posteriors and registries and nothing above it. `atmaos/` and `reporting/` read everything and are read by nothing. No module imports an HTTP client except `data_contract/connectors/`.

---

## 2. Repository layout

```
spec/                         this spec, decisions.md, facts/ (facts packs), manifests/, reviews/
legacy/                       version 1, untouched (D4)
registries/                   versioned YAML: bounds.yaml, diagnostics.yaml, channels.yaml,
                              guarantee_templates.yaml, decision_defaults.yaml, priors/
configs/                      per-client config; secrets never here (.env only)
src/bayesian_marketing/
  core/                       §4 schemas: money, scope, quantities, feasibility, gates,
                              decisions, economics, provenance, registries loader
  data_contract/              §5.1 schema, normalize, quarantine
    readers/                  meta.py, google_ads.py, linkedin.py, ga4.py, orders.py (file exports)
    connectors/               meta.py, google_ads.py, linkedin.py, ga4.py (live API pulls)
  model_spec/                 §5.2 FunnelSpec, compile_model
  prior_registry/             §5.3
  funnel_state/               §5.4
  derived_metrics/            §5.5
  lag/                        §5.6
  floors/                     §6.1 estimability (detectability, path_barriers: interface only)
  status_registry/            §6.2
  test_design/                §6.3
  inference/                  §7 router, conjugate, sampler_numpyro, fallback
  diagnostics/                §7.4
  decision/                   §8 compare, stopping, reallocation, allocation, guarantees, run_record
  claims/                     §10 narration claim check (G5), prior proposal intake
  atmaos/                     §11 BayesianTool.compare socket and G3.4 evidence
  reporting/                  §12
  simulate/                   §9 scenario generator with ground truth
  audit/                      §8.7 guarantee-versus-outcome report
  pipeline.py                 §13.6
tests/
  acceptance/                 frozen; one file per piece
  oracle/                     North Pier answer key (§9.2)
  property/  simulation/  gates/
data/
  scenarios/                  scenario YAML (committed)
  recordings/                 redacted connector exchanges (committed)
  generated/                  simulator output (gitignored)
```

---

## 3. Conventions

All timestamps UTC ISO-8601. Dates are account-local after normalization and the timezone is recorded. Money is a `Money(amount: Decimal, currency: str)`; floats never stand for dollars. `RegistryRef` is a string such as `"bounds/estimability/posterior_width@v1"`. `inputs_hash` is sha256 of canonical JSON (sorted keys, no whitespace). Every random draw takes a seed that is recorded. Every public function has type annotations and a docstring.

---

## 4. Core schemas (`core/`)

Field names and required fields are normative. Schemas from v0.1 not repeated here carry over unchanged: `DistributionSpec` (§4.1), `Scope` (§4.2), `Provenance` (§4.3), `GateResult` and `Gate` (§4.6), `DiagnosticsReport` (§4.7), `ChannelModel` (§4.10), `ElicitationRecord`, `PriorRecord` (§4.10, plus `resolution_path: list[str]`).

### 4.4 `Feasibility`

As v0.1, with two fields added:

```python
class Feasibility(BaseModel):
    status: Literal["estimable", "marginal", "below_floor"]
    basis: Literal["quantity_precision", "decision_loss"]   # §6.1
    bound_ref: RegistryRef
    bound_version: str
    available: float
    required: float | None
    target_precision: float
    assumptions: list[str]
    reasons: list[str]          # every downgrade appends one; never empty when status != estimable
    checked_at: datetime
```

Statuses only move down as data flows downstream (I5). Moving up requires a new check on new data, producing a new object.

### 4.5 `Quantity`

```python
class Quantity(BaseModel):
    quantity_id: str
    name: str                    # ctr | cvr | cpa | roas | aov | cpm | contribution | ...
    scope: Scope
    estimate: DistributionSpec
    feasibility: Feasibility
    provenance: Provenance
    evidence_class: Literal["delivery", "platform_attributed",
                            "commercially_realized", "causally_incremental",
                            "deterministic", "simulated"]
    design: Literal["observational", "randomized", "holdout", "simulated", "none"]
    diagnostics_ref: str | None
    degradation: list[str]       # DegradationNotice ids, §7.5
    ceiling_ref: RegistryRef | None
```

**Contracts.** `evidence_class="causally_incremental"` requires `design in {"randomized", "holdout"}`; a validator rejects any other combination. Anything computed from platform-reported conversions is `platform_attributed`, whatever model produced it. `commercially_realized` requires an orders-file source in `provenance.data_pull_ids`. `simulated` requires a simulator source, and the reporting layer refuses to render a simulated quantity in a client report (it renders in test and demo reports, watermarked).

### 4.8 `Recommendation` and `Guarantee`

```python
class Guarantee(BaseModel):
    kind: Literal["posterior_probability", "expected_loss", "value_of_information",
                  "constant_factor", "competitive_ratio", "none"]
    statement_math: str
    statement_plain: str         # rendered from guarantee_templates only (I8)
    assumptions: list[str]
    bound_ref: RegistryRef | None
    bound_verified: bool

class Recommendation(BaseModel):
    recommendation_id: str
    action: Literal["allocate", "reallocate", "hold", "stop_test", "continue_test",
                    "collect_more_data", "repair_measurement", "not_knowable"]
    scope: Scope
    params: dict
    basis: list[str]             # quantity_ids
    economics_ref: str           # ClientEconomics version used
    guarantee: Guarantee
    expected_benefit: Money | None
    expected_loss: Money | None
    reversibility: Literal["reversible", "costly", "irreversible"]
    rationale_slots: dict[str, str]   # template slots; prose is filled in AtmaOS (D2)
    requires_human_approval: Literal[True]
    status: Literal["proposed", "approved", "rejected", "expired"]
    approval_ref: str | None     # AtmaOS approval id when approved or rejected
```

**Contracts.** `constant_factor` and `competitive_ratio` are permitted only when the registry entry they cite has `verified: true` and `regime_validated: true`. Until then the guarantee renderer refuses them (D1). `repair_measurement` and `not_knowable` are first-class outcomes (Manuscript Appendix C).

### 4.9 `ClientEconomics` (new)

```python
class ClientEconomics(BaseModel):
    economics_id: str            # versioned; recommendations cite it
    client: str
    currency: str
    price_per_order: DistributionSpec | Money       # or derived from AOV quantity
    variable_cost_per_order: Money                   # production, fulfillment, processing, returns
    contribution_per_order: Money                    # computed; validator checks the subtraction
    repeat_value: DistributionSpec | None            # lifetime value beyond first order, optional
    loss_tolerance: Money                            # largest expected loss the client accepts per decision
    survival_constraint: Money | None                # downside the client cannot absorb
    source: str                                      # who supplied it, when
    approved_by: str | None
```

**Contracts.** No dollar-denominated decision runs without an approved `ClientEconomics` (gate G9). Break-even CPA equals contribution per order; break-even revenue ROAS equals price over contribution (Manuscript Appendix A, exercise 4).

### 4.11 `RunRecord` (replaces v0.1 `LedgerEntry`)

```python
class RunRecord(BaseModel):
    run_id: str
    started_at: datetime
    engine_version: str
    config_hash: str
    dataset_hashes: list[str]
    gate_results: list[GateResult]
    quantities: list[str]
    recommendations: list[str]
    route_log: list[str]         # inference routes and reasons
    seeds: dict[str, int]
```

Append-only (I7). `realized_outcome` reconciliation happens in AtmaOS against its `outcomes` table; the engine's `audit/` reads it back through the socket.

---

## 5. Layer 1: the generative model

### 5.1 `data_contract/`

**Interface.**

```python
def read_export(platform: Platform, path: Path, config: ClientConfig) -> PlatformPull: ...
def pull(platform: Platform, config: ClientConfig, window: DateWindow) -> PlatformPull: ...  # connectors
Platform = Literal["meta", "google_ads", "linkedin", "ga4", "orders"]

class PerformanceRow(BaseModel):
    entity_ids: dict[str, str]           # account, campaign, ad_set, ad
    date: date
    impressions: int
    clicks: int
    conversions_observed: int | None     # whole-count conversions where the platform gives them
    conversions_reported: float | None   # the platform's headline figure, possibly modeled/fractional
    conversions_modeled_share: float | None
    attribution_window: str              # e.g. "7d_click_1d_view"; required
    spend: Money
    revenue_reported: Money | None

class OrderRow(BaseModel):                # orders file: commerce system or CRM export
    order_id: str
    ordered_at: datetime
    value: Money
    refunded: Money
    attributed_entity: dict[str, str] | None   # utm / click id join when available
```

**Contracts.**

- C1. Malformed rows are quarantined with a reason, never coerced. Clicks above impressions, negative counts, conversions above clicks and unknown currency all quarantine.
- C2. Timezone normalization happens here only.
- C3. If neither `conversions_observed` nor `conversions_modeled_share` is available, the pull is flagged `partial_truth=True`.
- C4. Pulls are idempotent per (platform, account, window, attribution_window); a re-pull gets a new `pull_id`.
- C5. A change in `attribution_window` within one window splits the data and records a measurement change; it is never silently merged (Manuscript ch. 10).
- C6. Readers accept the platform's own export column names; the mapping lives in `registries/channels.yaml`, not code.
- C7. Connectors write a redacted recording of every exchange when `RECORD=1`; tests replay recordings and never reach the network.

**Failures.** `IngestionError` typed by cause (auth, rate limit, schema drift, empty). An empty response from a sandbox or test account is `EmptyAccount`, not an error.

### 5.2 `model_spec/`

`FunnelSpec` and `StageSpec` as v0.1 §5.2, with stages `delivery` (impressions per dollar), `ctr`, `cvr`, `value`, and optional `lag`.

**Contracts.**

- C1. CTR and CVR are coupled: ad-level `(logit ctr, logit cvr)` are drawn from a bivariate normal around campaign means with an LKJ(η) prior on the correlation, η from the registry. A spec without the coupling fails validation (`UncoupledFunnelError`). When the number of ads is below `registries/diagnostics.yaml: min_ads_for_coupling`, every derived quantity carries the reason "funnel correlation set by prior, not estimated".
- C2. `value` is a modeled stage. With an orders file: order value is log-normal per ad, partially pooled. Without one: daily revenue given n conversions is Gamma(shape = n·k, rate = k/μ), the sum of n Gamma(k, k/μ) order values. A code path that computes ROAS from a fixed revenue-per-conversion fails acceptance test A1.
- C3. `delivery`: impressions on day d ~ Poisson(spend_d / CPM_ad × 1000) with log-CPM partially pooled. Spend is an observed input (D8).
- C4. Structural zeros (paused, zero spend) are explicit inputs, never filtered rows.
- C5. `compile_model` is backend-agnostic and emits a `CompiledModel` any `PosteriorSampler` accepts.
- C6. Fractional `conversions_reported` never enters a binomial likelihood. If only fractional counts exist, the cvr stage uses a Poisson rate on clicks with the fraction as a continuous observation, every resulting quantity is capped at `marginal` with the reason "platform-modeled conversions", and the report says so.
- C7. `dynamics: static` is the default and the fallback for windows shorter than the registry's `min_days_for_dynamics`; `random_walk` is available for longer windows.

### 5.3 `prior_registry/`

Interface as v0.1 §5.3 (`resolve`, `propose`, `approve`).

- C1. A prior without an approved `ElicitationRecord` blocks the fit for that parameter path (G8).
- C2. Resolution order client → vertical → framework default; every hop recorded in `resolution_path`.
- C3. Priors are immutable once used; revisions are new versions.
- C4. Vertical-level priors are accepted only as records imported from AtmaOS with a promotion id; the engine never computes a prior from another client's data.
- C5. `prior_from_cohorts(rates, discount)` implements the method-of-moments construction in Manuscript ch. 5 and records the discount as a disclosed judgment.
- C6. Every approved prior ships with a prior predictive check (Manuscript ch. 5): the 99th percentile of simulated CTR or CVR must fall below the registry's plausibility ceiling or approval is refused.

### 5.4 `funnel_state/`

As v0.1 §5.4. States are immutable, linked by `supersedes`, and quarantined when G3 fails.

### 5.5 `derived_metrics/`

As v0.1 §5.5, plus `aov`, `cpm`, `cpc`, `contribution`, `p_exceeds(threshold)`, `expected_opportunity_loss`. Comparisons use joint draws only.

### 5.6 `lag/` (new)

```python
def lag_cdf(platform: Platform, account: str, as_of: date) -> LagModel: ...
def mature_clicks(rows: list[PerformanceRow], lag: LagModel, as_of: date) -> list[float]: ...
```

- C1. The lag CDF is estimated from history when at least `min_lagged_conversions` exist, else taken from the registry default for the platform's attribution window, with that fact recorded.
- C2. Effective exposure for a click cohort of age a is clicks × F(a). The cvr likelihood uses effective exposure.
- C3. A stop decision (§8.3) may not cite a cohort younger than the registry's `min_maturity` (F(a) ≥ 0.9 by default).

---

## 6. Layer 2: the information budget

### 6.1 `floors/estimability`

```python
def quantity_feasibility(q: Quantity, target: PrecisionTarget, regime: RegimeInfo) -> Feasibility: ...
def decision_feasibility(options: list[Quantity], econ: ClientEconomics) -> Feasibility: ...
```

**Quantity basis.** Let w be the relative half-width of the 90% posterior interval. `estimable` if w ≤ target, `marginal` if w ≤ target × `marginal_multiplier`, else `below_floor`. `required` is the projected data volume at which the preposterior expected w reaches target, holding the posterior mean fixed. A hard minimum count (`min_events`) applies first as a conservative guard. All three numbers come from `registries/bounds.yaml` entry `bounds/estimability/posterior_width@v1`.

**Decision basis.** The decision is `estimable` when the expected opportunity loss of the best option is at most `ClientEconomics.loss_tolerance`; `marginal` when within `marginal_multiplier` of it; else `below_floor`, with `required` the projected volume at which it would fall under tolerance.

- C1. Bound parameters come from the registry (I6).
- C2. A regime mismatch (fractional conversions, attribution change inside the window, coupling set by prior) downgrades one level with a reason.
- C3. Research-result entries (Framework §11) exist in the registry with `verified`, `regime_validated` and `client_visible: false`; `floors/` never reads them (D1).
- C4. `detectability` and `path_barriers` are interfaces only in this version; calling them raises `NotInScope`.

### 6.2 `status_registry/`

As v0.1 §6.5: single writer, immutable statuses, `supersedes` links.

### 6.3 `test_design/`

```python
def evpi(decision: DecisionProblem) -> Money: ...
def evsi(decision: DecisionProblem, design: TestDesign) -> Money: ...
def cost_of_knowing(design: TestDesign, econ: ClientEconomics, state: FunnelState) -> MoneyInterval: ...
def validate_design(design: TestDesign) -> DesignAssessment: ...
```

- C1. EVSI follows Manuscript ch. 6: expected value with the test result minus expected value now, before test cost.
- C2. `cost_of_knowing` is an interval from the CPC and CPM posteriors, never a point.
- C3. A design whose test cost exceeds its EVSI is returned with recommendation "do not buy this test" and the cheapest redesign found that clears it, if any.
- C4. A design that cannot separate message from audience (no randomization) is labeled observational; anything it estimates is `platform_attributed` at best.

---

## 7. Layer 3: inference

### 7.1 `inference/router`

```python
def route(spec: FunnelSpec, data: FunnelData) -> Route   # conjugate | nuts | vi, with reason
```

- C1. `conjugate` only for an isolated rate or the Gamma-Poisson CPA model, with no hierarchy and no coupling. A conjugate route is labeled in every quantity and the report.
- C2. Route and reason go to the run record.
- C3. VI is behind a flag and, before first production use per client, must agree with NUTS on a held subset within the registry tolerance.

### 7.2 `inference/conjugate`

Beta-Binomial for rates; Gamma-Poisson for conversions per dollar, giving CPA ~ InvGamma(α + n, β + spend) (the v1 CPA update, kept, see `legacy/modules/cpa_model.py`). Exact, no diagnostics needed; the report says "conjugate fast path (exact)".

### 7.3 `inference/sampler_numpyro`

Non-centered parameterization by default; chains, draws, warmup and target_accept from config; seeds recorded.

### 7.4 `diagnostics/`

As v0.1 §7.4. Defaults in `registries/diagnostics.yaml`: R̂ ≤ 1.01, ESS bulk and tail ≥ 400, divergences = 0, per-stage PPC Bayesian p-value in [0.05, 0.95]. `passed` is set only by gate G3.

### 7.5 `inference/fallback`

Chain `nuts → nuts with simplified spec (no dynamics, then no coupling) → conjugate isolated`. Every step emits a `DegradationNotice` attached to every affected quantity. Dropping the coupling marks the result as violating I9 and caps every quantity at `marginal`.

---

## 8. Layer 4: decisions

### 8.1 `decision/compare`

```python
def compare(options: list[Quantity], objective: Objective, econ: ClientEconomics) -> Comparison
# Comparison: p_best per option, expected contribution per option, expected opportunity loss per
# option, p_exceeds_break_even per option, decision feasibility
```

Joint draws only. This is what the AtmaOS socket returns (§11).

### 8.2 `decision/reallocation`

- C1. Switching cost per channel (learning-phase reset, from `registries/channels.yaml`, with a disclosed default when unknown) enters the expected benefit.
- C2. Emits `hold` when expected benefit minus switching cost ≤ 0 or expected loss exceeds tolerance (Manuscript ch. 7: the $1,170 − $250 = $920 < $1,000 example is a frozen test).
- C3. Recommendations respect `survival_constraint` when set: an action whose 5th-percentile contribution breaches it is not recommended.

### 8.3 `decision/stopping`

- C1. `stop_test` needs a decision-basis `estimable` status computed on mature cohorts only (§5.6 C3).
- C2. Otherwise `continue_test` with the expected remaining cost from `cost_of_knowing`, or `not_knowable` when the required volume exceeds the client's stated test budget.
- C3. Thresholds are per-client config over registry defaults, logged per decision.

### 8.4 `decision/allocation`

Early allocation by posterior expected contribution under budget and per-arm caps (Thompson-style or expected-value split, chosen by config), with `guarantee.kind = "posterior_probability"`. The one-sample prophet rule of Framework §6.1 is an interface stub that raises `NotInScope` until its registry entry is verified (D1).

### 8.5 `decision/guarantees`

`render_guarantee(g) -> str` from `registries/guarantee_templates.yaml` only (I8). Every template names the model, the evidence class and the main assumption. Provisional entries render "provisional" or are refused per §4.8.

### 8.6 `decision/run_record`

SQLite, append-only by trigger, holding `RunRecord`s and `Recommendation`s as proposed. Approval status is read from AtmaOS through the socket, never set locally (D3).

### 8.7 `audit/`

`guarantee_report(window)` compares each recommendation's stated expected benefit and loss with outcomes reconciled in AtmaOS, or with simulator ground truth in shadow runs (§9.4).

---

## 9. Test data: simulator, answer key, public data (D5)

### 9.1 `simulate/`

```python
def generate(scenario: Path, seed: int, out: Path) -> GroundTruth: ...
```

A scenario YAML declares accounts, campaigns, ads, days, true parameters (CPM, CTR, CVR, their correlation, AOV distribution, lag distribution, modeled-conversion share, attribution window), and events (creative fatigue, delivery-mix shift, attribution-window change, tracking outage, pause). `generate` writes, per platform, files using that platform's own export column names, an orders file, and `ground_truth.json` with every true parameter and the true value of every derived quantity.

**Required scenarios** (`data/scenarios/`):

| Scenario | What it tests |
|---|---|
| `north_pier` | Day two and day fourteen totals from the Manuscript |
| `tiny_campaign` | Below-floor rendering end to end |
| `negative_dependence` | 12 ads, CTR and CVR negatively correlated; joint vs independent ROAS (Manuscript ch. 8) |
| `delivery_mix_shift` | 42 → 22 orders per 1,000 clicks with no within-placement change (Manuscript ch. 10) |
| `attribution_window_change` | C5 split and measurement-change notice |
| `lag_heavy` | Late conversions; premature stop must be refused |
| `fractional_conversions` | Modeled counts only; C6 cap to marginal |
| `switching_cost_hold` | Reallocation must say hold |
| `many_accounts` | Hierarchy, SBC and sampler load |

### 9.2 North Pier answer key (`tests/oracle/`)

Recomputed independently on 2026-10-30 with scipy 1.18.1 and integration (not sampling); every value matches the Manuscript.

| Case | Input | Expected |
|---|---|---|
| CTR day two | Beta(2,98) prior; A 40/2,000, B 34/2,000 | Beta(42,2058), Beta(36,2064); means 2.00%, 1.714%; 95% CI A 1.446%–2.641%, B 1.204%–2.311%; P(A>B) = 0.7548 |
| CVR day fourteen | Beta(1,49); A 8/400, B 18/340 | Beta(9,441), Beta(19,371); means 2.00%, 4.872%; 95% CI A 0.921%–3.480%, B 2.966%–7.215%; P(B>A) = 0.9907 |
| Expected contribution, 1,000 clicks | $32 contribution; CPC $1.25, $500/340 | A −$610.00, B +$88.39; P(B higher) = 0.9624 |
| Expected opportunity loss | same | choose A $704.21, choose B $5.82 (tolerance ±$0.01) |
| Break-even | same | thresholds 3.906%, 4.596%; P(A clears) = 0.0083, P(B clears) = 0.5741 |
| EVPI and EVSI | 40% success, +$2,000 / −$1,000; test 75% / 25% | EV now $200; EVPI $600; P(positive) 0.45; posteriors 2/3 and 0.1818; EVSI $250 |
| Sample size | 3% vs 4%, two-sided α 0.05, power 0.8 | 5,301 clicks per arm (5,300.74) |
| Prior from cohorts | rates .013 .017 .019 .021 .023 .027; discount 0.25; then 10/200 | κ 829.51; Beta(16.59, 812.92); Beta(4.148, 203.23); posterior mean 3.473% |
| Dependence | CTR 4%/CVR 1% or CTR 1%/CVR 5%; 10,000 imps, $200, $80 | paired ROAS 1.6, 2.0, mean 1.8; independent 0.4, 1.6, 2.0, 8.0, mean 3.0 |
| Delivery mix | 800/200 then 300/700 clicks at 5% / 1% | 42 then 22 orders |
| Economics | $80 price, $48 cost; then $56 cost | break-even CPA $32, ROAS 2.5; ROAS 3.33 |
| Hold | keep $1,000; switch 70% $1,500 / 30% $400; cost $250 | switch $1,170 − $250 = $920 → hold |

Tolerance: 4 significant figures unless stated.

### 9.3 Public data

Candidates, each verified in the facts pack (license, fields, access) before any test depends on it: the GA4 obfuscated sample e-commerce export in BigQuery public data (`bigquery-public-data.ga4_obfuscated_sample_ecommerce`, 2020-11-01 to 2021-01-31), for real order-level revenue and its spread; and any public ad-campaign dataset with impressions, clicks, spend and conversions per ad, if one with a usable license is found. Public data feeds the value-stage and lag checks; it is never presented as client evidence.

### 9.4 Shadow replay

A scheduled job feeds a scenario to the pipeline one day at a time, writes every recommendation to the run record, and scores it against ground truth: realized regret, interval coverage, and whether "not knowable" was said when the truth was in fact not resolvable from the data. This is the engine's standing calibration record until real accounts arrive.

---

## 10. AI boundary (`claims/`) (D2)

```python
def check_narrative(draft: str, bundle: ReportBundle) -> GateResult: ...   # G5
def intake_prior_proposal(proposal: PriorProposal) -> str: ...            # pending PriorRecord
```

- C1. `check_narrative` extracts every number, percentage, money amount and comparative ("higher", "beats", "caused") from the draft. Each number must match a quantity in the bundle within its rounding; each comparative must match a comparison in the bundle; any causal verb requires a `causally_incremental` quantity; below-floor quantities may appear only in the registry's "not knowable yet" phrasing; marginal quantities need the caveat sentence.
- C2. No module in this repo imports an LLM client. A test greps the dependency tree and source for known client packages.

---

## 11. AtmaOS socket (`atmaos/`)

The engine provides the function the atma_brain G8 adapter will call. The adapter itself is built in atma_brain under its G8 piece.

```python
def compare(dataset_uri: str, *, metric: str, variants: list[str], priors: dict[str, Any],
            window: dict[str, Any], segments: dict[str, Any]) -> dict    # BayesianResult-shaped
def observation_evidence(result: dict, tool_result_id: str) -> dict      # G3.4 evidence payload
```

| `BayesianResult` field | Filled from |
|---|---|
| `posterior` | per variant: `DistributionSpec.summary`, `feasibility`, `evidence_class`, `design`, `quantity_id` |
| `probability_best` | `Comparison.p_best` |
| `expected_loss` | `Comparison.expected_opportunity_loss` (amounts as strings with currency) |
| `uncertainty` | decision feasibility, intervals, degradation notices, diagnostics summary, route |
| `config_hash` | `RunRecord.config_hash` |
| `tool_version` | package version plus registry versions |

`observation_evidence` carries exactly the G3.4 list: tool version, dataset snapshot hash, window, metric, priors, configuration, segments, result, uncertainty and `tool_result_id`.

**Evidence class mapping** (inventory §VIII asks for a mapping, not a new epistemology):

| Engine `evidence_class` / `design` | Inventory class |
|---|---|
| raw `delivery` or `platform_attributed` row | observed metric |
| raw orders row | observed metric (commercially realized) |
| `deterministic` (break-even from economics) | deterministic derived quantity |
| posterior quantity, `observational` | model inference / prediction |
| posterior quantity, `randomized` or `holdout` | experimental estimate |
| `simulated` | simulation |

A proposal to add `feasibility` and `evidence_class` as first-class `BayesianResult` fields goes to atma_brain's G8 pack; this repo does not edit atma_brain.

---

## 12. Reporting (`reporting/`)

As v0.1 §9.3 C1 to C4, with: a knowability section listing what was observed, what was platform-modeled, what the attribution window was, and what is not knowable yet with required vs available; every number labeled with its evidence class in plain words ("platform-reported", "from your order system", "estimated by model", "from a randomized test"); simulated reports watermarked and never sent as client reports. Narrative blocks come from AtmaOS and pass G5 before render; a report with no narrative renders template sentences only.

---

## 13. Gates

| Gate | Fires at | Pass criteria (registry-configurable) | On fail |
|---|---|---|---|
| G1 ingestion | `read_export`, `pull` | rows validate; timezone normalized; attribution window present; channel model fresh | quarantine rows; pull blocked if channel stale |
| G2 feasibility | `status_registry.publish` | bound resolvable; regime recorded | quantity not published |
| G3 diagnostics | after every fit | §7.4 thresholds | state quarantined; fallback chain |
| G4 ceiling | allocation or segmentation quality claims | ceiling entry exists | claim blocked (dormant in this version: no such claims are made) |
| G5 narration | before any narrative renders | §10 C1 | draft rejected with the failing claims listed |
| G6 approval | before a recommendation is marked approved | AtmaOS approval record exists and names a person | stays proposed |
| G7 provenance | `render_report` | every number traces to a quantity with valid provenance, feasibility, diagnostics | render blocked; missing links listed |
| G8 prior approval | `prior_registry.resolve` | elicitation approved; prior predictive check passed | fit blocked for that path |
| G9 economics | any dollar-denominated decision | approved `ClientEconomics` | decision returns `not_knowable` with reason "no approved economics" |
| G10 evidence class | `Quantity` construction and render | §4.5 contracts; no simulated quantity in a client report | object rejected |

### 13.6 Pipeline

```
read/pull (G1) → lag → compile + resolve priors (G8) → route → fit (G3, fallback)
  → derive quantities (G10) → feasibility (G2) → decisions (G9, guarantees from templates)
  → run record → [AtmaOS: narration, approval (G6)] → claim check (G5) → render (G7)
```

---

## 14. Invariants

v0.1 I1, I2, I5, I6, I7, I8, I9 and I10 carry over. Changed:

- I3. No execution path exists in this repo. Platform writes, if ever, go through AtmaOS's `AdsAdapter` with its grants and approvals.
- I4. No LLM client is imported anywhere in this repo (D2).
- I11 (new). Causal language requires a randomized or holdout design.
- I12 (new). No dollar decision without approved economics.
- I13 (new). Simulated data never reaches a client report.

---

## 15. Pieces, waves and checks

Waves follow dependencies. Within a wave, builders run in parallel in their own worktrees, at most four. Each piece lists the files it may touch; a diff outside the list is refused.

| Wave | Piece | Files | Depends on | Frozen acceptance tests (`tests/acceptance/test_<piece>.py`) |
|---|---|---|---|---|
| 0 | S0 skeleton (integrator) | everything as empty contracts; `pyproject.toml`; registries with v1 entries; `core/` complete | spec review answered | `test_S0_schemas_validate_examples`, `test_S0_registry_swap_needs_no_code`, `test_S0_no_llm_client_importable` |
| 1 | P1 data contract readers | `data_contract/` except `connectors/` | S0 | `test_P1_quarantine_fuzz` (hypothesis), `test_P1_reads_each_platform_export`, `test_P1_attribution_change_splits`, `test_P1_fractional_kept_separate` |
| 1 | P2 simulator | `simulate/`, `data/scenarios/` | S0 | `test_P2_ground_truth_matches_generated_totals`, `test_P2_exports_parse_with_P1_column_maps`, `test_P2_seed_reproducible` |
| 1 | P3 conjugate path and decision math | `inference/conjugate.py`, `derived_metrics/`, `decision/compare.py`, `test_design/` | S0 | every row of §9.2 as `test_P3_oracle_<case>`; `test_P3_comparisons_use_joint_draws` |
| 1 | P4 floors, status, report | `floors/`, `status_registry/`, `reporting/`, `decision/guarantees.py` | S0 | `test_P4_tiny_campaign_renders_not_knowable`, `test_P4_less_data_never_improves_status`, `test_P4_G7_blocks_untraced_number`, `test_P4_simulated_not_in_client_report` |
| 2 | P5 joint model and sampler | `model_spec/`, `inference/router.py`, `inference/sampler_numpyro.py`, `funnel_state/` | wave 1 | `test_P5_uncoupled_spec_rejected`, `test_P5_roas_wider_with_modeled_value` (A1), `test_P5_sbc_reference_funnel` (≥100 fits, rank uniformity), `test_P5_recovers_negative_dependence` |
| 2 | P6 diagnostics and fallback | `diagnostics/`, `inference/fallback.py` | wave 1 | `test_P6_rhat_fixture_fails_G3`, `test_P6_degradation_never_silent`, `test_P6_quarantined_state_unreadable_by_derive` |
| 2 | P7 priors and lag | `prior_registry/`, `lag/` | wave 1 | `test_P7_unapproved_prior_blocks_fit`, `test_P7_prior_predictive_rejects_implausible`, `test_P7_cohort_prior_matches_oracle`, `test_P7_lag_corrects_immature_cohorts` |
| 2 | P8 live connectors | `data_contract/connectors/`, `data/recordings/` | P1 | `test_P8_<platform>_replay_matches_reader_schema` ×4, `test_P8_empty_account_is_not_error`, `test_P8_recordings_redacted` |
| 3 | P9 decisions | `decision/stopping.py`, `decision/reallocation.py`, `decision/allocation.py`, `decision/run_record.py`, `audit/` | wave 2 | `test_P9_hold_fixture`, `test_P9_premature_stop_refused`, `test_P9_below_floor_forces_continue`, `test_P9_run_record_append_only`, `test_P9_every_recommendation_templated_and_needs_approval` |
| 3 | P10 claims and AtmaOS socket | `claims/`, `atmaos/` | wave 2 | `test_P10_A_ai_property` (100+ adversarial bundles), `test_P10_causal_verb_needs_randomized`, `test_P10_result_fits_BayesianResult`, `test_P10_evidence_matches_G3_4` |
| 4 | Integrate and smoke | `pipeline.py` | all | `test_smoke_every_scenario_end_to_end`, `test_shadow_replay_scores_written` |

**Merge gate per piece.** Its frozen tests pass, the full suite passes, ruff is clean, and the diff stays inside its file list.

---

## 16. Facts packs required (`spec/facts/`)

| Pack | Contents | For |
|---|---|---|
| F1 platform exports | column names and meanings of each platform's standard export (Meta Ads Manager, Google Ads report, LinkedIn Campaign Manager, GA4 exploration), attribution window encoding, currency and timezone handling | P1, P2 |
| F2 Meta Marketing API | insights endpoint, fields (impressions, clicks, spend, actions, action_values), breakdowns, attribution settings, pagination, rate limits, API version current on build day, sandbox ad account behavior (recorded probe) | P8 |
| F3 Google Ads API | GAQL resources and metrics (impressions, clicks, cost_micros, conversions, conversions_value), test account behavior (serving metrics empty), developer token access level, login-customer-id | P8 |
| F4 LinkedIn Marketing API | adAnalytics finder, pivots, fields (impressions, clicks, costInLocalCurrency, conversion fields), tier and test account behavior (recorded probe), versioned header | P8 |
| F5 GA4 Data API | runReport, dimensions and metrics for sessions, purchases, revenue; demo property access; BigQuery sample dataset schema | P1, P8, §9.3 |
| F6 NumPyro and ArviZ | versions pinned on build day; LKJ, non-centered patterns; ArviZ rhat/ess/loo signatures | P5, P6 |
| F7 AtmaOS contract | `adapters/bayesian/base.py`, G3.4 text, G8 text, `Record` base class, frozen test names | P10 |

Every endpoint and field named in connector code must appear in its pack (build protocol step 8).

---

## 17. Undecided (for the owner, after blind review adds to it)

1. Registry defaults: target relative half-width (proposed 20%), `marginal_multiplier` (1.5), `min_events` (10 conversions), `min_ads_for_coupling` (8), `min_maturity` (0.9). These shape what clients are told is knowable.
2. Default `loss_tolerance` when a client has not set one: none (decision returns `not_knowable`) or a stated fraction of the decision's spend.
3. Switching cost default for a channel with no account history.
4. Whether to run a small owner-funded campaign (a book or Growth Bastards) to give the shadow job one real account. It costs real money and is the only route to real performance data before a client exists.
5. GA4 credentials: a Google Cloud service account, separate from the three ad-platform keys.
