# Live view: hourly feed and internal dashboard. Specification v0.2

Written 2026-11-07 by Claude (integrator). v0.1 plus the disposition of blind review live 01
(`spec/reviews/review_blind_live_01.md`, `spec/reviews/review_blind_live_01_disposition.md`), every
part of which the owner answered on 2026-11-07. Build under
`/Users/atma1/gh_all/system_instructions/7_Build Protocol.md`. Extends spec v0.3; nothing in v0.3
changes except where §3 says so, and each such change is in D41, D42 or D43.

Numbers in square brackets name the review finding a passage settles.

## 0. The blueprint, in the owner's words

"It is supposed to be a live feed that can be monitored in a dashboard." Sixty minutes between
reads, "things won't be moving that fast". "We also need our own internal dashboard that we see. So
let's start with our version, and then we'll work on what the users can see." The client-facing
view waits on the customer-experience work and on how clients get access to the personas assigned
to them. Standalone on this machine, the owner the only viewer.

The foundation documents already point here: the Decision Framework (§5.5) names "daily (or
intra-day) posterior refresh, changing reporting from monthly PDFs to living dashboards, with the
diagnostics gate preserving honesty at speed". The inventory (§VIII) asks that a numerical dashboard
"distinguish delivery, platform-attributed, commercially realized, and causally incremental
outcomes" and never conflate them. Spec v0.3 §14 keeps "no real-time/intraday bidding logic"; this
build reads and shows, it never writes to an ad platform.

## 1. What is built

| Piece | What | Files |
|---|---|---|
| L0 | Skeleton, integrator, one hand | everything in §2 marked L0 |
| L1 | Connector widening (Meta) | `data_contract/connectors/meta.py` |
| L2 | Store, poll, prune | `live/store.py`, `live/poll.py`, `live/prune.py` |
| L3 | View and server | `live/view.py`, `live/serve.py`, `live/templates/live.html`, `live/templates/index.html` |
| L4 | Engine refresh | `live/refresh.py` |

Meta only in this version. Google Ads, LinkedIn and GA4 are not polled. `live poll --all` means
every client config in `configs/`, each client's Meta account only [1.5].

What it is not: no client-facing page, no writes to Meta, no new probability theory, no new
dependency beyond the standard library and what `pyproject.toml` already lists.

Order [2.30]: L0, then the re-recording (§3.5), then the acceptance tests (frozen), then L1 and L2
in parallel against the L0 contracts and fakes, then L3 and L4 in parallel once L1 and L2 have
merged. L3 and L4 are written against the merged store, not a fake of it, for their smoke tests;
their acceptance tests still use `FakeStore`.

## 2. Layout and conventions

```
src/bayesian_marketing/live/
  __init__.py          L0: docstring; exports
  contracts.py         L0: records and Protocols of §4
  config.py            L0: load_client(id), all_clients(), filled by L0 (small, no builder)
  registry.py          L0: LiveRegistry model and load_live_registry()
  store.py             L2 (L0 writes the schema constant and the class shell)
  poll.py              L2
  prune.py             L2
  refresh.py           L4
  view.py              L3
  serve.py             L3
  templates/live.html  L3
  templates/index.html L3
registries/live.yaml   L0
registries/phrasing.yaml   L0 adds status_labels and the live block (§5 L3), version bumped
src/bayesian_marketing/floors/estimability.py   L0 adds event_floor (§5 L3 C5)
src/bayesian_marketing/reporting/render.py      L0 adds finding_lines, not_knowable_lines (§5 L3 C6)
src/bayesian_marketing/data_contract/connectors/base.py   L0: Fetched.account
src/bayesian_marketing/data_contract/connectors/http.py   L0: redact_text (§5 L2 C3)
src/bayesian_marketing/core/records.py          L0: ClientConfig fields (§3.2)
src/bayesian_marketing/core/data.py             L0: PlatformPull.account (§3.3)
src/bayesian_marketing/data_contract/connectors/pull.py   L0: copies Fetched.account to PlatformPull
src/bayesian_marketing/cli.py                   L0: live subcommands
pyproject.toml         L0: package data for live/templates/*.html [2.37]
data/live/             gitignored: live.sqlite, recordings/<client_id>/<poll_id>/, logs/
scripts/live/          L0: com.atma.bayes.live_poll.plist.in, com.atma.bayes.live_view.plist.in,
                       install.sh, uninstall.sh, run_with_keys.sh
tests/fakes/live.py, tests/fakes/meta_api.py    L0
tests/acceptance/test_L1.py .. test_L4.py       frozen before builders
tests/unit/l1 .. l4                             builders' own
```

