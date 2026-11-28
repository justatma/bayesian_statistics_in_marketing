# F2: Meta Marketing API (Graph API), read-only reporting

Compiled 2026-11-03. Every line carries a tag: VERIFIED (read in official Meta doc on the fetch date), INFERRED (third-party source or reasoning), UNKNOWN (searched, not found). Source short names are listed at the end; all fetched 2026-11-03.

## 1. Version and URL

- Latest Graph API version is v26.0, released 2026-07-29, expiry "TBD". VERIFIED [S1]
- v25.0 released 2026-02-18, expires 2028-07-29. v24.0 expires 2028-02-18. v23.0 expires 2027-10-08. v22.0 expires 2027-05-20. v21.0 expires 2027-01-21. v20.0 expires 2026-09-24 (already past as of today). v19.0 and earlier are expired. VERIFIED [S1]
- Version sits between host and path: `https://graph.facebook.com/v26.0/{node}/{edge}`. VERIFIED [S2]
- A call with no version uses the version set in the app dashboard ("Upgrade API Version" card). Meta recommends always specifying it. VERIFIED [S2]
- A version stays usable for two years after the next version's release; after that, calls fall to the next oldest usable version. VERIFIED [S2]
- Recommendation for the connector: pin the version in config, default `v26.0` (or `v25.0` for the longest runway to expiry), never omit. INFERRED (reasoning from the two rows above)
- Insights doc examples already use v26.0. VERIFIED [S3]

## 2. Insights endpoints

- `GET /act_{ad_account_id}/insights` and `GET /{ad_id}/insights`. Edge also exists on campaign and ad set IDs. VERIFIED [S3][S4]
- `account_id` in the path takes the `act_` prefix; the `account_id` field on the Ad Account object is the numeric ID without the prefix, and `id` is `act_{numeric}`. VERIFIED [S5]
- Default with no params: basic metrics, typically past 30 days (`date_preset` default `last_30d`). VERIFIED [S3][S4]
- Requires `ads_read`. VERIFIED [S3]
- `limit`: integer, no default or maximum stated in the reference. UNKNOWN (searched S4, S6)

### Parameters (v26.0 reference, S4)

| Param | Type | Accepted values / default | Status |
|---|---|---|---|
| `level` | enum | `ad`, `adset`, `campaign`, `account`. Default not stated. | VERIFIED |
| `fields` | list of strings | see Fields below | VERIFIED |
| `time_range` | object | `{"since":"YYYY-MM-DD","until":"YYYY-MM-DD"}`. since starts at midnight of that day, until runs to midnight of the following day (doc wording). Send as JSON string in the query. | VERIFIED (shape); JSON-string encoding INFERRED |
| `time_ranges` | list of objects | same shape as `time_range` | VERIFIED |
| `date_preset` | enum | default `last_30d`; includes `today`, `yesterday`, `last_7d`, `last_28d`, `last_90d`, `maximum`, etc. `lifetime` disabled since v10.0, replaced by `maximum`, which returns up to 37 months. | VERIFIED |
| `time_increment` | enum or integer | `monthly`, `all_days` (default), or an integer. Integer 1 meaning one row per day: not spelled out in the reference. | VERIFIED (type, default); daily meaning of `1` INFERRED (task brief and common usage) |
| `breakdowns` | list of enums | long enum: `age`, `country`, `gender`, `region`, `dma`, `publisher_platform`, `platform_position`, `device_platform`, `impression_device`, `placement_path`, `frequency_value`, `product_id`, `zip`, `hsid`, many more. | VERIFIED |
| `action_attribution_windows` | list of enums | default `default`. Enum: `1d_view`, `7d_view`, `28d_view`, `1d_click`, `7d_click`, `28d_click`, `1d_ev`, `dda`, `default`, `7d_view_first_conversion`, `28d_view_first_conversion`, `7d_view_all_conversions`, `28d_view_all_conversions`, `skan_*`, `incrementality`, `incrementality_first_conversion`, `incrementality_all_conversions`, `custom`, `1d_sequenced`, `7d_sequenced`, `28d_sequenced`. | VERIFIED |
| `action_breakdowns` | list of enums | default empty list; includes `action_type`, `action_device`, `action_destination`, `action_target_id`, `action_reaction`, `action_video_type`, `conversion_destination`, etc. If unset, `action_type` is added implicitly. | VERIFIED [S4][S7] |
| `action_report_time` | enum | `impression`, `conversion`, `mixed`, `lifetime` | VERIFIED |
| `use_unified_attribution_setting` | boolean | default not stated. Third-party/notice wording: true means use each ad object's own attribution setting. | param VERIFIED; semantics INFERRED [S8 search snippet, not fetched in full] |
| `use_account_attribution_setting` | boolean | default `false`. Reported as deprecated in the Insights doc (search snippet only). | VERIFIED (exists, default); deprecation INFERRED |
| `filtering` | list of filter objects | each `{field, operator, value}`; operators include `EQUAL`, `NOT_EQUAL`, `GREATER_THAN`, `IN`, `NOT_IN`, `CONTAIN`, `IN_RANGE`, `STARTS_WITH`, etc. | VERIFIED |
| `sort` | list of strings | default empty | VERIFIED |
| `limit` | integer | see above | UNKNOWN |
| `default_summary` / `summary` | bool / list | default false | VERIFIED |

