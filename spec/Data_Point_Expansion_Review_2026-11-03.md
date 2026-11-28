# Bayesian toolkit: expanded data opportunities and engineering questions

Prepared for Atma and the Bayesian toolkit engineer, 3 November 2026. Consultant review and proposed capability catalogue, not an approved replacement specification or an implementation assignment.

## Conclusion

`spec/data_points.md` is a useful inventory of the current narrow reporting-and-decision interface. It is not yet a comprehensive inventory of evidence useful for advertising decisions. Its strongest coverage is daily delivery, orders and simple unit economics. Its weakest coverage is the commercial journey after a lead, variation in customer and product value, the settings and interventions that produced delivery, creative and site changes, measurement reliability, and evidence capable of supporting causal claims.

The opportunity is to understand **which marketing actions create worthwhile customers and contribution, under which conditions, with what uncertainty**. Collecting more columns is only useful when their definitions, relationships and decision use are explicit. Some proposed inputs belong in an evidence or diagnostics layer; some require a new model; some are only context for a human. They should not all be fed into the current funnel model.

This catalogue deliberately reaches beyond the first release. It is a menu of useful evidence, not a demand that every client supply everything or that engineering build everything before the toolkit is usable.

## 1. What this review establishes

Read locally: `spec/data_points.md`; the v0.3 specification's overview and core definitions; `core/data.py`, `decisions.py`, `records.py`, `scope.py`; the row-reader conversion checks; `registries/channels.yaml`; the follow-up register; and P8's manifest, including its review fixes. Paths below are relative to this repository. Repository HEAD observed during the review: `e9f9646` (Wave 3 briefs P9, P10); the repository is actively changing.

This was a read-only inspection of project implementation and a document-writing task. No project code, tests, connectors or paid calls were run. A field's appearance in a schema establishes representation, not that ingestion, inference, reporting and live validation all work.

The engineer already records subscriptions, vertical priors, customer identity and product-level orders as follow-ups. Those are existing directions to deepen, not discoveries of entirely overlooked work. P8's manifest reports substantial connector testing but incomplete real-account replay coverage. Historical manifest results are reported evidence, not fresh test results from this review.

### Corrections or clarifications before adding more inputs

| Finding | Local evidence | Suggested treatment |
|---|---|---|
| “Used” combines merged implementation and work still building | Opening definition of `data_points.md` | Track separately: specified, represented, ingested, consumed by analysis, tested with fixtures, verified against a live source. Avoid one maturity flag for all six. |
| The list implies names and objective/result type are available, but the normalized performance schema has neither an explicit name field nor an objective/result-type field | `core/data.py:PerformanceRow` has `entity_ids`, date, counts, money and attribution fields | Determine whether these survive elsewhere. If not, describe them as connector/context data needing a place, rather than present model inputs. Preserve a stable ID separately from a changeable name. |
| “Observed” is too easy to read as independently verified | GA4 `SiteRow` and orders are grouped as observed outcomes | Distinguish instrument-recorded events, reconciled financial transactions, platform-attributed results and estimates. A tagged purchase event may be duplicated or missing. A settled payment verifies receipt, not that an ad caused it. |
| Reported conversions above clicks are quarantined | `data_contract/readers/rows.py:performance_fields`; P8 manifest open question 7 | Make validity depend on conversion semantics. View-through, multiple events per click, reporting-date differences and attribution rules can make this legitimate. Preserve the source row. Do not simply remove a model check: a click-trial model still needs compatible successes and trials or a different likelihood. |
| Zero-spend days are treated as structural zeros in the funnel input contract | `core/data.py:FunnelData` docstring | Check whether delayed conversions, refunds, offline sales, credits or corrections on such days are retained elsewhere. Zero delivery is different from zero outcomes. Resolve the reporting clock before deciding which terms belong in the likelihood. |
| Shared client economics is not sufficient for many-product or many-plan businesses | `ClientEconomics` has a single variable cost and optional fixed price/repeat value | Allow effective-dated product/plan/cohort economics where needed. Keep the existing simple case. A blended margin can reverse which campaign appears preferable. |
| A single first-click timestamp is not a complete journey or verified ad match | `OrderRow.first_click_at`, optional UTM and `click_id` | Record the clock, matching rule, confidence and missingness. A click identifier needs a valid account-scoped mapping, not an assumption that the identifier directly supplies an ad ID. |
| “Required” should depend on the decision | `data_points.md` opening; `ClientEconomics.loss_tolerance` is nullable but approval/gates constrain decisions | Separate minimum ingestion fields, minimum fields for a named analysis, and fields needed before an actionable recommendation. Missing retention should block a lifetime-value claim, not a descriptive click report. |

## 2. How to read the expanded catalogue

