# The Bayesian Marketing Decision Framework

**Version 0.1 — Framework Foundation Document**
**Status:** North-star reference for the rebuild of the Bayesian ad-performance template
**Purpose:** Define the theoretical framework, layer architecture, and design commitments that all subsequent specification and build work must implement. Nothing in the build may contradict this document; changes to this document require an explicit revision decision.

---

## 0. Provenance: What This Replaces

The original template (`bayesian_ads.ipynb` + `modules/`) was built around a simple implicit claim: *each metric of each ad is an independent coin — count outcomes, update a conjugate prior, report the posterior.*

That claim produced four independent closed-form updaters:

| Metric | v1 model | v1 limitation |
|---|---|---|
| CTR | Beta-Binomial on impressions → clicks | Independent of all other metrics |
| CVR | Beta-Binomial on clicks → conversions | Independent of CTR; no pooling across ads |
| CPA | Inverse-Gamma updated by conversions and cost | Heuristic construction, not derived from a generative process |
| ROAS | Gamma derived from CPA posterior | `revenue_per_conversion` plugged in as a fixed constant — its uncertainty is discarded |

Three structural flaws follow from that foundation, and the rebuild exists to fix them:

1. **The funnel was modeled as four coins.** CTR, CVR, CPA, and ROAS of the same ad are jointly distributed products of one process. Four independent updaters cannot express funnel correlation, cannot pool strength across ads, and cannot propagate uncertainty coherently.
2. **A random quantity was frozen.** ROAS treated revenue-per-conversion as a known constant, so the ROAS posterior inherited none of its true uncertainty.
3. **The diagnostics were decorative.** v1 plotted i.i.d. draws from already-known closed-form posteriors and captioned them as evidence of "convergence." There was no iterative sampler, so there was nothing to converge. The appendix asserted a guarantee the system never tested.

The rebuild keeps v1's genuine virtues — transparency, explainability, conjugate speed where honest — and rebuilds the foundation.

---

## 1. Design Philosophy: Five Commitments

The framework is defined by five commitments. Every component, every output, and every client-facing sentence must be traceable to one of them.

**Commitment 1 — Knowledge is a joint posterior, not a table of metrics.**
The system's state of knowledge is the posterior distribution over a single, joint, hierarchical generative model of the funnel. CTR, CVR, CPA, ROAS, and every other quantity are *derived* from that one posterior. They are never modeled independently.

**Commitment 2 — Every reported quantity passes an information-budget check.**
Before any number reaches a report, the system classifies it as **estimable**, **marginal**, or **below floor**, using provable sample-complexity floors and detectability thresholds. Quantities below floor are reported as *not knowable from current data* — never smoothed over.

**Commitment 3 — Every recommendation is a decision rule with a stated guarantee.**
The system does not produce "insights." It produces decisions (allocate, reallocate, stop, continue) whose performance is stated relative to a provable optimum — e.g., "guaranteed within a constant factor of the offline optimum even with one observation per ad set."

**Commitment 4 — Every claim respects the measurement channel's ceiling.**
Platform reporting is a noisy channel with provable information ceilings (privacy aggregation, attribution loss). The framework treats those ceilings as fixed constraints and states them to clients. No component may promise precision the channel cannot carry.

**Commitment 5 — AI proposes; verification gates decide.**
AI is used aggressively — to elicit priors, criticize models, design experiments, and draft narratives — but nothing reaches a client without passing the deterministic gates: information-budget status, convergence diagnostics, and ceiling checks.

The intended epistemological stance in one sentence:

> *We maintain an honest, joint state of knowledge about the funnel; we say what is knowable, recommend what is defensible, and state the limits of both.*

---

## 2. Architecture at a Glance

```
                    ┌─────────────────────────────────────────────┐
                    │        CROSS-CUTTING: AI SERVICES           │
                    │  prior elicitation · model criticism ·      │
                    │  experiment design · gated narration        │
                    └──────────────┬──────────────────────────────┘
                                   │ (proposals only — never ungated output)
┌──────────────────────────────────▼──────────────────────────────────┐
│ LAYER 1 — GENERATIVE MODEL        "What the world is"               │
│ Joint hierarchical funnel: impressions → clicks → conversions → $   │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ joint posterior over funnel state
┌──────────────────────────────────▼──────────────────────────────────┐
│ LAYER 2 — INFORMATION BUDGET      "What is knowable from this data" │
│ Estimability floors · detectability thresholds · path barriers      │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ feasibility status per quantity
┌──────────────────────────────────▼──────────────────────────────────┐
│ LAYER 3 — INFERENCE               "How knowledge is computed"       │
│ Conjugate fast path · gradient-based MCMC/VI · exact cross-tabs ·   │
│ real diagnostics (R̂, ESS, LOO, posterior predictive)                │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ verified posterior + derived quantities
┌──────────────────────────────────▼──────────────────────────────────┐
│ LAYER 4 — DECISION                "What the knowledge is for"       │
│ Early allocation · reallocation with switching costs ·              │
│ long-run reward · test stopping rules                               │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ decisions with stated guarantees
┌──────────────────────────────────▼──────────────────────────────────┐
│ LAYER 5 — MEASUREMENT REALITY     "What platforms let you see"      │
│ Noise ceilings on attribution · optimization caps on segmentation   │
└─────────────────────────────────────────────────────────────────────┘
```