- Narrowing windows: only conversion-type metrics support windows longer than 1 day. Metrics are unavailable when aggregating across multiple attribution settings, and unavailable with some breakdowns such as age or gender (applies to off-Facebook action types). VERIFIED [S11][S7]
- Windows available with `action_attribution_windows=1d_click,7d_click,1d_view,incrementality`. VERIFIED [S7][S11]
- Since 2026-01-12 the API no longer returns `7d_view` and `28d_view` in actions, conversions, results. `1d_click`, `7d_click`, `28d_click`, `1d_ev`, `1d_view` remain. The v26.0 enum still lists `7d_view` and `28d_view`, so do not rely on the enum; do not request them. VERIFIED [S10] (announced 2025-10-16). Third-party claim that requesting them yields blanks or zeros without error: INFERRED [S8 search result, vendor blog].
- What `default` resolves to (the account/ad attribution setting vs 7d_click + 1d_view): the field is described only as "default attribution window" (`value` key). UNKNOWN exact mapping. Third-party sources say 7d_click and 1d_view historically. INFERRED.
- Breakdown history limits since 2026-01-12: unique-count fields and hourly breakdowns 13 months; `frequency_value` 6 months; `mmm` breakdowns async only; plain totals up to 37 months. VERIFIED [S10]. Error 3018 fires when `since` is beyond 37 months. VERIFIED [S4]
- Reach-related breakdowns older than 13 months: up to 10 requests per ad account per day. VERIFIED [S6]

### Fields (S4 field table, types as documented)

| Field | Type | Returned by default |
|---|---|---|
| `date_start` | string (YYYY-MM-DD) | yes |
| `date_stop` | string | yes |
| `account_id` | numeric string | yes |
| `account_name` | string | no |
| `account_currency` | string | no |
| `campaign_id` | numeric string | yes |
| `campaign_name` | string | not shown in the table I fetched. UNKNOWN default flag. |
| `adset_id` | numeric string | yes |
| `adset_name` | string | not shown. UNKNOWN default flag. |
| `ad_id` | numeric string | yes |
| `ad_name` | string | not shown. UNKNOWN default flag. |
| `impressions` | numeric string | yes |
| `reach` | numeric string | no |
| `clicks` | numeric string | no |
| `inline_link_clicks` | numeric string | no |
| `spend` | numeric string | yes |
| `actions` | list of AdsActionStats | no |
| `action_values` | list of AdsActionStats | no |
| `purchase_roas` | list of AdsActionStats | no |
| `attribution_setting` | string | no |

- Names and types in the table above: VERIFIED [S4]. `campaign_name`, `adset_name`, `ad_name` exist as fields: INFERRED (standard and consistent with the `*_id` fields; table fetch omitted them).
- Rule for builders: always pass `fields=` explicitly. Defaults shift and not all of these return by default. INFERRED (reasoning)
- Response envelope: `{"data":[...], "paging":{...}, "summary":[...]}`. VERIFIED [S4]
- With `level=ad` and `time_increment=1`, each row carries `date_start` and `date_stop` equal to the same day. INFERRED (common behavior; not stated in fetched docs)

