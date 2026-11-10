# F7b: Published benchmarks for Jovannah priors (link CTR, lead rate per link click)

Compiled 2026-11-10. Purpose: set priors for the two per-ad rates the engine models for Jovannah (fine jewelry, $795 rings, first Meta campaign, OUTCOME_LEADS, US women 25-55, mostly mobile Facebook, ads to a Shopify page with a single-field Klaviyo "Founding Circle" email form).

Our metrics:
- CTR = link clicks / impressions (Meta "CTR (link click-through rate)").
- Lead rate = pixel Lead events / link clicks, attribution 7-day click + 1-day view, so view-through leads sit in the numerator with no matching click in the denominator.

Tags: VERIFIED (primary page or PDF read on 2026-11-10, number present), SECONDARY (quoted by a third party, primary not read), UNVERIFIED (vendor or practitioner claim with no method), INFERRED (my reasoning, sources named), NOT FOUND.

## Sources

| ID | Publisher, title | URL | Data date | Sample / method as stated |
|---|---|---|---|---|
| S1 | WordStream/LocaliQ, Facebook Ads Benchmarks 2026 (PDF) | https://www.wordstream.com/wp-content/uploads/2026/09/ws-guide-facebook-ads-benchmarks-2026.pdf | Apr 1 2025 to Jun 30 2026 | 1,892 US campaigns, traffic and leads objectives; "Averages are technically median figures" |
| S2 | LocaliQ, Facebook advertising benchmarks (same 2026 data, industry tables) | https://localiq.com/blog/facebook-advertising-benchmarks/ | page updated Sep 23 2026 | tables only; methodology deferred to S1 |
| S3 | WordStream, Facebook Ads Benchmarks 2025 | https://www.wordstream.com/blog/facebook-ads-benchmarks-2025 | Apr 1 2024 to Jun 30 2025 | 554 traffic + 726 leads US campaigns; min 3 (traffic) / 2 (leads) campaigns per subcategory; medians |
| S4 | Meta Business Help Center, CTR (link click-through rate) | https://www.facebook.com/business/help/877711998984611 | live page | definition |
| S5 | Databox, Facebook Ads Benchmarks | https://databox.com/benchmarks/facebook-benchmarks | page "Last updated on November 10, 2026", monthly | 2,800+ companies of 1,000 to 100,000+ employees; median, bottom 25%, top 25% per company |
| S6 | Madgicx Research, Meta Ads Benchmarks (October 2026) | https://madgicx.com/research/meta-ads-benchmarks | Sep 1-30 2026 | medians and 25th-75th percentile; sample size and unit not stated |
| S7 | Triple Whale, Facebook Ad Benchmarks by Industry | https://triplewhale.com/blog/facebook-ads-benchmarks | Aug 1 2025 to Jul 31 2026 (published Aug 17 2026) | 40,000+ ecommerce brands; medians; CTR and CVR definitions not stated |
| S8 | Lebesgue, Meta Ads Benchmarks 2026 by Industry and AOV | https://lebesgue.io/facebook-ads/meta-ads-benchmarks-by-industry-and-aov | posted Sep 7 2026; data period not stated | medians across ecommerce businesses in their dataset; sample size not stated; CTR definition not stated |
| S9 | Unbounce, What's a good conversion rate (2024 Conversion Benchmark Report) | https://unbounce.com/landing-pages/whats-a-good-conversion-rate/ | page updated Jul 25 2025; report 2024 | 57M+ conversions, 41,000 landing pages, 464M pageviews; medians; "good" = 75th percentile |
| S10 | Unbounce, 2024 Conversion Benchmark Report landing page | https://unbounce.com/conversion-benchmark-report/ | 2024 report | channel figures stated as averages |
| S11 | Unbounce, Ecommerce conversion rate (2024 report section) | https://unbounce.com/conversion-benchmark-report/ecommerce-conversion-rate/ | 2024 report | medians |
| S12 | Klaviyo Help Center, Signup form analytics | https://help.klaviyo.com/hc/en-us/articles/360015960712 | updated Oct 21 2026 | definitions; benchmark guidance |
| S13 | Klaviyo blog, Sign-up form best practices (Maria Trotta) | https://www.klaviyo.com/blog/sign-up-form-best-practices | published Aug 6 2026 | practitioner ranges from account audits; no sample stated |
| S14 | WordStream, Facebook Lead Ads vs. Landing Pages | https://www.wordstream.com/blog/ws/2019/02/14/facebook-lead-ads-vs-landing-pages | 60 days before Feb 2019 | 3,000+ client campaigns, ~$9.5M spend; "average" |
| S15 | Motion (now runneth.com), Creative Benchmarks 2026: Winners are rare | https://runneth.com/library/research/creative-benchmarks-2026/winners-are-rare | "2026 dataset", period not stated | 578,750 creatives, 6,015 accounts, $1.29B Meta spend |
| S16 | LaunchList, Waitlist conversion rate glossary | https://getlaunchlist.com/glossary/waitlist-conversion-rate | updated Oct 22 2026 | definition only |

