# F1 Facts pack: manual platform exports (CSV/XLSX)

Fetched/searched 2026-11-03. Status column meanings: VERIFIED = read in an official page I fetched. INFERRED = third-party page, a search snippet of an official page I could not open in full, or reasoning. UNKNOWN = not found.

Overall warning for builders: the official help centers (Meta, Google Ads, LinkedIn) do not publish the literal CSV header strings. Meta's help pages are JavaScript rendered and returned only titles to my fetcher. Almost every literal header below is therefore INFERRED or UNKNOWN. The reader must match headers case-insensitively, tolerate missing columns, and let the user map columns. Do not hard-code a header as certain.

Global source index (S-codes used below):
- S1 https://support.google.com/google-ads/answer/2404036 (fetched 2026-11-03)
- S2 https://support.google.com/google-ads/answer/2404176 (fetched 2026-11-03)
- S3 https://support.google.com/google-ads/answer/7489070 (fetched 2026-11-03)
- S4 https://support.google.com/google-ads/answer/6270625 (fetched 2026-11-03)
- S5 https://developers.google.com/google-ads/api/fields/v20/metrics (fetched 2026-11-03, first 100k chars only, so only metrics.all_conversions was read)
- S6 https://www.linkedin.com/help/linkedin/answer/107773 (fetched 2026-11-03)
- S7 https://www.linkedin.com/help/lms/answer/a441785/ (fetched 2026-11-03)
- S8 https://www.linkedin.com/help/lms/answer/a426359 (fetched 2026-11-03)
- S9 https://www.linkedin.com/help/lms/answer/a422513 (fetched 2026-11-03)
- S10 https://www.linkedin.com/help/lms/answer/a445476/ (fetched 2026-11-03)
- S11 https://support.google.com/analytics/answer/9317657 (fetched 2026-11-03)
- S12 https://support.google.com/analytics/answer/7579450 (fetched 2026-11-03)
- S13 https://support.google.com/analytics/answer/7029846 (fetched 2026-11-03)
- S14 https://developers.google.cn/analytics/bigquery/web-ecommerce-demo-dataset?hl=es (fetched 2026-11-03)
- S15 https://adwize.ai/facebook-ads-report-template (third party, fetched 2026-11-03)
- S16 https://dashops.io/resources/exporting-data-from-meta-ads-manager (third party, fetched 2026-11-03)
- S17 https://adsuploader.com/blog/export-facebook-ads-data (third party, fetched 2026-11-03)
- S18 https://www.dataslayer.ai/blog/how-to-connect-meta-ads-to-google-sheets (third party, fetched 2026-11-03)
- S19 WebSearch snippets of docs.oursprivacy.com/docs/channels/import-meta-ads and /import-google-ads (third party; the pages themselves returned 404 when fetched, so only the search snippet text was seen, 2026-11-03)
- S20 WebSearch snippet of docs.adapty.io/docs/how-to-get-spends-data-from-fb-business-manager (third party; fetch returned 404, snippet only, 2026-11-03)
- S21 WebSearch snippets of Meta Business Help Center pages (facebook.com/business/help/3265285920226789 and /205067636197240; fetch returned page title only, 2026-11-03)
- S22 WebSearch snippet of support.google.com/ds/answer/1184148 (Search Ads 360 / Display Search help, NOT Google Ads; fetch 404; snippet only, 2026-11-03)
- S23 WebSearch snippet of https://ads-developers.googleblog.com/2014/10/new-to-adwords-api-excluding-headers.html (legacy AdWords API, 2026-11-03)
- S24 https://www.owox.com/blog/articles/duplicate-transactions-in-google-analytics.md (search snippet only, 2026-11-03)

---

## 1. Meta Ads Manager (ad-level report export)

### 1.1 Export mechanics