Every entry below is a **candidate extension**, unless marked as already represented or listed as an existing follow-up. Specific API support, permissions, retention and compatible breakdowns must be verified per source. Availability in an advertising interface is not proof it can be fetched through an approved API. Client exports or an explicit unknown state can be valid alternatives.

Each row groups related attributes; it is not a proposed database table. Field names are descriptive concepts, not commitments to add exact schema keys. Preserve raw inputs and derive ratios from the underlying counts and money. A rate without its denominator, population, window and uncertainty is incomplete evidence.

### A. Business objective, economics and operating limits

Source: client-approved finance, sales and operational records. Existing base: `ClientEconomics`, `Objective`, `Horizon`; the richer breakdowns below are proposed.

| Candidate data | What it helps decide |
|---|---|
| Business model; acquisition versus retention objective; target outcome and qualifying definition; planning horizon | What success actually means for this client, rather than defaulting every business to purchases |
| SKU, category, service or plan; selling price; discounts; tax treatment; gross versus net revenue convention | Compare like value with like value |
| Effective-dated COGS, shipping subsidy, fulfillment, payment fees, commissions, onboarding and variable service/support costs | Estimate contribution rather than merely revenue |
| Return/refund/chargeback probabilities, amounts and maturation delays | Correct apparently profitable acquisitions that later lose value |
| Cash collection schedule, payment terms, bad debt and financing/payment-plan costs | Distinguish booked revenue from cash and fundable growth |
| Contribution target, maximum acceptable acquisition cost, payback horizon, loss tolerance and downside limit | Evaluate whether a recommendation fits the business's risk limits |
| Inventory, production/service capacity, sales capacity, delivery geography and available booking slots | Avoid recommending demand the business cannot serve |
| Minimum channel commitments, budget ceiling, pacing, contractual spend and cost of changing course | Define feasible actions, not just an unconstrained mathematical optimum |
| Source, owner approval, effective dates and uncertainty of every economic assumption | Reproduce the decision and test sensitivity to disputed margins or values |

Accounting definitions must prevent counting returns twice through both net revenue and an expected-return cost. Distinguish advertising contribution from company profit after fixed overhead. A survival constraint should specify whether it concerns cash, spend, contribution or capacity; these are different quantities.

### B. Campaign configuration and delivery state

Source: authorized platform configuration snapshots, change history and operator records. Current performance rows retain hierarchy IDs; most settings below need additional representation.

| Candidate data | What it helps decide |
|---|---|
| Campaign objective, optimization event, conversion action and counting rule | Whether comparable-looking results represent comparable outcomes |
| Daily/lifetime budget, shared budget ID, actual pacing and spend limit | Whether poor delivery reflects budget or demand |
| Bid strategy, target CPA/ROAS, bid caps, portfolio bidding and effective changes | Interpret changes in volume, cost and audience selection |
| Start/stop times, status, policy rejection, scheduled hours and account interruptions | Separate paused or ineligible delivery from unsuccessful delivery |
| Learning/limited-delivery status and recorded resets, where available | Assess whether recent performance is a stable regime |
| Automatic audience expansion, automatic placements, dynamic creative and asset-generation settings | Identify what the platform was free to change during a supposed test |
| Conversion-tracking and attribution configuration history | Detect breaks in measurement continuity |
| Campaign/ad-set/asset relationships with valid-from/to times | Avoid joining today's settings onto yesterday's results |

An operator log may be the only source for some interventions. Record that limitation rather than fabricating a complete historical platform state.

### C. Audience composition, geography and exposure

Source: approved platform aggregate reporting, configured targeting and client segments. Targeting intent and reached audience are different records.

| Candidate data | What it helps decide |
|---|---|
| Prospecting/retargeting designation, audience definition/version, exclusions and acquisition/retention audience | Whether an apparent winner is mostly harvesting existing demand |
| Country/region, language, device, OS, placement, network and hour/day where reportable | Locate performance variation and check whether the delivery mix changed |
| Aggregate B2B industry, company size, job function and seniority where permitted | Assess whether delivery reaches the intended professional market |
| Reach, frequency and exposure distribution, including their reporting window | Detect saturation and repeated exposure; unique reach must not be summed across overlapping windows |
| Existing-customer suppression and known customer share of reached/converting users | Separate new-customer acquisition from reacquisition |
| Overlap estimates and their method, when legitimately available | Understand competition between campaigns; unknown cross-platform overlap remains unknown |
| Segment-level eligible population and reported/suppressed coverage | Avoid treating a small disclosed subset as the whole audience |

Demographic cells can be suppressed or restricted. This proposal is aggregate analysis, not a request to collect private member profiles or infer individual sensitive characteristics.

### D. Search, shopping and auction conditions

Source: supported search/shopping reports, product feeds and approved exports.