Dependency rule (v0.3 §1): `live/` imports `core`, `data_contract`, `pipeline`, `floors`,
`reporting.render` (the two public helpers and the phrasing loader). `cli.py` is the one module that
imports `live/` [2.37]. HTTP to Meta stays in `data_contract/connectors/`. `serve.py` uses
`http.server.ThreadingHTTPServer`, binds the loopback address only, and sends no request anywhere.

Timestamps UTC ISO-8601 (v0.3 §3). Ids: `poll_<sha8>` where sha8 is the first 8 hex of sha256 over
`client_id|platform|started_at.isoformat()` with microseconds [2.23]; `lv_<sha8>` over
`poll_id|at.isoformat()` for a refresh. Money as `Money` inside, decimal text in SQLite, text on the
page. The clock is injected (`Clock`, `now() -> datetime`, UTC, tz-aware).

## 3. Changes to v0.3 objects (L0, decision rows D41 and D43)

### 3.1 Insights names and objective

F2b (`spec/facts/F2_meta_live.md`) verified all five fields; `OBJECTIVE_REQUESTED = True`.

`INSIGHT_FIELDS` gains `account_name`, `campaign_name`, `adset_name`, `ad_name`, and `objective` if
facts pack F2b verifies it [2.1]. Mapping in `_record` [2.2]:

| API key | target |
|---|---|
| `account_name` | `entity_ids.account_name` |
| `campaign_name` | `entity_ids.campaign_name` |
| `adset_name` | `entity_ids.ad_set_name` |
| `ad_name` | `entity_ids.ad_name` |
| `objective` | `objective` |

The pull lands each `entity_ids.<key>_name` target in `PerformanceRow.entity_names[<key>]` with the
suffix stripped (D34, `data_contract/readers/rows.py` `NAME_SUFFIX`), so `entity_names` has the same
keys as `entity_ids`: `account`, `campaign`, `ad_set`, `ad` (build log B4).

If F2b cannot verify `objective` on `act_<id>/insights` at `level=ad`, it is not requested,
`PerformanceRow.objective` stays None, the page shows `objective not read`, and no acceptance test
depends on it. The test for objective is written conditionally on a constant
`meta.OBJECTIVE_REQUESTED` that L0 sets from F2b.

### 3.2 `ClientConfig`

```python
class ClientConfig(Frozen):                       # core/records.py
    ...                                            # existing fields unchanged
    conversion_event: dict[Platform, str] = {}     # platform -> action_type
    conversion_event_confirmed: dict[Platform, bool] = {}   # False or absent: provisional
    priors: dict[str, str] = {}                    # parameter path -> approved prior id (L4)
```

`conversion_type(elements, wanted: str | None) -> str | None` replaces `purchase_type` in `meta.py`
(D43). With `wanted` set, the count comes from that `action_type` in `actions` and the value from
the same type in `action_values` [2.5]. When `wanted` appears in neither, `conversions_reported` is
0.0 on every row, rows are still stored, and the pull note reads
`conversion event {wanted} not seen in this pull`. When it is found, the note reads
`conversion event {wanted} used`. With `wanted` None, the v0.3 purchase order applies unchanged.

A lead event's `revenue_reported` is None on every row, whatever `action_values` holds: D33, a lead
is never valued [2.6b]. A config event is a lead event when its string contains `lead`.

Jovannah's string [2.6]: the integrator sets `conversion_event: {meta: <string>}` from what her
account returns in the re-recording (§3.5) and logs the string in `spec/decisions.md`.
`conversion_event_confirmed` stays absent (provisional) until her first signup confirms the label;
the page marks the event name `(provisional)` until then.