## 3. actions, action_values, purchase_roas shape

- Each is a list of AdsActionStats objects. VERIFIED [S4]
- Entry keys: `action_type` (string), `value` (numeric string, default window), and per-window keys named `1d_click`, `7d_click`, `28d_click`, `1d_view`, `7d_view`, `28d_view`, `1d_ev`, `1d_sequenced`, `7d_sequenced`, `28d_sequenced`, `dda`, `incrementality`, `inline`, `custom`, plus `_all_conversions` and `_first_conversion` variants. Also `action_destination`, `action_target_id`, `action_device`, `action_reaction`, `action_carousel_card_id`, `action_carousel_card_name`, `action_canvas_component_name`, `action_video_sound`, `action_video_type` appear when the matching `action_breakdowns` is set. VERIFIED [S11]
- Per-window keys appear only for windows you requested through `action_attribution_windows`. INFERRED (reasoning; third-party reports consistent)
- Illustrative entry (shape INFERRED from S11 key list, values invented): `{"action_type":"offsite_conversion.fb_pixel_purchase","value":"3","7d_click":"3","1d_view":"0"}`
- `purchase_roas` entries use the same list shape, with `action_type` such as `omni_purchase` and a ratio in `value`. INFERRED (third-party). UNKNOWN in official docs fetched.
- Documented action_type examples: `link_click`, `like`, `offsite_conversion.fb_pixel_purchase`, grouped `omni_purchase`. VERIFIED [S11]
- Purchase types seen in practice: `omni_purchase` (all channels total), `offsite_conversion.fb_pixel_purchase` (website pixel), plain `purchase`. INFERRED [S12 third-party]. Official list of all action_type strings: UNKNOWN (not found in fetched Meta docs).
- Lead types: `lead` (plain), `offsite_conversion.fb_pixel_lead` (pixel). INFERRED [S12]. `onsite_conversion.lead_grouped`: UNKNOWN, no source confirmed it.
- Custom conversions appear as `offsite_conversion.custom.<ID>`. INFERRED [S12]
- Families duplicate each other (`omni_purchase` is a roll-up of pixel, app, and onsite purchases), so summing across action_types double counts. Pick one action_type per metric. INFERRED [S12]
- Developer thread reports `omni_purchase` rejected as a value in the `fields` param at account level. This concerns `fields`, not action_type strings. INFERRED, single forum report, unverified.

## 4. Value types, fractions, modeling

- Metrics arrive as strings: sample responses show `"impressions": "4"`, and the reference types them "numeric string". Parse with Decimal or int/float after reading. VERIFIED [S7][S4]
- Rate-style fields (CPC etc.) are strings too. INFERRED
- Estimated/modeled data: Meta states that "Insights breakdown values are estimated". The breakdown `is_conversion_id_modeled` flags modeled conversion bits (only with `total_postbacks_detailed`). VERIFIED [S7]
- Whether `actions` values can be fractional (modeled/attributed splits, e.g. "2.4"): not documented in the pages fetched. UNKNOWN. Third-party vendors say modeled conversions are included in action_values for purchases and that they can take up to 72 hours to settle. INFERRED [S13 vendor docs]. Builder rule: parse all conversion values as Decimal, not int. INFERRED (defensive reasoning).
- Data freshness: insights refresh every 15 minutes and "do not change after 28 days of being reported". VERIFIED [S6]
- Reporting timezone: insights are reported in the ad account's timezone (Meta's advice to schedule pulls with the account timezone in mind). VERIFIED [S6]. Date ranges in `time_range` are therefore account-local days. INFERRED.

## 5. Pagination

- Cursor paging: `paging.cursors.before` and `paging.cursors.after`; follow `paging.next` (full URL) until it is absent. VERIFIED [S14]
- A page can be empty yet carry `next`. Keep following until `next` is gone. A short page does not mean the end. VERIFIED [S14]
- Do not store cursors long term. VERIFIED [S14]
- Error 2642 "Invalid cursor values". VERIFIED [S4]
- Whether `paging.next` embeds the access token in the URL: UNKNOWN in fetched docs. INFERRED yes (long-standing behavior); builders must not log it.

## 6. Async report jobs