## 1. Meta CTR benchmarks

Definition anchor. Meta defines CTR (link click-through rate) as "link clicks divided by impressions"; CTR (all) counts every click on the ad, link or not. VERIFIED [S4]. This is our CTR.

### 1a. Sources that state link CTR versus all-clicks CTR

| Source | Segment | CTR (all) | Link CTR | Spread given | Status |
|---|---|---|---|---|---|
| S5 Databox | all Facebook Ads, per company | 1.90% median | 1.18% median | link: bottom 25% 0.80%, top 25% 1.95%; all: 1.19% / 3.24% | VERIFIED |
| S6 Madgicx | overall | 2.97% median | 1.53% median | overall IQR not shown | VERIFIED |
| S6 Madgicx | Apparel & Fashion | 3.96% (IQR 2.47-5.75%) | 2.00% (IQR 1.22-3.16%) | 25th-75th pct | VERIFIED |
| S6 Madgicx | Beauty & Personal Care | 3.24% (IQR 1.72-5.60%) | 2.16% (IQR 1.08-4.72%) | 25th-75th pct | VERIFIED |
| S6 Madgicx | Home Goods & Furnishings | 4.26% (2.31-5.17%) | 2.37% (0.98-3.07%) | 25th-75th pct | VERIFIED |
| S6 Madgicx | Food & Beverage Products (lowest link) | 1.23% (0.53-3.61%) | 0.68% (0.19-2.28%) | 25th-75th pct | VERIFIED |

Ratio link/all from these rows: Databox 0.62, Madgicx overall 0.52, Apparel & Fashion 0.51, Beauty 0.67. INFERRED (arithmetic on S5, S6). All-clicks CTR runs roughly 1.5x to 2x link CTR.

Madgicx covers 13 industries; jewelry is not one of them. Databox mixes all objectives and skews to large companies (1,000+ employees), so its median is a mature-advertiser figure.

### 1b. Sources that do not state the click definition

| Source | Segment | CTR | Notes | Status |
|---|---|---|---|---|
| S1 WordStream 2026 | Leads objective, all industries | 2.70% | prior year 2.58% (S1 text) | VERIFIED |
| S1 WordStream 2026 | Traffic objective, all industries | 1.93% | prior year 1.71% | VERIFIED |
| S2 LocaliQ 2026 | Traffic, Apparel / Fashion & Jewelry | 1.51% | CPC $0.71 | VERIFIED |
| S2 LocaliQ 2026 | Traffic, Shopping, Collectibles & Gifts | 1.88% | down 54.48% YoY per S1 | VERIFIED |
| S2 LocaliQ 2026 | Traffic, Beauty & Personal Care | 2.73% | highest traffic CTR | VERIFIED |
| S2 LocaliQ 2026 | Leads, Beauty & Personal Care | 1.35% | lowest leads CTR; down 47.06% YoY per S1 | VERIFIED |
| S2 LocaliQ 2026 | Leads, range across 14 industries | 1.35% to 4.18% | no apparel/jewelry/retail row in leads | VERIFIED |
| S3 WordStream 2025 | Traffic, Apparel / Fashion & Jewelry | 1.29% | traffic range 0.80% to 4.13% across 21 industries | VERIFIED |
| S3 WordStream 2025 | Leads, all industries | 2.59% | leads range 1.05% to 3.92% across 15 industries; Beauty 2.55% | VERIFIED |
| S7 Triple Whale | all ecommerce, all objectives | 2.39% median | prior period 2.06% | VERIFIED |
| S7 Triple Whale | Apparel & Accessories | 2.44% | Beauty 2.46%, Lifestyle & Boutique 2.44%; industry range 1.88% to 3.02% | VERIFIED |
| S8 Lebesgue | Jewellery & Accessories, AOV $200+ | 1.98% | $100-200: 1.87%; $50-100: 1.92%; under $50: 1.50% | VERIFIED |
| S8 Lebesgue | Fashion, AOV $200+ | 1.78% | Beauty & Wellness $200+: 1.33% | VERIFIED |