| # | Fact | Source | Status |
|---|------|--------|--------|
| M1 | Ads Reporting (the Reports tool) exports as XLSX (formatted data), XLSX (raw data), CSV, or PNG. | S21 | INFERRED |
| M2 | Ads Manager table path: Reports, then Export table data, then CSV or Excel. | S19, S20 | INFERRED |
| M3 | Raw XLSX has "stable column names"; formatted XLSX has "human-friendly labels". Prefer raw XLSX or CSV for pipelines. | S17 | INFERRED |
| M4 | Ad-level rows require exporting from the Ads tab. An export taken at Campaign or Ad set level lacks ad columns. | S19 (snippet) | INFERRED |
| M5 | Some UI columns do not export: Tags, Age, Gender, Location, Body, Destination Type, Link, Preview Link, Related Page, Title. Age/Gender can appear as rows if applied as a breakdown. | S17 | INFERRED |
| M6 | Cell values beginning with +, -, =, or @ are wrapped in `< >` in exported files. | S17 | INFERRED |
| M7 | Ad-level rows do not always sum to the campaign row. | S16 | INFERRED |

### 1.2 Column headers (English). Literal export strings are not in any official page I could read.

| Concept | Header string as best known | Notes | Source | Status |
|---|---|---|---|---|
| Date range start | `Reporting starts` | Appears when no daily breakdown is chosen. | S19, S20 | INFERRED |
| Date range end | `Reporting ends` | Same. | S19, S20 | INFERRED |
| Date (daily breakdown) | UNKNOWN (likely `Day`) | Searched for sample daily export headers; none found. | - | UNKNOWN |
| Account id / name | UNKNOWN | Searched; no source. | - | UNKNOWN |
| Campaign name | `Campaign name` | | S19, S20 | INFERRED |
| Campaign id | `Campaign ID` | | S20 | INFERRED |
| Ad set name | `Ad Set Name` (Adapty spelling, capital S) or `Ad set name` | Sources disagree on case. Match case-insensitively. | S20 | INFERRED |
| Ad set id | `Ad set ID` / `Ad Set ID` | Case unconfirmed. | S20 | INFERRED |
| Ad name | `Ad name` | Not confirmed in any fetched source. | - | UNKNOWN |
| Ad id | `Ad ID` | | S20 | INFERRED |
| Impressions | `Impressions` | | S15, S19 | INFERRED |
| Reach | `Reach` (UI column name; estimated from sampled data, not additive across rows) | Export header presumed equal to UI name. | S15 | INFERRED |
| Link clicks | `Link clicks` | Clicks on links in the ad leading to the chosen destination. | S15 | INFERRED |
| All clicks | `Clicks (all)` | Includes link clicks, reactions, comments, shares, media clicks. This is the header the vendor import docs require. | S19 | INFERRED |
| Amount spent | `Amount spent (USD)` | Currency code is in parentheses in the header; for a non-USD account the header differs (e.g. a different 3-letter code). | S19 | INFERRED |
| Results | `Results` (plus `Result indicator` / `Cost per result`) | Meaning depends on campaign objective, so mixed objectives are not comparable. | S15 | INFERRED |
| Purchases (count) | UNKNOWN (UI name likely `Purchases`) | Not confirmed. | - | UNKNOWN |
| Purchase value | `Purchases conversion value` (S15 spelling); other sources write `Purchase conversion value` | Spelling differs between sources. | S15, S16 | INFERRED |
| ROAS | `Purchase ROAS (return on ad spend)` | | S15 | INFERRED |
| Attribution setting column | UNKNOWN as a literal export header. Searched Meta help, Jon Loomer, vendor docs. | See 1.3. | - | UNKNOWN |

### 1.3 Attribution window

| # | Fact | Source | Status |
|---|------|--------|--------|
| M8 | An export "carries the attribution setting that was active when you ran it". Exports under different settings give different conversion numbers. | S16 | INFERRED |
| M9 | Ads Manager default attribution setting is 7-day click and 1-day view. | WebSearch result summary of third-party guide (jonloomer.com page itself returned 403) | INFERRED |
| M10 | Attribution setting value strings, and the exact column that holds them in a CSV (for example "7-day click or 1-day view"): UNKNOWN. | - | UNKNOWN |
| M11 | How a changed attribution setting shows in a CSV: not found. Per M8, the only evidence is that numbers differ and the setting is not part of a row key. Builders must make the user declare the window at import. | S16 (reasoning) | INFERRED |
| M12 | On 2026-01-12 Meta removed `7d_view` and `28d_view` windows from the Ads Insights API. Older CSVs may contain windows that no longer exist. | S18 | INFERRED |