- When: try sync first; use async when sync times out or volume is large. VERIFIED [S6]
- Submit: `POST /act_{id}/insights` (or `POST /{ad_object}/insights`) with the same params as GET. Returns `{"report_run_id":"<numeric string>"}`. No Graph object is created. VERIFIED [S4][S6]
- Poll: `GET /{report_run_id}` and read `async_status` and `async_percent_completion` until `async_status` = `Job Completed` and percent = 100. VERIFIED [S6]
- Statuses: `Job Not Started`, `Job Started`, `Job Running`, `Job Completed`, `Job Failed` (fix query and retry), `Job Skipped` (job expired, resubmit). VERIFIED [S6]
- Fetch: `GET /{report_run_id}/insights` (paged as usual). VERIFIED [S6]
- `report_run_id` expires after 30 days. VERIFIED [S6]
- A request including retries can take up to an hour. VERIFIED [S6]
- Since v25.0 failed reports return `error_code`, `error_message`, `error_subcode`, `error_user_title`, `error_user_msg` on the report run. VERIFIED [S6]
- When sync is not enough: Meta states "no explicit limit for when a query will fail"; data-per-call limits (rows and data points) fail with `error_code=100`, subcode `1487534`; remedy is narrow date range or fewer ad IDs. VERIFIED [S6]
- Practical rule for the connector (level=ad, daily, one account): chunk date ranges (e.g. per month), fall back to async on timeout or subcode 1487534. INFERRED (reasoning from S6).
- `mmm` breakdowns require async. VERIFIED [S10]

## 7. Rate limiting

Headers:

| Header | Content | Status |
|---|---|---|
| `x-app-usage` | `{"call_count":28,"total_time":25,"total_cputime":25}` (percent of app quota) | VERIFIED [S15] |
| `x-ad-account-usage` | `{"acc_id_util_pct":9.67,"reset_time_duration":100,"ads_api_access_tier":"standard_access"}`. The platform doc labels it for "Ads API v3.3 and older"; the Marketing API rate-limiting doc lists it as current with fields `acc_id_util_pct`, `reset_time_duration`, `ads_api_access_tier`. | VERIFIED [S15][S16] |
| `x-business-use-case-usage` | keyed by business or object ID, each an array of `{type, call_count, total_cputime, total_time, estimated_time_to_regain_access (minutes), ads_api_access_tier}`. Example type `ads_insights`, tier `development_access`. The Marketing API doc spells the name `X-Business-Use-Case`; the platform doc spells `X-Business-Use-Case-Usage`. Read case-insensitively, check both. | VERIFIED [S15][S16] |
| `x-fb-ads-insights-throttle` | `app_id_util_pct`, `acc_id_util_pct`, `ads_api_access_tier`. Meta says check it on every Insights response. | VERIFIED [S6][S16] |

Tier names:
- Values seen in header examples: `development_access`, `standard_access`. VERIFIED [S15]
- The Marketing API doc says labels were renamed: Standard Access is now Limited Access, Advanced Access is now Full Access. The rate-limit table uses "Development (Limited)" and "Full access". Whether the header string changed from `standard_access` to a new value: UNKNOWN. Builders must treat the tier string as opaque.

Error codes:

| Code | Subcode | Meaning | Status |
|---|---|---|---|
| 4 | none | app-level "Application request limit reached" | VERIFIED [S16] |
| 4 | 1504022, 1504039 | Ads Insights app-level throttle. 1504022 also "Too many API requests" global throttle. | VERIFIED [S16][S6] |
| 17 | 2446079 | ad account API-level, "User request limit reached" | VERIFIED [S16] |
| 17 | 1885172 | spend limit changes, 10 per day (write; irrelevant to read-only) | VERIFIED [S16] |
| 613 | 1487742 | ad account API-level | VERIFIED [S16] |
| 613 | 5044001, 4841018, 1487632, 1487225 | write-side limits (mutation QPS, concurrent edits, budget changes, ad creation) | VERIFIED [S16] |
| 613 | 1996 | inconsistent request volume for the app | VERIFIED [S15] |
| 613 | null | abuse prevention "Calls to this api have exceeded the rate limit" | VERIFIED [S16] |
| 80000 | none | Ads Insights BUC limit | VERIFIED [S15] |
| 80001 | | Page calls with page/system user token | VERIFIED [S15] |
| 80002 | | Instagram BUC | VERIFIED [S15] |
| 80003 | | Custom Audience BUC | VERIFIED [S15] |
| 80004 | | Ads Management BUC | VERIFIED [S15] |
| 80005 | | LeadGen BUC | VERIFIED [S15] |
| 80006 | | Messenger BUC | VERIFIED [S15] |
| 80008 | | WhatsApp Business Management | VERIFIED [S15] |
| 80009 | | Catalog Management | VERIFIED [S15] |
| 80014 | | Catalog Batch | VERIFIED [S15] |
| 80007, 80010-80013 | | not listed in S15 | UNKNOWN (searched S15, S16) |
| 32 | | Pages API limit (user token on page calls) | VERIFIED [S15] |
| 341 | | "Application limit reached" per error-handling guide; transient | VERIFIED [S17] |

