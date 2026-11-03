# F3 Facts pack: Google Ads API (read-only reporting)

Researched 2026-11-03 (fetch date for every source below unless stated). Tools: WebFetch/WebSearch only. No API called, no credentials used.
Tags: VERIFIED = stated on an official Google page I fetched. INFERRED = third-party or reasoning. UNKNOWN = not found, with what was searched.

## 0. Headline correction for builders

The task brief assumed a developer token from a manager account's API Center. That model ended.

- [VERIFIED] Developer tokens were sunset on September 9, 2026. Access levels now belong to the Google Cloud project that owns the OAuth client or service account. Sending a developer-token header is optional and ignored by servers; Google will reject it in a future major version. Source: https://developers.google.com/google-ads/api/docs/api-policy/developer-token (2026-11-03)
- [VERIFIED] New users need neither a developer token nor a manager account. Enabling the API in a Cloud project grants Test access; Explorer access is applied for on the Google Ads API Overview page in Cloud Console. A manager account is needed only to link and manage multiple accounts. Same source.
- [VERIFIED] The API Center page is deprecated, kept only to view historical developer details. "Where the developer token is shown": nowhere for new projects. Same source.
- [VERIFIED] Moving a token to a new project is no longer supported. Same source.
- [INFERRED] Design consequence: the connector must NOT require a developer token. Make it an optional config value; send the header only if set. Third-party coverage agrees on the Sept 2026 change (ppc.land, relevantaudience.com, seen only as search snippets; dates there say Sept 10).

## 1. Version and endpoints

- [VERIFIED] Latest major is v26 (released 2026-10-14, sunset Nov 2027). Latest minor v26.1 (2026-10-28). v25 sunset Aug 2027; v24 May 2027 (v24.2 June 2027); v23 Feb 2027. v26.2 is projected for Nov 2026 (tentative). Sunset dates are approximate months, not days. Source: https://developers.google.com/google-ads/api/docs/sunset-dates
- [VERIFIED] REST search: `POST https://googleads.googleapis.com/v26/customers/CUSTOMER_ID/googleAds:search` with JSON body containing `query`. Source: https://developers.google.com/google-ads/api/rest/common/search
- [VERIFIED] `googleAds:searchStream` uses the same URL shape with the method swapped. No pageToken. Output is one streamed JSON array (not a single object). Same source.
- [INFERRED] Each array element is a batch object with `results`, `fieldMask`, `requestId` (from my knowledge of the API; the page I fetched did not show the example, the searchStream example URL returned 404). Builders must handle a JSON array of batches and concatenate `results`.
- [INFERRED] Pin the version in one constant (`GOOGLE_ADS_API_VERSION = "v26"`); the major version changes about quarterly and old ones sunset about 15 months after release.
- [VERIFIED] The example error body names `google.ads.googleads.v26.errors.GoogleAdsFailure`, consistent with v26 being live. Source: https://developers.google.com/google-ads/api/docs/best-practices/understand-api-errors

## 2. Headers

| Header | Status |
|---|---|
| `Authorization: Bearer ACCESS_TOKEN` | [VERIFIED] always required |
| `login-customer-id: MANAGER_ID` (no hyphens) | [VERIFIED] needed only when a manager account calls a client account; not needed if the OAuth user has direct access to the target client account |
| `developer-token` | [VERIFIED] optional and ignored since 2026-09-09 |
| `Content-Type: application/json` | [INFERRED] standard for POST bodies |

Source for first two: https://developers.google.com/google-ads/api/rest/auth . Customer IDs go in the URL as 10 digits with no hyphens [VERIFIED for login-customer-id; INFERRED for the URL id].