**Data flow discipline:** information flows downward; *status flags flow with it*. A quantity that fails Layer 2's check arrives at Layer 4 already marked below-floor, and Layer 4 must recommend "collect more data" instead of an allocation. No layer may silently upgrade a status.

**Verification provenance:** Several bounding results drawn on below come from a 2026 research corpus of machine-generated proofs. Results marked **[verified]** carry a machine-checked Lean formalization. Results marked **[provisional]** are strong claims without completed formal verification; they are used as *design guidance and honest language*, never as hard-coded formulas. See §10 for the risk policy this implies.

---

## 3. Layer 1 — The Generative Model Layer

**"What the world is."**

### 3.1 Description

A single generative model of the advertising funnel replaces the four independent metric updaters. The model describes the causal chain every platform user travels:

```
impressions ──CTR──▶ clicks ──CVR──▶ conversions ──value model──▶ revenue
                          │                            ▲
                          └────── cost model (spend) ──┘
```

Every metric is a property of this chain, and the posterior over the chain's parameters is the system's complete state of knowledge. The model is **hierarchical** at four levels:

1. **Ad level** — each ad's funnel parameters.
2. **Campaign/ad-set level** — ads pool strength toward their campaign's distribution.
3. **Client/account level** — campaigns pool toward account-level regularities.
4. **Vertical level** — accounts pool toward cross-client regularities of their industry (this is where accumulated agency knowledge lives).

And **time-aware**: parameters evolve (random-walk or state-space dynamics), because creative fatigue, seasonality, and auction drift make any fixed-parameter model wrong within weeks.

Key modeling decisions:

- **CTR**: Binomial or Beta-Binomial (the latter when impression-level overdispersion appears, which it does on every real platform).
- **CVR**: Binomial or Beta-Binomial, *jointly modeled with CTR* so that click quality propagates (high-CTR/low-intent traffic must show up as correlated structure, not as two unrelated posteriors).
- **Cost**: spend given conversions modeled explicitly (Gamma or log-normal family), replacing v1's heuristic Inverse-Gamma update.
- **Revenue per conversion**: a *modeled random quantity* with its own likelihood — the direct fix for v1's plug-in flaw. ROAS is then a **derived functional of the joint posterior**, with every source of uncertainty propagated.
- **Zero-inflation and structural zeros**: new ads, paused ad sets, and platform delivery constraints produce zeros that are structural, not unlucky — modeled as such.

### 3.2 Objectives

1. One posterior from which every reportable quantity is derived — no independent metric models anywhere in the system.
2. Partial pooling such that a two-day-old ad borrows statistically defensible strength from its campaign, vertical, and history — instead of starting from a flat prior.
3. Full uncertainty propagation to derived metrics: ROAS intervals that include revenue-per-conversion uncertainty by construction.
4. A time dimension, so "the world changed" is a modeled event rather than a silent assumption violation.

### 3.3 Components (buildable modules)

| Component | Responsibility |
|---|---|
| `model_spec/` | Declarative model definitions (funnel stages, likelihoods, hierarchy, time dynamics) in a probabilistic programming language (PyMC or NumPyro) |
| `prior_registry/` | Versioned, documented priors per vertical and client; every prior carries an elicitation record (source, date, strength, justification) |
| `data_contract/` | Schema validation for platform ingestion (Meta, LinkedIn, GA4): required fields, units, timezone, attribution window — rejects malformed pulls before modeling |
| `derived_metrics/` | Pure functions mapping posterior samples → CTR/CVR/CPA/ROAS/ marginal-value distributions |
| `funnel_state/` | The persisted posterior object — the single source of truth all upper layers read |

### 3.4 Potential Outcomes

- Coherent joint statements impossible in v1: *"P(Ad A beats Ad B on ROAS) = 0.83, accounting for correlated CTR/CVR and revenue uncertainty."*
- New ads get informative shrinkage priors within hours instead of waiting days for standalone significance.
- Revenue-side uncertainty appears in client reports for the first time — typically widening ROAS intervals on small accounts, which is the honest answer.
- A substrate on which Layer 2's feasibility checks and Layer 4's decision rules can operate on the *whole* funnel rather than one coin at a time.

### 3.5 Marketing Analysis & Assessment Implications