| Candidate data | What it helps decide |
|---|---|
| Keyword, actual query where disclosed, match type, negatives and brand/non-brand classification | Distinguish demand capture from exploration and identify irrelevant traffic |
| Query intent/theme with classification confidence and taxonomy version | Pool related intent without pretending a model-generated label is a fact |
| Search impression share, budget/rank limitations and eligible auction coverage where available | Diagnose whether more budget could plausibly buy more exposure |
| Placement exclusions, search partner/network and invalid-click adjustments | Interpret traffic quality and later cost corrections |
| Product feed status, disapprovals, product ID, stock, price and feed version | Explain shopping performance changes unrelated to ad persuasion |
| Auction or competitive indicators available through an authorized report/export | Add market context without assuming every UI auction metric has an API equivalent |

### E. Creative content and creative history

Source: platform assets, Growth Bastards' creative records and authorized CIE outputs. Do not rebuild CIE inside the statistics toolkit.

| Candidate data | What it helps decide |
|---|---|
| Creative family, concept, asset/version ID, first-live date and revisions | Pool evidence across related creative and identify actual changes |
| Headline, body, hook, offer, CTA, image/video reference, format, length and aspect ratio | Associate performance with testable creative choices |
| Proposition, pain addressed, objection, proof type, customer stage and message angle | Form useful creative hypotheses beyond “ad A beat ad B” |
| Brand/product, audience fit and destination/offer consistency | Diagnose whether a message wins the wrong attention |
| Human-coded versus model-coded attributes, annotator/model version, confidence and disagreements | Prevent subjective creative tags becoming unquestioned ground truth |
| Exposure age, cumulative reach/frequency and concurrent creative rotation | Investigate fatigue separately from changing audience mix or competition |
| Video starts, timed views, completion events and engagement counts with platform definitions | Diagnose attention losses; keep these as proxies unless linked to valued outcomes |
| Dynamic combination/asset eligibility and actual delivered combination when disclosed | Know whether a “creative test” isolates a creative at all |

A correlation between a tag and performance is a hypothesis, particularly when the platform selected who saw each asset. It does not independently identify the effect of a hook or color.

### F. Landing pages, forms and checkout

Source: consented site instrumentation, web logs, CMS/deployment history, experiment tools and Dr. UX findings where available. Dr. UX remains a separate tool.

| Candidate data | What it helps decide |
|---|---|
| Final URL, landing-page ID/version, offer/price version and deployment time | Join an ad to the experience actually delivered |
| Landing-page views versus clicks; sessions and eligible users by source | Detect load/redirect/tracking losses without assuming clicks equal visits |
| Product views, add-to-cart, checkout start, payment attempt and successful payment, with event definitions | Locate drop-off along a commercial funnel |
| Form start, field-level validation failures, submission, confirmation and deduplication | Distinguish a weak offer from a broken or burdensome form |
| Page speed, availability, server/payment errors and device-specific failures | Detect operational causes of falling conversion |
| Shipping charges, delivery promise, coupon, trust/proof elements and checkout steps | Interpret changes to conversion and basket economics |
| Experiment ID, assignment, eligible population and actual variant seen | Support a valid page experiment rather than a before/after comparison |
| Dr. UX observation IDs, severity, evidence and implementation dates | Link qualitative diagnosis to a later, separately evaluated intervention |

Engagement time, scroll and clicks are diagnostic proxies, not automatic evidence of satisfaction or purchase intent. Different funnel steps can have different denominators and observation windows.

### G. Leads, qualification and B2B sales

Source: CRM, lead forms, scheduling, sales records and payment systems. This is a particularly important missing extension for Growth Bastards' B2B clients.

| Candidate data | What it helps decide |
|---|---|
| Stable lead/contact ID, account/company ID and opportunity ID, with explicit link relationships | Avoid counting five contacts at one company as five independent buying opportunities |
| Lead creation, qualification, meeting booked/attended, opportunity, won/lost and cash-received timestamps | Model the commercial journey and the delay to value |
| Stage definitions/version and stage-change history, including reopened or regressed opportunities | Prevent today's CRM status being mistaken for the state known at the decision date |
| Spam, duplicate, invalid contact, disqualification and reason codes | Judge lead quality rather than optimize cheap submissions |
| Intended-customer fit: use case, company size, industry, region and buying readiness | Estimate value and fit of acquired demand |
| Response time, follow-up count, sales ownership, contactability and sales capacity | Separate acquisition problems from follow-up or fulfillment problems |
| Contract value, expected margin, payment schedule, delivery cost and realized receipts | Estimate value per acquired lead without treating pipeline as cash |
| Source associations, touch history, match confidence and unattributed share | Quantify what can and cannot be traced back to acquisition |
| Stage-specific loss reasons, time-to-close and still-open observation cutoff | Retain incomplete journeys without classifying every open deal as a failure |