D33 holds: `compare` on `cvr` or `cpa` for a lead client still raises `NotInScope`.

### 3.3 Account fields

`ACCOUNT_FIELDS` becomes `("timezone_name", "currency", "name", "account_status", "spend_cap",
"amount_spent")` [1.6]. `Fetched` gains `account: dict[str, str]`, the API's raw values as text,
missing keys absent. `PlatformPull` gains `account: dict[str, str] = {}` (core/data.py, D43) and
`pull()` copies it across [2.22]. `spend_cap` and `amount_spent` are kept in the API's units;
`view.py` converts them (§5 L3 C2). F2b confirms the unit (expected: minor units, cents for USD)
[2.3].

### 3.4 Registry

```yaml
# registries/live.yaml
version: "2026-11-07"
freshness_date: "2026-11-07"     # informational; staleness blocks nothing [2.33]
interval_seconds: 3600
lookback_days: 7
stale_after_seconds: 7200
recordings_keep_days: 7
page_refresh_seconds: 300        # [2.35]
bind: "127.0.0.1"
port: 8765
account_status:                  # Meta account_status codes; unknown codes shown as the code
  "1": active
  "2": disabled
  "3": unsettled
  "7": pending risk review
  "8": pending settlement
  "9": in grace period
  "100": pending closure
  "101": closed
  "201": any active
  "202": any closed
```

The codes are a fact for F2b to confirm; any it cannot confirm are dropped from the map.
`LiveRegistry` (pydantic, `live/registry.py`) validates the file; `load_live_registry(root=None)`
reads it through `core.registries.load("live")`.

### 3.5 Recordings

Both recordings change URL (insights fields and account fields) [2.4], so the integrator re-records
in one session, after L0 and before the acceptance tests are written [2.29]: `meta_empty` from a
window before the account's first spend, and `meta_jovannah_7d` from the last seven days.
Recordings are never hand-edited. `tests/acceptance/test_P8.py` and `tests/unit/p8` must stay green
on the new recordings with no change to their assertions. If the new `meta_jovannah_7d` has rows,
`test_P8.py`'s empty-account replay points at `meta_empty` only (it already does).

## 4. Contracts (L0 lays these down; builders fill bodies)