- **Assessment language changes from point comparisons to joint probabilistic claims.** "Ad A has higher CVR" becomes "P(A > B) = 0.91 under the joint funnel posterior" — comparable across metrics because all come from one object.
- **Cross-campaign learning becomes a feature clients can feel**: an agency's history in a vertical visibly sharpens early reads for the next client in that vertical. This is a genuine competitive moat and should be marketed as such.
- **Honesty about small accounts**: hierarchical shrinkage will sometimes pull a flashy early result toward the vertical mean. The framework treats this as correct behavior, not a bug to be configured away.
- **Auditability**: because every number derives from one model, client questions of the form "where did this number come from?" have a single answer path — posterior ← funnel state ← data contract.

### 3.6 Failure Modes & Risks

- Misspecified hierarchy (over-pooling) can homogenize genuinely different ads → mitigated by Layer 3 model criticism and per-level variance monitoring.
- Time dynamics add model complexity; a static special case must remain available and is the correct fallback for short tests.
- Joint models fail jointly: Layer 3's diagnostic gates are the defense, and the conjugate per-metric fast path remains as degraded-mode fallback.

### 3.7 Replaces in v1

`cvr_model.py`, `cpa_model.py`, `roas_model.py`, and the inline CTR update in Cell 3; the flat Beta(1,1) default priors; the plug-in `revenue_per_conversion`.

---

## 4. Layer 2 — The Information Budget Layer

**"What is knowable from this data."**

### 4.1 Description

The framework's most novel layer. Its premise: *before computing what we believe, establish what is knowable.* Every quantity the system might report is first classified by feasibility against provable bounds:

- **Estimability floors.** Research result 140 **[verified]** proves that estimation under resource constraints requires samples on a provable order to reach a target precision — a floor no model, however clever, can go below. The layer operationalizes the principle: for each requested quantity and target precision, compute the minimum data requirement and compare against data on hand.
- **Detectability thresholds.** Result 229 **[provisional]** pins exact thresholds below which community (segment) structure in a network is *statistically unrecoverable by any algorithm*. Operationalized as: audience-segment reports carry a detectability check; below-threshold segments are not reported as findings at all.
- **Reconstruction barriers.** Result 122 **[provisional]** shows that reconstructing sequences from lossy, deletion-corrupted traces requires super-polynomially many samples at constant loss rates, and is feasible only when the loss rate is tiny. Operationalized as a feasibility gate on user-journey and path-level attribution from incomplete event streams.

The layer assigns every quantity one of three statuses:

| Status | Meaning | Downstream rule |
|---|---|---|
| **Estimable** | Data exceeds the floor for the target precision | Report normally |
| **Marginal** | Within a defined band of the floor | Report with widened intervals + explicit caveat |
| **Below floor** | Provably insufficient data | Report as "not knowable yet"; Layer 4 must not act on it |

### 4.2 Objectives

1. Make "we can't know that yet" a computed, defensible system output rather than an analyst's judgment call.
2. Size test campaigns *before* spend: given a target decision (e.g., distinguish 15% relative CVR lift), output required impressions/clicks/conversions and the dollar cost of knowing.
3. Prevent the two classic failure modes of marketing analytics: over-reading small samples, and segmenting audiences below the detectability threshold.
4. Give the narration layer a hard rule it cannot violate: never narrate a below-floor quantity as a finding.

### 4.3 Components

| Component | Responsibility |
|---|---|
| `floors/estimability` | Minimum-sample calculators per quantity class (rate, ratio, revenue metric), parameterized by target precision and confidence |
| `floors/detectability` | Segment-detectability checker: given audience-graph density and volume, classify candidate segmentations as detectable/below threshold |
| `floors/path_barriers` | Feasibility gate for journey-level reconstruction given observed event-loss rates |
| `test_design/` | Pre-spend validator: proposed test design → floor check → expected cost of a conclusive answer |
| `status_registry/` | The authoritative per-quantity status object consumed by Layers 3–5 and narration |

### 4.4 Potential Outcomes

- A **cost-of-knowing number** attached to every proposed test: "Distinguishing these two creatives at 90% confidence requires ≈ N conversions ≈ $X at current CPA." This transforms budget conversations with clients.
- Automatic suppression of statistically impossible deliverables (e.g., segment-level ROAS on a segment with 6 conversions).
- A defensible answer to the eternal client question "why do we need a bigger test budget?" — a floor, not an opinion.
- Honest early-campaign behavior: week-one outputs are mostly "marginal/below floor," which is the truth, and the system says so.

### 4.5 Marketing Analysis & Assessment Implications