Lead-to-win value should carry uncertainty in qualification, close probability, time and margin. Distinguish sales-entered forecast probabilities from calibrated estimates. Using eventual won/lost status to predict a past decision leaks future information.

### H. Orders, products, refunds and fulfillment

Source: shop/order management, payments, returns and finance. Order IDs, value, refunded amount and timestamps already exist; customer/SKU detail is already a follow-up.

| Candidate data | What it helps decide |
|---|---|
| Order-line ID, SKU/category, quantity, unit price, discounts and allocated costs | Measure product-level contribution and basket mix |
| Order, authorization, capture, fulfillment, refund and chargeback timestamps/statuses | Distinguish intent, money received and retained value |
| Refund/return amount, reason, returned quantity and recoverable inventory value | Measure acquisition quality beyond first-sale ROAS |
| New/repeat customer flag based on available history; prior-order history coverage | Avoid claiming “new” simply because an import starts this month |
| Cohort, acquisition source and original versus repeat order | Estimate acquisition value without crediting every repeat purchase as a new acquisition |
| Inventory/stockout, delivery delay, canceled orders and fulfillment failures | Explain sales constraints and dissatisfaction |
| Fraud/test-order/staff-order/duplicate exclusions with reasons | Reconcile commercial outcomes to valid transactions |
| Shipping, tax, discounts, fees and FX convention as separate components | Make revenue and margin definitions consistent across sources |

### I. Subscriptions and membership

Source: member registry, subscription billing, payment history and authorized product usage. This expands the subscription follow-up already recorded for Sparklist.

| Candidate data | What it helps decide |
|---|---|
| Member/customer/subscription ID, acquisition cohort, plan and billing cadence | Identify the population and appropriate economic unit |
| Signup, trial start/end, activation, first paid invoice and service start | Avoid equating free signups with paying subscribers |
| Invoice/renewal schedule, invoices paid, amount collected, credits and refunds | Estimate actual receipts rather than nominal plan-price revenue |
| Cancellation requested versus service end; reason; voluntary versus failed-payment churn | Separate demand loss from billing failure and define retention correctly |
| Pauses, reactivation, upgrades, downgrades, seats and price changes | Follow changing value rather than a static $/month |
| Observation cutoff, left-truncated history and still-active indicator | Treat surviving members as incomplete observations, not infinite lifetime or zero churn |
| Variable service/support/onboarding cost and margin by plan/cohort | Estimate retained contribution rather than retained revenue |
| Activation/usage milestones and satisfaction/support indicators, when legitimately collected | Investigate predictors of retention without using information unavailable at acquisition time |
| Acquisition-source match and missingness by cohort | Compare channel value without silently dropping members with unknown origins |

Price × average months is only a rough starting approximation. A useful model sums expected net contribution over a declared horizon, with survival, payment, cost and discounting assumptions and uncertainty. The simple approximation becomes reasonable only under appropriate constant-price, margin and retention assumptions. A 300-member dataset cannot automatically support dozens of independent channel-by-plan retention curves.

### J. Customer lifecycle, retention and referrals

Source: CRM, transactions, support and referral systems.

| Candidate data | What it helps decide |
|---|---|
| Tenant-scoped pseudonymous customer ID and defensible entity-resolution rules | Connect a permitted lifecycle without creating an unnecessary identity database |
| First acquisition, repeat purchases, time between orders and cohort age | Estimate repeat value with incomplete observation handled correctly |
| Retained revenue/contribution, expansion, contraction and customer concentration | Identify durable value rather than a high initial order |
| Referral source/code, referred customer and incentive cost | Value referral-driven acquisition without double-counting both sides |
| Support/return behavior and satisfaction measures with response coverage | Investigate quality of acquired customers; respondents are not necessarily representative |
| Loyalty benefits and retention-marketing exposure/cost | Separate acquisition economics from ongoing costs of retaining the customer |

### K. Measurement, attribution and event identity

Source: measurement configuration, event pipeline, server/client tracking diagnostics and reconciliation records. Attribution settings already exist; this needs more detailed semantics.

| Candidate data | What it helps decide |
|---|---|
| Event ID, event name/version, eligible population and event counting rule | Define exactly what a conversion means and deduplicate it |
| Event time, interaction time, ingestion time, reporting date and timezone | Align different clocks and avoid false daily disagreements |
| Click-through versus view-through; attribution model/window; primary/secondary outcome | Keep incompatible outcomes separate |
| Browser/server/offline event origin and deduplication linkage | Avoid counting the same purchase multiple times |
| Modeled/estimated component and known/unknown modeled share | Preserve the difference between recorded and reconstructed quantities |
| Transaction reconciliation status, event-to-order match rate and unmatched counts/value | Assess how much outcome evidence is financially grounded |
| Consent/measurement coverage by population and changes to tagging/consent | Identify who is missing from the measured sample |
| Attribution replay/restatement history and data maturity at each pull | Avoid treating a revised historical report as the information available earlier |
| Relationship among multiple platforms' claims on the same outcome | Avoid summing platform-attributed revenue as unique business revenue |