S1 says the leads objective is used with "Facebook Lead Ads", the in-app Instant Form. VERIFIED [S1, S3]. A click on a lead ad opens the form, so the leads-objective CTR in S1 to S3 is very likely not a website link CTR. INFERRED. The WordStream lead-campaign CTR is therefore not our metric, and probably reads high against it.

Clicks on Instant Form lead ads versus clicks to a website: no source found that splits the two. NOT FOUND.

Mobile Facebook versus Instagram CTR, and CTR for US women 25-55: no primary benchmark found. NOT FOUND.

## 2. Meta lead conversion rate (leads per click)

| Source | Segment | CVR | Definition as stated | Status |
|---|---|---|---|---|
| S1 WordStream 2026 | Leads objective, all industries | 8.54% median | S2: "total number of leads by your total number of clicks"; click type not stated; Instant Form lead ads | VERIFIED |
| S2 LocaliQ 2026 | Leads, Beauty & Personal Care | 5.63% | as above; CPL $50.91 | VERIFIED |
| S2 LocaliQ 2026 | Leads, range across 14 industries | 4.15% (Automotive For Sale) to 15.87% (Education) | as above | VERIFIED |
| S3 WordStream 2025 | Leads objective, all industries | 7.72% median (prior year 8.67%) | as above | VERIFIED |
| S3 WordStream 2025 | Leads, Beauty & Personal Care | 5.29% | as above | VERIFIED |
| S3 WordStream 2025 | Leads, range across 15 industries | 3.77% (Furniture) to 18.25% (Restaurants & Food) | as above | VERIFIED |
| S14 WordStream 2019 | Lead Generation objective (Instant Form) | 12.54% average | leads / clicks; 3,000+ campaigns | VERIFIED |
| S14 WordStream 2019 | Conversion objective to a landing page | 10.47% average | leads / clicks; same dataset | VERIFIED |

S14 is the only source found that measures website (landing page) leads per click on Meta. It is old, mixes B2B and B2C clients of a PPC software firm, and reports averages. In the same 2019 data, landing-page campaigns converted at 0.83x the Instant Form rate. INFERRED (10.47 / 12.54).

No apparel, jewelry, retail or ecommerce row exists in any leads-objective table found (S1, S2, S3). NOT FOUND.

Purchase CVR on Meta, for context only (a purchase is a much harder action than an email sign-up): Triple Whale median 1.53% all ecommerce, Apparel & Accessories 1.47% [S7, VERIFIED]; Lebesgue Jewellery & Accessories 1.39% at AOV $200+, Fashion 1.06% at $200+ [S8, VERIFIED]. Lebesgue shows conversion falling as AOV rises in most industries. VERIFIED [S8].

## 3. Landing page and sign-up form benchmarks

### 3a. Unbounce 2024 Conversion Benchmark Report

Conversion counts both form and click conversion events on Unbounce-hosted landing pages ("click", "form" and "mixed" types are analysed). VERIFIED [S10]. The denominator is visitors to the page. Unbounce reports medians "in most cases" and calls the 75th percentile "good". VERIFIED [S9].

| Segment | Median | 75th pct ("good") | Status |
|---|---|---|---|
| All industries | 6.6% | 11.4% to 40.8% depending on industry | VERIFIED [S9, S10] |
| Ecommerce landing pages | 4.2% | 11.4% | VERIFIED [S9, S11] |
| Ecommerce, fashion and beauty subcategory | 1.3% | not given | VERIFIED [S9, S11] |
| Ecommerce, food and beverage | 7.1% | not given | VERIFIED [S11] |
| Entertainment, sweepstakes (often an email-only entry, per S9) | 47.5% | top performers to 79.8% | VERIFIED [S9] |
| Entertainment overall | 12.3% | 40.8% | VERIFIED [S9] |