### 1.4 Currency, timezone, count type, totals, formatting

| # | Fact | Source | Status |
|---|------|--------|--------|
| M13 | Currency is in the header of the spend column, as `Amount spent (<CODE>)`. Account-level currency. | S19 | INFERRED |
| M14 | The ad account has its own time zone, which defines the day boundary in the export. How the CSV states the time zone: UNKNOWN. | S16 | INFERRED (zone rule); UNKNOWN (statement) |
| M15 | Whether `Results`, `Purchases`, and value columns contain decimals / modeled values: UNKNOWN. | - | UNKNOWN |
| M16 | Totals/summary row: Adapty instructs "don't add any summary rows" when exporting, implying the export dialog can include one. Default state and position: UNKNOWN. | S20 | INFERRED |
| M17 | Number formatting (thousands separators, percent signs, "--" for empty): UNKNOWN for Meta. | - | UNKNOWN |

---

## 2. Google Ads (UI table download and Report Editor)

### 2.1 Export mechanics

| # | Fact | Source | Status |
|---|------|--------|--------|
| G1 | Download formats from a statistics table: Excel .csv, .csv, .tsv, .pdf, .xlsx, .xml, Google Sheets. | S1 | VERIFIED |
| G2 | "More options" lets you add segments, compress file size, include additional data. Segments applied to the table appear as rows in the report. | S1, S2 | VERIFIED |
| G3 | Report Editor downloads include .csv and .xml. | S3 | VERIFIED |
| G4 | On screen, totals for all rows are listed at the bottom of the statistics table. Whether the downloaded file includes them is not stated on that page. | S1 | VERIFIED (screen); UNKNOWN (file) |
| G5 | Title row and date-range row above the column header, and `Total: ...` rows at the bottom of UI downloads: not found in any current Google Ads help page. Legacy AdWords API reports had a report-name-with-date-range header row and a summary row at the end, removable with skipReportHeader / skipReportSummary. Treat the UI layout as plausible but unconfirmed. Reader should detect the header row by scanning for a known column name and drop rows whose first cell starts with `Total`. | S23 | INFERRED |
| G6 | CSV downloads are UTF-16 encoded (Excel CSV and plain CSV), ID columns are written as `="number"`, and names containing commas are quoted. This text comes from a Search Ads 360 help page, not Google Ads. Applicability is unconfirmed. | S22 | INFERRED |

### 2.2 Column headers

| Concept | Header string | Source | Status |
|---|---|---|---|
| Date / Day | UNKNOWN (likely `Day` when segmented by day) | - | UNKNOWN |
| Account id/name | UNKNOWN (likely `Customer ID`, `Account`) | - | UNKNOWN |
| Campaign id/name | UNKNOWN (likely `Campaign ID`, `Campaign`) | - | UNKNOWN |
| Ad group id/name | UNKNOWN (likely `Ad group ID`, `Ad group`) | - | UNKNOWN |
| Ad id / name | UNKNOWN | - | UNKNOWN |
| Impressions | `Impr.` (trailing period) | S19 snippet | INFERRED |
| Clicks | UNKNOWN as literal; Google Ads has one click metric (clicks on the ad), not a link-vs-all split | - | UNKNOWN |
| Cost | UNKNOWN literal (likely `Cost`) | - | UNKNOWN |
| Currency | UNKNOWN (likely a `Currency code` column) | - | UNKNOWN |
| Conversions | `Conversions` (primary conversion actions only, excludes view-through) | S4 | VERIFIED |
| All conversions | `All conversions` (primary and secondary actions). The page also writes the value column as `All conv. value`. | S4 | VERIFIED |
| Conversion value | `Conv. value` ("new Google Ads experience" name) | S4 | VERIFIED |
| View-through | `View-through conversions`, excluded from `Conversions` | S4 | VERIFIED |
| Attribution setting column | None known; attribution is per conversion action | - | UNKNOWN |

### 2.3 Attribution, count type, currency, timezone