- **Test design becomes a pre-spend deliverable.** Assessment shifts from post-hoc ("the test was inconclusive") to ex-ante ("this design cannot resolve that question; here is the design that can, and its price").
- **Segmentation claims gain a gate.** Audiences below the detectability threshold are excluded from reported findings — eliminating a major source of phantom targeting insights and client whiplash.
- **Client trust mechanics change.** A system that sometimes says "not knowable yet" earns the right to be believed when it says "estimable, and here it is."
- **Competitive positioning**: few marketing analytics products can state *why* a question is unanswerable with a bound behind it. This is a differentiator in pitches and QBRs.

### 4.6 Failure Modes & Risks

- The underlying bounds are largely **worst-case/asymptotic**; used naively they can be over-conservative. Policy: floors are conservative design constraints with documented assumptions, tuned against simulation on realistic campaign regimes (see §9 verification policy).
- Two of the three bounding results are **[provisional]** — the layer is architected so a bound can be swapped or revised without touching downstream consumers (bounds live in the registry, not in code).
- Status labels must be presented as *engineering assessments*, not mathematical guarantees, in client-facing material.

### 4.7 Replaces in v1

Nothing — this layer is entirely new. v1 had no feasibility concept; its implicit claim was that every computable posterior is reportable, which is false.

---

## 5. Layer 3 — The Inference Layer

**"How knowledge is computed — and how we check the computation."**

### 5.1 Description

Layer 3 computes the Layer 1 posterior and *proves its own work*. It operates three routes, selected by model shape:

1. **Conjugate fast path.** Where a likelihood-prior pair is honestly conjugate (pure Beta-Binomial subproblems, e.g., a single isolated rate with no pooling), the closed form is used. This path is kept deliberately: it is fast, exact, and transparent — v1's one genuinely good idea.
2. **Gradient-based posterior computation.** The joint hierarchical model is sampled with real MCMC (NUTS-class samplers) or approximated with variational inference for large accounts. The theoretical license for this scaling story comes from result 139 **[provisional]**: well-conditioned log-concave posteriors — the class covering most hierarchical funnel models — are sampleable at near-dimension-free query cost, with a matching lower bound. Practically: gradient-based inference is the correct default, and there is a principled answer to "when is more tuning pointless?"
3. **Exact cross-tab inference.** Campaign reporting lives on contingency tables (segment × creative × outcome cells, margins fixed by platform delivery). Result 115 **[provisional]** — exact uniform sampling and approximate counting for such tables — underwrites *exact conditional inference* on cross-tabs where v1-style asymptotic approximations silently degrade on sparse cells.

**Diagnostics become real.** The v1 "trace plots" (i.i.d. draws from a known posterior, captioned as convergence evidence) are replaced by the standard, meaningful suite:

- **R̂** (split-chain potential scale reduction) and **ESS** (effective sample size) on every reported parameter;
- **Posterior predictive checks** — does the fitted model reproduce the observed data's shape?
- **LOO cross-validation** for model comparison (e.g., Binomial vs. Beta-Binomial; static vs. time-varying);
- **Divergence/treedepth monitoring** as sampler health signals.

No quantity proceeds to Layer 4 unless its sampler passed diagnostics. Failure routes to fallback (simpler model or conjugate fast path) with a logged degradation notice.

### 5.2 Objectives

1. Posterior computation that scales from a two-ad test to a multi-account agency portfolio without method changes.
2. Every published number accompanied by machine-checkable evidence that the computation converged and the model fits.
3. A model-criticism loop: misfit is detected by the system, not by a client's sharper eye.
4. Exact inference on sparse cross-tabs — the everyday reality of niche campaigns — instead of approximations that break exactly when data is scarce.

### 5.3 Components

| Component | Responsibility |
|---|---|
| `inference/router` | Selects conjugate / MCMC / VI per model and data regime |
| `inference/sampler_pool` | NUTS-class sampling with caching; VI for large-scale accounts |
| `inference/crosstab_exact` | Exact/approximate counting-based inference on contingency tables |
| `diagnostics/suite` | R̂, ESS, divergences, posterior predictive checks, LOO; emits pass/fail gates |
| `diagnostics/critic` | AI-assisted interpretation of diagnostic output (see §8) — proposes respecification, never overrides a failed gate |
| `inference/fallback` | Degraded-mode path: documented simplification chain when full model fails |

### 5.4 Potential Outcomes

- Every report carries a silent guarantee: *the numbers in this document passed convergence and fit checks*, with an appendix that means it this time.
- Sparse-segment inference stops producing absurd intervals (the classic asymptotic-approximation failure on 3-conversion segments).
- Model choice (pooled vs. unpooled, static vs. dynamic) becomes an evidenced comparison instead of a habit.
- VI path makes same-day posterior refresh feasible at agency scale.

### 5.5 Marketing Analysis & Assessment Implications

