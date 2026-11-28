# F5 Facts pack: GA4 Data API and the GA4 BigQuery public sample

Researched 2026-11-03 (fetch date for every source below unless stated). Tools: WebFetch/WebSearch only. No API called, no credentials used.
Tags: VERIFIED = stated on an official Google page I fetched. INFERRED = reasoning or third-party. UNKNOWN = not found, with what was searched.

## 1. runReport

- [VERIFIED] `POST https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport`. The path takes `properties/1234`; ID is not in the body. Source: https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/properties/runReport
- [VERIFIED] Body fields: `dateRanges[]`, `dimensions[]`, `metrics[]`, `dimensionFilter`, `metricFilter`, `offset` (string, default 0), `limit` (string, default 10,000, max 250,000 per request), `metricAggregations[]`, `orderBys[]`, `currencyCode` (ISO 4217; default property currency), `cohortSpec`, `keepEmptyRows` (default false: all-zero-metric rows are dropped), `returnPropertyQuota` (bool), `comparisons[]`. Same source.
- [VERIFIED] Response: `dimensionHeaders[]`, `metricHeaders[]`, `rows[]`, `totals[]`/`maximums[]`/`minimums[]` (only if requested), `rowCount` (total rows, independent of limit/offset), `metadata`, `propertyQuota`, `kind` = "analyticsData#runReport". Source: https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/RunReportResponse
- [INFERRED] Pagination: loop offset += limit until offset >= rowCount. `limit`/`offset` are strings in JSON; send as strings or numbers per proto3 JSON (both accepted by convention). Cap at 250,000.
- [INFERRED] Row shape: `rows[i].dimensionValues[j].value` and `rows[i].metricValues[j].value`, all values strings, order matches headers. Not on pages fetched; this is the documented DimensionValue/MetricValue shape from general knowledge. Probe must record.
- [INFERRED] Example body: `{"dateRanges":[{"startDate":"2026-10-01","endDate":"2026-10-31"}],"dimensions":[{"name":"date"},{"name":"sessionSource"},{"name":"sessionMedium"},{"name":"sessionCampaignName"}],"metrics":[{"name":"sessions"},{"name":"keyEvents"},{"name":"purchaseRevenue"}],"limit":"10000","offset":"0","keepEmptyRows":false,"returnPropertyQuota":true}`
- [VERIFIED] `GET https://analyticsdata.googleapis.com/v1beta/properties/{id}/metadata` lists dimensions and metrics for a property including custom ones; id 0 gives universal metadata only; needs scope analytics.readonly or analytics. Source: https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/properties/getMetadata . Use it to validate names at runtime.
- [VERIFIED] Changelog: 2026-09-14 added `dataTruncationReasons` to ResponseMetaData (truncated reports list type, message, affected dates; seen in v1 changelog entry, version channel not stated beyond that). Source: https://developers.google.com/analytics/devguides/reporting/data/v1/changelog
- [UNKNOWN] Whether `dataTruncationReasons` appears on v1beta runReport or only v1 alpha. Changelog entry did not specify. Parser should ignore unknown fields.

## 2. Dimension and metric names

Source: https://developers.google.com/analytics/devguides/reporting/data/v1/api-schema

| API name | Kind | Status and note |
|---|---|---|
| date | dimension | [VERIFIED] YYYYMMDD |
| sessionSource | dimension | [VERIFIED] |
| sessionMedium | dimension | [VERIFIED] |
| sessionCampaignName | dimension | [VERIFIED] includes Google Ads, manual, other campaigns |
| sessionGoogleAdsCampaignId | dimension | [VERIFIED] exists; Google Ads campaign ID for the session |
| firstUserCampaignName | dimension | [VERIFIED] campaign that first acquired the user |
| transactionId | dimension | [VERIFIED] |
| ecommercePurchases | metric | [VERIFIED] counts `purchase` events only |
| purchaseRevenue | metric | [VERIFIED] purchase + in-app purchase + app store subscription revenue minus refunds |
| totalRevenue | metric | [VERIFIED] purchase + subscription + ad revenue minus refunds |
| sessions | metric | [VERIFIED] |
| keyEvents | metric | [VERIFIED] |
| conversions | metric | [VERIFIED DEPRECATED] changelog 2024-05-06 maps `conversions` to `keyEvents`; `isConversionEvent` dimension to `isKeyEvent`. Use keyEvents. |