- 613 is shared across limit types. Use the subcode to classify. VERIFIED [S16]

Quotas:
- Ad account API-level score: read = 1 point, write = 3 points. Development (Limited): max score 60, decay 300 s, block on max 300 s. Full access: max 9000, decay 300 s, block 60 s. VERIFIED [S16]
- BUC `ads_insights` per ad account per hour: `190000 + 400 x active ads - 0.001 x user errors` for Full access; `600 + 400 x active ads - 0.001 x user errors` for Development. VERIFIED [S16]
- App-level platform limit: `200 x number of users` calls per rolling hour. VERIFIED [S15]. Number of users for a dev-mode app: UNKNOWN.
- Upgrade to Full access: 500+ Marketing API calls in past 15 days and error rate under 15% over last 500 calls. VERIFIED [S16]
- Practical consequence: on development tier one `level=ad` insights call is cheap in points but the 60-point cap with 300 s decay means bursts of more than about 60 reads inside a window block the account for 300 s. INFERRED (arithmetic from S16; whether each insights page costs 1 point is not stated, UNKNOWN).
- Backoff rule: Meta says add backoff as utilization nears 100%, space queries, avoid parallel queries. VERIFIED [S6]
- Retryable per error guide: codes 1, 2, 4, 17, 341, 368. Do not retry 10, 102, 190, 200-299 without fixing token or permission. VERIFIED [S17]. Treat 613 and 80000-80014 as retryable after backoff: INFERRED.
- HTTP status for rate-limit errors (400 vs 429): UNKNOWN in fetched docs. Builders should key off `error.code`, not HTTP status.

## 8. Ad account fields (GET /act_{id})

- `GET /v26.0/act_{id}?fields=timezone_name,currency,account_status,timezone_id,timezone_offset_hours_utc`. VERIFIED [S5]
- `timezone_name`: string (IANA-style name, e.g. "America/Los_Angeles"; format example INFERRED). `timezone_id`: unsigned int. `timezone_offset_hours_utc`: float. `currency`: string from account settings. VERIFIED [S5] (types), INFERRED (example format)
- `account_status` integer codes: 1 ACTIVE, 2 DISABLED, 3 UNSETTLED, 7 PENDING_RISK_REVIEW, 8 PENDING_SETTLEMENT, 9 IN_GRACE_PERIOD, 100 PENDING_CLOSURE, 101 CLOSED, 201 ANY_ACTIVE, 202 ANY_CLOSED. VERIFIED [S5]
- `account_currency` on insights rows equals the account currency. INFERRED (name match)
- Listing accounts the token can see (`/me/adaccounts`): not fetched. UNKNOWN in this pack.

## 9. Sandbox ad accounts

- Created from the app dashboard: add the Marketing API product, then create and link a sandbox ad account on its Tools page. No funding source required. One sandbox ad account per app regardless of tier. VERIFIED [S18] (blog dated 2023-06-21; current status of the dashboard path not rechecked)
- Cannot be used in Ads Manager, only via API. Meta does not deliver ads, so no spend or impressions accumulate. VERIFIED [S18]
- Insights: "Insights API is currently not supported because changes in the sandbox environment do not go live." Expect empty or error. VERIFIED [S18]. Whether it returns `{"data":[]}` or an error: UNKNOWN, needs the probe.
- Sandbox object creation (campaigns etc.) works through Graph API with a user token; the connector is read-only so this is only needed to create test fixtures by hand. VERIFIED [S18] (subset of Marketing APIs)
- Does the sandbox use a different host or `act_` ID format: UNKNOWN (blog gives no base URL).
- Limits on development tier beyond the one-account rule: UNKNOWN. Older 2014 post says development access is limited to the developer's own ad accounts, max 5, heavily rate limited. INFERRED [S19, old, may be stale].
- Conclusion for design: sandbox accounts cannot validate real insights parsing. Use recorded or fixture payloads for tests; real validation needs a real ad account with spend. INFERRED (from the two bullets above).