| # | Fact | Source | Status |
|---|------|--------|--------|
| G7 | Data-driven attribution and other attribution models give fractional credit, shown as decimals like 0.33 or 0.50. Conversion columns show two decimals. So `Conversions`, `Conv. value`, `All conversions` can be non-integer. | S4 | VERIFIED |
| G8 | API field metrics.all_conversions is type DOUBLE. | S5 | VERIFIED |
| G9 | The `Conversions` column only counts actions marked as included (account-default conversion goals; unchecking excludes the action). Changing this setting changes the column retroactively for reporting. | S4 | VERIFIED |
| G10 | Conversion window is set per conversion action and is not in the row. The pages I read do not state this, and App Connect view-through uses a 24-hour lookback by default. A row has no window field. | S4 (partial) | INFERRED |
| G11 | Currency and time zone are account-level settings. Their appearance in downloads: UNKNOWN. | - | UNKNOWN |
| G12 | Number formatting ("--" for empty, thousands separators, percent signs): not found. UNKNOWN. | - | UNKNOWN |

---

## 3. LinkedIn Campaign Manager (ad performance export)

| # | Fact | Source | Status |
|---|------|--------|--------|
| L1 | Export path: Advertise, confirm time range (top right), Export (upper right), pick a Report Type, pick a column view (for ad set/ad performance), pick time breakdown, Export. | S7 | VERIFIED |
| L2 | Reports download as CSV. | S6, S7 | VERIFIED |
| L3 | Report types: Ad set performance, Ad performance, Audience network ad set performance, Audience network ad performance, Professional demographics, Conversion performance, Conversion ad performance, Leads, Conversation ad CTA performance, Placements ad set performance, Placements ad performance. | S6 | VERIFIED |
| L4 | Time breakdown options: Daily, Monthly, All. None for Professional demographics or at ad account level. | S7 | VERIFIED |
| L5 | Column view choices: all columns, a default view such as performance, or a custom view. Dashboard-only metrics are excluded: Key results, Cost per result, Bid, MRC net/gross impressions and clicks, Leads (data-driven attribution). | S6 | VERIFIED |
| L6 | Dashboard metric names: `Spent` ("Amount you spent on ads impressions or interactions"), `Clicks` ("Total chargeable clicks based on your ad set's objective"), `Impressions`, `Conversions`, `Leads`. Literal CSV headers are UNKNOWN. | S10 | VERIFIED (dashboard names) |
| L7 | Conversion metrics: `Conversions`, `Click Conversions`, `View Conversions`, `Conversion Rate`, `Cost Per Conversion`, `Total Conversion Value`, `Return on Ad Spend`. Shown via the "Conversions & Leads" column view. | S9, S8 | VERIFIED |
| L8 | `Clicks` is chargeable clicks by objective, not all clicks. A separate all-click or landing-page-click header: UNKNOWN. | S10 | VERIFIED (definition); UNKNOWN (header) |
| L9 | Conversion window options: 1, 7, 30, or 90 days, for click and view separately. Recommended and Campaign Manager default is 90-day click, 90-day view. Event registration conversions changed in April 2025 to 30-day click and 30-day view. 180/365-day windows exist for some Conversions API / CSV conversions. | S8 | VERIFIED |
| L10 | Window changes apply only to conversions counted after the change. Historic counts do not change. | S8 | VERIFIED |
| L11 | The window is set per conversion action. It does not appear to be a row column in the export (not stated either way). | S8 | INFERRED |
| L12 | LinkedIn may use modeled conversions when individual attribution is not possible. Whether the CSV shows decimals: UNKNOWN. | S9 | VERIFIED (modeling); UNKNOWN (decimals) |
| L13 | Literal header strings for date, account, campaign group, campaign, creative / ad id and name, currency, reach: UNKNOWN. Searched LinkedIn help, vendor docs; none list them. | - | UNKNOWN |
| L14 | Time zone, currency, preamble rows, totals row, number formatting: not stated on S6 or S7. | S6, S7 | UNKNOWN |

---

## 4. GA4

### 4.1 UI exports

