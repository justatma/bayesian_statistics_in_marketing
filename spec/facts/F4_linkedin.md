# F4: LinkedIn Marketing API (Advertising API, Development Tier), read-only reporting

Compiled 2026-11-03. Tags: VERIFIED (read in official Microsoft Learn LinkedIn doc on the fetch date), INFERRED (reasoning or non-official), UNKNOWN (searched, not found). Sources listed at the end, all fetched 2026-11-03.

## 1. Base URL, headers, versions

- Base: `https://api.linkedin.com/rest/` (versioned API; first released June 2022). VERIFIED [S1]
- Required headers on every call: `Authorization: Bearer {token}`, `Linkedin-Version: YYYYMM`, `X-Restli-Protocol-Version: 2.0.0`. The versioning page writes `Linkedin-Version`; the error-handling page writes `X-LinkedIn-Version`. Send `Linkedin-Version` as the versioning page does. VERIFIED [S1][S4]
- No default version: "the latest version is not applied by default". VERIFIED [S1]
- Missing header: HTTP 400, body `{"status":400,"code":"VERSION_MISSING","message":"A version must be present. Please specify a version by adding the Linkedin-Version header."}`. VERIFIED [S3]
- Deprecated or non-active version: HTTP 426, body `{"status":426,"code":"NONEXISTENT_VERSION","message":"Requested version yyyymmdd is not active"}`. VERIFIED [S3][S13]
- Latest version as of 2026-11-03 per docs (page dated 2026-10-15): `202610` (October 2026). VERIFIED [S1]. Whether `202611` has been published since: UNKNOWN (fetched pages predate it). Monthly cadence suggests mid-November. INFERRED
- Cadence and policy: new version monthly, each supported for a minimum of one year before sunset. VERIFIED [S1]
- Sunset table [S5]:
  - 202510 and earlier: status Deprecated (202510 sunset 2026-10-15). VERIFIED
  - 202511: sunset 2026-11-16, status Active. VERIFIED
  - 202601 2027-01-15; 202602 2027-02-15; 202603 2027-03-16; 202604 2027-04-15; 202605 2027-05-15; 202606 2027-06-15; 202607 2027-07-15; 202608 2027-08-17; 202609 2027-09-15; 202610 2027-10-15. All Active. VERIFIED
- Choice for the connector: pin `202610` as a config value, not hard-coded, and expect to bump at least yearly. INFERRED
- LinkedIn may ship a patch to any version for security, privacy or bug fixes. VERIFIED [S1]
- Rest.li 2.0 syntax is required for most calls; leaving out `X-Restli-Protocol-Version: 2.0.0` on adAccounts gives "Syntax exception in path variables". VERIFIED [S6]

## 2. adAnalytics finder

Endpoint `GET https://api.linkedin.com/rest/adAnalytics`. Permission `r_ads_reporting`. VERIFIED [S7]

Three finders: `q=analytics` (one pivot), `q=statistics` (up to three pivots), `q=attributedRevenueMetrics` (CRM revenue; out of scope). VERIFIED [S7]

### q=analytics

```
GET /rest/adAnalytics?q=analytics&pivot=CREATIVE&timeGranularity=DAILY
    &dateRange=(start:(year:2026,month:10,day:1),end:(year:2026,month:10,day:31))
    &accounts=List(urn%3Ali%3AsponsoredAccount%3A123456789)
    &fields=impressions,clicks,landingPageClicks,costInLocalCurrency,costInUsd,externalWebsiteConversions,dateRange,pivotValues
```

