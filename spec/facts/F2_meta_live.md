# F2b: Meta live-view additions (names, objective, account node, lead action types)

Compiled 2026-11-07, extends F2_meta.md. Tags: VERIFIED (doc text read on the fetch date), INFERRED (reasoning, source named), UNKNOWN. Version in use: v26.0 (meta.py API_VERSION). Doc pages are not version-pinned in the URLs below.

Sources
- S1 https://developers.facebook.com/docs/graph-api/reference/adaccount/insights/ (Ads Insights field table; the /docs/marketing-api/reference/ads-insights/ URL returned 404 on fetch)
- S2 https://developers.facebook.com/docs/marketing-api/reference/ad-account/
- S3 https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/
- S4 https://developers.facebook.com/docs/marketing-api/reference/ad-campaign-group/

## 1. Name fields on the insights edge at level=ad

- `account_name` is a field on the insights edge, type string. VERIFIED [S1] (table row "account_name | string | account_name")
- `campaign_name` is a field, type string. VERIFIED [S1]
- `adset_name` is a field, type string. VERIFIED [S1]
- `ad_name` is a field, type string. VERIFIED [S1]
- Restriction of these four to a particular `level`: the table states none. Valid at level=ad: INFERRED (no restriction stated; `ad_name` is the level's own name, the others are parent names). Confirmed only by the recorded probe.

## 2. objective and optimization_goal

- `objective` is a field on the insights edge, type string. VERIFIED [S1] (row "objective | string | objective"; the description column only repeats the name)
- `optimization_goal` is a field on the insights edge, type string. VERIFIED [S1] (row "optimization_goal | string | optimization_goal")
- Values of the insights `objective` field: S1 lists none. UNKNOWN from the insights page.
- The campaign `objective` enum (S4, campaign create endpoint): APP_INSTALLS, BRAND_AWARENESS, CONVERSIONS, EVENT_RESPONSES, LEAD_GENERATION, LINK_CLICKS, LOCAL_AWARENESS, MESSAGES, OFFER_CLAIMS, OUTCOME_APP_PROMOTION, OUTCOME_AWARENESS, OUTCOME_ENGAGEMENT, OUTCOME_LEADS, OUTCOME_SALES, OUTCOME_TRAFFIC, PAGE_LIKES, POST_ENGAGEMENT, PRODUCT_CATALOG_SALES, REACH, STORE_VISITS, VIDEO_VIEWS. VERIFIED [S4]
- S4 says the OUTCOME_* values are the newer objectives and "These older objectives are deprecated with the release of Marketing API v17.0." VERIFIED [S4]
- The insights `objective` returns values from that same set (so OUTCOME_LEADS, OUTCOME_SALES, LINK_CLICKS are all possible strings). INFERRED (same field name, campaign-level setting; the insights page does not say). Treat as an open string, do not hard-fail on an unseen value.
- Values of `optimization_goal`: not in S1 or S4. UNKNOWN.
- Whether the `objective` field is returned at level=ad (campaign property carried to ad rows): INFERRED yes; confirm in the probe.

## 3. Ad account node (GET act_{id}?fields=...)

- `name`: string. "Name of the account. If not set, the name of the first admin visible to the user will be returned." VERIFIED [S2]
- `account_status`: unsigned int32 ("Status of the account"). VERIFIED [S2]. JSON number expected. INFERRED (int type)
- `spend_cap`: numeric string. VERIFIED [S2] (returned as a string such as "0", not a JSON number)
- `amount_spent`: numeric string, "Current amount spent by the account with respect to `spend_cap`. Or total amount in the absence of `spend_cap`." VERIFIED [S2]
- `spend_cap` unit: "Value specified in basic unit of the currency, for example 'cents' for `USD`." VERIFIED [S2]. Minor units, so USD divisor 100.
- S2 Updating section describes the write parameter `spend_cap` differently, as a float in "standard denomination of the currency, e.g. 23.50 for USD $23.50". VERIFIED [S2]. That is the write side; the read is minor units. Not used by this read-only connector.
- `amount_spent` unit: S2 states none. UNKNOWN in the doc. INFERRED minor units like `spend_cap` (the description measures it against `spend_cap`). Confirm in the probe by comparing with the sum of insights `spend` (major units, F2 §2).
- `spend_cap` when no limit is set: "A value of `0` means no spending-cap." VERIFIED [S2]. As a numeric string the value is "0". Whether the key is absent instead for some accounts: UNKNOWN. Parser should treat absent, "0" and 0 as no cap.

## 4. account_status codes

All VERIFIED [S2]:
- 1 ACTIVE
- 2 DISABLED
- 3 UNSETTLED
- 7 PENDING_RISK_REVIEW
- 8 PENDING_SETTLEMENT
- 9 IN_GRACE_PERIOD
- 100 PENDING_CLOSURE
- 101 CLOSED
- 201 ANY_ACTIVE
- 202 ANY_CLOSED
- 201 and 202 are listed as statuses but read as filter groupings; whether the API ever returns them on a single account: UNKNOWN. INFERRED not returned on a single account node.
- No other codes (4, 5, 6) are listed. Any code outside the list: UNKNOWN meaning, keep the raw integer.

## 5. Lead action types in actions and action_values

From the Ads Action Stats page [S3]:
- `lead`: "All offsite leads plus all On-Facebook leads". VERIFIED [S3]
- `offsite_conversion.fb_pixel_lead`: "Leads" (the website pixel Lead event). VERIFIED [S3]
- `onsite_conversion.lead_grouped`: "All On-Facebook Leads". VERIFIED [S3]
- `leadgen_grouped`: "On-Facebook leads coming from Messenger and Instant Forms". VERIFIED [S3]
- `onsite_web_lead`: not listed in S3. UNKNOWN.
- Overlap: by the description, `lead` is a roll-up of offsite (pixel) leads plus on-Facebook leads, so it overlaps `offsite_conversion.fb_pixel_lead` and `onsite_conversion.lead_grouped`, as `omni_purchase` overlaps purchases. INFERRED from the `lead` description; S3 does not use the word roll-up or give an arithmetic rule.
- S3 lists no `omni_lead`. The grouped `omni_*` list in S3 is: omni_app_install, omni_purchase, omni_add_to_cart, omni_complete_registration, omni_view_content, omni_search, omni_initiated_checkout, omni_achievement_unlocked, omni_activate_app, omni_level_achieved, omni_rate, omni_spend_credits, omni_tutorial_completion, omni_custom. VERIFIED [S3]
- S3 does not say how `omni_*` relate to their members. The omni_purchase roll-up claim in F2 §3 stays INFERRED.
- Rule for the build: pick one lead type per pull, never sum. For a website pixel Lead event the specific type is `offsite_conversion.fb_pixel_lead`; `lead` also counts it plus any on-Facebook leads. Which strings the owner's account emits: UNKNOWN until the probe.
- `action_values` carries the same action_type strings: INFERRED (same AdsActionStats list type, F2 §3). A lead has a value only if the pixel event sends one.

## 6. Response shape effects of adding fields

- Paging: S1 says only "For more details about pagination, see the Graph API guide". Nothing states that more fields change paging, `limit` or cursors. VERIFIED (absence on S1); effect UNKNOWN beyond that.
- Field order: S1 states no order. The table is alphabetical. Order of keys in the JSON rows: UNKNOWN. INFERRED that JSON object order is not a contract.
- Recorded-URL replay: the request URL changes when `fields` changes (comma list in the query), so any replay keyed on the full URL will miss. This follows from the URL text, INFERRED, and matches the meta.py comment. A replay keyed on method, path and a chosen subset of params is unaffected.
- Rows with the new fields carry extra string keys. Name fields could change row count only if S1 said so; it does not. Row count and `paging` effect: UNKNOWN, INFERRED none.

## Consequences for the build

OBJECTIVE_REQUESTED = True
account_status_map: {1: ACTIVE, 2: DISABLED, 3: UNSETTLED, 7: PENDING_RISK_REVIEW, 8: PENDING_SETTLEMENT, 9: IN_GRACE_PERIOD, 100: PENDING_CLOSURE, 101: CLOSED, 201: ANY_ACTIVE, 202: ANY_CLOSED}
spend unit: minor currency units (cents for USD), divisor 100 for USD (spend_cap VERIFIED; amount_spent INFERRED)