## 10. Access tokens

- Short-lived user token: from the app dashboard / Graph API Explorer "Get Token". Lifetime: UNKNOWN in fetched docs. INFERRED about one to two hours (common knowledge, not sourced).
- Long-lived exchange: `GET https://graph.facebook.com/{version}/oauth/access_token?grant_type=fb_exchange_token&client_id={app-id}&client_secret={app-secret}&fb_exchange_token={token}`. Response `{"access_token":"...","token_type":"bearer","expires_in":5183944}`. Lifetime about 60 days. Run server-side because of the app secret. An expired token cannot be exchanged. The returned token is a different string; replace the stored one. VERIFIED [S20]
- Long-lived tokens are not refreshed automatically; re-exchange before expiry while still valid. INFERRED from "expired token cannot be exchanged" [S20].
- System user token: `POST /{version}/{SYSTEM-USER-ID}/access_tokens` with `business_app`, `scope` (comma list, e.g. `ads_read`), optional `set_token_expires_in_60_days=true`, `appsecret_proof`, and `access_token` of an admin. Omit the flag for a non-expiring token; expiring (60-day) is Meta's recommended option and the docs say "all integrations should adopt expiring tokens". The system user must first install the app: `POST /{SYSTEM-USER-ID}/applications`. The old `/ads_access_token` endpoint no longer works. `ads_read` is a listed scope. VERIFIED [S21]
- Business Settings UI path: Users, System Users, select user, Generate new token, pick app and permissions; token is shown once. VERIFIED [S22]
- Non-expiring tokens can still be invalidated by revocation or asset changes. INFERRED [S23 vendor]
- Debug: `GET https://graph.facebook.com/v26.0/debug_token?input_token={token}&access_token={app-token-or-developer-user-token}`. Requires an app access token (`{app-id}|{app-secret}`) or an app developer's user token. Response `{"data":{...}}` with `app_id`, `application`, `type` (e.g. `USER`), `is_valid` (bool), `expires_at` (unix; 0 for non-expiring per common behavior, INFERRED), `data_access_expires_at`, `issued_at` (long-lived only), `scopes` (string list), `granular_scopes` (`[{scope, target_ids?}]`), `user_id`, `profile_id`, `metadata`, and `error {code,message,subcode}` for bad tokens. VERIFIED [S24][S25]. The `{app-id}|{app-secret}` string form of app token: INFERRED (standard, not in fetched text).
- Meta does not notify on token invalidation; track expiry or handle errors. VERIFIED [S25]
- Expired token error: code 190. Error 102 means session; 10 and 200-299 mean permission. VERIFIED [S17]
- Passing the token: `access_token` query param or `Authorization: Bearer`. Bearer header: INFERRED (supported by Graph API; not in fetched docs).
- `appsecret_proof` requirement for read calls depends on app setting "Require App Secret". UNKNOWN for this app.

## 11. Error response shape

```json
{"error":{"message":"...","type":"OAuthException","code":190,"error_subcode":463,"error_user_title":"...","error_user_msg":"...","fbtrace_id":"..."}}
```

- Fields: `message`, `type` (e.g. `OAuthException`), `code`, `error_subcode`, `error_user_title`, `error_user_msg` (localized), `fbtrace_id` (short-lived support ID). VERIFIED [S17]
- `is_transient`: not in the error-handling doc. UNKNOWN. INFERRED present on some errors in practice.
- Insights reference error codes: 100 invalid parameter, 105 too many parameters, 190 invalid token, 200 permissions, 613 rate limit, 2500 query parse error, 2635 deprecated API version, 2642 invalid cursor, 3001 invalid query, 3018 start date beyond 37 months. VERIFIED [S4]
- Data-per-call: code 100, subcode 1487534. VERIFIED [S6]
- HTTP status on errors is usually 400 (also 401/403/500). UNKNOWN in fetched docs; key off `error.code`.