Channel figures from S10, stated as averages across all industries: Facebook 13%, Instagram 17.9%, paid social 12%, paid search 10.9%, email 19.3%. VERIFIED [S10]. S11 says ecommerce Facebook traffic is "hovering around the ecommerce industry median" and the top-performing Facebook pages reach 15.3%; the Facebook median itself is in a chart I could not read. VERIFIED for the quoted text; the number NOT FOUND.

Device: 83% of analysed visits were mobile, and mobile converts 8% less than desktop across industries. VERIFIED [S10]. For ecommerce, mobile visitors convert "almost 18% less often". VERIFIED [S11].

The ecommerce medians mostly measure product pages pushing toward a purchase or a click, not a free sign-up. The 1.3% fashion and beauty figure is not comparable to an email form. INFERRED.

### 3b. Klaviyo sign-up forms

Submit rate = total submitted form events / total viewed form events, counting every submit rather than unique profiles, excluding teaser-only views. VERIFIED [S12]. Denominator is form views, not page visits or ad clicks.

| Claim | Value | Status |
|---|---|---|
| Klaviyo's recommended floor for popups and flyouts | "about 3% or higher" | VERIFIED [S12] |
| Peer benchmarks available | popup forms only; "not available for flyout, full page, or embed forms" | VERIFIED [S12] |
| Standard popup (first touch on homepage) | 3-8% | VERIFIED as stated by a Klaviyo strategist [S13]; method not stated |
| Exit-intent forms | 10-13% | VERIFIED as stated [S13]; method not stated |
| Brands seen by the author | 8-20% | VERIFIED as stated [S13]; anecdotal |
| Full-page forms have the highest submit rate among form types | no number | SECONDARY (Klaviyo Academy, quoted in a search result; page not read) |

Embedded form or dedicated landing page submit rate from Klaviyo: NOT FOUND.

### 3c. Single-field email, waitlist and pre-launch pages

LaunchList defines waitlist conversion as sign-ups / visitors and says there is "no honest benchmark" because conversion depends on who arrives. VERIFIED [S16]. Ranges seen in search snippets (20-40% for email-only asks, 3-10% for paid-ad traffic, an 11% "median waitlist" from a roundup) come from vendors with no stated method. UNVERIFIED; do not use as anchors.

The only measured anchor for a near email-only ask is Unbounce sweepstakes at 47.5% median [S9], which carries a prize incentive. Jovannah's form offers membership, not a prize. INFERRED.

## 4. First campaigns, new brands, and spread between ads

New account or first campaign versus established accounts: no published dataset found that splits CTR or conversion by account age. NOT FOUND. Search returned only practitioner blogs without data.

Closest proxies:
- Motion [S15]: about 5% of creatives are "winners" (spend at least 10x the account median and at least $500). Hit rate runs from about 3.8% for Micro accounts (under $10K/month) to about 8.2% for Enterprise ($1M+/month). About half of all ads receive little or no spend, and roughly 6% of ads in an account capture most of its spend. VERIFIED. No CTR, CVR or CPA dispersion is reported.
- WordStream subcategory cells swing hard year to year with minimum cell sizes of 2 to 3 campaigns [S3]: Beauty leads CTR 2.55% (2025) to 1.35% (2026); Shopping, Collectibles & Gifts traffic CTR up 146% in 2025 then down 54.48% in 2026; Furniture leads CTR up 155.41% in 2026. VERIFIED [S1, S3]. The industry medians are themselves noisy at the level of a few campaigns.
- Across-company and across-account spread: Databox link CTR quartiles 0.80% / 1.18% / 1.95% [S5]; Madgicx Apparel & Fashion link CTR quartiles 1.22% / 2.00% / 3.16% [S6]. VERIFIED. These describe accounts or companies, not ads within one campaign.
- Unbounce: ecommerce median 4.2% against 75th percentile 11.4% [S9]. VERIFIED. Page-to-page spread across many offers.

Within-campaign spread of CTR or conversion between ads: NOT FOUND in any published benchmark. The Motion spend concentration means Meta will give a few ads most of the impressions, so per-ad sample sizes will be very uneven. INFERRED [S15].

## Implications for priors