- **The diagnostics appendix becomes a trust asset** rather than decoration: sophisticated clients and procurement teams increasingly ask how marketing numbers are produced; a real diagnostics appendix is a credible answer.
- **Assessment cadence can accelerate**: reliable VI inference supports daily (or intra-day) posterior refresh, changing reporting from monthly PDFs to living dashboards — with the diagnostics gate preserving honesty at speed.
- **Model criticism is client-visible**: "we changed the model because the checks said so" is a maturity signal in assessment meetings.

### 5.6 Failure Modes & Risks

- MCMC on hierarchical models can be slow or funnel-prone → non-centered parameterizations as default; VI fallback with validated error bounds.
- Exact cross-tab methods rely on a **[provisional]** result → implemented behind the registry pattern with classical enumeration fallback on small tables.
- Diagnostic thresholds (e.g., R̂ < 1.01) are conventions, not laws → thresholds configurable per client risk posture, defaults conservative.

### 5.7 Replaces in v1

`diagnostics.py` (i.i.d. posterior draws mislabeled as convergence evidence) and Cell 5's trace-plot appendix. Replaced with the real suite above.

---

## 6. Layer 4 — The Decision Layer

**"What the knowledge is for."**

### 6.1 Description

v1's posteriors went into a PDF and stopped. Layer 4 converts posterior knowledge into **actions with stated guarantees**. It owns four decision families:

**1. Early-campaign allocation (the flagship capability).**
Grounded in result 111 **[provisional]**: distribution-independent allocation rules exist that need only **one observation per ad set** yet guarantee a universal constant fraction of the offline optimum — under matroid constraints (the mathematics of "split a budget across ad sets subject to capacity constraints"), and even when the environment is adversarial and observes your entire strategy. The design translation: *early campaigns do not need long exploration phases before a defensible budget commitment.* The layer implements one-sample allocation rules with the guarantee stated alongside every recommendation.

**2. Budget reallocation with switching costs.**
Moving budget between campaigns is not free: platform learning phases reset, delivery destabilizes. This is the structure of the k-server problem; result 110 **[provisional]** pins the best achievable worst-case competitive ratio. The layer benchmarks its reallocation policy against the provable optimum, and — critically — *declines* to reallocate when the switching cost exceeds the guaranteed gain. "Don't touch it" becomes a computed recommendation.

**3. Long-run reward optimization.**
Result 104 **[partially verified]** makes exact strategy computation for mean-payoff/stochastic games — the formal skeleton of steady-state ROAS optimization under an adversarial auction environment — tractable in regimes previously out of reach. Used for sustained-campaign strategy rather than daily knobs.

**4. Test stopping and continuation.**
Posterior-based stopping rules (probability of superiority, expected loss) — but every stopping decision passes back through Layer 2: a test may only stop early if the remaining uncertainty is estimable at the target precision. This closes the loop between the budget and decision layers.

### 6.2 Objectives

1. Every recommendation carries its guarantee in plain language: what the rule promises, relative to what optimum, under what assumptions.
2. Early-campaign decisions become defensible: act on one-sample rules with a constant-factor guarantee, or explicitly defer with the cost-of-knowing attached (Layer 2).
3. Reallocation decisions internalize switching costs; the system must sometimes recommend inaction, and say why.
4. A complete decision log: posterior state in → rule applied → action out → realized result, enabling guarantee-versus-outcome audit.

### 6.3 Components

| Component | Responsibility |
|---|---|
| `decision/early_allocation` | One-sample prophet-type allocation rules under budget (matroid) constraints |
| `decision/reallocation` | Switching-cost-aware reallocation policy + benchmark against provable competitive optimum |
| `decision/long_run` | Mean-payoff strategy computation for sustained campaigns |
| `decision/stopping` | Posterior stopping rules gated by Layer 2 floors |
| `decision/guarantees` | Plain-language guarantee renderer attached to every recommendation |
| `decision/log` | Append-only decision ledger for audit and guarantee validation |

### 6.4 Potential Outcomes

- The product's category shifts: from *reporting tool* to *decision system with audit trail*.
- Week-one campaigns get real recommendations ("commit 70/30 now — guaranteed within factor c of optimal, assumptions stated") instead of "insufficient data, check back."
- Fewer harmful reallocations: the system quantifies the cost of touching a campaign in learning phase and recommends patience when that dominates.
- Guarantee-versus-outcome audits accumulate into evidence the framework itself works — usable in sales and renewal conversations.

### 6.5 Marketing Analysis & Assessment Implications

- **Account management changes character**: budget meetings revolve around stated guarantees and the decision ledger, not chart interpretation.
- **Assessment becomes outcome-linked**: because every recommendation is logged with its guarantee, quarterly assessment can compute realized-versus-guaranteed performance — a genuinely new accountability artifact in marketing services.
- **Restraint as a billable virtue**: "we recommend not reallocating; switching cost exceeds guaranteed gain" is the kind of recommendation that retains clients, and only this layer can generate it credibly.
- **Risk communication improves**: guarantees are stated in worst-case terms, so upside surprises are common and downside is bounded — the right shape for client psychology.

