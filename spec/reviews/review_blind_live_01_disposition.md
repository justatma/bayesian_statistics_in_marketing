# Disposition of blind review live 01 (proposed)

Review: `spec/reviews/review_blind_live_01.md`. Written 2026-11-07 by Claude (integrator). All of part A answered by the owner on 2026-11-07. Once answered, the rulings go into
spec v0.2 of the live view and the decision rows into `spec/decisions.md`, then L0 starts.

## A. For the owner

| # | Question | Recommendation |
|---|---|---|
| 1.1 | Should the page name the two outcome classes it does not show (commercially realized, causally incremental)? | Answered by the owner 2026-11-07: yes. The page shows delivery and platform-attributed numbers only; the line stops a cost per signup being read as a cost per sale. |
| 1.3 | v0.3 G7 says every rendered number comes from an engine quantity. The live page computes CTR, CPC and cost per conversion straight from stored rows. Allow it for the internal page only? | Answered by the owner 2026-11-07: allow, internal only. Each such number labelled as a platform count; the client view stays under G7. Recorded as D42. |
| 2.36a | Where is the keys file, so the launchd poll job can read `META_ACCESS_TOKEN`? | Answered by the owner 2026-11-07: `/Users/atma1/.secrets/keys.env`. Loaded into the environment without printing, never read aloud, never copied into a repository. `install.sh` makes the launchd job load the file at run time; no value goes into the plist. |
| 2.6 | Who sets `conversion_event` in `configs/jovannah.yaml`, and to which string? | Answered by the owner 2026-11-07: the integrator sets it from what her account returns and logs the string. The pixel's lead label is carried as provisional until the first signup confirms it. |
| §7 | The six defaults in spec §7 (7-day lookback, port 8765, 7-day recordings, 2-hour stale banner, engine skipped until her approvals, the name "live view"). | Answered by the owner 2026-11-07: "the six defaults stand; Jovannah's economics are approved, the priors are not yet". Checked: `configs/economics/jovannah.json` approved by the owner at 2026-11-07T17:40Z with a $150 loss tolerance (commit 99550b5). The engine section will show the G8 skip until her CTR priors are approved, which is put to the owner when L4 is reached. |

## B. Integrator rulings

Owner, 2026-11-07: "Settle as written." All rows below go into live view spec v0.2.