Both priors below are for a single ad's true rate, before any Jovannah data, expressed as a median and a 90% interval on a log scale (lognormal or logit-normal with sigma about 0.7, so the 90% bounds sit at about 3.2x either side of the median). INFERRED throughout; the reasoning is tied to the facts above.

| Rate | Central value | Plausible 90% range | Implied log-scale sigma |
|---|---|---|---|
| CTR (link) = link clicks / impressions | 1.1% | 0.35% to 3.5% | ~0.7 |
| Lead rate = pixel Leads / link clicks | 7% | 2% to 22% | ~0.7 |

### CTR (link)

The two sources that report link CTR directly put the median at 1.18% (Databox, all advertisers) and 1.53% (Madgicx overall), with apparel and fashion at 2.00%. Sources with unstated definitions run higher (Triple Whale 2.39%, WordStream leads 2.70%), which fits them being all-clicks or form-open CTRs; scaling by the 0.5 to 0.67 link/all ratio found in S5 and S6 brings them to about 1.2% to 1.8%. Lebesgue's jewelry figure at AOV $200+ is 1.98%, definition unstated. Several things push Jovannah below the apparel median: a cold audience with no retargeting pool or social proof, an unknown brand on its first campaign, a leads objective that optimizes delivery for sign-ups rather than clicks (practitioner quote in S3: CTRs tend to fall as you focus on conversion), and mostly Facebook feed placements rather than Instagram. Hence 1.1%, near the Databox median and below the fashion figures.

The width comes from the Databox link-CTR interquartile range (0.80% to 1.95%, log sigma about 0.66) and Madgicx apparel (1.22% to 3.16%, about 0.70). Those are between-account spreads. A single ad's prior has to cover both "what kind of account is Jovannah" and "how does this creative differ from its siblings"; with no published within-campaign spread, sigma 0.7 is the defensible floor rather than a ceiling. If the engine pools ads within the campaign, the between-ad sigma should be learned from her data and this prior applies to the campaign-level mean.

Definition gaps: our CTR is Meta's link CTR [S4], which matches Databox and Madgicx exactly. WordStream, LocaliQ, Triple Whale and Lebesgue do not say which CTR they report; treat them as upper anchors.

### Lead rate per link click

No published benchmark measures this exact ratio for ecommerce. The nearest anchors, from most to least comparable:
1. Meta to landing page, leads per click: 10.47% average (WordStream 2019, mixed industries) [S14].
2. Landing pages, all industries: 6.6% median, Facebook-sourced visitors 13% average [S9, S10].
3. Meta Instant Form leads per click: 8.54% median 2026, Beauty 5.63% [S1, S2]. Instant Forms convert above landing pages (S14 ratio 0.83), so the website equivalent is around 7%.
4. Klaviyo popups: 3% floor, 3-8% typical, per form view [S12, S13]. A popup interrupts a shopper; Jovannah's page exists only for the sign-up, so it should beat a popup.

These cluster around 6% to 10%. Pulling the centre down to 7%: a link click is not a landing-page view (some taps never load the page on mobile), mobile converts 8% to 18% below desktop [S10, S11], and a $795 product with an unknown brand gives weaker intent. Pushing it up: one field, no price asked, and 1-day view-through leads land in the numerator with no click in the denominator, which inflates our ratio against every benchmark above (all of which are per-click or per-view only). These roughly offset; 7% sits between the Unbounce all-industry median and the WordStream landing-page figure.

The 90% range of 2% to 22% spans the Klaviyo popup floor at the bottom and the top quartile of landing pages (11.4% ecommerce, Facebook top performers 15.3%) with room above for view-through inflation. Unbounce's median-to-75th-percentile gap (4.2% to 11.4%) implies a much wider spread across pages generally, but that spread mixes very different offers; one offer on one page should vary less. INFERRED.

Definition gaps: Unbounce divides by page visitors, Klaviyo by form views, WordStream by clicks of unstated type. None includes view-through conversions. Our numerator does. If view-through leads turn out to be a large share of pixel Leads, the engine should split them out or widen the upper tail rather than move the centre.

### What would tighten these

Nothing published closes the two biggest gaps: a jewelry or ecommerce leads-objective benchmark with a website destination, and the spread of CTR between ads inside one campaign. Jovannah's own first-week data on a handful of ads will dominate both priors quickly; the priors matter most for ads with under a few thousand impressions or a few hundred link clicks.