### 6.6 Failure Modes & Risks

- The anchoring results are **[provisional]** and their guarantees are **worst-case/distributional** — they license the *rule shapes* and honest language, not literal performance promises. The `guarantees` renderer must never overstate.
- Decision automation raises agency liability questions → all decisions ship as recommendations with human approval in v2.0; automation is a later, explicitly-versioned step.
- Stopping rules interact with platform delivery lag (conversion delay) → conversion-lag correction is a required Layer 1 input before stopping logic engages.

### 6.7 Replaces in v1

Nothing — v1 had no decision layer at all. Its implicit endpoint was "the analyst reads the PDF and decides." Layer 4 makes the system's own reasoning explicit, guaranteed, and auditable.

---

## 7. Layer 5 — The Measurement Reality Layer

**"What platforms let you see."**

### 7.1 Description

Every number entering the system arrives through a degraded channel: privacy aggregation, ATT-era signal loss, modeled conversions, attribution windows, and platform-side estimation. Layer 5 makes the channel an explicit object with explicit limits, in two families:

**1. The noise ceiling on attribution.**
Result 119 **[provisional]** proves a sharp limit of information theory: after independent noise corrupts observations, no clever summary retains more mutual information than the single best coordinate — with exact contraction bounds at every signal strength. Translated: *there is a provable ceiling on what privacy-noised platform reporting can ever tell you, and no post-processing — Bayesian or otherwise — exceeds it.* The layer models each platform's reporting as a channel with a stated ceiling and refuses to promise precision beyond it.

**2. The optimization caps on what downstream tooling can achieve.**
Three **[verified]** results establish that classical marketing-analytics optimization problems are at their provable ceilings:

- **Result 102** — allocation/partitioning problems of the Max-Cut class: known approximation algorithms are provably optimal; no future solver does better.
- **Result 96** — kernel clustering (the backbone of audience/creative clustering): a specific loss factor is provably unbeatable.
- **Result 125** — k-median (segment-center and facility-type selection): the optimal approximation factor is pinned exactly.

The layer maintains a **ceiling registry**: for each optimization the system performs, the provable cap, the algorithm used, and the current gap to the cap. When the gap is zero, the system says "at the provable cap" — and effort moves elsewhere.

### 7.2 Objectives

1. Every platform integration carries an explicit channel model: what was measured, what was modeled by the platform, what was lost, and the resulting information ceiling.
2. Attribution claims are issued *relative to the ceiling*: "this is the maximum recoverable signal given the channel," not absolute truth language.
3. Optimization effort is allocated rationally: zero-gap problems are declared finished; engineering effort concentrates where a gap exists.
4. Client communication about measurement limits becomes specific and defensible instead of apologetic.

### 7.3 Components

| Component | Responsibility |
|---|---|
| `channels/registry` | Per-platform channel models: signal-loss type, aggregation level, attribution windows, modeled-conversion flags |
| `channels/ceiling_estimator` | Information-ceiling estimates per channel; feeds Layer 2 floors (channel loss tightens floors) |
| `ceilings/registry` | Provable optimization caps per problem class; current algorithm; measured gap |
| `ceilings/language` | Client-facing phrasing library for ceilings ("provably at the cap," "maximum recoverable signal") |

### 7.4 Potential Outcomes

- Attribution sections of reports change genre: from "here is what happened" to "here is the maximum knowable, and where we sit relative to it."
- An end to chasing impossible precision: the ceiling registry is a standing answer to "can we get more granular?" — sometimes the honest answer is "provably not, for anyone, on this platform."
- Rational R&D allocation: the registry shows which components are at their caps (stop optimizing) and which have headroom (invest).

### 7.5 Marketing Analysis & Assessment Implications

- **Measurement conversations become a strength.** Agencies lose clients over attribution disappointment; a system that states the ceiling *before* the campaign reframes disappointment as physics, and the agency as the honest broker.
- **Assessment reports gain a "knowability" section**: what was measured, what was modeled, what is provably unknowable this quarter — the single most credibility-building section a client report can have.
- **Competitive claims get discipline**: "our segmentation is at the provable cap" is a stronger sales line than "our AI is better" — and unlike the latter, it survives scrutiny.
- **Cross-platform comparisons get honest normalization**: channel ceilings differ per platform; comparing raw Meta and LinkedIn precision without ceiling context is an error the framework now prevents.

### 7.6 Failure Modes & Risks

