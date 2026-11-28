# ENG-BAYES data point index

What the engine can take in today and how far each data point has really travelled. Field names follow `src/bayesian_marketing/core/` and `registries/channels.yaml`. The wider catalogue of evidence worth adding later is `spec/Data_Point_Expansion_Review_2026-11-03.md`; this index covers only what the engine has a path for.

## Maturity ladder

Each data point gets six separate answers, because they differ for the same field.

| Step | Meaning |
|---|---|
| Spec | spec v0.3 or a decision defines it |
| Repr | a core type can hold it |
| Ingest | a reader (CSV export) or connector (API) fills it |
| Use | a model, decision or report consumes it |
| Tested | a fixture or simulator test exercises that path |
| Live | verified against a real account or export |

Marks: **y** yes; **–** no; **D34** being added now by the D34 integration fix; **P5/P11** arrives with that piece (P5 joint model, P11 pipeline). As of 2026-11-03, live verification exists only for GA4 (the owner's Tao of Atma property) and for an empty Meta account.

"Required" is per use. Ingest needs only the ingest-minimum fields; a decision also needs the decision-minimum fields; a named claim (lifetime value, causal lift) needs its own evidence and is refused without it.

## 1. Client and account setup (`ClientConfig`)

| Data point | Needed for | Spec | Repr | Ingest | Use | Tested | Live |
|---|---|---|---|---|---|---|---|
| Client id | ingest | y | y | y | y | y | – |
| Account timezone | ingest | y | y | y | y | y | GA4 |
| Reporting currency | ingest | y | y | y | y | y | GA4 |
| Ad account id per platform | ingest | y | y | y | y | y | Meta (empty) |
| Agency access on each ad account | ingest | y | – | y | – | – | Meta |
| GA4 property id, agency login as Viewer | site outcomes | y | y | y | y | y | GA4 |

## 2. Unit economics (`ClientEconomics`)

| Data point | Needed for | Spec | Repr | Ingest | Use | Tested | Live |
|---|---|---|---|---|---|---|---|
| Price per order, or "use modeled order value" | decisions | y | y | file | y | y | – |
| Variable cost per order | decisions | y | y | file | y | y | – |
| Loss tolerance per decision | decisions (G9) | y | y | file | y | y | – |
| Owner approval of the economics | decisions | y | y | file | y | y | – |
| Survival floor | allocation | y | y | file | y | y | – |
| Test budget | buy-more-data decisions | y | y | file | y | y | – |
| Switching cost (learning phase) | keep-vs-switch | y | registry | registry | y | y | – |
| Repeat purchase value | value beyond first order | y | y | file | – | – | – |
| Per-product or per-plan economics | many-product clients | – | – | – | – | – | – |

"file" means the economics JSON a client run points at; intake writes it.

## 3. Ad performance, per ad per day (`PerformanceRow`)

| Data point | Needed for | Spec | Repr | Ingest | Use | Tested | Live |
|---|---|---|---|---|---|---|---|
| Date (daily rows only; aggregates quarantined) | ingest | y | y | y | y | y | – |
| Account, campaign, ad set, ad ids | ingest | y | y | y | y | y | – |
| Account, campaign, ad set, ad names | reports | y | y | D34 | D34 | D34 | – |
| Campaign objective / optimization event | comparability | y | y | D34 | D34 | D34 | – |
| Impressions | delivery, CTR, CPM | y | y | y | y | y | – |
| Clicks (Meta link clicks) | CTR, CPC, CVR trials | y | y | y | y | y | – |
| Spend | cost metrics | y | y | y | y | y | – |
| Currency | money checks | y | y | y | y | y | – |
| Reported conversions (may be fractional or modeled) | platform series | y | y | y | y | y | – |
| Reported conversions above clicks (view-through etc.) | platform series | y | y | D34 | D34 | D34 | – |
| Reported conversion value | platform ROAS | y | y | y | y | y | – |
| Attribution setting | series splits, lag curve | y | y | y | y | y | – |

## 4. Orders and sales (orders format in `registries/channels.yaml`)

| Data point | Needed for | Spec | Repr | Ingest | Use | Tested | Live |
|---|---|---|---|---|---|---|---|
| Order id | dedupe | y | y | y | y | y | – |
| Ordered at, with timezone offset | observed conversions, lag | y | y | y | y | y | – |
| Order value and currency | order value, ROAS | y | y | y | y | y | – |
| Refunded amount | net value | y | y | y | y | y | – |
| UTM source, medium, campaign, content | order-to-campaign match | y | y | y | P11 | – | – |
| Click id (fbclid, gclid, li_fat_id) | order-to-ad match | y | y | y | P11 | – | – |
| First click time | client's own lag curve | y | y | y | y | y | – |
| Customer id | repeat value, cohorts | – | – | – | – | – | – |
| Order lines: SKU, quantity, unit price | product contribution | – | – | – | – | – | – |

UTMs and click ids are associations under a matching rule, not proof that an ad caused the order.

## 5. Site analytics (GA4, `SiteRow`)

| Data point | Needed for | Spec | Repr | Ingest | Use | Tested | Live |
|---|---|---|---|---|---|---|---|
| Date | ingest | y | y | y | y | y | y |
| Session source, medium, campaign | channel mapping | y | y | y | y | y | y |
| Sessions | site conversion rate | y | y | y | y | y | y |
| Ecommerce purchases | site-recorded conversions | y | y | y | y | y | y |
| Purchase revenue | site-recorded value | y | y | y | y | y | y |
| Property timezone and currency (response metadata) | normalization | y | y | y | y | y | y |
| Sampling, thresholding, data-loss flags | data quality | y | notes | D34 | D34 | D34 | – |

GA4 purchases are events the site tag recorded. They can be duplicated or missed, so the engine calls them site-recorded, not verified orders.

## 6. Subscriptions and members (planned)

| Data point | Needed for | Spec | Repr | Ingest | Use | Tested | Live |
|---|---|---|---|---|---|---|---|
| Objective "subscription_contribution" | naming the goal | y | y | – | refused (D33) | y | – |
| Member id, signup, paid start, cancel or still active | retention | – | – | – | – | – | – |
| Plan price, billing period, invoices paid, refunds | value per subscriber | – | – | – | – | – | – |
| Acquisition source per member | value per channel | – | – | – | – | – | – |

Still-active members are incomplete observations, not zero churn.

## 7. Leads (planned)

| Data point | Needed for | Spec | Repr | Ingest | Use | Tested | Live |
|---|---|---|---|---|---|---|---|
| Objective "leads" | naming the goal | y | y | – | refused (D33) | y | – |
| Lead, qualification, opportunity, won/lost, cash dates | lead-to-cash value | – | – | – | – | – | – |

## 8. History for priors

| Data point | Needed for | Spec | Repr | Ingest | Use | Tested | Live |
|---|---|---|---|---|---|---|---|
| Framework default priors (10, owner-approved D32) | every fit | y | y | registry | y | y | – |
| Past results per campaign or month (counts) | client priors | y | y | function | y | y | – |
| Owner approval of each client prior | client fits (G8) | y | y | y | y | y | – |
| Industry and product for a vertical prior | clients without history | y | – | – | – | – | – |
| Vertical benchmark tables with sample sizes | vertical priors | – | – | – | – | – | – |

## 9. Decision settings and outcomes

| Data point | Needed for | Spec | Repr | Ingest | Use | Tested | Live |
|---|---|---|---|---|---|---|---|
| Objective: contribution, orders or clicks | decisions | y | y | request | y | y | – |
| Horizon: clicks, impressions, spend or days | decisions | y | y | request | y | y | – |
| Options compared | decisions | y | y | request | y | y | – |
| Test design: cost, size, duration | test decisions | y | y | y | y | y | – |
| Approval of each recommendation | acting | y | y | y | y | y | – |
| Realized outcome after a decision | shadow scoring | y | y | y | y | y | – |

## What each tester needs first

| Tester | Minimum |
|---|---|
| Client with no history (Jo, Meta) | sections 1, 2 and 3 for her account; a vertical prior once section 8's vertical rows exist |
| Client with history (Lieven) | sections 1, 2 and 4; section 6 before any subscriber-value claim; section 3 for the platform he picks |