- `q` is `analytics`. VERIFIED [S8]
- `pivot`: single value. Enum includes `ACCOUNT`, `CAMPAIGN`, `CREATIVE`, `CAMPAIGN_GROUP`, `COMPANY`, `SHARE`, `CONVERSION`, `SERVING_LOCATION`, `CARD_INDEX`, `PLACEMENT_NAME`, `IMPRESSION_DEVICE_TYPE`, `EVENT_STAGE`, conversation-node pivots, and many `MEMBER_*` demographic pivots (not wanted here). `MEMBER_DESIGNATED_MARKET_AREA` needs 202609 or later. Main samples use plain `pivot=CREATIVE`; some samples use the paren form `pivot=(MEMBER_COUNTRY_V2)`. VERIFIED [S7][S8]
- `timeGranularity`: `ALL`, `DAILY`, `MONTHLY`, `YEARLY`. Required. VERIFIED [S8]
- `dateRange`: Rest.li 2.0 object encoding, `dateRange=(start:(year:2024,month:5,day:28),end:(year:2024,month:9,day:30))`. Start required, end optional (open range, end defaults to today). Both inclusive. Dates are UTC. Samples use unpadded integers (one sample shows `month:03`); use unpadded. In samples the parentheses, colons and commas stay literal; only URN colons are percent-encoded. VERIFIED [S7][S8]
- Facets (at least one required, per "Yes unless another facet is provided"): `accounts`, `campaigns`, `campaignGroups`, `shares`, `companies`. `campaignType` needs at least one other facet. VERIFIED [S8]
- URN list encoding: `accounts=List(urn%3Ali%3AsponsoredAccount%3A123)`; several items comma-separated inside `List(...)`. The statistics sample leaves colons unencoded (`campaigns=List(urn:li:sponsoredCampaign:1234567)`), so both forms appear in the docs. URN forms: `urn:li:sponsoredAccount:{id}`, `urn:li:sponsoredCampaign:{id}`, `urn:li:sponsoredCreative:{id}`. VERIFIED [S7]
- A `creatives=List(urn:li:sponsoredCreative:...)` facet is not in the query-parameter table I read. Pivoting by CREATIVE while filtering by `campaigns` or `accounts` is shown in the docs. A creatives facet: UNKNOWN in the docs read; INFERRED to exist.
- `fields`: comma-separated metric names, maximum 20 per request. If `fields` is left out, only `impressions` and `clicks` come back (prose), though the parameter table marks `fields` as required. Always send it. VERIFIED [S7][S8]
- `sortBy.field` and `sortBy.order` are optional (`COST_IN_LOCAL_CURRENCY`, `IMPRESSIONS`, `CLICKS`, `ONE_CLICK_LEADS`, `OPENS`, `SENDS`, `EXTERNAL_WEBSITE_CONVERSIONS`; `ASCENDING`, `DESCENDING`). VERIFIED [S8]

### q=statistics

`GET /rest/adAnalytics?q=statistics&pivots=List(CAMPAIGN,CREATIVE)&timeGranularity=DAILY&dateRange=...&campaigns=List(...)&fields=...`. Up to three pivots in `pivots=List(...)`. Same facets, dateRange and fields rules. VERIFIED [S7][S8]. `pivotValues` carries one URN per pivot in the order of the pivot list. VERIFIED [S9] (description: one URN per pivot). For this connector one pivot (`CREATIVE`, ad level) is enough. INFERRED

### Metric field names (all present in the schema table, VERIFIED [S9])

| Field | Type | Notes |
|---|---|---|
| `impressions` | long | "impressions" for Sponsored Content, "sends" for Sponsored Messaging |
| `clicks` | long | chargeable clicks |
| `landingPageClicks` | long | clicks to the creative landing page |
| `costInLocalCurrency` | BigDecimal | account currency; a JSON string in the sample (`"19.91833"`) |
| `costInUsd` | BigDecimal | USD |
| `externalWebsiteConversions` | long, default 0 | post-click or post-view; "group level attribution or estimation can be used" |
| `externalWebsitePostClickConversions` | long, default 0 | |
| `externalWebsitePostViewConversions` | long, default 0 | |
| `conversionValueInLocalCurrency` | BigDecimal | non-demographic pivots only; advertiser-set value per conversion, summed over the range |
| `oneClickLeads` | long | One Click Lead Gen leads |
| `approximateMemberReach` | long | non-demographic pivots only; only when the range is 92 days or fewer |
| `dateRange` | DateRange | UTC, start and end inclusive |
| `pivotValues` | string[] | URNs, e.g. `["urn:li:sponsoredCreative:123"]` |