- Channel models date quickly (platforms change reporting APIs and privacy policies) → registry entries carry freshness dates; stale channels trigger review tasks.
- Ceiling language must never be used to excuse sloppy measurement → Layer 5 reports what is *still measurable* with the same prominence as what is not.
- Result 119 is **[provisional]** → used as design guidance; the **[verified]** caps (102/96/125) are safe to state as fact.

### 7.7 Replaces in v1

v1's data loaders (`data_loader.py` stubs) ingested platform numbers as ground truth. Layer 5 makes the channel's limits a first-class object instead of an unmentioned assumption.

---

## 8. Cross-Cutting Layer — AI Services

**"AI proposes; verification gates decide."**

v1 used AI for exactly one thing: GPT-generated narrative prose about summary statistics (`openai_client.py`, still pointing at a deprecated model). The rebuild uses AI in five roles, all subject to one iron rule: **AI output is a proposal until it passes the deterministic gates.**

### 8.1 The five roles

**1. Prior elicitation (feeds Layer 1).**
LLMs convert client history, past campaign data, vertical knowledge, and account-manager judgment into *documented hierarchical priors* — each with an elicitation record in the `prior_registry`: source, rationale, strength, date. This replaces v1's flat Beta(1,1) defaults with an actual elicitation workflow, and converts agency experience into a compounding asset.

**2. Model criticism (feeds Layer 3).**
AI interprets diagnostic output — posterior predictive checks, LOO comparisons, R̂/ESS failures — and proposes respecifications ("CVR shows overdispersion; suggest Beta-Binomial"). Proposals are executed only if the diagnostics suite confirms improvement. The AI is the critic; the gates are the editor.

**3. Experiment design (feeds Layers 2 & 4).**
Given Layer 2 floors, AI proposes test designs — duration, split, budget allocation, success criteria — scored by expected information gain against the cost-of-knowing. Humans approve; the design enters the decision ledger.