```python
# live/contracts.py
class PollRecord(Frozen):
    poll_id: str; client_id: str; platform: Platform; account_id: str
    started_at: datetime; finished_at: datetime | None
    window: tuple[date, date]
    status: Literal["ok", "error", "interrupted"]   # "interrupted": started, no outcome row
    error: str | None
    pull_id: str | None; n_rows: int; n_quarantined: int; empty_account: bool
    timezone: str | None; currency: str | None
    account: dict[str, str]
    recording_dir: str | None

class LiveRow(Frozen):
    poll_id: str; client_id: str; platform: Platform
    entity_ids: dict[str, str]; entity_names: dict[str, str]; objective: str | None
    date: date; impressions: int; clicks: int; spend: Money
    conversions_reported: float | None; conversions_observed: int | None
    revenue_reported: Money | None; attribution_window: str

class RefreshRecord(Frozen):
    refresh_id: str; poll_id: str; client_id: str; at: datetime
    status: Literal["ran", "skipped", "failed"]; reason: str | None
    run_id: str | None

class Store(Protocol):
    def begin_poll(self, rec: PollRecord) -> None        # writes the polls row; outcome fields ignored
    def finish_poll(self, rec: PollRecord, rows: list[LiveRow]) -> None   # outcome + rows, one transaction
    def latest_poll(self, client_id: str, *, ok_only: bool = True) -> PollRecord | None
    def rows(self, poll_id: str) -> list[LiveRow]
    def polls(self, client_id: str, *, limit: int) -> list[PollRecord]   # newest first
    def add_refresh(self, rec: RefreshRecord) -> None
    def latest_refresh(self, client_id: str) -> RefreshRecord | None
    def clients(self) -> list[str]                       # sorted

class SqliteStore:                                       # live/store.py, implements Store
    @classmethod
    def open(cls, path: Path, *, read_only: bool = False) -> SqliteStore   # creates schema; idempotent
    def close(self) -> None

class Clock(Protocol):
    def now(self) -> datetime

# live/config.py
def load_client(client_id: str, root: Path | None = None) -> ClientConfig   # configs/<id>.yaml
def all_clients(root: Path | None = None) -> list[ClientConfig]          # configs/*.yaml, sorted
# root defaults to <repo>/configs, or BAYES_CONFIG_DIR when set

# live/poll.py
def poll(config: ClientConfig, store: Store, clock: Clock, *, platform: Platform = "meta",
         registry: LiveRegistry, record_root: Path | None) -> PollRecord

# live/prune.py
def prune(record_root: Path, store: Store, clock: Clock, keep_days: int) -> list[Path]

# live/refresh.py
def refresh(config: ClientConfig, poll_rec: PollRecord, store: Store, clock: Clock,
            *, data_dir: Path, config_root: Path) -> RefreshRecord

# live/view.py
def render(store: Store, client_id: str, clock: Clock, *, registry: LiveRegistry,
           phrasing: dict[str, Any], data_dir: Path, config: ClientConfig) -> str
def render_index(store: Store, clock: Clock, *, registry: LiveRegistry) -> str

# live/serve.py
def make_server(store_path: Path, *, registry: LiveRegistry, clock: Clock, data_dir: Path,
                config_root: Path, port: int | None = None) -> ThreadingHTTPServer
def serve(store_path: Path, *, registry: LiveRegistry, clock: Clock, data_dir: Path,
          config_root: Path) -> None              # make_server + serve_forever + SIGTERM

# floors/estimability.py
def event_floor(status: Literal["marginal", "estimable"]) -> int

# reporting/render.py
def finding_lines(q: Quantity, phrasing: dict[str, Any]) -> dict[str, Any]       # public _finding
def not_knowable_lines(q: Quantity, phrasing: dict[str, Any]) -> dict[str, Any]  # public _not_knowable

# data_contract/connectors/http.py
def redact_text(s: str, secrets: Iterable[str]) -> str
```

### 4.1 Store schema [2.20, 2.21, 2.28]

```sql
PRAGMA journal_mode=WAL;   -- set on open (read-write); busy_timeout 5000 on every connection
CREATE TABLE IF NOT EXISTS schema_info (key TEXT PRIMARY KEY, value TEXT NOT NULL);
  -- ('schema_version', '1')
CREATE TABLE IF NOT EXISTS polls (
  poll_id TEXT PRIMARY KEY, client_id TEXT NOT NULL, platform TEXT NOT NULL,
  account_id TEXT NOT NULL, started_at TEXT NOT NULL,
  window_start TEXT NOT NULL, window_end TEXT NOT NULL, recording_dir TEXT);
CREATE TABLE IF NOT EXISTS poll_outcomes (
  poll_id TEXT PRIMARY KEY REFERENCES polls(poll_id), finished_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ok','error')), error TEXT,
  pull_id TEXT, n_rows INTEGER NOT NULL, n_quarantined INTEGER NOT NULL,
  empty_account INTEGER NOT NULL, timezone TEXT, currency TEXT, account_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rows (
  poll_id TEXT NOT NULL REFERENCES polls(poll_id), client_id TEXT NOT NULL, platform TEXT NOT NULL,
  ad_id TEXT NOT NULL, date TEXT NOT NULL,
  entity_ids_json TEXT NOT NULL, entity_names_json TEXT NOT NULL, objective TEXT,
  impressions INTEGER NOT NULL, clicks INTEGER NOT NULL,
  spend_amount TEXT NOT NULL, spend_currency TEXT NOT NULL,
  conversions_reported REAL, conversions_observed INTEGER,
  revenue_amount TEXT, revenue_currency TEXT, attribution_window TEXT NOT NULL,
  PRIMARY KEY (poll_id, ad_id, date));
CREATE TABLE IF NOT EXISTS refreshes (
  refresh_id TEXT PRIMARY KEY, poll_id TEXT NOT NULL REFERENCES polls(poll_id),
  client_id TEXT NOT NULL, at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ran','skipped','failed')), reason TEXT, run_id TEXT);
CREATE INDEX IF NOT EXISTS polls_client_started ON polls(client_id, started_at);
CREATE INDEX IF NOT EXISTS refreshes_client_at ON refreshes(client_id, at);
-- for each of polls, poll_outcomes, rows, refreshes:
CREATE TRIGGER IF NOT EXISTS <t>_no_update BEFORE UPDATE ON <t>
  BEGIN SELECT RAISE(ABORT, 'live store is append-only'); END;
CREATE TRIGGER IF NOT EXISTS <t>_no_delete BEFORE DELETE ON <t>
  BEGIN SELECT RAISE(ABORT, 'live store is append-only'); END;
```