- Not every metric works with every pivot. `IMPRESSION_DEVICE_TYPE` excludes reach and conversion metrics. VERIFIED [S7][S8]
- In samples counts are JSON numbers, cost is a JSON string. Parse cost with Decimal, counts as int. VERIFIED (sample shapes) [S7]
- Conversions can be group-level estimates, so treat them as approximate integers. VERIFIED [S9]
- A field left out of `fields` is absent from the element in the samples. INFERRED
- Attribution windows behind `externalWebsiteConversions`: not defined on the pages read. UNKNOWN. They are set per conversion rule in Campaign Manager. INFERRED

### Response shape

```json
{"elements":[{"clicks":177,"impressions":54494,
  "dateRange":{"start":{"year":2024,"month":1,"day":1},"end":{"year":2025,"month":5,"day":24}},
  "pivotValues":["urn:li:sponsoredCreative:1234567"]}],
 "paging":{"count":10,"links":[],"start":0}}
```

VERIFIED [S7]. With `timeGranularity=DAILY` the sample elements have start and end on the same day (one element per day per pivot value). VERIFIED [S7]

### Restrictions

- adAnalytics does not support pagination. Response is limited to 15,000 elements. Split by date range or account if more could return. The `paging` object still appears in samples; do not rely on it. VERIFIED [S7]
- Empty `elements` when there is no activity or when the caller lacks read access. No error. VERIFIED [S7]
- Throttle: 45 million metric values per 5-minute window (metric values = fields requested times rows returned). Over that gives 429 `TOO_MANY_REQUESTS`. VERIFIED [S7]
- Long URLs can give 414; docs point to query tunneling. VERIFIED [S7]
- Retention: performance data (account, campaign, creative) retained 10 years; professional-demographic data 2 years. VERIFIED [S7]
- The same page says that with `timeGranularity=ALL`, a start or end outside "the 6-month daily retention period" is rounded to month boundaries and the whole month returned. That sits oddly beside 10-year retention. The task brief's "2-year lookback" matches the demographic figure only. The real lookback for `DAILY` at the CREATIVE pivot: UNKNOWN, needs the probe. Error `DATE_TOO_EARLY` (400) exists for out-of-range dates. VERIFIED (error exists) [S7]
- Minimum date range or minimum granularity: none stated. UNKNOWN
- Delays: performance metrics near real-time; demographic metrics 12 to 24 hours; `videoWatchTime` and `averageVideoWatchTime` up to 48 hours. VERIFIED [S7]
- Accuracy: the page says professional-demographic metrics are approximate for member privacy, and lists minor inconsistencies when comparing similar time ranges, summed daily rows against the full period, and campaign sums against account totals. Advice: use a full-period query and the highest level you need for exact totals. VERIFIED [S7]
- Timezone: API dates are UTC. Whether that matches the account's Campaign Manager day: UNKNOWN. A boundary mismatch is plausible. INFERRED

## 3. Ad accounts

