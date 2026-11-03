# ENG-BAYES data point index

Every data point the engine can use, where it comes from, and what it powers. Status: **used** means the engine reads it today (wave 1 merged or wave 2 building); **specified** means spec v0.3 defines it and a later wave builds it (P9 decisions, P11 pipeline); **planned** means a logged follow-up (`spec/followups/open.md`) and not yet in the spec. Source of truth for field names: `src/bayesian_marketing/core/` and `registries/channels.yaml`.

Required means the engine refuses to decide without it. Everything else improves precision or unlocks a feature.

## 1. Client and account setup (`ClientConfig`)

| Data point | Required | Status | Powers |
|---|---|---|---|
| Client id | yes | used | every record, approval and report |
| Account timezone | yes | used | normalizing dates (§5.1 C2), lag in calendar days (D27) |
| Reporting currency | yes | used | money checks; refuses mixed currencies (G9) |
| Ad account id per platform (Meta `act_…`, Google Ads customer id, LinkedIn account id) | per platform used | used | connectors |
| Partner or user access for the agency on each ad account | per platform used | used | connectors read with the agency's token |
| GA4 property id, with the agency login as Viewer | no | used | site-side conversions, the observed check on platform-reported numbers |

## 2. Unit economics (`ClientEconomics`)

| Data point | Required | Status | Powers |
|---|---|---|---|
| Price per order, or "use the modeled average order value" | yes | used | value of a conversion (D14) |
| Variable cost per order: production, fulfilment, payment fees, expected returns | yes | used | contribution = price − variable cost (D14) |
| Loss tolerance per decision (default policy 5% of monthly spend) | yes | used | whether a decision is knowable (D9, D16, G9) |
| Survival floor: the spend or contribution level the business cannot drop below | no | specified | allocation never recommends below it (P9) |
| Test budget | no | used | whether buying more data is worth it (EVSI, §6.3) |
| Repeat purchase value (a distribution) | no | specified | value beyond the first order |
| Switching cost when changing ads (learning-phase cost) | no | specified | hold vs switch (`switching_cost_hold`) |
| Who approved the economics, and when | yes | used | economics must be approved before any decision |

## 3. Ad platform performance, per ad per day (`PerformanceRow`)

Pulled by the connectors or read from a CSV export. Hierarchy: account → campaign → ad set (ad group, LinkedIn campaign) → ad.

| Data point | Required | Status | Powers |
|---|---|---|---|
| Date (daily breakdown) | yes | used | everything; non-daily aggregates are quarantined |
| Account, campaign, ad set and ad ids and names | yes (ad id) | used | the funnel per ad; pooling across ads |
| Impressions | yes | used | CTR, CPM (delivery) |
| Link clicks (Meta), clicks (Google Ads, LinkedIn) | yes | used | CTR, CPC, CVR trials |
| Spend | yes | used | CPM, CPC, CPA, ROAS |
| Currency | yes | used | money checks |
| Conversions as the platform reports them (may be fractional or modeled) | no | used | platform-attributed CVR, CPA; flagged as reported, not observed (C8) |
| Conversion value as reported | no | used | platform ROAS, with its caveat |
| Attribution setting (e.g. 7-day click, 1-day view) | yes | used | splits the series when it changes (C5); sets the lag curve |
| Objective / result type (Meta "Results") | no | used | flags mixed objectives; Results are not assumed to be purchases |

## 4. Orders and sales (CRM, shop, payments)

The engine's own orders format (`registries/channels.yaml`, `orders`). The intake maps any CRM or shop export into it.

| Data point | Required | Status | Powers |
|---|---|---|---|
| Order id | yes | used | dedupe |
| Ordered at (timestamp with timezone offset) | yes | used | observed conversions, lag |
| Order value and currency | yes | used | observed order value, AOV, ROAS |
| Refunded amount | yes | used | net value |
| UTM source, medium, campaign, content | no | used | ties an order to a campaign and ad |
| Click id (fbclid, gclid, li_fat_id) | no | used | ties an order to an ad more reliably than UTMs |
| First click time | no | used | conversion lag estimated from the client's own data (P7) |
| Customer id | no | planned | repeat value, cohorts |
| Product / SKU and quantity | no | planned | per-product value when a client sells several things |

## 5. Site analytics (GA4, `SiteRow`)

| Data point | Required | Status | Powers |
|---|---|---|---|
| Date | yes | used | daily series |
| Session source, medium, campaign | yes | used | channel and campaign mapping |
| Sessions | yes | used | site-side conversion rate |
| Ecommerce purchases | yes | used | observed conversions when no orders export exists |
| Purchase revenue | yes | used | observed value |

## 6. Subscriptions and members (planned)

| Data point | Required | Status | Powers |
|---|---|---|---|
| Member id, signup date, cancel date (or still active) | for subscription clients | planned | retention curve |
| Plan price per period and billing period | for subscription clients | planned | value per subscriber |
| Acquisition source per member (UTM or click id at signup) | no | planned | value per channel, not only per subscriber |
| Pauses, plan changes, failed payments | no | planned | refines retention |

## 7. History for priors (P7)

| Data point | Required | Status | Powers |
|---|---|---|---|
| Past campaign results: clicks, conversions per campaign or month | no | used | client priors via `prior_from_cohorts`, discounted |
| Industry, product type, price point, platform, audience temperature | no | planned | picks a vertical prior for clients without history |
| Vertical benchmark tables with their sample sizes | no | planned | the vertical priors themselves; owner-approved |
| Owner approval of each prior | yes before client use | used | G8 blocks unapproved priors on client data |

## 8. Decision and test settings (per decision)

| Data point | Required | Status | Powers |
|---|---|---|---|
| Objective: contribution, orders or clicks | yes | used | what "better" means |
| Horizon: clicks, impressions, spend or days | yes | used | the size of the decision being priced |
| Options being compared (which ads, ad sets or channels) | yes | used | compare, allocate, stop or continue |
| Test design: cost, sample size, duration | no | used | value of the test vs its cost |

## 9. Outcomes, after a decision

| Data point | Required | Status | Powers |
|---|---|---|---|
| What was approved and acted on | yes | used | append-only run record |
| What happened afterwards (realized results) | no | specified | shadow scoring of the engine's own calls |

## What each tester needs first

| Tester | Minimum to start |
|---|---|
| A client with no history (Jo) | sections 1, 2 and 3 on her Meta account; section 7 industry fields once vertical priors exist |
| A client with history (Lieven) | sections 1, 2 and 4, plus 6 for members; section 3 for whichever platform he chooses |