`latest_poll` is `polls LEFT JOIN poll_outcomes`, newest `started_at` first; with `ok_only` it
requires `status='ok'`. A polls row with no outcome reads back as `status="interrupted"`. The view
opens the store read-only (`file:...?mode=ro` URI), one connection per request.

## 5. Pieces

### L2. Store, poll, prune

- C1. Window [2.24]: the `lookback_days` account-local dates ending today inclusive, today being
  `clock.now()` converted to the account time zone (the latest ok poll's `timezone`, else the
  config's). For 7: today and the six days before. `poll` calls
  `data_contract.connectors.pull.pull(platform, config, window)`. With `record_root` given,
  `BAYES_RECORD_DIR` is set to `<record_root>/<client_id>/<poll_id>` for that call only, inside a
  context manager that restores the previous value [2.23]. The newest ok poll's rows are the
  truth for the dates it covers.
- C2. Append-only, as §4.1. Every poll inserts.
- C3. Errors are rows. `poll` catches `Exception` [2.22]: the outcome is `status="error"`,
  `error="<ExceptionClass>: <message>"` passed through `redact_text(msg, secrets)` where `secrets`
  are the values of every credential name in `http.py`'s credential list present in the
  environment; `redact_text` also replaces any `access_token=<value>` with `access_token=REDACTED`
  [2.25]. `poll` never raises; the CLI exits 1 when the outcome is an error.
- C4. Ledger and prune. The recording directories are the shadow ledger. After `finish_poll`,
  `poll` calls `prune(record_root, store, clock, registry.recordings_keep_days)` when `record_root`
  is set [2.27]. A directory's age is its poll's `started_at` from the store; a directory under
  `record_root` whose name is no poll in the store is left alone and logged. The store keeps every
  row.
- C5. Early [2.26]: when the latest ok poll for the client started less than `interval_seconds`
  before `clock.now()`, the CLI prints `early: last good poll <n> minutes ago` and polls anyway.
- C6. Secrets. The store and recordings hold no credential value and no `access_token=` other than
  `access_token=REDACTED`.

Checks, `tests/acceptance/test_L2.py`, using `tests/fakes/meta_api.py` handlers through the
connector's transport and fake credential values set in env:
a poll over a three-ad, three-day fake stores 9 rows and one ok poll; an auth error stores an error
poll with no rows and an error text without the fake token; UPDATE and DELETE on each of the four
tables raise `sqlite3.IntegrityError` or `sqlite3.DatabaseError` with `append-only`; a second poll
stores a second set and `latest_poll` returns it; a polls row with no outcome reads back
`interrupted` and `latest_poll(ok_only=True)` skips it; `prune` removes exactly the directories
whose poll started more than `keep_days` before the clock; the window for a clock of
2026-11-07T03:00Z and zone America/New_York ends 2026-11-06; the secrets grep over the SQLite file
and recording tree finds no fake credential value.

### L1. Connector widening

§3.1 to §3.3. Checks, `tests/acceptance/test_L1.py`: a fake element with the four names fills
`entity_names` with `account`, `campaign`, `ad_set`, `ad` (B4); with
`OBJECTIVE_REQUESTED`, `objective` is filled; `conversion_event={"meta": "lead"}` over elements
carrying `lead` and `omni_purchase` gives `conversions_reported` from `lead`, `revenue_reported`
None, and the note `conversion event lead used`; the same with `lead` absent gives 0.0 and the note
`conversion event lead not seen in this pull`; no `conversion_event` gives `omni_purchase` with its
value; an account response with all six fields lands in `PlatformPull.account` as text; the
re-recorded `meta_empty` replays with `empty_account=True`; `test_P8.py` passes unchanged.

### L3. View and server

One HTML page per client, rendered per request from the store. No JavaScript.
`<meta http-equiv="refresh" content="{page_refresh_seconds}">`. Rounding from `phrasing.yaml`
`rounding` (percent 1 decimal, money 0 decimals). Fixed strings live in `phrasing.yaml` under a new
`live:` block (L0 writes them; the template reads them, never hard-codes them) [2.18, 2.19]:

```yaml
live:
  title: "Live view: {client_id}"
  h_account: "Account"
  h_delivery: "Delivery"
  h_conversions: "Conversions"
  h_budget: "Information budget (counts against floors, not estimates)"
  h_engine: "Engine"
  banner_error: "The latest poll failed at {at} UTC: {error}"
  banner_stale: "No good poll since {at} UTC ({hours} hours)."
  banner_interrupted: "The poll started at {at} UTC has no outcome: poll interrupted."
  no_poll: "No poll yet."
  no_limit: "no limit set"
  objective_missing: "objective not read"
  none_yet: "none yet"
  not_reported: "not reported"
  event_not_seen: "The event {event} was not seen in this pull."
  provisional: "(provisional)"
  lead_sentence: "The engine counts leads and does not put a value on them (D33), so this page shows no revenue and no return on spend."
  not_shown: "Not shown: revenue the business booked, and what the ads caused. Neither is measured yet."
  platform_count: "platform count"
  no_engine: "No engine run yet."
  engine_skipped: "Engine skipped: {reason}."
  engine_failed: "Engine run failed: {reason}."
  no_diagnostics: "conjugate fit, no sampler diagnostics"
status_labels:
  below_floor: "below floor"
  marginal: "marginal"
  estimable: "estimable"
```

- C1. Header: h1 `live.title`; platform; account name and id; time zone; currency; last good poll
  in UTC and account-local; next expected (last good `started_at` + `interval_seconds`). Banners,
  any that apply, in this order: `banner_error` when the latest poll of any status is an error;
  `banner_interrupted` when it is interrupted; `banner_stale` when the latest ok poll started more
  than `stale_after_seconds` ago. No poll at all: `no_poll` and nothing else below the header.
- C2. Account (h2 `h_account`): `amount_spent` against `spend_cap`, each converted from minor units
  by the currency's exponent (ISO 4217, from a small table in `view.py`: 2 by default, 0 for JPY,
  KRW, CLP, ...) to `Money`; `no_limit` when `spend_cap` is "0" or absent. Status from
  `live.yaml` `account_status`, unknown codes as the code.
