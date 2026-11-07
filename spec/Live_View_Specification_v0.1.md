# Live view: hourly feed and internal dashboard. Specification v0.1

Written 2026-11-07 by Claude (integrator) from the owner's rulings of the same day. Build under
`/Users/atma1/gh_all/system_instructions/7_Build Protocol.md`. Extends spec v0.3; nothing in v0.3
is changed except where §3 says so, and each such change is a decision row.

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

Four pieces behind one skeleton:

| Piece | What | Module |
|---|---|---|
| L0 | Skeleton: package, contracts, store schema, config key, registry, launchd files, CLI wiring (integrator, one hand) | `live/` |
| L1 | Connector widening: names, objective, the client's conversion event, account spend fields (Meta) | `data_contract/connectors/meta.py`, `core/records.py` (skeleton), `registries/channels.yaml` (skeleton) |
| L2 | Store and poll: one read per hour per client into SQLite, append-only, with the ledger and pruning | `live/store.py`, `live/poll.py` |
| L3 | View and server: the page, rendered from the store on each request, served on localhost | `live/view.py`, `live/serve.py`, `live/templates/` |
| L4 | Engine refresh: after each poll, a delivery-class comparison when the client's approvals exist, else a recorded skip | `live/refresh.py` |

What it is not: no client-facing page, no writes to Meta, no new probability theory, no new
dependency beyond the standard library and what `pyproject.toml` already lists (httpx, jinja2,
pydantic, pyyaml). SQLite is the standard library's `sqlite3`, already the run record's store
(v0.3 §1).

## 2. Layout and conventions

```
src/bayesian_marketing/live/
  __init__.py          §1 docstring; exports Store, poll, render, serve, refresh
  contracts.py         L0: pydantic records below, Protocols for Store and Clock
  store.py             L2
  poll.py              L2
  prune.py             L2
  refresh.py           L4
  view.py              L3
  serve.py             L3
  templates/live.html  L3 (Jinja2)
registries/live.yaml   L0: interval_seconds 3600, lookback_days 7, stale_after_seconds 7200,
                       port 8765, bind 127.0.0.1, recordings_keep_days 7, version, freshness_date
configs/<client>.yaml  gains conversion_event (§3.2)
data/live/             gitignored: live.sqlite, recordings/<client_id>/<poll_id>/
scripts/live/          com.atma.bayes.live_poll.plist, com.atma.bayes.live_view.plist,
                       install.sh, uninstall.sh
tests/acceptance/test_L1.py .. test_L4.py   frozen before builders
tests/unit/l1 .. l4                         builders' own
```

Dependency rule (v0.3 §1) holds: `live/` sits beside `atmaos/` at the top of the tree and imports
`core`, `data_contract`, `pipeline`, `floors`, `reporting`'s phrasing loader; nothing imports
`live/`. HTTP stays in `data_contract/connectors/`. `serve.py` uses `http.server` from the standard
library, binds to the loopback address only, and sends no request anywhere.

Timestamps UTC ISO-8601 (v0.3 §3). Ids: `poll_<sha8>`, `lv_<sha8>` for a refresh. Money as
`Money` inside, text on the page. The clock is injected (`Clock` protocol, `now() -> datetime`) so
tests fix time.

## 3. Changes to v0.3 objects (skeleton, decision rows)

### 3.1 `PerformanceRow` is unchanged. The Meta connector fills what D34 left open

`INSIGHT_FIELDS` gains `account_name`, `campaign_name`, `adset_name`, `ad_name`, `objective`
(the campaign objective as the API states it). They fill `entity_names` and `objective` through
the existing `PERF_TARGETS` names (`entity_ids.*_name`, `objective`), exactly as Google Ads does
(D34 manifest). Facts pack F2 must confirm each field name on `act_<id>/insights` at `level=ad`
before L1 starts; a field the pack cannot verify is left out and the omission recorded.