UTMs and click IDs provide association under matching rules; neither proves incrementality. Do not assume all platforms expose a modeled-share field or a complete user-level path.

### L. Data quality, coverage and source provenance

Source: connector responses, ingestion logs, data manifests and reconciliation. Existing pulls/manifests already carry useful provenance and quarantine records.

| Candidate data | What it helps decide |
|---|---|
| Source system, API/export version, request dimensions, filters, metric definitions and account | Reproduce what was requested and interpret its meaning |
| Row grain, time grain, entity scope, timezone and currency | Prevent incompatible joins and totals |
| Pull time, as-of cutoff, source update time and estimated maturity | Distinguish fresh but immature data from mature historical data |
| Returned versus expected coverage, partial failures, truncation and missing pages | Know whether the result represents a complete pull |
| Sampling rate, thresholding, suppressed cells, “other” aggregation and restricted metrics | Avoid treating incomplete/disclosed data as an exhaustive census |
| Null/zero/unknown/not applicable/suppressed/not collected states | Prevent missing conversion counts from becoming genuine zero outcomes |
| Identity/join coverage, unmatched value and deduplication rules | Quantify bias introduced by combining sources |
| Raw record/file hash, normalization version and correction lineage | Audit changes and reproduce historical decisions |
| Quarantine reason, affected totals and recovery/disposition | Show the economic importance of rejected records |
| Retention/access scope and approved analytical purpose | Keep evidence usable within the rights under which it was supplied |

A low-coverage segment can yield a precise estimate of the wrong population. Include data-quality uncertainty and selection limitations alongside sampling uncertainty where relevant.

### M. Time, seasonality, demand and outside context

Source: business calendars, operating logs and licensed/public data with recorded publication times.

| Candidate data | What it helps decide |
|---|---|
| Weekday, holiday, payday, seasonal cycle and geography-specific calendar | Distinguish recurring demand variation from a campaign effect |
| Promotions, product launches, sales events and changing prices | Identify interventions that alter value or conversion |
| Organic search demand, branded-query trends and market demand indicators | Check whether the addressable demand changed |
| Competitor promotions/prices and major category events, with evidence | Add plausible context; do not assume an observed competitor action caused a change |
| Weather, local events or macro indicators when commercially relevant | Test a defined explanatory hypothesis rather than indiscriminately collect everything |
| Outages, shipping disruption, inventory/capacity changes and sales-team changes | Detect nonadvertising causes of changed outcomes |
| Source publication date, geographic coverage and revision history | Prevent hindsight leakage in backtests |

Context variables should be chosen using a causal understanding of the question. A variable caused by the advertising may be part of its effect, not a suitable adjustment variable.

### N. Other channels and demand already present

Source: consented cross-channel business records, email/CRM, SEO analytics and direct/offline activity.

| Candidate data | What it helps decide |
|---|---|
| Email sends/delivery, campaigns and downstream actions with dates | Identify concurrent retention or promotional activity |
| Organic search, direct, referral, affiliate, influencer and partner activity | Understand paid performance in the wider demand system |
| Offline events, outbound-sales activity, PR and sponsorship exposure/cost | Avoid attributing every sales change to paid ads |
| Full media spend and commercial outcomes aligned over time/geography | Enable a future aggregate-response analysis when the data are adequate |
| Cross-channel timing, overlaps and known coordinated campaigns | Detect confounding and potential interaction hypotheses |

Collecting these series does not itself produce causal channel decomposition. Marketing-mix modeling is a separate, validated capability, not a free consequence of a wider import.

### O. Experiment design and incrementality

Source: experiment assignment logs, platform lift studies, geographic tests and preregistered plans. Existing `TestDesign` records arms, allocation and design flags; the following is a richer experiment record.

| Candidate data | What it helps decide |
|---|---|
| Experiment ID, hypothesis, estimand, primary outcome, meaningful effect and analysis plan version | Define the actual question before interpreting a result |
| Eligible population, randomization unit, assignment time and assignment probability | Evaluate whether treatment and control support the claimed comparison |
| Treatment assigned, actual exposure, noncompliance and cross-arm contamination | Separate assignment effects from exposure associations |
| Control/holdout definition, geography boundaries and preperiod outcomes | Assess baseline comparability and possible spillovers |
| Cluster/household/company relationship, repeated users and interference | Avoid pretending correlated observations are independent |
| Concurrent experiments, treatment changes and platform allocation changes | Identify tests that failed to isolate an intervention |
| Outcome follow-up, censoring, exclusions, missingness and attrition by arm | Avoid biased comparisons of incomplete outcomes |
| Actual sample allocation, sample-ratio checks and exclusion reasons | Detect assignment or measurement problems |
| Stopping/decision policy, repeated looks and chosen outcome/segment history | Assess selection effects and reproduce the decision process |
| Lift estimate, uncertainty, covariance where available and source study limitations | Use experiments to inform decisions or priors without treating estimates as exact |