## Sources (all fetched 2026-11-03)

- S1 https://developers.facebook.com/docs/graph-api/changelog/versions
- S2 https://developers.facebook.com/docs/graph-api/guides/versioning
- S3 https://developers.facebook.com/docs/marketing-api/insights
- S4 https://developers.facebook.com/docs/graph-api/reference/adaccount/insights/
- S5 https://developers.facebook.com/docs/marketing-api/reference/ad-account/
- S6 https://developers.facebook.com/docs/marketing-api/insights/best-practices
- S7 https://developers.facebook.com/documentation/ads-commerce/marketing-api/insights/breakdowns
- S8 WebSearch result summaries (third-party), 2026-11-03
- S10 https://developers.facebook.com/blog/post/2025/10/16/ads-insights-api-metric-availability-updates/
- S11 https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/v23.0
- S12 third-party search results (pipeboard meta-ads-mcp source, affectgroup, funnel.io), not Meta docs
- S13 https://docs.vortexiq.ai/nerve-centre/kpi-cards/facebook-ads/total-revenue (vendor, via search)
- S14 https://developers.facebook.com/docs/graph-api/results
- S15 https://developers.facebook.com/docs/graph-api/overview/rate-limiting/
- S16 https://developers.facebook.com/documentation/ads-commerce/marketing-api/overview/rate-limiting.md
- S17 https://developers.facebook.com/docs/graph-api/guides/error-handling/
- S18 https://developers.facebook.com/blog/post/2023/06/21/marketing-api-sandbox-capability-now-re-enabled
- S19 https://developers.facebook.com/blog/post/2014/10/22/introducing-ads-api-access-levels/ (search snippet only)
- S20 https://developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived
- S21 https://developers.facebook.com/docs/business-management-apis/system-users/install-apps-and-generate-tokens
- S22 https://developers.facebook.com/documentation/ads-commerce/marketing-api/collaborative-ads/managed-partner-ads/api-guide/prerequisites/generate-access-token-system-user.md
- S23 vendor guides via search (woocommerce.com, selligent), not Meta docs
- S24 https://developers.facebook.com/docs/graph-api/reference/debug_token/
- S25 https://developers.facebook.com/docs/facebook-login/guides/%20access-tokens/debugging


## Not yet covered

- Official full list of `action_type` strings and their definitions.
- `GET /me/adaccounts` and `/{business}/owned_ad_accounts` listing shapes.
- `limit` maximum for insights; exact default for `action_attribution_windows=default`.
- Whether the `parameters` reference page for v26.0 differs from the v23-era reference I fetched.
- App Review / `ads_read` Standard vs Advanced access path in the new dashboard.
- Breakdown-specific retention beyond the 2026-01-12 notice; any later changelog entries (the out-of-cycle changes page was not fetched).

## Open questions

1. What does `default` in `action_attribution_windows` resolve to for this client's accounts, and does the row's `attribution_setting` field state it per row?
2. Can conversion values be non-integer strings in practice for modeled conversions? Decide Decimal vs int after the probe.
3. Does `time_increment=1` return a row for zero-activity days, or are they omitted? (Affects gap filling.)
4. Does sandbox insights return `{"data":[]}` or an error, and which code?
5. Exact HTTP status and header casing for rate limit errors on development tier.
6. Which purchase and lead `action_type` strings appear for the owner's actual pixel and lead forms?
7. Does the owner's app require `appsecret_proof`?
8. Does the tier header string still say `development_access`/`standard_access` after the rename to Limited/Full?

## Recorded probe still needed

When the owner supplies a token, one recorded session should capture, with the token redacted: `debug_token`; `GET act_{id}?fields=timezone_name,currency,account_status`; one daily `level=ad` insights call with explicit `fields` and `action_attribution_windows`; a deliberately bad-version and bad-token error body; one sandbox insights call; and the response headers (`x-app-usage`, `x-ad-account-usage`, `x-business-use-case-usage`, `x-fb-ads-insights-throttle`). The owner runs it; this pack does not.