- [VERIFIED] The 2024-05-06 changelog entry text: "Modify any report requests that use a Deprecated Metric ... to use the Key Event Metric instead." Source: changelog page above.
- [VERIFIED] `campaignId` and `campaignName` dimensions are present only for key events; session- and first-user-scoped campaign dimensions are not subject to that note. api-schema page.
- [VERIFIED] Marking an event as a key event affects reports from that point forward only. api-schema page.
- [VERIFIED] Custom dimensions and metrics fail if not registered in the property. api-schema page.
- [UNKNOWN] Whether `conversions` still returns data or errors in v1beta today (marked deprecated; removal date not found). Do not use it.
- [UNKNOWN] Dimension/metric compatibility for the specific combination of transactionId with sessionCampaignName, sessionGoogleAdsCampaignId and purchaseRevenue. Not on the schema page. Check with the Data API `checkCompatibility` method or the probe. [INFERRED] Scope mixing (event-scoped transactionId with session-scoped dimensions) is usually allowed but can produce attribution oddities.
- [INFERRED] Join key to Google Ads: sessionGoogleAdsCampaignId equals Ads campaign.id. Only populated for sessions linked to Google Ads (property must be linked to the Ads account and auto-tagging on). Not verified by doc; UNKNOWN officially.
- [INFERRED] GA4 revenue is in the property currency (`currencyCode` in the request can override); Google Ads cost is in the Ads account currency. Do not add them without checking.

## 3. Quotas

Source: https://developers.google.com/analytics/devguides/reporting/data/v1/quotas

| Core quota | Standard | Analytics 360 |
|---|---|---|
| Tokens per property per day | 200,000 | 2,000,000 |
| Tokens per property per hour | 40,000 | 400,000 |
| Tokens per project per property per hour | 14,000 | 140,000 |
| Concurrent requests per property | 10 | 50 |
| Server errors per project per property per hour | 10 | 50 |

- [VERIFIED] All the above rows. Each request draws from the buckets at once; cost varies with rows, dimensions, metrics, filters, date range, cardinality.
- [VERIFIED] Exhausted bucket gives `429 RESOURCE_EXHAUSTED`. Daily quotas reset at midnight Pacific Time; hourly refresh within the hour. Only HTTP 500 and 503 count against the server-error quota. Retry 429/500/503 with truncated exponential backoff and a retry cap.
- [VERIFIED] Set `returnPropertyQuota: true`; response `propertyQuota` has six QuotaStatus fields (`consumed`, `remaining`): `tokensPerDay`, `tokensPerHour`, `concurrentRequests`, `serverErrorsPerProjectPerHour`, `potentiallyThresholdedRequestsPerHour`, `tokensPerProjectPerHour`. Source: https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/PropertyQuota
- [INFERRED] Connector: log `propertyQuota.tokensPerDay.remaining` on every call and stop before the daily bucket empties; keep concurrency to 1.
- [UNKNOWN] Token cost of a typical report. Probe measures it via consumed.

## 4. Auth

