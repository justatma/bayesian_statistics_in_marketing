# Blind spec review 01

Reviewed: `spec/reviews/Bayesian_Marketing_System_Specification_v0.2.md`, against the Framework, Spec v0.1, the Manuscript, `spec/decisions.md` D1 to D8, the AtmaOS contract (`adapters/bayesian/base.py`, `spec/03_agency.md` G3 and G8), the inventory (§I, §V, §VIII) and the build protocol.
Reviewer: Sonnet, fresh agent, no access to the author's reasoning. Date: 2026-10-30.
Disposition of each finding: `spec/Bayesian_Marketing_System_Specification_v0.3.md` §0.2.

## 1. Where v0.2 does not implement the blueprint as amended

1. The socket lacks functions the spec relies on. §11 defines only `compare` and `observation_evidence`, but §8.6 reads approval through the socket, §4.11 and §8.7 read outcomes through it, §12 takes narrative from AtmaOS, and §4.8 hands recommendations to AtmaOS. G6 and `audit/` cannot run, and recommendations are never returned.
2. `expected_loss` has the wrong type. `base.py` declares `dict[str, float]`; §11 sends amounts as strings with currency, which fails validation.
3. `compare` cannot satisfy both G8 and G9. The AtmaOS signature carries no client identity and no economics, while §8.1 requires `econ` and G9 forces `not_knowable` without it. §11 does not say what `dataset_uri` resolves to, which `metric` values are allowed, or how `priors` and `segments` map to `PriorRecord` and `Scope`. The inventory §VIII envelope is not resolved.
4. The North Pier oracle cannot come from the production route. §7.1 C1 sends a coupled two-ad funnel to NUTS with pooling, which gives different numbers from Beta(42,2058). I1 and I9 forbid per-metric models in production. The status of conjugate quantities under I9 is not stated.
5. The quantity floors make the headline case unreportable. At a 20% target, day-two CTR A is 25% (marginal), and day-fourteen CVR A is 54% and B is 37% (both below floor). The spec does not say whether decision-basis status overrides quantity-basis status; Framework §4.1 forbids acting on below-floor input. Relative half-width means nothing for contribution (−$610) or anything near zero.
6. D1 is contradicted by §8.5 and §4.8, which render provisional entries to clients when a flag flips.
7. Blueprint items were dropped with no ruling and no §0 row: `crosstab_exact`, `decision/long_run`, and the Layer 5 `ChannelModel`, even though G1 still checks "channel model fresh". The VI route has no file, piece or test, and the fallback chain changed silently.
8. The cost stage cites a "v0.1 §5.2" that does not match. Most types used in the interfaces are never defined.
9. Statistics:
   - These are correct: the compound Gamma revenue model, the InvGamma CPA model, n = 5,300.74, κ = 829.51, and the EVPI, EVSI and hold arithmetic.
   - §5.2 C6 is wrong: a Poisson pmf is undefined at non-integer counts.
   - §5.6 C2 is wrong: `clicks × F(a)` as fractional binomial trials is not the likelihood. The correct form is thinned success probability `cvr·F(a)`.
10. Four significant figures and ±$0.01 cannot come from Monte Carlo joint draws. Those values need quadrature.
11. `ClientEconomics` is inconsistent: contribution is a point value while price and order value are distributions.
12. Wave dependencies are wrong in five places:
    - P3 needs P4's decision feasibility.
    - P4 reporting needs P10's claim check.
    - P9 and P10 form a cycle.
    - P10 needs `pipeline.py`, which is in wave 4.
    - P3 returns a `FunnelState` that P5 owns.
13. Evidence-class mapping has gaps:
    - `commercially_realized`, `causally_incremental` and `design: none` are not mapped.
    - The combination of `platform_attributed` and `randomized` is labeled an experimental estimate while I11 bars causal language for it.
    - Simulator-fed quantities are ambiguous.

## 2. What v0.2 leaves undecided

1. How the reader decides between `conversions_observed` and `conversions_reported`. The `partial_truth` condition differs from the C6 trigger.
2. The lag model has no data source; daily aggregates carry no delay. `min_lagged_conversions` has no value.
3. Decision scale: tolerance is per decision while loss is per 1,000 clicks. `Objective` has no horizon, and there is no projection method for the required volume.
4. Registry numbers have no source:
   - These have no value: LKJ η, `min_days_for_dynamics`, the plausibility ceiling, the VI tolerance, the G5 rounding, the default lag curves, `max_age_days`, the per-arm caps, the learning-phase costs, and the sampler settings.
   - `decision_defaults.yaml` is never specified.
   - `min_events` = 10 is inert against a 20% target, which needs about 68 events.
5. SBC has no statistic or threshold, and is slow as a frozen test. A1 needs a frozen-value reference that C2 forbids in source.
6. The A-ai property test has no generator or ground truth, and the LLM package list is not given.
7. No piece owns G6, G9 or G10. Every registry value would have to live in S0, and nobody is assigned to write S0's examples.
8. Client, demo and internal reports are not distinguished, and `ReportBundle` is undefined.
9. Neither `dataset_uri` resolution nor the GA4-to-orders join is defined. The public-data licenses are unverified.
10. The vertical prior import has no function, the format of `intake_prior_proposal`'s return is undeclared, and the caller of `approve` is unspecified.
11. Cross-platform hierarchy and the evidence class of `platform: None` aggregates are not stated.
12. The PPC band and the several "registry tolerance" values are conventions with no value.

## Owner items raised

These questions were raised for the owner:

- Whether decision-basis status overrides quantity-basis status.
- Whether contribution is a point or a distribution.
- Which route produces North Pier.
- Whether the dropped modules are out of scope.
- Whether provisional entries are ever shown to clients.
- The defaults.
- How the socket carries client identity, economics and the envelope.
- Whether an owner-funded real account is wanted.