An observational comparison remains observational even if computed using Bayesian methods. Budget changes selected by an optimization algorithm are not randomized experiments merely because allocation varied.

### P. Spend response, saturation and carryover

Source: historical configuration/outcome series and credible budget experiments. These require models beyond a constant-efficiency funnel.

| Candidate data | What it helps decide |
|---|---|
| Spend and delivery over meaningful variation, by period/market/channel | Whether an additional dollar is likely to perform like the average dollar |
| Recorded budget interventions and why they occurred | Assess whether spend rose because demand had already risen |
| Reach/frequency trajectories and audience capacity | Investigate saturation |
| Lagged media exposure and post-exposure outcome series | Investigate carryover under a defensible model |
| Marginal response estimates, parameter dependence and uncertainty | Inform allocation without treating historical ROAS as a stable response curve |
| Extrapolation boundaries, capacity constraints and switching/learning costs | Avoid confident recommendations far outside observed or tested conditions |

Separate last-click conversion delay from the persistence of advertising's influence. These are different mechanisms and need different evidence. Sparse low-spend clients may not support this analysis at all.

### Q. Historical evidence and priors

Source: the client's historical outcomes, approved benchmark datasets and qualified experimental results. Existing prior approval and cohort priors are a foundation.

| Candidate data | What it helps decide |
|---|---|
| Population, industry, product, price, geography, platform and funnel-stage definition | Whether historical evidence is relevant to the current client |
| Counts, exposure, conversion definition, observation window and maturity | Distinguish a measured rate from an unsupported benchmark percentage |
| Study/source selection method, date and representativeness | Assess selection and publication bias |
| Cohort differences, dispersion and dependency among records | Avoid false effective sample sizes |
| Prior parameters, effective sample size, discounting and transfer rationale | Make the strength of borrowed evidence explicit |
| Approval/effective time, model version, conflict checks and sensitivity to alternative priors | Reconstruct what was knowable and check whether the prior drives the recommendation |

An industry label alone is a weak basis for a strong prior. An apparent 10,000-record benchmark may supply far less transferable information if definitions or selection differ.

### R. Decisions, implementation and realized outcomes

Source: approval/action logs, platform read-back and follow-up financial records. Current records capture approvals and generic outcomes; richer execution and follow-up semantics are proposed.

| Candidate data | What it helps decide |
|---|---|
| Candidate actions, chosen/rejected action, approval, rationale and decision-time snapshot | Reproduce why the system preferred a choice |
| What actually changed, actor, timestamp, previous/new values and platform confirmation | Distinguish a recommendation from an implemented intervention |
| Action delay, partial execution, reversal and deviation from the approved plan | Explain why realized results differ from the prediction |
| Predictive distribution, horizon, decision threshold and intended population | Score the prediction against the outcome it actually forecast |
| Mature realized revenue, contribution, loss and follow-up cutoff | Learn from commercially meaningful outcomes |
| Concurrent interventions, measurement changes and missing outcome data | Prevent post-decision changes from becoming unjustified causal credit |
| Calibration, interval coverage, directional errors and refusal/abstention performance | Evaluate the engine across many decisions |

Observed results after a choice do not reveal what an unchosen action would have achieved. Counterfactual regret needs simulation ground truth, a credible experiment, or an explicitly justified estimator; it is not directly observed in ordinary action logs.

### S. Brand, demand creation and customer attitudes

Source: properly designed surveys, brand-lift studies, customer research and demand indicators. These extend the catalogue beyond immediate direct-response outcomes.

| Candidate data | What it helps decide |
|---|---|
| Unaided/aided awareness, consideration, preference, trust and purchase intention | Assess whether marketing changes the conditions for later purchase; intention is not an actual purchase |
| Question wording/order, survey version, sampling frame, recruitment method, respondent count, response rate and weights | Establish what the measurements mean and whom they represent |
| Baseline/follow-up dates, exposed/control assignment where valid, geography and customer status | Distinguish a designed lift study from a change in who answered |
| Customer-reported discovery source, reasons for buying/not buying and alternatives considered | Identify overlooked demand sources and positioning opportunities; reported recall has limitations |
| Share-of-search, branded demand, organic/direct traffic and category-demand context | Track possible demand creation without treating every correlated rise as advertising impact |
| Unsubscribes, complaints, negative feedback, customer distrust and support burden | Include adverse outcomes and guardrails alongside clicks and sales |

Keep different survey scales and definitions explicit. Repeated cross-sectional surveys and following the same respondents are different designs. Brand evidence may justify a different decision horizon, but it does not license an invented monetary value for every awareness point.