- [VERIFIED] User credentials work. Quickstart uses `gcloud auth application-default login --scopes="https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/analytics.readonly"`; client libraries read ADC / `GOOGLE_APPLICATION_CREDENTIALS`. Must enable "Google Analytics Data API v1" in the Cloud project. Source: https://developers.google.com/analytics/devguides/reporting/data/v1/quickstart-client-libraries
- [VERIFIED] Scope: `https://www.googleapis.com/auth/analytics.readonly`. Same source and getMetadata page.
- [VERIFIED] Service account: enable `analyticsdata.googleapis.com` (and `analyticsadmin.googleapis.com` for Admin calls); in the GA UI give the service account email at least Viewer (`roles/analytics.viewer`) on the target property. Source: https://developers.google.com/analytics/devguides/MCP
- [VERIFIED] Keyless via impersonation, same page: `gcloud auth application-default login --impersonate-service-account=SERVICE_ACCOUNT_EMAIL --scopes="https://www.googleapis.com/auth/analytics.readonly,https://www.googleapis.com/auth/cloud-platform"`. Insufficient-scope error text: "Request had insufficient authentication scopes" (fix: re-run with scopes).
- [VERIFIED] Impersonation needs the Service Account Token Creator role (`roles/iam.serviceAccountTokenCreator`) on the target service account for your user, and the Service Account Credentials API enabled. Python among listed languages with automatic discovery; "not supported by all authentication libraries". Source: https://docs.cloud.google.com/docs/authentication/use-service-account-impersonation
- [VERIFIED] Org policy: `iam.disableServiceAccountKeyCreation` is enforced by default for organizations created on or after May 3, 2024; not retroactive. Admin with `orgpolicy.policyAdmin` can override (Console: Organization policies > constraint > Manage policy > Override parent's policy > Add a rule > Enforcement off > Set policy; or `gcloud resource-manager org-policies disable-enforce iam.disableServiceAccountKeyCreation --organization ORG_ID`). Source: https://docs.cloud.google.com/resource-manager/docs/organization-policy/restricting-service-accounts
- [VERIFIED] Keyless options named by Google: impersonation (short-lived credentials), Service Account Credentials API, attached service accounts on GCP compute, Workload Identity Federation (for external identities such as AWS/GitHub). Source: https://docs.cloud.google.com/iam/docs/service-account-creds
- [INFERRED] For a local Python script on a laptop: (a) user ADC with analytics.readonly (simplest; user must have GA access; refresh-token caveats from F3 section 8 apply if a custom OAuth client in Testing is used, but gcloud's own client avoids that) or (b) ADC impersonation of a service account (no key; the service account is added as Viewer on the property). Workload Identity Federation is not suited to a laptop with no external IdP. (b) is documented for GA4 by Google (MCP page); (a) is documented by the quickstart.
- [UNKNOWN] Whether the gcloud default client is accepted for the analytics.readonly scope without `--client-id-file`. Quickstart does not mention it; the Google Ads guide uses `--client-id-file`. Probe will show it.
- [UNKNOWN] Whether an ADC user token via gcloud needs a quota project for analyticsdata (X-Goog-User-Project). Not on pages fetched. Searched quickstart and MCP page. [INFERRED] if a 403 mentions a quota project, run `gcloud auth application-default set-quota-project PROJECT_ID`.

## 5. Finding the property ID

- [VERIFIED] Sign in to Google Analytics, Admin, choose the property, open Property Settings, read the numeric "PROPERTY ID". Source: https://developers.google.com/analytics/devguides/reporting/data/v1/property-id (also Firebase: Project settings > Integrations > Google Analytics integration).
- [VERIFIED] Do not confuse with the Measurement ID ("G-..."), which belongs to a web data stream (Admin > Data streams). Source: https://support.google.com/analytics/answer/12270356
- [INFERRED] The URL path uses the numeric ID prefixed with `properties/`.

## 6. BigQuery public sample

Source for all in this section unless stated: https://developers.google.com/analytics/bigquery/web-ecommerce-demo-dataset

- [VERIFIED] Table pattern: `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`, Google Merchandise Store, GA4 standard ecommerce plus enhanced measurement. Date range 2020-11-01 to 2021-01-31 (three months). Daily shards `events_YYYYMMDD`; filter with `_TABLE_SUFFIX BETWEEN '20201201' AND '20201231'` (suffix usage confirmed in https://developers.google.com/analytics/bigquery/basic-queries).
- [VERIFIED] Obfuscation: "obfuscated data that emulates what a real world dataset would look like." Placeholders documented: `<Other>`, `NULL`, `''`. Internal consistency "might be somewhat limited". Not comparable with the GA demo account.
- [UNKNOWN] "(data deleted)" placeholder: not mentioned on the dataset page. Searched dataset page, basic-queries, web search. Handle it defensively as just another string.
- [VERIFIED] Export schema fields (source: https://support.google.com/analytics/answer/7029846): `event_date` STRING YYYYMMDD in the registered time zone; `event_timestamp` INTEGER microseconds UTC; `event_name` STRING; `user_pseudo_id` STRING; `traffic_source.name|medium|source` STRING (first-user acquisition, do not change later, not populated in intraday tables); `collected_traffic_source` RECORD with `manual_campaign_id`, `manual_source`, `manual_medium`, `gclid` (and others); `ecommerce.transaction_id` STRING; `ecommerce.purchase_revenue_in_usd` FLOAT (populated for purchase events only); `ecommerce.purchase_revenue` FLOAT local currency; `session_traffic_source_last_click` RECORD (session-level, last-click).
- [VERIFIED] Purchase queries in the docs filter `event_name = 'purchase'` and read the `value` event parameter; one query uses `event_name IN ('in_app_purchase','purchase')`. Source: basic-queries page. No doc query shown for `ecommerce.transaction_id`, `purchase_revenue_in_usd`, or `traffic_source`.
- [INFERRED] Sample query: `SELECT event_date, user_pseudo_id, ecommerce.transaction_id, ecommerce.purchase_revenue_in_usd, traffic_source.source, traffic_source.medium, traffic_source.name FROM \`bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*\` WHERE event_name='purchase' AND _TABLE_SUFFIX BETWEEN '20201201' AND '20201231'`. Syntax follows the verified schema; not run.
- [INFERRED] `traffic_source.*` is first-user acquisition, not session source. Session-level attribution needs `session_traffic_source_last_click` or `collected_traffic_source` (the latter exists in the export schema but whether the 2020-21 sample populates it is UNKNOWN; table schema not inspected).
- [UNKNOWN] Whether `ecommerce.transaction_id` is obfuscated or blank in the sample (some values may be `(not set)` or null). Dataset page does not say.
- [UNKNOWN] Whether the sample contains Google Ads campaign ids or gclid. Not stated; the sample's `collected_traffic_source` may be null. Probe.
- [UNKNOWN] Dataset license / terms of use, and whether it may be used to test a commercial tool. Searched: the dataset page ("contains no terms of use or license information"), the public-data program page (https://docs.cloud.google.com/bigquery/public-data, which says each dataset's Cloud Marketplace listing has details and gives no blanket license), web search (no result). The Marketplace listing could not be fetched (header overflow error). Treat as unresolved; the owner should read the Marketplace listing. [INFERRED] Using it only to test schema handling and a query is the evident purpose ("emulates what a real world dataset would look like") but that is not a license.
- [VERIFIED] Program facts: Google pays for storage; you pay for queries; first 1 TB/month free; no SLA; many datasets hosted by third parties. Source: https://docs.cloud.google.com/bigquery/public-data
- [VERIFIED] BigQuery sandbox: no credit card or billing account; 1 TiB processed query data per month; 10 GiB lifetime storage cap; tables expire after 60 days; no streaming inserts, no DML, no Data Transfer Service; public datasets queryable via `bigquery-public-data`. Source: https://docs.cloud.google.com/bigquery/docs/sandbox
- [INFERRED] Reading only needs a Cloud project with BigQuery API (sandbox project is enough); `jobUser` permission on the project to run queries. Not stated explicitly on a page fetched.
- [INFERRED] Dataset location is probably US multi-region (bigquery-public-data samples are US; the program page says `samples` tables are US). For the GA4 dataset specifically UNKNOWN. The BigQuery client must run the query job in a matching location or leave location unset.
- [VERIFIED] The legacy UA sample (`google_analytics_sample.ga_sessions`) is a different dataset (Aug 2016 to Aug 2017, GA360 UA). Do not confuse. Source: https://support.google.com/analytics/answer/7586738

## Not yet covered

- Table-level schema inspection of the sample (INFORMATION_SCHEMA) and a row count.
- Official page on `checkCompatibility`.
- The Marketplace listing and terms for the GA4 sample.
- Whether the GA4 Data API requires linking to Google Ads for sessionGoogleAdsCampaignId (official doc not found).
- Admin API or property link checks.

## Open questions

1. Does the owner's Google Workspace/org allow service account key creation (org created after 2024-05-03 means blocked by default)? If blocked, choose user ADC or impersonation.
2. Does the owner have a GA4 property with Ads linked and auto-tagging on, and Viewer or higher on it?
3. Which currency: property currency versus Ads account currency.
4. Is the sample dataset's license acceptable for the intended testing? Owner must read the Marketplace listing.
5. Which GA4 campaign dimension is the join key to Ads: sessionGoogleAdsCampaignId (ID) or sessionCampaignName (name, which can differ from the Ads name)?

## Recorded probe still needed (owner supplies credentials later)

1. `GET /v1beta/properties/{id}/metadata`: record the full list and confirm each name in section 2 exists; confirm `conversions` presence/absence.
2. `runReport` for one day: date, sessionSource, sessionMedium, sessionCampaignName, sessionGoogleAdsCampaignId, metrics sessions, keyEvents, purchaseRevenue, with `returnPropertyQuota: true`; record raw body, headers, quota tokens consumed.
3. `runReport` with transactionId plus sessionGoogleAdsCampaignId plus purchaseRevenue: check compatibility and null handling.
4. Paging test: limit 2, offset 0 then 2; confirm rowCount behavior and string types.
5. Auth test for whichever route is chosen (user ADC; impersonation), including the quota-project 403 case and gcloud default client acceptance.
6. BigQuery: `SELECT COUNT(*), MIN(event_date), MAX(event_date) FROM ...events_*`, then INFORMATION_SCHEMA.COLUMNS for field presence, then the purchase query; record counts of '<Other>', NULL, '(not set)', '(data deleted)' in traffic_source and transaction_id; record job location and bytes processed (stay under sandbox limits).