- C3. Delivery (h2 `h_delivery`): one row per ad (campaign, ad set, ad: name and id; a missing name
  shows the id only); column groups today, yesterday, last 7 days [2.17], each impressions, link
  clicks, spend, CTR, CPC. Periods use account-local dates over the latest ok poll's rows [2.16].
  CTR = clicks / impressions, CPC = spend / clicks, each over sums for the period; zero
  denominator shows `none yet`. The CTR cell reads `{pct}% ({clicks} / {impressions})`. Above the
  table, once: `evidence_plain.delivery`, then `platform_count` (D42). Objective per campaign, or
  `objective_missing`.
- Unit costs (CPC, cost per conversion) round to `rounding.unit_money_decimals` (2); totals to
  `money_decimals` (0). Counts are plain digits, as `2.0% (20 / 1000)` shows (B8).
- C4. Conversions (h2 `h_conversions`): same rows; the event name (or `purchases` when none is set)
  with `provisional` when not confirmed; count and cost per conversion (spend / count, `none yet`
  at zero, `not reported` when the count is None) per period; the rows' `attribution_window`.
  Above the table, once: `evidence_plain.platform_attributed`, then `platform_count`. Under it:
  `event_not_seen` when an event is configured, the poll has rows, and their conversion counts
  sum to 0 (Meta omits an action that did not occur, so 0 everywhere is "not seen"; B8); `lead_sentence` for a lead event; `not_shown`
  always [1.1].