- Permission `r_ads` (read) or `rw_ads`. Caller needs an ad account role; `VIEWER` is read-only. VERIFIED [S6]
- List: `GET /rest/adAccounts?q=search`. With no search criteria, all accounts the caller can access. Filter syntax `search=(type:(values:List(BUSINESS)),status:(values:List(ACTIVE,CANCELED)))`; `test` is a scalar, `search=(test:false)`; `sortOrder=DESCENDING`. VERIFIED [S6]
- Paging: cursor-based since 202401; `pageSize` (max 1,000) and `pageToken`; next token in `metadata.nextPageToken`. VERIFIED [S6]
- Response: `{"elements":[{...}],"metadata":{"nextPageToken":"..."}}`. VERIFIED [S6]
- Element fields: `id` (long), `name`, `currency` (3-letter code, default USD), `status` (`ACTIVE`, `CANCELED`, `DRAFT`, `PENDING_DELETION`, `REMOVED`), `type` (`BUSINESS`, `ENTERPRISE`), `test` (boolean, default false, immutable), `reference` (org or person URN), `servingStatuses`, `changeAuditStamps`, `version`. VERIFIED [S6]
- BRL accounts are billed in USD but show budgets and spend in BRL, so `costInLocalCurrency` would be BRL. VERIFIED [S6]
- Fetch one: `GET /rest/adAccounts/{id}`. VERIFIED [S6]
- Per account caps: 5,000 campaigns, 15,000 creatives. VERIFIED [S6]
- Campaign and creative listing under an account (`/adAccounts/{id}/adCampaigns?q=search`, `/adCreatives?q=search`) exists for name resolution; field shapes not fetched. VERIFIED (endpoints shown) [S6]; shapes UNKNOWN. URN resolution has its own page, referenced by [S7]; not fetched.

### Test ad accounts

- Create: `POST /rest/adAccounts` with body including `"test": true`, `"type":"BUSINESS"`, `currency`, `name`, `reference` (org URN) and the notify flags. The new ID comes back in the `x-restli-id` response header. VERIFIED [S6]. Creating needs write permission (`rw_ads`), which a read-only connector will not hold. INFERRED
- Development tier allows creating 1 test ad account through the API; real accounts must be made in Campaign Manager. VERIFIED [S10]
- One test account per developer application; second attempt gives `TEST_ACCOUNT_LIMIT_REACHED` (400). VERIFIED [S6][S3]
- Test accounts are BUSINESS type only; an existing account cannot be converted; cannot be created in Campaign Manager. VERIFIED [S6]
- Test accounts: ads never served, creatives auto-rejected, no billing. "No reporting data is available from /adAnalytics for test campaigns." Expect `{"elements":[]}` per the empty-response rule. VERIFIED [S6][S7]. Exact body for a test account: UNKNOWN, needs the probe.
- Account search returns test accounts unless `test:false` is passed. VERIFIED [S6]

## 4. OAuth 2.0 three-legged flow