- [VERIFIED] Token refresh: `POST https://www.googleapis.com/oauth2/v3/token` with form fields grant_type=refresh_token, client_id, client_secret, refresh_token. The "v3" is unrelated to the Ads API version. Same rest/auth page.
- [VERIFIED] Access tokens last one hour (single-user guide, search snippet of https://developers.google.com/google-ads/api/docs/oauth/single-user-authentication).

## 3. Python library vs httpx

- [VERIFIED] PyPI `google-ads` current version 35.0.0, released 2026-10-29; Python >=3.10,<3.15. Source: https://pypi.org/project/google-ads/
- [UNKNOWN] Which API version 35.0.0 targets. PyPI page does not say. Not found in release notes (page truncated, second half not read).
- [VERIFIED] Updated client libraries do not need a developer token. Developer-token page above.
- [VERIFIED] Official libraries are gRPC-based (except Perl). Source: https://developers.google.com/google-ads/api/rest/overview
- [INFERRED] Recommendation per spec: raw httpx against REST. Reasons: no grpc dependency, version pinned by URL. Cost: you hand-parse JSON (camelCase keys, int64 as strings, enums as strings).
- [INFERRED] REST JSON convention: field names are lowerCamelCase in responses (`adGroupAd.ad.id`, `metrics.costMicros`); int64 values (`clicks`, `impressions`, `costMicros`, ids) arrive as strings; `conversions` as JSON number. Not shown on pages I fetched; confirmed by general proto3-JSON rules. Probe must confirm.

## 4. GAQL fields

Query shape: `SELECT ... FROM resource WHERE segments.date BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'`. Source for date format: https://developers.google.com/google-ads/api/reference/rpc/v26/Segments

| Field | Status |
|---|---|
| segments.date (string, yyyy-MM-dd) | [VERIFIED] rpc Segments v26 |
| segments.conversion_action (string, resource name, e.g. customers/1/conversionActions/2) | [VERIFIED] |
| segments.conversion_action_name (string) | [VERIFIED] |
| segments.conversion_lag_bucket (enum, days between impression and conversion) | [VERIFIED] |
| segments.conversion_or_adjustment_lag_bucket (enum, includes adjustments) | [VERIFIED] |
| segments.days_to_conversion | [VERIFIED ABSENT] no such field in v26 Segments reference. Do not use. |
| metrics.conversions (double), metrics.conversions_value (double), metrics.all_conversions (double) | [VERIFIED] rpc Metrics v26 |
| metrics.cost_micros (int64), impressions (int64), clicks (int64) | [VERIFIED] |
| ad_group_ad.ad.id, ad_group_ad.ad.name | [VERIFIED] listed on https://developers.google.com/google-ads/api/fields/v26/ad_group_ad (types not seen) |
| customer.id, customer.descriptive_name, customer.currency_code, customer.time_zone, campaign.id, campaign.name, ad_group.id, ad_group.name | [UNKNOWN] by fetch (page 2.2 MB, only first 100k chars read; these fields did not appear). Standard fields, widely used, so expected to exist; probe must confirm. |

- [VERIFIED] segments.conversion_action, conversion_action_name, conversion_lag_bucket, date are listed as selectable with ad_group_ad; metrics.conversions listed too, subject to a FROM-clause filter I could not see. Fields page above.
- [VERIFIED] `metrics.conversions` counts only conversion actions with `include_in_conversions_metric = true`; `all_conversions` counts every action regardless. Both double. Metrics page https://developers.google.com/google-ads/api/reference/rpc/v26/Metrics
- [INFERRED] `metrics.conversions` is fractional under data-driven attribution and cross-device or view-through weighting (my knowledge; the doc says only "double"). Store as Decimal/float, never int.
- [VERIFIED] cost_micros is int64 micros. [INFERRED] 1,000,000 micros = 1 currency unit of customer.currency_code, so cost = cost_micros / 1_000_000. The Metrics page gives type only; the unit definition is general API knowledge.
- [VERIFIED] Segmenting by conversion_action changes granularity to one row per conversion action per campaign, and rows with zero conversions are excluded. Source: https://developers.google.com/google-ads/api/docs/conversions/reporting
- [VERIFIED] Compatibility is governed per-field by the `selectable_with` list; an incompatible mix fails with QueryError (PROHIBITED_SEGMENT_WITH_METRIC_IN_SELECT_OR_WHERE_CLAUSE = 53, and in v23+ PROHIBITED_FIELD_OR_SEGMENT_WITH_METRIC = 65). Sources: https://developers.google.com/google-ads/api/docs/reporting/segmentation and the v23 query_error diff page.
- [UNKNOWN] Exact list of which of segments.conversion_action / conversion_action_name / conversion_lag_bucket are compatible with metrics.conversions on ad_group_ad. Searched fields page (truncated), segmentation page, rpc pages, web search. Not stated.
- [INFERRED] Working rule (Fivetran troubleshooting, https://fivetran.com/docs/connectors/applications/google-ads/troubleshooting/conversion-action-segments-unavailable, plus experience): conversion-action segments combine with conversion metrics (conversions, conversions_value, all_conversions) but NOT with impressions, clicks, cost_micros. Therefore use TWO queries: (A) cost/clicks/impressions plus conversions totals by segments.date with no conversion_action segment; (B) conversions/conversions_value by segments.date and segments.conversion_action(+_name). Probe must confirm for lag bucket.
- [INFERRED] Metrics in a query with a `segments.date` filter are daily; rows with all-zero metrics may be omitted.
- [INFERRED] Dates and the account time zone: segments.date is in the account time zone (customer.time_zone). Standard, but not on a page I fetched.

## 5. Conversion window

- [VERIFIED] ConversionAction has `click_through_lookback_window_days` (int64) and `view_through_lookback_window_days` (int64), also `id`, `name`, `status`, `include_in_conversions_metric` (bool), `attribution_model_settings`. No ranges or defaults documented. Source: https://developers.google.com/google-ads/api/reference/rpc/v26/ConversionAction
- [INFERRED] Query: `SELECT conversion_action.id, conversion_action.name, conversion_action.status, conversion_action.include_in_conversions_metric, conversion_action.click_through_lookback_window_days, conversion_action.view_through_lookback_window_days, conversion_action.attribution_model_settings.attribution_model FROM conversion_action`. Resource name `conversion_action` in GAQL is standard; not tested here. Probe needed.
- [INFERRED] Window is a per-action setting, current value only; history of changes is not in this resource.

## 6. Access levels

All from https://developers.google.com/google-ads/api/docs/access-levels unless stated.

- [VERIFIED] Levels belong to a Google Cloud project. Test: test accounts only, 15,000 ops/day, granted automatically on enabling the API. Explorer: test and production accounts; production capped at 2,880 ops/day, test accounts 15,000. Basic: production and test, 15,000/day each, needs brand verification and Explorer first. Standard: unlimited ops/day, manual audit (page says 10 business days review).
- [VERIFIED] Daily limit is a sliding 24-hour window; exceeding it returns an error. All levels also have system rate limits.
- [VERIFIED] Explorer apply path: Cloud Console, Google Ads API Overview page for the project; confirm current level is Test; expand "Upgrade access level"; Next access level shows Explorer; click "Apply for access". Google may upgrade automatically on submit.
- [VERIFIED] Explorer restricts: CustomerService.CreateCustomerClient; CustomerUserAccessInvitationService, CustomerUserAccessService; KeywordPlan* services, AudienceInsightsService, ReachPlanService; PaymentsAccountService, BillingSetupService, AccountBudgetProposalService, InvoiceService. Reads via search/searchStream are not on the restricted list.
- [VERIFIED] Calling a production account with a Test-access project returns AuthorizationError.CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION on v25+ (v24 and earlier: ACTION_NOT_PERMITTED). Developer-token page.
- [VERIFIED] Known issues: some Explorer applications rejected for eligibility; brand-verified projects on Free Trial or with suspended billing may be rejected; projects upgraded after 2026-09-09 may get AUTHORIZATION_ERROR on production calls, workaround is to apply with a new Cloud project. Roles needed to manage access: Owner, Editor, Quota Administrator, Service Usage Admin. Developer-token page.
- [VERIFIED] Explorer eligibility is described only as completing initial API sign-up; Google may or may not let you apply.
- [VERIFIED] The owner's situation (email "project 930569165807 approved and activated for Explorer Access", no manager account visible) is consistent with the new model: no manager account and no developer token are needed. [INFERRED] That email is not itself a source; I have not seen it.
- [UNKNOWN] Whether search/searchStream calls (reads) count as "operations" toward the 2,880/day cap, and how many operations one search costs. Searched access-levels and rate-limits pages. Not stated. Treat each request as potentially 1 operation until the probe measures it, and keep call volume low.
- [UNKNOWN] Whether Explorer production access requires the OAuth user to already have access to a Google Ads account (obviously yes in practice for data to be returned). The access-levels page does not say.
- [INFERRED] The owner still needs a real Google Ads account (or access to one) that the OAuth user can read. An Explorer project plus no Ads account returns nothing.

## 7. Test accounts

Source: https://developers.google.com/google-ads/api/docs/first-call/test-accounts

- [VERIFIED] Create a test manager account (button on that page, sign in with a Google account not linked to your production manager). In it: Accounts > Create new account makes a test client account, automatically a test account. Create test campaigns. Record both 10-digit IDs; client ID is the `customer_id`, manager ID is `login-customer-id` if authenticating through the manager.
- [VERIFIED] Test accounts do not serve ads; serving metrics (impressions, conversions, cost) are empty. Bid simulations, conversion uploads, billing untestable. Up to 50 test accounts per hierarchy. Throttling possible. Deleted after a year with no activity.
- [VERIFIED] Test accounts work with a Test-access project; no production access needed.
- [INFERRED] So test accounts validate auth, headers, GAQL syntax, response shape, and campaign/ad_group/ad structure, but never metric values. Metric parsing must be tested with recorded fixtures or a production account on Explorer.

## 8. OAuth

- [VERIFIED] Scope: `https://www.googleapis.com/auth/adwords`. Source: https://developers.google.com/google-ads/api/docs/oauth/single-user-authentication
- [VERIFIED] Single-user flow: client ID type "Desktop app" works best with gcloud; "Web application" also works but needs OAuth 2.0 Playground. Configure consent screen with the adwords scope; create OAuth client; download JSON as credentials.json; the signing-in user must have access to all target Ads accounts and a passkey set up (new passkey may carry a 7-day trust delay). Command:
  `gcloud auth application-default login --scopes=https://www.googleapis.com/auth/adwords,https://www.googleapis.com/auth/cloud-platform --client-id-file=PATH_TO_CREDENTIALS_JSON`
  Result `application_default_credentials.json` holds `client_id`, `client_secret`, `refresh_token`. If the app is unverified click Advanced then "Go to PROJECT_NAME (unsafe)".
- [VERIFIED] Refresh tokens for external apps with publishing status "Testing" expire in 7 days (exception: only name/email/profile scopes). Other revocation causes: user revoked, unused six months, too many live tokens (100 per account per client ID), admin policy `admin_policy_enforced`. Source: https://developers.google.com/identity/protocols/oauth2#expiration
- [VERIFIED] The Google Ads single-user page itself says nothing about the Testing 7-day expiry.
- [UNKNOWN] Documentation statement that "Internal" user type avoids the 7-day expiry. The OAuth page describes the 7-day rule only for external Testing apps and gives no Internal rule. Reasoning only: [INFERRED] Internal apps (Workspace org only) are not subject to Testing expiry, which is Google's published behavior elsewhere; I did not fetch it. Alternative that is documented: publish the external app to "In production" (unverified is allowed with the warning screen, per the Advanced / unsafe click-through above) [INFERRED that this removes the 7-day limit; the doc only says the limit applies to Testing].
- [VERIFIED] A service account route exists for Google Ads: create the service account and JSON key, then an Ads admin adds its email as a user in Google Ads: Admin > Access and security > Users tab "+"; "Email only" level not supported. Source: https://developers.google.com/google-ads/api/docs/oauth/service-accounts . Docs say to use it for accounts you already have access to, and to fall back to single-user OAuth if org policy blocks service accounts. [INFERRED] The key-creation org policy in F5 section 3 applies here too.
- [VERIFIED] Google Ads OAuth credentials must live in the same Cloud project where the API is enabled and that has the access level. Source: https://developers.google.com/google-ads/api/docs/oauth/overview

## 9. Pagination, errors, quota

- [VERIFIED] `search` returns fixed pages of 10,000 rows; response keys `results`, `nextPageToken`, `fieldMask`; resend identical query with `pageToken`. Source rest/common/search.
- [UNKNOWN] `pageSize` request parameter in v26 REST (the page does not mention it). Do not send it.
- [UNKNOWN] `totalResultsCount`, `summaryRowSetting`, `returnTotalResultsCount`: not on the page. Not used.
- [VERIFIED] Quota error shape per docs (HTTP 429, gRPC code 8): `{"code":8,"message":"...","details":[{"@type":"type.googleapis.com/google.ads.googleads.v26.errors.GoogleAdsFailure","errors":[{"errorCode":{"quotaError":"RESOURCE_EXHAUSTED"},"message":"...","location":{...optional}}],"requestId":"..."}]}`. `requestId` also in the `request-id` response header. Source: understand-api-errors page.
- [INFERRED] On the wire Google REST errors are normally wrapped as `{"error":{"code":..,"message":..,"status":..,"details":[...]}}`. The doc example omitted the `error` wrapper. Parser must accept both: look for `details[]` with `@type` ending `GoogleAdsFailure` under either the root or `error`.
- [VERIFIED] Each GoogleAdsFailure error has an `errorCode` object keyed by category (e.g. `quotaError`, `authenticationError`, `requestError`), `message`, optional `location`. Same source and search snippets.
- [VERIFIED] Rate-limit error name in the best-practices page is RESOURCE_TEMPORARILY_EXHAUSTED. QPS limits are separate per customer ID and per Cloud project; also requests/minute and operations/minute; token bucket. Retry with exponential backoff and jitter (about 2, 4, 8 seconds). Source: https://developers.google.com/google-ads/api/docs/best-practices/rate-limits
- [VERIFIED] RESOURCE_EXHAUSTED handling: back off 1s, 2s, 4s with jitter and a retry cap; reduce rate. Understand-api-errors page.
- [INFERRED] Daily-cap breach on Explorer will also surface as a quota-class error; builders should treat it as non-retryable within the same day (backoff will not help) and stop with a clear message.
- [UNKNOWN] Whether Retry-After header is sent. Not on pages fetched.

## Not yet covered

- Release-notes second half (python library to API version mapping, Explorer announcement date).
- Per-field existence for customer.* / campaign.* / ad_group.* (fields pages truncated).
- searchStream REST example page (404 on guessed URL).
- Internal user type official statement.

## Open questions

1. Does the owner have a Google Ads account with real spend that the OAuth user can read? If not, only test accounts (no metrics) are possible.
2. Which Google account will do OAuth: a Workspace user (Internal option) or a personal Gmail (Testing = 7 days, or publish to production)?
3. Do reads consume Explorer operations, and how many per search?
4. Should the connector use user OAuth or a service account (depends on org policy; see F5 section 3)?
5. Is customer-level access direct, or through a manager (login-customer-id needed)?

## Recorded probe still needed (owner supplies credentials later)

1. `GET /v26/customers:listAccessibleCustomers` with only Authorization: confirm auth and that no developer-token is needed; record response.
2. One `googleAds:search` on `customer` (id, descriptive_name, currency_code, time_zone): confirms field names and JSON casing; record raw body and headers (request-id).
3. One `googleAds:searchStream` on ad_group_ad for one day with impressions, clicks, cost_micros, conversions: record array shape, int64-as-string behavior, fractional conversions.
4. Query B with segments.conversion_action and segments.conversion_lag_bucket plus metrics.conversions; record the error if incompatible, and the same with impressions to confirm the split rule.
5. `conversion_action` resource query: record lookback fields.
6. Test account (test manager + client) call to record the empty-metrics shape.
7. Deliberate error: bad customer id and a Test-access call to a production account, record error body (wrapper or not).
8. Count operations before and after on the Cloud Console quota page to learn how reads count.