**4. Gated narration (replaces v1's only AI role).**
The narrative model receives each quantity **plus its Layer 2 status and Layer 5 ceiling context**, under a hard prompt-level and output-level constraint: below-floor quantities may only be described as "not yet knowable"; marginal quantities only with their caveats; estimable quantities with their intervals. Output is validated against the status registry before rendering — a claim-checking pass, not a vibes pass.

**5. Guarantee translation (serves Layer 4).**
AI converts the decision layer's mathematical guarantees into accurate plain language, validated against templates — never free-styled. "Within a constant factor of the offline optimum" must not become "near-optimal performance guaranteed."

### 8.2 What AI is never allowed to do

- Override a diagnostic gate, a floor status, or a ceiling flag.
- Invent quantities, intervals, or guarantees not present in the pipeline outputs it receives.
- Narrate a below-floor quantity as a finding.
- Modify its own prompts, elicitation records, or validation rules.

### 8.3 Marketing Analysis & Assessment Implications

- **Narratives become trustworthy by construction**, which is what makes AI narration usable in client-facing documents at all — the difference between an AI feature and an AI liability.
- **The agency's accumulated expertise becomes infrastructure**: prior elicitation turns senior staff judgment into versioned, reusable priors — an asset that survives employee turnover.
- **AI-generated experiment designs make "test culture" cheap** to offer every client, not just sophisticated ones.

---

## 9. Cross-Cutting Policy — Verification, Provenance & Honesty Gates

The rebuild adopts the generate→verify→trust discipline end to end:

1. **Every number in every output is traceable**: posterior sample ← funnel state ← validated data pull. The reporting layer physically cannot render a number without its provenance chain.
2. **Gates, not guidelines**: information-budget status (Layer 2), diagnostic pass (Layer 3), ceiling flags (Layer 5), and narration validation (§8.4) are code-enforced gates. A failed gate blocks, logs, and routes to fallback.
3. **Versioned registries**: priors, floors, channel models, and ceilings are versioned configuration, so a revised bound (e.g., a **[provisional]** result later corrected) propagates by config change, not code surgery.
4. **Decision ledger audits**: quarterly, realized outcomes are compared against stated guarantees; systematic shortfall triggers framework review.
5. **Honesty defaults**: where a choice exists between a more impressive and a more accurate statement, the framework mandates accurate. This is a product feature, and sales material should say so.

---

## 10. Risk Register

| Risk | Severity | Mitigation |
|---|---|---|
| **[Provisional]** bounding results (111, 110, 115, 119, 122, 139, 229) are later revised or corrected | Medium | Bounds live in versioned registries; used as design guidance and conservative language, never hard-coded constants; framework review on any upstream correction |
| Worst-case bounds applied as if typical-case | Medium | Bounds documented with assumptions; calibrated against simulation on realistic campaign regimes before client-facing use |
| Over-engineering: five layers for a two-ad test | Medium | Full layer stack activates progressively by account scale; the conjugate fast path + floors is a complete minimal deployment |
| Hierarchical pooling hides genuinely exceptional ads | Medium | Per-level variance monitoring; shrinkage strength reported alongside every pooled estimate |
| Automation liability in Layer 4 | High | v2.0 ships recommendations only, human-approved; automation is a separate, later decision |
| Channel registry staleness (platform API/policy changes) | Medium | Freshness dates + automated review tasks |
| AI narration overreach | High | Output validated against status registry; templated guarantee language; claim-checking pass before render |

---

## 11. Summary Map — Research Results to Framework Components

| Result | Status | Layer | Component(s) | Function in framework |
|---|---|---|---|---|
| 140 — memory–sample floors | **[verified]** | 2 | `floors/estimability` | Minimum-data requirements per quantity & precision |
| 229 — segment detectability threshold | **[provisional]** | 2 | `floors/detectability` | Segments flagged detectable / below threshold |
| 122 — path-reconstruction barriers | **[provisional]** | 2 | `floors/path_barriers` | Feasibility gate on journey-level attribution |
| 139 — log-concave sampling cost | **[provisional]** | 3 | `inference/router`, `sampler_pool` | License for gradient-based inference at scale; tuning stopping point |
| 115 — exact cross-tab inference | **[provisional]** | 3 | `inference/crosstab_exact` | Exact conditional inference on sparse campaign tables |
| 111 — one-sample allocation guarantees | **[provisional]** | 4 | `decision/early_allocation` | Defensible early-campaign budget commitment |
| 110 — reallocation competitive optimum | **[provisional]** | 4 | `decision/reallocation` | Benchmark for switching-cost-aware pacing |
| 104 — long-run strategy tractability | **partially [verified]** | 4 | `decision/long_run` | Steady-state ROAS strategy computation |
| 119 — attribution information ceiling | **[provisional]** | 5 | `channels/ceiling_estimator` | Max recoverable signal per platform channel |
| 102 — allocation optimization cap | **[verified]** | 5 | `ceilings/registry` | "Provably at the cap" for allocation/partitioning |
| 96 — clustering optimization cap | **[verified]** | 5 | `ceilings/registry` | Cap for audience/creative clustering quality |
| 125 — k-median optimization cap | **[verified]** | 5 | `ceilings/registry` | Cap for segment-center selection quality |

---

## 12. The Framework Statement

For client-facing and team-facing use, the framework in one paragraph:

> *This system is a hierarchical Bayesian estimator of the full advertising funnel, built on five commitments. It maintains one joint state of knowledge — never independent metric models. Every reported quantity passes an information-budget check against provable data floors, so the system says "not knowable yet" when that is the truth. Every recommendation is a decision rule with a stated guarantee relative to a provable optimum. Every measurement claim respects the provable ceilings of the platform channels the data arrived through. And AI assists at every layer — proposing priors, criticizing models, designing experiments, drafting narratives — but nothing reaches a client without passing the verification gates. We say what is knowable, recommend what is defensible, and state the limits of both.*

---

## Appendix A — v1 → v2 Honest Accounting

| v1 element | Status | v2 disposition |
|---|---|---|
| Beta-Binomial CTR/CVR updaters | Sound but isolated | Absorbed as conjugate fast path within Layer 1/3 |
| Inverse-Gamma CPA updater | Heuristic, not generative | Replaced by explicit cost model in joint funnel |
| Gamma ROAS with plug-in revenue-per-conversion | Discards uncertainty | Replaced by derived functional with full propagation |
| Beta(1,1) flat priors everywhere | No elicitation | Replaced by versioned prior registry + AI elicitation |
| "Diagnostic" trace plots of i.i.d. posterior draws | Meaningless | Replaced by R̂/ESS/PPC/LOO suite with gates |
| GPT-3.5 narrative from summary stats | Unguided, unvalidated | Replaced by gated narration against status registry |
| Data loader stubs | Trusted input | Replaced by validated data contracts + channel models |
| PDF report as endpoint | Dead end | Reporting becomes one consumer of the funnel state; decision ledger is the other |

## Appendix B — Glossary (selected)

- **Funnel state** — the persisted joint posterior over all Layer 1 parameters; the single source of truth.
- **Information budget** — the data-and-channel-determined limit on what can be known at a given precision.
- **Floor / ceiling** — a lower bound on data required (floor) / upper bound on achievable quality (ceiling), drawn from provable results.
- **Estimable / marginal / below floor** — the three feasibility statuses every quantity carries.
- **Gate** — a code-enforced check that blocks output on failure; distinct from a guideline.
- **Decision ledger** — append-only record of recommendations, guarantees, and realized outcomes.
- **[verified] / [provisional]** — whether a bounding research result carries a completed machine-checked proof.

---

*End of framework document. Next step: derive the technical specification (module interfaces, data schemas, gate contracts) from §§3–8 for build with Claude Code.*