- The developer app needs the Advertising API product (apply on the app's Products tab); available scopes show on the Auth tab. VERIFIED [S10][S11]
- Authorize: `GET https://www.linkedin.com/oauth/v2/authorization` with `response_type=code`, `client_id`, `redirect_uri`, `state` (optional, recommended), `scope` (URL-encoded, space-delimited, e.g. `r_ads%20r_ads_reporting`). VERIFIED [S11]
- Auth code lifespan: 30 minutes. Callback gets `code` and `state`. Failure callback gets `error` (`user_cancelled_login`, `user_cancelled_authorize`), `error_description`, `state`. VERIFIED [S11]
- Token: `POST https://www.linkedin.com/oauth/v2/accessToken`, `Content-Type: application/x-www-form-urlencoded`, body `grant_type=authorization_code`, `code`, `client_id`, `client_secret`, `redirect_uri`. VERIFIED [S11]
- Response: `access_token`, `expires_in` (seconds; "all access tokens are issued with a 60-day lifespan", example 5184000), `refresh_token` and `refresh_token_expires_in` (only if the app has programmatic refresh), `scope`. VERIFIED [S11]
- Token length is about 500 characters; plan for 1000 or more. VERIFIED [S11]
- Redirect URI rules: HTTPS; absolute; query parameters ignored; no `#`; must match a URL registered on the app's Auth tab, else 401 "Redirect_uri doesn't match". Postman callback is `https://oauth.pstmn.io/v1/callback`. Whether `http://localhost` is allowed: UNKNOWN (page says "via HTTPS").
- Requesting a different scope than before invalidates all previously issued tokens for that app and member; users must re-authorize when scopes change. VERIFIED [S11]
- Manual token: Developer Portal token generator, `https://www.linkedin.com/developers/tools/oauth/token-generator`. VERIFIED [S11]
- Without refresh tokens, "refresh" means running the authorization flow again; the consent screen is skipped if the member is still logged in to linkedin.com and the current token has not expired. VERIFIED [S11]
- Programmatic refresh tokens: "available for all approved Marketing Developer Platform (MDP) partners" [S12], but "a limited set of partners" on the OAuth page [S11]. Whether a Development-tier-only app gets them: UNKNOWN. Check for `refresh_token` in the first token response.
- If enabled: access token 60 days, refresh token 365 days with a fixed TTL (using it does not extend it). Refresh: `POST https://www.linkedin.com/oauth/v2/accessToken` with `grant_type=refresh_token`, `refresh_token`, `client_id`, `client_secret`. Response has a new `access_token`, `expires_in`, the same `refresh_token` and a smaller `refresh_token_expires_in`. After 365 days the member must reauthorize. LinkedIn may revoke tokens at any time. VERIFIED [S12]
- The refresh doc's sample JSON shows `expires_in: 86400` and `refresh_token_expires_in: 525600`, contradicting its prose (60 days and 365 days). Trust the prose and read `expires_in` from the response. VERIFIED (contradiction exists) [S12]
- Token errors: refresh with a bad token gives 400 `invalid_request` "The provided authorization grant or refresh token is invalid, expired or revoked". Bad code gives 401 or 400 `invalid_request` or `invalid_redirect_uri`. VERIFIED [S11][S12]
- API calls with a revoked token: 401 "The token has been revoked". Expired: 401. VERIFIED [S13]

## 5. Development tier limits and rate limits

- Two tiers: Development and Standard. VERIFIED [S10]
- Development: Read has no limit on ad accounts you administer. Create: 1 test ad account via API. Edit: updates for up to 5 ad accounts. "POST for up to 5 Ad Accounts and GET for an unlimited number of accounts." VERIFIED [S10]
- "All API calls at all access levels are made on production data." VERIFIED [S10]
- Apply on the app's Product tab for the Advertising API. Standard needs a build-and-test period and LinkedIn review. VERIFIED [S10]
- Rate limits count per 24 hours and reset at midnight UTC. Two kinds: application (all calls) and member (per member per app). VERIFIED [S14]
- Numeric limits are not published. Look them up in Developer Portal, app, Analytics tab; an endpoint appears only after at least one call that UTC day. VERIFIED [S14]. Numeric daily limit for adAnalytics on this tier: UNKNOWN.
- 429 message: "Resource level throttle limit for calls to this resource is reached." Also used rarely for infrastructure protection, which clears itself. VERIFIED [S13]
- Retry-After header or usage headers: none documented. UNKNOWN. Builder rule: on 429 back off with jitter; if it persists, assume the daily quota is spent until 00:00 UTC. INFERRED
- Developer admins get email alerts at 75% of application quota, with a 1 to 2 hour delay. VERIFIED [S14]
- Separate adAnalytics throttle of 45 million metric values per 5 minutes (section 2). VERIFIED [S7]
- Retry only 500, 503 `UNDER_MAINTENANCE`, 504 and 429 (with backoff). Do not retry 400, 401, 403. The status codes are VERIFIED [S13][S7]; the retry policy is INFERRED.
- Read access is unlimited in account count at this tier, so the read-only connector is not bound by the 5-account edit cap. INFERRED from [S10]

## 6. Error JSON shape

Basic shape, all endpoints:

```json
{"message":"Empty oauth2_access_token","serviceErrorCode":401,"status":401}
```

- Fields `message`, `serviceErrorCode`, `status`. VERIFIED [S13]
- Newer shape, on adAccounts, adCampaigns and adCampaignGroups only: adds `code` (string, e.g. `FIELD_VALUE_TOO_LOW`), `errorDetailType` (`com.linkedin.common.error.BadRequest`), `errorDetails` (`inputErrors[]`, `conditionalInputErrors[]`). If `code` is present it is the new shape. VERIFIED [S3]
- Batch errors: `{"results":{...},"errors":{"<key>":{...}}}`. VERIFIED [S3]
- adAnalytics error table: 400 `MISSING_FIELD`, 400 `INVALID_VALUE_FOR_FIELD`, 400 `START_DATE_AFTER_END_DATE`, 400 `DATE_TOO_EARLY`, 401 `EMPTY_ACCESS_TOKEN`, 403 `USER_NOT_AUTHORIZED`, 404 `NOT_FOUND`, 414 `REQUEST_URI_TOO_LONG`, 429 `TOO_MANY_REQUESTS`, 500 `INTERNAL_ERROR`, 503 `UNDER_MAINTENANCE`. VERIFIED [S7]. Whether those labels arrive in a `code` field for adAnalytics (not on the new-shape endpoint list): UNKNOWN. Key off HTTP status first, then `message`.
- Version errors carry `code`: 400 `VERSION_MISSING`, 426 `NONEXISTENT_VERSION`. VERIFIED [S3]
- 404 can mean a restricted API for Ads (see 403). VERIFIED [S13]
- A downstream token verification failure returns 500. VERIFIED [S13]
- Headers to log for support: `x-li-uuid`, `x-li-fabric`, `x-li-request-id`. VERIFIED [S13]

## Sources (all fetched 2026-11-03)

- S1 https://learn.microsoft.com/en-us/linkedin/marketing/versioning
- S3 https://learn.microsoft.com/en-us/linkedin/marketing/error-responses
- S4 https://learn.microsoft.com/en-us/linkedin/marketing/versioning (curl example header spelling)
- S5 https://learn.microsoft.com/en-us/linkedin/marketing/integrations/migrations
- S6 https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads/account-structure/create-and-manage-accounts
- S7 https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads-reporting/ads-reporting
- S8 https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads-reporting/ads-reporting-schema (query parameter tables)
- S9 same page as S8 (metrics table)
- S10 https://learn.microsoft.com/en-us/linkedin/marketing/integrations/marketing-tiers
- S11 https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow
- S12 https://learn.microsoft.com/en-us/linkedin/shared/authentication/programmatic-refresh-tokens
- S13 https://learn.microsoft.com/en-us/linkedin/shared/api-guide/concepts/error-handling
- S14 https://learn.microsoft.com/en-us/linkedin/shared/api-guide/concepts/rate-limits
- (S2 unused.)

## Not yet covered

- Campaign, campaign group and creative listing endpoints (fields, paging) and URN resolution response shapes.
- Query tunneling syntax for long adAnalytics URLs.
- `adAccountUsers?q=authenticatedUser` as an alternative account list.
- Conversion rule configuration and attribution window definitions (Conversions API pages).
- Per-metric availability matrix by pivot beyond the notes above.

## Open questions

1. Does the Development-tier app receive `refresh_token` and `refresh_token_expires_in` in the token response, or must the owner re-authorize every 60 days?
2. What is the real maximum lookback for `timeGranularity=DAILY`, `pivot=CREATIVE`: 6 months, 2 years or 10 years? Which error comes back when exceeded?
3. Is `202611` live yet, and does `202610` behave differently from `202609` for adAnalytics?
4. Is a `creatives=List(...)` facet accepted on `q=analytics`?
5. What attribution window do `externalWebsiteConversions` use for the owner's conversion rules?
6. Does a response day match the Campaign Manager account-timezone day, or is it strictly UTC?
7. What are the numeric daily limits for adAnalytics on this app (Developer Portal Analytics tab)?
8. Is `http://localhost:PORT` accepted as a redirect URI for a local OAuth helper?
9. What does adAnalytics return for a test account: empty `elements` or an error?

## Recorded probe still needed

When the owner supplies a token, one recorded session should capture, with token redacted: the token endpoint response keys (refresh token present or not); `GET /rest/adAccounts?q=search` with the Rest.li header; one `q=analytics&pivot=CREATIVE&timeGranularity=DAILY` call with an explicit `fields` list of 20 or fewer over a short range; one call with a start date older than six months and one older than two years; one call against a test account; and the response headers on every call. The owner runs it; this pack does not.