### T. App, phone and offline commercial journeys

Source: authorized app analytics, call records with appropriate permission, booking systems, POS and offline sales exports. These are optional business-model extensions, not claims that the current connectors support them.

| Candidate data | What it helps decide |
|---|---|
| App install, activation, meaningful feature use, trial, in-app purchase and subscription events | Distinguish low-cost installs from acquired users who receive and pay for value |
| App/version, device context, measurement framework, reporting delay and aggregation restrictions | Avoid forcing app-attribution data into website click semantics |
| Call ID, source/match method, connected versus missed call, qualification and booking outcome | Measure commercial phone leads rather than telephone-button clicks |
| Appointment booking, attendance, cancellation, service delivery and payment | Separate demand, no-shows and fulfilled sales |
| Store/location, POS transaction, product economics, local availability and opening hours | Evaluate local advertising against the business that could actually be served |
| Coupon/redemption or other offline match, confidence and unmatched share | Preserve partial linkage without inventing complete customer journeys |

Offline events need their actual commercial timestamps and a defensible match, not automatic last-click assignment. Raw call recordings and personal identities are not required by default; structured, appropriately scoped outcome records can often answer the question.

## 3. Numerical and contextual evidence should remain distinct

Interviews, call transcripts, support themes, competitive findings, Boswell research, CIE assessments and Dr. UX findings can explain a plausible mechanism or suggest a test. They are useful evidence even when not numerical. Preserve their source, date, population, limitations and interpretation status. A model-generated sentiment score is not automatically an interval-scale measure; an expert's confidence is not a calibrated probability.

For example, three customer interviews can suggest that shipping surprises hurt checkout. The appropriate chain is: preserve that observation, identify the proposed page change, test or monitor it with the right population and outcome, then evaluate what the result supports. Do not convert three interviews into an invented conversion-rate prior.

## 4. Representation that keeps this manageable

Keep the daily performance row small. Consider linked, independently versioned records for:

1. Business definitions and approved economics, effective-dated by product/plan where needed.
2. Campaign configuration and change events.
3. Creative, offer and landing-page versions, linked to existing specialist-engine evidence.
4. Outcome events: leads, opportunity stages, transactions, subscriptions and refunds.
5. Audience/placement/product breakdowns, each with its own grain and coverage.
6. Measurement definitions, quality metadata, reconciliation and source snapshots.
7. Experiments and assignment/exposure evidence.
8. Decision-time inputs, recommendations, actual actions and mature follow-up.

This is a conceptual grouping, not a prescription for eight new services. Reuse existing manifests, pull provenance, registries, AtmaOS evidence records and event structures wherever adequate. Prevent one-to-many joins from multiplying spend or revenue. Never join a breakdown total and an unsegmented total as if they were independent observations.

### A proposed field-dictionary entry

For each selected attribute record: definition; raw versus derived; unit/currency; source and exact supported field; grain/primary key; event and availability times; allowed null states; join rule; validation; coverage/uncertainty; source-of-truth priority; analytical consumer; authorization/retention scope; and maturity evidence.

Maturity evidence should answer: does it exist in a source, can we acquire it, can we represent it, does a model/report consume it, has that path been tested, and has a real-client reconciliation succeeded? These answers can differ for the same attribute.

### Statistical handling

Retain numerator/denominator pairs rather than importing CTR or CVR as independent facts. Keep repeat events, repeated people and clustered companies explicit. Preserve joint uncertainty where value components depend on one another; multiplying independent point estimates can materially understate risk. Treat missingness, financial restatements, outcome delay and source disagreement as analytical facts rather than cosmetic warnings.

Useful derived outputs include contribution per acquisition, paid lead-to-cash value, retention-adjusted contribution, payback distribution, break-even probability, marginal return and value of further research. Each requires a declared model and compatible evidence; their appearance here is not a claim that they already exist.

## 5. Suggested next discussion with the engineer

I suggest agreeing the following objectives and acceptance evidence, without delaying existing sound work or scheduling a giant rebuild.

| Objective | Demonstration that would make the extension useful |
|---|---|
| Correct the evidence and outcome semantics | One reconciled example distinguishing a platform-reported result, a site event and a paid/refunded order; legitimate incompatible counts retained without being forced into a click-binomial model |
| Support the client's actual business model | Jewelry: net SKU/customer contribution with repeat orders separated. Membership: still-active members and payment history handled correctly. B2B: qualified leads linked through opportunities to receipts. Implement only the relevant case for each client. |
| Preserve measurement and operating changes | A recommendation can name the settings, creative/page versions, tracking regime and intervention history in effect for its data |
| Expand diagnostics with usable breakdowns | A change in audience/device/placement mix is distinguishable from a within-segment performance change, without duplicated totals or dozens of unsupported segment winners |
| Establish a credible learning record | Decision-time data, approved action, confirmed execution and mature outcomes remain distinct; backtests cannot use future approvals, final deal status or later report revisions |
| Reserve causal and response claims for adequate evidence | A documented experiment or qualified response-model path identifies what its evidence supports, including refusal when the data cannot answer |