- C5. Information budget (h2 `h_budget`): per ad, clicks against `event_floor("marginal")` and
  `event_floor("estimable")` (17 and 68 at the current registry: `ceil((z/w)^2)`, z the two-sided
  normal quantile at `level` 0.90, w = `caveat_rel_half_width` 0.40 and `rel_half_width` 0.20)
  [2.14]; the same for conversions (`not reported` when None); a word from `status_labels` for each:
  below the marginal floor `below_floor`, at or above it `marginal`, at or above the estimable floor
  `estimable` [2.15].
- C6. Engine (h2 `h_engine`): with `latest_refresh` status `ran`, the snapshot
  `<data_dir>/runs/<run_id>.json` (loaded with `pipeline.load_snapshot` inside a context that sets
  `BAYES_DATA_DIR` to `data_dir`) [2.13]: per quantity, `finding_lines(q, phrasing)`, and
  `not_knowable_lines(q, phrasing)` for each below-floor quantity; the snapshot's `diagnostics` per
  route in words, or `no_diagnostics` when the list is empty [1.2]. Skipped: `engine_skipped`;
  failed: `engine_failed`; none: `no_engine`.
- C7. Honesty: no number on the page comes from anything but the store, the snapshot, or the
  registries. Every percentage shows its counts. No string from `negation_frames` or
  `generic_phrases` appears in the rendered page or the templates (test over the rendered HTML of
  the full fixture). Footer: `watermark.internal` [2.35].
- C8. Server [2.34]: routes `GET /` (index: each client, last good poll UTC, link), `GET
  /client/<id>` (404 when the id is not in `store.clients()`), `GET /health`
  (`{"ok": true, "last_poll": {client_id: iso | null}}`, `application/json`). Pages
  `text/html; charset=utf-8`. Query strings ignored (the path before `?` is routed). Any other
  method 405, any other path 404. One stdout line per request: `METHOD PATH STATUS MSms`. SIGTERM
  shuts down cleanly. The config for a client page comes from `live.config.load_client`.

Checks, `tests/acceptance/test_L3.py`, rendering from `FakeStore` with `FixedClock`: the h1 and
the five h2 strings; `evidence_plain.delivery` exactly once, before the delivery table, and
`evidence_plain.platform_attributed` exactly once, before the conversion table; a CTR cell
`2.0% (20 / 1000)` for a fixture ad; the error banner with the fixture message; the stale banner
for a last good poll 7201 seconds old and none at 7199; the interrupted banner; a lead client shows
`lead_sentence`, `(provisional)`, and no `ROAS` and no `revenue` cell; `not_shown` present; an
unlimited account shows `no limit set`; a cap of "150000" in USD shows `$1,500`; budget words for
16, 17, 67, 68 clicks are below floor, marginal, marginal, estimable; the engine section renders
`finding_lines` output from a fixture snapshot, the skip sentence from a skipped refresh, and
`No engine run yet.` with none; no banned phrase in the rendered HTML; `make_server(port=0)` in a
thread answers `/health` with JSON, `/client/unknown` 404, `/anything` 404, `POST /` 405,
`/client/<id>?x=1` 200.

### L4. Engine refresh