| # | Ruling |
|---|---|
| 1.2 | Engine section shows the run's G3 result in words, or "conjugate fit, no sampler diagnostics" when none ran. |
| 1.4 | One decision row covers the recording replacement, the test-fake move and `purchase_type` becoming `conversion_type`. |
| 1.5 | Meta only in this version, stated in §1. `--all` means every client config in `configs/`, Meta account only. |
| 1.6 | D41 amended to list `name` among the account fields. |
| 2.1 | Facts pack F2b checks `objective` on insights at `level=ad` against Meta's docs and the live response. If it is not there, `objective` stays None, the page shows "objective not read", and no check depends on it. |
| 2.2 | Mapping fixed in spec: `account_name`, `campaign_name`, `adset_name` to `entity_ids.ad_set_name`, `ad_name`, each to its `PERF_TARGETS` name. |
| 2.3 | `Fetched.account` holds the API's raw strings. `view.py` converts minor units to `Money` by the currency's exponent (USD 2). F2b confirms the unit. |
| 2.4 | The account URL changes too; both recordings are re-made in one session. |
| 2.5 | `wanted` is matched in `actions` for the count and `action_values` for the value. Not found: count 0, rows still stored, note says "event not seen in this pull", page says the same above the table. |
| 2.6b | A lead client's `revenue_reported` is None, not 0 (D33: never valued). |
| 2.7 | `live/config.py` (L0) loads `configs/<id>.yaml` into `ClientConfig`; `--all` globs `configs/*.yaml`. `economics_path` is already in `configs/jovannah.yaml` (commit 99550b5), resolved relative to `configs/`. |
| 2.8, 2.9, 2.10, 2.11 | L4 does not write a CSV. It builds the `DatasetManifest` in memory and calls `pipeline.execute(..., pulls=[...])` with a `PlatformPull` rebuilt from the latest good poll's rows, the path shadow replay already uses. Variants are ad ids; `entity_map` maps each ad id to itself; window is the poll's window; one ad means `skipped` with "one ad, nothing to compare". Prior ids come from a new optional config key `priors: {path: prior_id}`; absent means `skipped` with the G8 text. Economics: `economics_id` is the stem of `economics_path`, `manifest_dir` its parent's parent. |
| 2.12 | `GateFailure` reasons joined with "; ". Any `GateFailure` is `skipped` (the gates are refusals, not faults), anything else `failed`. |
| 2.13 | `refresh` sets `BAYES_DATA_DIR` for the call with a context manager. The page reads the snapshot and renders through new public `reporting.render.finding_lines` and `not_knowable_lines`, taking snapshot quantities. L0 adds them as thin public names over the existing helpers. |
| 2.14 | L0 adds `floors.estimability.event_floor(status) -> int` computing `ceil((z/w)^2)` from `registry_target()`. The acceptance test asserts the computed numbers, not "about 17". Conversions None shows "not reported". |
| 2.15 | L0 adds `status_labels` to `phrasing.yaml` (registry version bumped). |
| 2.16 | CTR = link clicks / impressions, CPC = spend / link clicks, cost per conversion = spend / conversions, all summed over the period first. Zero denominator shows "none yet". Rounding from `phrasing.yaml` `rounding`. Today = the poll's `finished_at` converted to the account zone. Test asserts the CTR cell contains its own click and impression counts. |
| 2.17 | Periods become today, yesterday, last 7 days. |
| 2.18, 2.19 | Exact heading strings, the D33 sentence and both banner texts fixed verbatim in v0.2. The acceptance tests match those strings. |
| 2.20 | Two tables: `polls` (one insert at start) and `poll_outcomes` (one insert at finish), both under the triggers, also `refreshes`. `latest_poll` joins them. A start with no outcome shows as "poll interrupted". |
| 2.21 | `open` is a classmethod on `SqliteStore`. WAL mode, 5s busy timeout, view opens read-only, one connection per request, `ThreadingHTTPServer`. |
| 2.22 | `PlatformPull` gains `account: dict[str, str] = {}` (a v0.3 change, in the decision row). `poll` catches `Exception`. |
| 2.23 | `poll_id` = sha8 of client, platform and `started_at` to the microsecond. The recording dir is set through a context manager that restores the env. launchd always passes `--record`. |
| 2.24 | Window = the 7 account-local days ending today, today included. |
| 2.25 | Error text passes through a new `redact_text` that blanks every credential value and any `access_token=` value. The secrets test sets fake credential values in env. |
| 2.26 | Early = within `interval_seconds` of the last good poll. |
| 2.27 | Age from the poll's `started_at` in the store. Each poll ends by calling `prune`. |
| 2.28 | Money stored as decimal text plus currency column. Full schema, keys and indexes in v0.2 §4. |
| 2.29 | Integrator re-records before the acceptance tests are written. `test_P8.py` gains no new assertions; the replaced recording must keep it green. Order stated in §5 L0. |
| 2.30 | Dependency order stated: L1 and L2 in parallel against the L0 contracts and fakes, L3 and L4 after both merge. |
| 2.31 | Five ads and the $1,500 cap are checked against the live read at the smoke run, not asserted in tests. |
| 2.32 | L4 fixtures use `synthetic=False` with approved economics and priors written into a temp dir, so G8 and G9 are exercised. |
| 2.33 | `live.yaml` gains `freshness_date` and `account_status` map. Staleness of `live.yaml` blocks nothing. |
| 2.34 | `text/html; charset=utf-8`; non-GET 405; unknown client 404; query strings ignored. Index lists each client with last good poll and a link. |
| 2.35 | Page refresh seconds move into `live.yaml` (`page_refresh_seconds: 300`). Watermark key `watermark.internal`. |
| 2.36b | `install.sh` writes `StartInterval` from `interval_seconds`, so the registry governs; a cadence change means rerun install. Missed hours on sleep are left to the stale banner. |
| 2.37 | `cli.py` is the one importer of `live/`, stated. Template shipped as package data in `pyproject.toml` (L0). |