Specific engineering questions worth answering from code and demonstrations:

- Which proposed inputs already survive raw pulls but are discarded during normalization? Retaining and exposing existing data may be sufficient for some diagnostic uses.
- Which “used” fields are only present in a type or an unmerged piece? Can the index show the actual consumer and evidence?
- What is the exact analytical unit for each conversion: click, person, company, transaction or repeat event? Which likelihood handles it?
- Can an immature period be analyzed without treating still-open sales or still-active members as failed outcomes?
- Can the client choose a business objective beyond orders/clicks without forcing leads and subscriptions into purchase semantics? `Objective.target` currently admits contribution, orders and clicks only.
- What fields are essential for the next real-client decision, and what would change if each optional field were known? This helps distinguish valuable additions from merely available data.
- Which specialized tools already produce the desired creative, UX or research evidence? Link their records instead of building duplicate assessment engines.

## 6. Examples of why the additions matter

**Jewelry:** Ad A's ROAS is higher, but its heavily discounted SKU has high shipping subsidy and returns. Ad B produces fewer orders but more retained contribution and more first-time customers. The decision needs order-line economics and mature refunds, not simply finer click reporting.

**Membership:** One campaign attracts cheap trial signups that seldom pay; another attracts members who stay and collect successfully. Signup, activation, invoice, cancellation and observation-cutoff data change the choice. A flat $140 conversion value hides the business model; an unqualified infinite lifetime extrapolation creates a different error.

**B2B:** One channel produces cheaper forms, many duplicates and few attended meetings. Another produces fewer qualified opportunities with long sales cycles. The useful comparison follows lead quality and stage timing to contribution, while keeping still-open opportunities uncertain.

**Creative:** An old ad's CPA rises after a landing-page release and a retargeting exclusion. Declaring “creative fatigue” from CPA alone would be premature. The change history narrows the explanations and suggests the next test.

## 7. Where to stop expanding

Do not require personal identities, private member profiles, unsupported cross-platform tracking, or individual-level exposures that a source does not legitimately supply. Do not make every contextual attribute a model parameter. Do not promise segment precision that the data cannot support. Do not use a richer observational dataset as a substitute for identification of causal effects.

The limit should be usefulness and evidence quality: **can this input change a valid diagnosis, forecast, test or decision, and can we establish what it means?** If yes, give it a defined path. If no, retain a source reference where useful without manufacturing analytical significance.

## 8. Primary-source checks supporting the expansion

Checked 3 November 2026. These verify examples of source capabilities and limitations, not full availability for the current client accounts or every field proposed above.

- Google's reporting interface supports queries across resources and segments; permitted field combinations still require verification. [Google Ads reporting](https://developers.google.com/google-ads/api/docs/reporting/overview).
- Google distinguishes conversion reporting metrics, including conversion-time reporting. This supports keeping the reporting clock explicit. [Conversion reporting](https://developers.google.com/google-ads/api/docs/conversions/reporting).
- Reported conversions may subsequently be adjusted. Financial and attribution records therefore need revision history rather than an assumption that the first report is final. [Conversion adjustments](https://developers.google.com/google-ads/api/docs/conversions/upload-adjustments).
- GA4 response metadata can disclose sampling, thresholding, aggregation-related data loss, restrictions, currency and timezone. These are useful analytical inputs. [GA4 response metadata](https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/ResponseMetaData).
- GA4's event export documents traffic-source and privacy-related fields; use of this export is a separate acquisition path from the current summary `SiteRow` connector. [BigQuery export schema](https://support.google.com/analytics/answer/7029846?hl=en).
- LinkedIn documents performance and aggregate professional-demographic reporting. Scope, metric compatibility, access and suppression must be checked before promising a breakdown. [LinkedIn reporting](https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads-reporting/ads-reporting?view=li-lms-2026-04).
- Subscription systems expose lifecycle and payment events, supporting a richer distinction among signup, paid service and cancellation. [Stripe subscription events](https://docs.stripe.com/billing/subscriptions/webhooks).
- Google's separate Meridian model accepts paid/organic media and contextual inputs. This is a useful example of why a future aggregate media model needs different data and assumptions; no adoption of Meridian is proposed here. [Meridian input data](https://developers.google.com/meridian/docs/advanced-modeling/input-data).

Meta's breakdown documentation could not be retrieved during this review (HTTP 429). No new Meta-specific field availability is asserted on that basis. Use the project's facts pack and an explicit supported-field check when selecting additions.