- C1. After an ok poll, `refresh` builds a `DatasetManifest` in memory for the client (no CSV)
  [2.8 to 2.11]: `synthetic=False`, `economics_id` the stem of `config.economics_path`,
  `entity_map` each ad id in the poll's rows to `{"meta": ad_id}`, files empty. It rebuilds one
  `PlatformPull` from the poll's `LiveRow`s and calls `pipeline.execute(manifest, request,
  manifest_dir=config_root, pulls=[pull])` with `metric="ctr"`, variants the poll's ad ids in
  sorted order, `window` the poll's window, the default CTR horizon, `priors=config.priors`, inside
  a context that sets `BAYES_DATA_DIR` to `data_dir` and restores it. Economics resolve to
  `<config_root>/economics/<economics_id>.json`, which for Jovannah is
  `configs/economics/jovannah.json` from `economics_path: economics/jovannah.json`.
- C2. Outcomes [2.12]: fewer than two ads: `skipped`, `one ad, nothing to compare`. No
  `economics_path`: `skipped`, `no economics file in the client config`. Any `GateFailure`:
  `skipped`, the gate's reasons joined with `; `. Any other exception: `failed`,
  `<ExceptionClass>: <message>`. `refresh` never raises.
- C3. One refresh per ok poll; none after an error poll. The record carries the run id.
- C4. `ctr` only.

Checks, `tests/acceptance/test_L4.py`, in a temp config root with `synthetic=False` [2.32]:
approved economics with a loss tolerance and approved CTR priors give `ran` and a snapshot with a
`ctr` quantity per ad; the same economics without a loss tolerance give `skipped` with
`no loss tolerance set` in the reason; an unapproved prior gives `skipped` with the G8 text; a
pipeline that raises `RuntimeError` (monkeypatched) gives `failed`; one ad gives the one-ad skip;
two ok polls give two refreshes.

### L0. Skeleton (integrator)

Everything marked L0 in §2. `live/config.py` and `live/registry.py` are filled by L0 (small and
shared). `event_floor`, `finding_lines`, `not_knowable_lines`, `redact_text`, the `Fetched.account`
and `PlatformPull.account` plumbing in `pull.py`, and the phrasing additions are filled by L0 with
unit tests, since they sit in hot or shared files. Builders' module bodies raise
`NotImplementedError`. `tests/fakes/live.py` (`FakeStore`, `FixedClock`) and
`tests/fakes/meta_api.py` (moved from `tests/unit/p8`, which then imports it, D43).

CLI (`cli.py`): `live poll --client <id> | --all [--record]`, `live serve`, `live prune`,
`live refresh --client <id>`. Data dir `data/live/` (overridable with `BAYES_LIVE_DIR`).

launchd [2.36]: `install.sh` renders the two `.plist.in` templates into
`~/Library/LaunchAgents/`, writing `StartInterval` from `interval_seconds` (a cadence change means
rerunning install). Both jobs run `scripts/live/run_with_keys.sh`, which sources
`/Users/atma1/.secrets/keys.env` into its own environment at run time with output suppressed, then
execs the CLI with the project's `.venv` Python. No credential value is written into a plist, a log,
the store or the repository. Poll job: `StartInterval`, `RunAtLoad`, always `--record`. View job:
`KeepAlive`, `ThrottleInterval 30`. Logs in `data/live/logs/`. Missed hours while the machine sleeps
are shown by the stale banner and not caught up.

## 6. Smoke run (protocol item 11), integrator

1. `live poll --client jovannah --record` against the live account: one ok poll, rows for the ads in
   the capped ad set with names, the conversion event named in the note. The count of ads and the
   $1,500 cap are checked here against the live read, not in tests [2.31].
2. `live serve` under launchd; `curl 127.0.0.1:8765/health` shows the poll; the client page shows
   the header, the cap line, the delivery table, the conversion table with `(provisional)`, the
   budget section, and the G8 skip sentence (her economics are approved, her CTR priors are not).
3. `launchctl list | grep com.atma.bayes` shows both jobs; the poll log shows one line per hour.
4. Secrets grep over `data/live/` with the real token value, read from the keys file by the grep
   script without printing, finds nothing.

## 7. Owner's answers, 2026-11-07

Lookback 7 days, port 8765 on the loopback address, recordings kept 7 days with rows forever, stale
banner after 2 hours, the name "live view": the defaults stand. Jovannah's economics are approved
(`configs/economics/jovannah.json`, 17:40 UTC, loss tolerance $150); her CTR priors are not yet, and
are put to the owner when L4 is reached. G7 exception for the internal page: D42. The "Not shown"
line: yes. Keys file: `/Users/atma1/.secrets/keys.env`, loaded at run time. Jovannah's conversion
event: set by the integrator from her account, logged, provisional until the first signup.

## 8. Settled by the integrator

Standard library server and SQLite; no new dependency. Page rendered per request; the store the
only state. Names and objective from the insights call. Builders on Opus, two at a time (L1 with
L2, then L3 with L4); facts pack F2b and reviews on Sonnet; 250,000 tokens per agent.