Consequence: the recorded insights URL changes, so `data/recordings/meta_empty/` is re-recorded
(integrator, from a window with no data on the first client's account) before the frozen tests
run. D34's open question 2 closes with this.

### 3.2 The client's conversion event

```python
class ClientConfig(Frozen):                  # core/records.py, one field added
    ...
    conversion_event: dict[Platform, str] = {}   # platform -> action_type, e.g. {"meta": "lead"}
```

The Meta connector's `purchase_type` becomes `conversion_type(elements, wanted: str | None)`: when
the config names an event, that `action_type` is the one copied to `conversions_reported` and
`revenue_reported` (value 0 when the API reports none for it); when it names none, the purchase
preference order of v0.3 applies unchanged. The pull note says which event was used and whether
it was found in the pull. The event name itself (`lead`, `offsite_conversion.fb_pixel_lead`,
`omni_purchase`, ...) is a fact: F2 confirms the strings Meta returns for a pixel Lead before L1
starts; the first client's own account is the check (F2 open question 6).

D33 holds: a lead objective is counted and shown, never valued. `compare` on `cvr`/`cpa` for a
lead-event client still raises `NotInScope` until the lead-to-cash model exists. The live view
shows counts and costs per conversion labelled platform-attributed, and says in words that the
engine does not value a lead.

### 3.3 Account fields

`ACCOUNT_FIELDS` gains `amount_spent`, `spend_cap`, `account_status`, `name`. `Fetched` gains
`account: dict[str, str]` carrying them as text; `PlatformPull.notes` is unchanged. The poll stores
them (§5). The spending limit is the one guard the client sets against a mistake; the page shows
it beside spend to date.

### 3.4 Registry

`registries/live.yaml` (schema in L0; loaded through `core.registries` like the others):

```yaml
version: "2026-11-07"
interval_seconds: 3600        # owner, 2026-11-07
lookback_days: 7              # each poll re-reads the last 7 account-local days (§5.2)
stale_after_seconds: 7200     # page banner when the last good poll is older
recordings_keep_days: 7
bind: "127.0.0.1"
port: 8765
```

## 4. Contracts (L0 lays these down; builders fill bodies)

```python
# live/contracts.py
class PollRecord(Frozen):
    poll_id: str; client_id: str; platform: Platform; account_id: str
    started_at: datetime; finished_at: datetime | None
    window: tuple[date, date]                       # account-local dates read
    status: Literal["ok", "error"]; error: str | None
    pull_id: str | None; n_rows: int; n_quarantined: int; empty_account: bool
    timezone: str | None; currency: str | None
    account: dict[str, str]                          # §3.3 fields as text
    recording_dir: str | None

class LiveRow(Frozen):                               # one PerformanceRow as stored
    poll_id: str; client_id: str; platform: Platform
    entity_ids: dict[str, str]; entity_names: dict[str, str]; objective: str | None
    date: date; impressions: int; clicks: int; spend: Money
    conversions_reported: float | None; conversions_observed: int | None
    revenue_reported: Money | None; attribution_window: str

class RefreshRecord(Frozen):
    refresh_id: str; poll_id: str; client_id: str; at: datetime
    status: Literal["ran", "skipped", "failed"]; reason: str | None
    run_id: str | None                               # pipeline run when status == "ran"

class Store(Protocol):
    def open(path: Path) -> Store                    # creates schema; idempotent
    def begin_poll(self, rec: PollRecord) -> None    # status may be "error" later; one row per poll
    def finish_poll(self, rec: PollRecord, rows: list[LiveRow]) -> None   # one transaction
    def latest_poll(self, client_id: str, *, ok_only: bool = True) -> PollRecord | None
    def rows(self, poll_id: str) -> list[LiveRow]
    def polls(self, client_id: str, *, limit: int) -> list[PollRecord]
    def add_refresh(self, rec: RefreshRecord) -> None
    def latest_refresh(self, client_id: str) -> RefreshRecord | None
    def clients(self) -> list[str]

class Clock(Protocol):
    def now(self) -> datetime                        # UTC, tz-aware

# live/poll.py
def poll(config: ClientConfig, store: Store, clock: Clock, *, platform: Platform = "meta",
         registry: LiveRegistry, record_root: Path | None) -> PollRecord

# live/prune.py
def prune(record_root: Path, clock: Clock, keep_days: int) -> list[Path]   # removed dirs

# live/refresh.py
def refresh(config: ClientConfig, poll_rec: PollRecord, store: Store, clock: Clock,
            *, data_dir: Path) -> RefreshRecord

# live/view.py
def render(store: Store, client_id: str, clock: Clock, *, registry: LiveRegistry,
           phrasing: dict[str, Any], data_dir: Path) -> str                 # HTML
def render_index(store: Store, clock: Clock, *, registry: LiveRegistry) -> str

# live/serve.py
def serve(store_path: Path, *, registry: LiveRegistry, clock: Clock, data_dir: Path) -> None
# routes: GET /  -> render_index; GET /client/<id> -> render; GET /health -> {"ok": true,
# "last_poll": ...}; anything else 404. Loopback only. No query parameters are read.
```

## 5. Pieces

### L2. Store and poll

- C1. **One poll, one read.** `poll` computes the window as the last `lookback_days` account-local
  days ending today (account timezone from the previous poll, else the config's), calls
  `data_contract.connectors.pull.pull(platform, config, window)` with `BAYES_RECORD_DIR` set to
  `<record_root>/<client_id>/<poll_id>` when `record_root` is given, and stores the result. The
  window re-reads recent days on purpose: Meta restates them as late conversions arrive (v0.3
  §5.6), and the newest poll's rows are the truth for the days it covers.
- C2. **Append-only.** Every poll inserts; nothing updates or deletes. A SQLite trigger refuses
  UPDATE and DELETE on `polls` and `rows` (the run record's pattern, v0.3 §1). `latest_poll`
  resolves "current" by `started_at`.
- C3. **Errors are rows.** A connector failure (auth, rate limit, network) becomes a poll with
  `status="error"` and the exception's class and message, secrets redacted by the connector's own
  `redact_url`. The poll never raises past `poll()`; the CLI exits non-zero.
- C4. **Ledger.** The poll's `request.json` and exchange files are the shadow ledger (protocol
  item 12). `prune` removes recording directories older than `recordings_keep_days`; the store
  keeps every row.
- C5. **Idempotence by hour.** A second poll within `interval_seconds` of a good one for the same
  client is still a poll (a new `poll_id`); the CLI prints that it is early. Nothing stops it,
  nothing merges it.
- C6. **Secrets.** The store holds no token, no app secret, no URL with a query string. A test
  greps the SQLite file and every recording for the credential values and `access_token=` with
  anything but `REDACTED`.

Checks: `tests/acceptance/test_L2.py` with the P8 handler fakes (`tests/unit/p8` builds Meta
responses in memory; L0 moves the handler and `_meta_row` into `tests/fakes/meta_api.py`). A poll
over a three-ad, three-day fake stores 9 rows and one ok poll; an auth error stores an error
poll and no rows; UPDATE on `rows` raises; a second poll stores a second set and `latest_poll`
returns it; `prune` removes only directories older than the keep; the secrets grep passes.

### L1. Connector widening

Everything in §3.1 to §3.3. Checks: `tests/acceptance/test_L1.py`: a fake insights element with
names and objective fills `entity_names` with all four keys and `objective`; a config with
`conversion_event={"meta": "lead"}` and elements carrying `lead` and `omni_purchase` actions
gives `conversions_reported` from `lead` and a note naming it; the same elements with no
`conversion_event` give `omni_purchase` (v0.3 order unchanged); an account response with
`spend_cap` and `amount_spent` lands in `Fetched.account`; `data/recordings/meta_empty/` replays
with the new URL and gives `empty_account=True`; `data/recordings/meta_jovannah_7d/` is replaced
by the re-recording of §3.1 (its URL no longer matches) and the P8 replay tests pass.

### L3. View and server

The page is one HTML document per client, rendered on each request from the latest good poll.
No JavaScript is required to read it; a `<meta http-equiv="refresh">` of 300 seconds keeps a
browser tab current. Sections, top to bottom:

- C1. **Header.** Client, platform, account name and id, account time zone and currency; last
  good poll time (UTC and account-local) and the next expected one; a banner when the latest poll
  is an error (its message) or the last good one is older than `stale_after_seconds`.
- C2. **Account line.** Spend to date against the account spending limit, both from §3.3, with
  "no limit set" when `spend_cap` is 0 or absent. Account status in words from a small map in
  `live.yaml` (`1` active; others as Meta names them; unknown codes shown as the code).
- C3. **Delivery table.** Campaign, ad set, ad, with name and id; three columns of periods: today
  (account-local), last 7 days, whole window read; in each: impressions, link clicks, spend, CTR,
  CPC. Every number in this table carries the evidence word for `delivery` from
  `registries/phrasing.yaml` (`evidence_plain.delivery`) in the column group header, once.
- C4. **Conversion table.** Same rows; the client's conversion event by name (or "purchases" when
  none is set), count and cost per conversion, under the `platform_attributed` evidence word, and
  the attribution window the API labelled the rows with. When the event is a lead, one sentence
  under the table: the engine counts leads and does not value them (D33), so no revenue, ROAS or
  contribution appears.
- C5. **Information budget.** Per ad: clicks so far against the registry's event floors for a
  rate (`registry_target` from `floors/estimability`, the same numbers the budget note used: about
  17 for marginal, about 68 for estimable) and the same for conversions; a word for each
  (`below floor`, `marginal`, `estimable`) from `phrasing.yaml`'s status labels. These are counts
  against floors, not posteriors; the section says so in its heading.
- C6. **Engine.** When `latest_refresh` for the client has `status="ran"`, the run's quantities
  per ad (from `<data_dir>/runs/<run_id>.json`): estimate interval, status, evidence class in
  words, and the `not_knowable` block when present, through the same `_finding` and
  `_not_knowable` helpers `reporting/render.py` uses, so the words are the report's words. When
  the refresh was skipped, the reason in one sentence (which approval is missing). When none has
  run, "no engine run yet".
- C7. **Honesty rules.** Nothing on the page is computed from a quantity the store does not hold.
  No percentage is shown without its count. No word from `phrasing.yaml`'s `negation_frames` or
  `generic_phrases` is used by the template (test). The watermark for `internal` reports
  (`phrasing.yaml`) appears in the footer: this is the internal view.
- C8. **Server.** `serve` binds `bind:port` from the registry, serves the three routes, logs one
  line per request to stdout (method, path, status, ms), reads no query string, and shuts down
  cleanly on SIGTERM. `/health` returns JSON with the last good poll time per client.

Checks: `tests/acceptance/test_L3.py` renders from a fake store (L0 provides `FakeStore` in
`tests/fakes/live.py`) and asserts: the five section headings; the delivery evidence word appears
once above the delivery table and the platform-attributed word once above the conversion table;
CTR shows beside its click and impression counts; a store with an error poll renders the banner
with the message; a last good poll older than the stale threshold renders the stale banner; a
lead-event client renders the D33 sentence and no ROAS; the engine section renders a quantity from
a fixture run file and the skip sentence from a skipped refresh; the template contains no banned
phrase; `serve` answers `/health` on an ephemeral port in a thread and 404 on `/anything`.

### L4. Engine refresh

- C1. After a good poll, `refresh` builds a `DatasetManifest` for the client from the poll's
  rows (written as a CSV export under `<data_dir>/live/<client_id>/<poll_id>/` in the Meta export
  map's own column names, so `read_export` reads it unchanged) and runs `pipeline.run` for
  `metric="ctr"` over the ads in the latest good poll with the default horizon for CTR
  (impressions), economics and priors from the client's config paths.
- C2. It runs only when the client's economics file exists and is approved and every prior it
  would use is approved (G8, G9 as the pipeline enforces them). Otherwise `status="skipped"` with
  the gate's own reason text. A pipeline exception is `status="failed"` with the exception class
  and message. The refresh never raises past `refresh()`.
- C3. One refresh per poll. The `RefreshRecord` carries the `run_id`; the run snapshot the
  pipeline writes is what the page reads (L3 C6).
- C4. `ctr` only in this version: it is the one delivery-class quantity and needs no conversion
  semantics. `cvr` and `cpa` on a lead-event client are refused by D33 and are not attempted.

Checks: `tests/acceptance/test_L4.py`: a client with approved economics and priors fixture gives
`status="ran"` and a run file with a `ctr` quantity per ad; a missing loss tolerance gives
`skipped` with the G9 text; an unapproved prior gives `skipped` with the G8 text; a pipeline
error gives `failed`; two polls give two refreshes.

### L0. Skeleton (integrator)

Package and contracts above; `registries/live.yaml` and its schema check in `core.registries`;
`ClientConfig.conversion_event`; `Fetched.account`; `tests/fakes/live.py` (`FakeStore`,
`FixedClock`) and `tests/fakes/meta_api.py` (moved from `tests/unit/p8`, which imports it from
there); CLI subcommands in `cli.py`: `live poll --client <id> [--all] [--record]`, `live serve`,
`live prune`, `live refresh --client <id>`; `scripts/live/` with the two launchd files and the
install script (poll: `StartInterval 3600`, `RunAtLoad`; view: `KeepAlive`, `ThrottleInterval 30`;
logs under `data/live/logs/`; the pattern of `~/Library/LaunchAgents/com.atma.edgehunter.*`).
The acceptance tests are then written by an agent that will never build (protocol item 4) and
frozen.

## 6. Smoke run (protocol item 11), integrator

1. `live poll --client jovannah --record` against the live account: one ok poll, rows for the
   five ads in the capped ad set, names present, the lead event named in the note.
2. `live serve` under launchd; `curl 127.0.0.1:8765/health` shows the poll; the client page shows
   the header, the cap line ($1,500), the delivery table with five ads, the lead table, the budget
   section, and "no engine run yet" or the skip sentence.
3. `launchctl list | grep com.atma.bayes` shows both jobs; the poll log shows one line per hour
   after the first two hours.
4. Secrets grep over `data/live/` passes.

## 7. Undecided, for the owner

Each with the default the build takes if unanswered.

1. **Lookback.** Re-read the last 7 account-local days each hour, so late conversions restate.
   Default 7.
2. **Port.** 8765 on the loopback address; the page is `http://127.0.0.1:8765/client/jovannah`.
   Default as stated.
3. **Recording retention.** Keep each hour's redacted exchanges 7 days, rows forever. Default 7.
4. **Stale banner.** After 2 hours without a good poll. Default 2 hours.
5. **Jovannah's approvals.** The engine section stays at "skipped" until her economics file
   (cost $235, price $795, a loss tolerance you set) and the CTR priors are approved by you. The
   page runs without them. Default: skipped until approved.
6. **Name.** "Live view" in code (`live/`), "the live view" in prose. Default as stated.

## 8. Settled by the integrator

- Standard library server and SQLite; no new dependency. Edge Hunter's launchd pattern reused
  (KeepAlive view, interval poll), its code not imported.
- The page is rendered per request, not written to disk; the store is the only state.
- Names and objective come from the insights call, not a second call per entity.
- `meta_empty` is re-recorded; `meta_jovannah_7d` is replaced by the same re-recording session
  (one window with rows, one without). Recordings are never hand-edited.
- No alerts beyond the page banners in this version.
- Builders on Opus, two at a time (L1 with L2, then L3 with L4); facts pack and reviews on
  Sonnet; token budget 250,000 per agent (protocol).