| # | Fact | Source | Status |
|---|------|--------|--------|
| A1 | Standard reports: Share this report, Download File, then Download PDF / Download CSV / Export to Google Sheets. CSV and Sheets are capped at 100,000 rows. | S11 | VERIFIED |
| A2 | Explorations: Export data icon (upper right) with Google Sheets, TSV, CSV, PDF, PDF (all tabs). Sheets/TSV/CSV export all data available in the selected visualization, possibly more rows than shown. | S12 | VERIFIED |
| A3 | Preamble comment lines at top of GA4 CSV, literal column headers (e.g. `Date`, `Event count`, `Purchase revenue`, `Transactions`), date format in CSV, time zone and currency statement: UNKNOWN. Searched Google help and web for the `#` comment header; not found. | - | UNKNOWN |
| A4 | Metric definitions (from search snippet of Google help): Ecommerce purchases counts the purchase event only. Transactions also counts in_app_purchase, subscription renew/convert, and refund events with value. Purchase revenue = purchases + in-app purchases + subscriptions - refunds. | Search snippet of support.google.com/analytics/answer/12924131 and 13428834 | INFERRED |
| A5 | GA4 has no ad-platform attribution window in an export row; attribution model is a property setting. Not read; UNKNOWN. | - | UNKNOWN |

### 4.2 BigQuery sample `bigquery-public-data.ga4_obfuscated_sample_ecommerce`

| # | Fact | Source | Status |
|---|------|--------|--------|
| A6 | Dataset id `ga4_obfuscated_sample_ecommerce` in project `bigquery-public-data`; data 2020-11-01 to 2021-01-31 (Google Merchandise Store). | S14 | VERIFIED |
| A7 | Some fields hold placeholder values `<Other>`, `NULL`, `''`; internal consistency limited by obfuscation. | S14 | VERIFIED |
| A8 | `event_date` is STRING in `YYYYMMDD`, in the registered time zone of the property. | S13 | VERIFIED |
| A9 | `event_timestamp` is INTEGER, microseconds, UTC. | S13 | VERIFIED |
| A10 | `event_name` STRING; `user_pseudo_id` STRING. | S13 | VERIFIED |
| A11 | `ecommerce.purchase_revenue_in_usd` FLOAT: purchase revenue in USD, standard unit, populated for purchase event only. | S13 | VERIFIED |
| A12 | `ecommerce.transaction_id` STRING: the transaction ID. | S13 | VERIFIED |
| A13 | `ecommerce.purchase_revenue` (local currency, in the event currency) also exists in the schema. Not seen in the page excerpt I got; reported by OWOX. | S24 | INFERRED |
| A14 | Raw events: summing revenue counts every purchase event. In the sample, some purchase events have NULL, `''`, or `(not set)` transaction_id (OWOX reports 906 such events; figure not independently checked). Dedupe on transaction_id before summing, and treat empty IDs as undedupable. | S24 | INFERRED |

---

## Open questions

What a builder still cannot know from this pack:

1. Literal English CSV header strings for Meta daily date, account, ad name, purchases, and attribution setting. Whether the Meta export has a totals row by default. A real sample export per platform is needed (the user can supply one).
2. Whether Meta's `Attribution setting` is a column in the CSV at all, and its exact value strings.
3. Meta: decimals or modeled values in `Results` / `Purchases`.
4. Google Ads: literal headers for date, IDs, names, Clicks, Cost, Currency code; whether UI downloads have a title line, a date-range line, and `Total:` rows; encoding (UTF-16 vs UTF-8) of Google Ads downloads; number format and `--` handling.
5. Google Ads: confirmation that conversion window is not exported per row.
6. LinkedIn: every literal header; date format; currency and time zone presence; whether any preamble exists; decimals in conversions.
7. GA4: the CSV preamble comment lines, header strings, and number formatting for report and Exploration exports; time zone and currency statement in the file.
8. Time zone: only the Meta rule (account time zone sets day boundaries) and GA4 BigQuery (property time zone) are sourced. Google Ads and LinkedIn time zone handling is not sourced.
9. Whether the user's Meta Ads Manager UI language and number locale change the header strings or decimal separators.
10. The owner-stated expectations (Google Ads `Total:` rows, `Impr.`) should be checked against a sample before the reader relies on them.
