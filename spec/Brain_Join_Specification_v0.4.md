# Brain join specification, v0.4

26 November 2026, the Bayesian Engineer. Version 0.2 takes the blind review of v0.1 (`spec/reviews/brain_join_blind_01.md`, Sonnet: 2 blocking, 6 major, 2 minor, 14 undecided). Every point is settled in S1 to S14 at the end. None needed the owner, so nothing went to him from this review. Version 0.3 takes the Principal Architect's note on v0.2 (26 Nov, P1 to P6 at the end). This spec covers the engine's side of joining the engine to AtmaOS and to Imani Brooks, the AtmaOS team member who explains the engine's work to the client. It follows spec 42 FR7.2 in the AtmaOS repository and the owner's rulings: D54 here, and D676 and D677 in AtmaOS. Pieces already built are listed so the rest can be read against them. Each piece below that has a status of "to build" has an interface and checks. Nothing in it is built until the blind spec review's undecided list is answered.

## Already built

| What | Where | Status |
|---|---|---|
| Account notebook, format bayes-notebook-1.0.0 | `spec/notebook_format.md`, `scripts/notebook_release.py` | Built. Releases 1 and 2 for Jovannah are imported on live by the Head Engineer's `atmaos/scripts/bayes_notebook_import.py`. |
| Full-history export for Arkwright | `scripts/export_history.py` (commit f225a15) | Built. Arkwright's intake spec is `atmaos/spec/inflow/bayesian_export_intake.md`. |

## J1. The canonical row form bayes-rows-c1 (the pointer rule)

This is the form a Bayesian posterior claim's pointer is checked under. The pointer was agreed on 26 Nov by the Arkwright Engineer and the Principal Architect, with the Head Engineer copied. A claim's evidence names `row_keys`, `rows_form` "bayes-rows-c1" and `rows_sha256` into the stored polls file. The file named is the first stored one that holds those keys. The Brain's resolver keeps its own copy of this rule, and the Head Engineer enters it in spec 42's registry of representation names when that registry is built.

The rule is exact:

1. A row is a JSON object as it appears in `polls.jsonl`. It has exactly the keys the export writes: `key`, `restates`, `describes`, `known_at`, `timezone`, `poll_id`, `platform`, `account`, `campaign`, `ad_set`, `ad`, `names`, `link_clicks`, `impressions`, `spend_amount`, `spend_currency`, `conversions_reported`, `conversions_observed`, `revenue_amount`, `revenue_currency`, `attribution_window` and `objective`.
2. Values are as stored. Integers are written bare, and amounts are the decimal strings Meta gives, such as `"12.34"`. `conversions_reported` is a JSON number as stored. Nulls are `null`. Dates and times are ISO 8601 text as stored.
3. Each row is serialised with keys sorted by Unicode code point, separators `,` and `:` with no spaces, UTF-8 output, and non-ASCII characters left as they are (no `\u` escapes). This is Python's `json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.
4. Rows are ordered by `key`, by Unicode code point, ascending. Each serialised row is followed by one line feed (0x0A).
5. `rows_sha256` is the lowercase hex SHA-256 of those bytes concatenated. An empty set hashes the empty string.
6. `names` in a row are the names as they stood in the poll that first saw that version. A rename alone is not a new version, because versions are cut on figures only (`MEASURES` in the export), so a stored key's names never change. A rename shows in the change history, and in the next version's names when a figure next changes (P6).
7. Keys are `meta:<ad id>:<YYYY-MM-DD>:v<n>`. `n` starts at 1 and goes up by one each time a poll's figures for that ad and day differ from the previous version's, taken over the full history in poll order. A figure set that changes and then returns is a new version, not the earlier one again (S36). A stored key never changes content, and a changed figure is a new key, `v<n+1>`. Arkwright's intake refuses any export that breaks this, at receive.

The reference implementation is `rows_sha256()` in `scripts/export_history.py`.

Checks: (a) a fixture of three rows with known bytes gives a stated hash, and the test holds that hash. (b) The hash doesn't depend on the order the rows are given in. (c) Changing any one value in any row changes the hash. (d) Two exports of the same store give identical `polls.jsonl` and identical `rows_sha256` for every run. (e) A row with a non-ASCII ad name hashes over its UTF-8 bytes, not over `\u` escapes. (g) In a fixture store, an ad is renamed between two polls with its figures unchanged: both exports give the same key, the same names (the first poll's) and the same `rows_sha256`.

## J2. Row hashes in the engine's own run record (to build)

Today a live run's `dataset_hashes` is empty, and its manifest id hashes the client and the poll id, not the content. After J2 the live refresh puts the bayes-rows-c1 hash of the rows the run read into `RunRecord.dataset_hashes` and `RunSnapshot.dataset_hashes`, as `"bayes-rows-c1:<hex>"`. The run file, the export's `runs.jsonl` and the stored copy then all name the same digest.

The `manifest_id` stays as it is. It feeds the seed and the run id (`pipeline.py`, `_seed` and `make_id("run_", ...)`), so changing it would change every result. The engine computes the rows' bayes-rows-c1 form from `LiveRow`s by the same rule and key numbering as the export. For this, the version numbering moves from the export script into one function in `live/` that both call.

`RunSnapshot` gains `row_keys: list[str]` (default empty, so older snapshots still load) and `rows_form: str | None`. The refresh fills both. `pipeline.execute` gains a keyword `extra_dataset_hashes: list[str] = ()`, which is added to the sorted file hashes. The live refresh passes `["bayes-rows-c1:<hex>"]`, and every other caller passes nothing and is unchanged. `observation_evidence` hashes `dataset_hashes` into `dataset_snapshot_hash`, so for new live runs that value now names the content. That is the point of the piece (S3).

`result_of` and `observation_evidence` carry the pointer for each posterior entry: `rows_form`, `rows_sha256` and `row_keys` from the snapshot, beside the run id and quantity id (S2). An old run without them gives `null` and an empty list, never a made-up value.

Interface: `bayesian_marketing.live.rows.versioned(store, client_id) -> (rows: list[dict], seen: dict[poll_id, list[key]], reads: list[dict])` and `bayesian_marketing.live.rows.rows_sha256(rows) -> str`. `export_history.py` imports them in place of its own copies, and `reads.jsonl` comes from the third value (S14).

Checks: (a) for every run in the live store after J2, `dataset_hashes` holds exactly one `bayes-rows-c1:` entry, equal to that run's `rows_sha256` in a fresh export, and the snapshot's `row_keys` equal the export's. (e) `result_of` on a post-J2 run gives each posterior entry the same `rows_sha256` and `row_keys`; on a pre-J2 run it gives `null` and an empty list. (b) Runs made before J2 are not rewritten. Their `dataset_hashes` stay empty, and the export still gives their `rows_sha256`. (c) The seed and run id of a refresh on a fixed poll are unchanged by J2. (d) The whole existing test suite passes.

## J3. Hand-off markers (to build)

These are the Head Engineer's shape of 26 Nov. A marker is one small JSON file in `$BAYES_DATA_DIR/markers/`, written to a temporary name and then renamed, so a reader never sees a half-written file. There are two kinds:

| Kind | File | Fields |
|---|---|---|
| `engine_run` | `run_<run_id>.json` | `kind`, `client_id`, `run_id`, `snapshot_path` (absolute), `snapshot_sha256` (of the run file's bytes), `rows_form`, `rows_sha256`, `row_keys`, `written_at` (UTC) |
| `notebook_release` | `nb_<release_id>.json` | `kind`, `client_id`, `release_id`, `release_path` (absolute), `release_hash`, `written_at` |

The refresh writes an `engine_run` marker as its last step after a run is saved. `write_release` writes a `notebook_release` marker after its own verify passes. The engine never reads, moves or deletes markers. AtmaOS's job reads them and is idempotent on `run_id` or `release_id`. A failed refresh writes no marker. The folder is `pipeline.data_dir() / "markers"` at the time of writing, which is the folder the live job's `BAYES_DATA_DIR` names. The AtmaOS job copies the snapshot into the artifact store and checks `snapshot_sha256`, as FR7.2 says. The engine never removes or rewrites a run file: `runs/` has no pruning, and the snapshot writer refuses an existing path. So the file is there whenever the job runs. The AtmaOS job may move a marker it has finished into `markers/done/`. The engine never looks there (S12).

A run with no marker can be left by a crash between the run file and the marker. `scripts/markers_backfill.py` writes the missing markers: for every run file with no marker in either folder, it writes one, by the same rule, and is idempotent. It runs once at install and can be run any time. Pre-J3 runs get markers the same way, with `rows_sha256` and `row_keys` null when the snapshot has none (S6).

Checks: (a) a refresh that saves a run leaves exactly one marker naming it, and its `snapshot_sha256` matches the file. (b) A refresh that is skipped or fails leaves none, tested on a fixture store after J3, not on pre-J3 runs. (e) `markers_backfill.py` on a folder with three runs and one marker writes exactly two, and a second run writes none. (c) A marker never exists without its run file. In the test, the write is interrupted before the rename and no marker is left. (d) A new release leaves a marker whose `release_hash` equals `verify()`'s.

## J4. check_client_figures (to build)

This is the check Imani runs on a sentence before she says it to the client. It is separate from `check_narrative`, which stays as it is for reports apart from the bug fix in J5.

Signature: `bayesian_marketing.atmaos.socket.check_client_figures(text: str, refs: list[dict]) -> dict`. AtmaOS imports the socket at call time, and the engine never imports atmaos (F7). Both directions use JSON-native dicts.

`refs` lists what the sentence rests on. Each ref is one of these:

| Ref | Fields | What the engine reads |
|---|---|---|
| run | `{"kind": "run", "run_id"}` | The run's snapshot file. |
| notebook entry | `{"kind": "notebook_entry", "release_id", "entry_id"}` | The entry in `notebook/<client>/releases/<release_id>/entries.jsonl`, after `verify()` passes on the release. |
| claim | `{"kind": "claim", "claim_id", "engine_item": {...}}` | `engine_item` is the engine pointer the AtmaOS claim's evidence holds: for a notebook claim `{"release_id", "entry_id"}`, for a posterior claim `{"run_id", "quantity_id"}`. The figure is checked against that quantity only. The rows pointer is the resolver's to check, not this call's (S5). The engine checks against its own files and echoes the claim id back. AtmaOS resolves a claim id to its engine item, because the engine can't read the Brain. |

Reading the sentence:

1. **Figures.** Every number in the text is a figure, except dates, times of day, years, and run, release and entry ids. That covers percentages, money (with `$` or a currency code), plain counts and ratios. A figure written in a form the reader can't parse fails, with the reason "figure in a form the checker cannot read". Quantities in words count as figures too: spelled numbers ("three dollars", "twelve sign-ups"), fractions ("a third", "half", "a quarter"), multiples and changes ("doubled", "twice as many", "tripled", "halved") and proportions ("most of", "nearly all", "the bulk of"). A spelled number is read as its numeral and placed like any other. A fraction, multiple, change or proportion fails with "a quantity in words the checker cannot place; state the figure", unless the same sentence also gives the figures it rests on and each of them is placed (P1).
2. **Subjects.** An ad is named by its id or its name. Names are read from the run's entity names or the notebook source objects. Matching ignores case, and treats an en dash, hyphen and spaces in a name as equal. An ad set or campaign is named the same way, and "the account" names the account.
3. **Metric words.** The existing aliases apply, plus lead vocabulary when the client converts on leads. Whether it does is read from the client config named by the ref: a run's `client_id`, or a release catalog's `client_id`. It uses the same rule as `live.refresh._conversion_kind` (S6). Refs naming two clients fail the call. For a notebook quantity, its metric words are its `name` with underscores read as spaces, plus the entry's tags. Its subject is the ad, ad set or campaign named in the entry's statement, or the account when none is. On a lead account, "sign-up", "sign-ups", "lead" and "leads" name the conversion, "cost per sign-up" and "cost per lead" name `cpa`, "sign-up rate" names `cvr`, and the words "order" and "purchase" fail with the reason "this account converts on sign-ups, not orders". "Link clicks", "click rate" and "click-through rate" name `ctr` or the link-click count. "Spend", "spent" and "budget" name money.
4. **Matching.** A figure is placed when one quantity among the refs has the same unit kind (percent, money, count or probability), the same subject if the sentence names one, the same metric if the sentence names one, and a value whose display at the registry's rounding equals the figure. Rounding follows the figure as written. Percent compares at the decimals the figure shows, 0 or 1, and no finer than the registry's `percent_decimals`. Cost-per money compares at `unit_money_decimals` (2). Other money compares at 2 decimals when the figure shows cents and at the registry's `money_decimals` (0) when it doesn't (S9). Counts compare whole. A probability reads either as a percent at 0 or 1 decimals, the way a person says it ("a 62% chance"), or as a decimal at `probability_decimals` (S8). An estimated quantity is placed by its q50 or mean. Its q05 or q95 places only when the sentence marks it as a bound: both ends are given ("between 4.0% and 4.7%", "4.0% to 4.7%"), or a bound word stands with it ("at least", "as low as", "at most", "as high as", "no more than", "no less than", "up to"). A lone q05 or q95 spoken as the value fails, with `should_read` the median (P2). When more than one quantity in the refs fits a figure and the sentence doesn't name enough to tell them apart, the figure fails with the reason "fits more than one figure in the refs; name the ad or the measure" and lists the candidates (S10).
5. **Status.** A figure placed on an `estimable` quantity passes. One placed on a `marginal` quantity passes only if the sentence also says that it is still an estimate. The required phrase is the registry's `caveat_marginal` or one of a new registry list, `caveat_marginal_aliases` ("still rough", "a rough estimate", "still an estimate"), anywhere in the same sentence, since a clause split must not cut it off. The list goes in `registries/phrasing.yaml` in the skeleton, and `check_narrative` doesn't read it (S7). A figure placed on a `below_floor` quantity fails, with the reason that the quantity is "not knowable yet" and the registry's `not_knowable` wording. An observed notebook quantity has no status and passes when placed.
6. **Unplaced.** A figure no ref places fails, with the reason "not found in the refs given; if it is derived (a difference, a total, a change), ask the engine for that quantity rather than rewording" (P5). It never passes silently. When a quantity of the same unit, subject and metric exists but its value differs, the result gives that quantity's value as `should_read`.
7. **Currency of the ref.** For a run ref, the result says whether it is the client's newest saved run and gives the run's window end and saved time. For a notebook ref, it says whether the release is the newest for the client. A sentence resting on a ref that is not the newest passes only if it carries a date or "as of"; otherwise every figure in it fails with "the ref is not the newest; date the figure or use the newest" (P3).
8. **Comparatives and causal words.** These are checked as `check_narrative` checks them, against the refs' comparison, if a run ref carries one.

Return:

```json
{
  "passed": false,
  "figures": [
    {"text": "4.4%", "placed": true, "ref": {"kind": "claim", "claim_id": "..."},
     "quantity": {"name": "ctr", "subject": "120253899504590526", "status": "marginal"},
     "value_at_rounding": "4.4%", "should_read": null,
     "caveat_required": true, "caveat_present": true, "reasons": []},
    {"text": "$1,600", "placed": false, "ref": {"kind": "notebook_entry", "...": "..."},
     "quantity": {"name": "account_spending_limit", "subject": "account", "status": null},
     "value_at_rounding": "$1,500", "should_read": "$1,500",
     "caveat_required": false, "caveat_present": false, "reasons": ["$1,600: the ref gives $1,500"]}
  ],
  "refs": [{"ref": {"kind": "run", "run_id": "..."}, "newest": true, "window_end": "2026-11-26", "saved_at": "..."}],
  "reasons": ["$1,600: the ref gives $1,500"],
  "engine_version": "bayesian-marketing ...",
  "inputs_hash": "<sha256 over text and refs>",
  "checked_at": "<UTC ISO 8601>"
}
```

`value_at_rounding` is the matched quantity's value at the rounding the figure was compared at, given whenever a quantity is matched. `should_read` is the same value, given only when the figure differs from it. Both are `null` when nothing matched (S7 of the review).

`passed` is true only if every figure is placed and passes and no sentence-level reason exists. A text with no figures passes with an empty `figures` list. A ref that can't be read (a missing run, a release that fails `verify()`, an unknown entry) makes the call fail with a reason naming the ref. It doesn't raise. Only a wrong argument type raises.

Where it runs: the check reads the engine's files on this machine, so it works only while Imani's turn runs here. To make running it against the Brain's stored copies cheap later, the loaders are parameters: `check_client_figures(text, refs, *, load_run=None, load_release=None)`, defaulting to the engine's own file loaders (P4).

What the caller does with a failure is the Head Engineer's to build: repair from `should_read`, or drop the figure, a bounded number of tries, and never send failing text. This call only reports.

Checks are the acceptance tests, frozen before the build. Each runs against fixture runs and a fixture notebook release, never the live store:
(a) "IMG3_TXT1 had a click-through rate of 4.4%, but it is still a rough estimate." with a run ref passes when IMG3's ctr is marginal at 4.4%.
(b) The same sentence without the caveat fails, naming the caveat.
(c) "Cost per sign-up for IMG3_TXT1 was $3.35, a rough estimate." passes on a lead account. "Cost per order" in the same sentence fails, naming sign-ups.
(d) "The account spending limit is $1,500." passes with a notebook entry ref holding that quantity, and fails with only a run ref.
(e) "The account spending limit is $1,600." with a ref holding a $1,500 account spending limit fails, with `should_read` "$1,500".
(f) A figure on a below_floor quantity fails, saying "not knowable yet".
(g) A claim ref whose engine item points at a notebook entry is checked exactly like that entry, and its claim id is echoed.
(h) A text with a date ("26 November"), a run id and no figures passes.
(i) An unreadable ref fails, naming it, and doesn't raise.
(j) Ad names with an en dash ("IMG2_TXT1 – Updated.") match with a hyphen or spaces.
(k) "A 62% chance" and "a 0.62 chance" both place on a p_best of 0.621.
(l) "$1,500" with refs holding both a $1,500 spending limit and a $1,500 lifetime budget, and no words naming either, fails as fitting more than one figure and lists both.
(m) Refs from two clients fail the call.
(n) "About three dollars a sign-up" places as $3 against a cpa whose median rounds to $3, and fails otherwise. "Sign-ups doubled" and "a third of the budget" fail as quantities in words, unless the figures they rest on are in the sentence and placed.
(o) "The click rate is 4.7%" fails when 4.7% is the q95 and the median is 4.4%, with `should_read` "4.4%". "Between 4.0% and 4.7%" and "as high as 4.7%" pass.
(p) A figure from a run that is not the client's newest fails in the present tense, and passes with "as of 20 November" or a date in the sentence. The same holds for a notebook entry in a superseded release.
(q) "$200 more than last week" fails, and its reason names a derived figure.

## J5. The lead path in check_narrative (to build, a fix)

On a lead account, `check_narrative` labels `cpa` "cost per order" and rounds it to whole dollars. That made it refuse a correct "$3.35" on 26 Nov. The fix: `claims/vocab.py` gains a lead table, `METRIC_LABELS_LEAD` and `METRIC_ALIASES_LEAD`, the purchase tables with `cpa` as "cost per sign-up" (aliases "cost per sign-up", "cost per lead", "cost per conversion", "cpa") and `cvr` as "sign-up rate". A function `labels(conversion_kind)` returns the right pair. Every place that reads `METRIC_LABELS` for a run reads `labels(run's conversion_kind)` instead: `pipeline.py` line 855, `cli.py` lines 188 to 208, `reporting/render.py` lines 123, 154 and 323, and `claims/check.py` lines 556 and 570. A lead report then says sign-ups everywhere. A purchase run reads the existing tables and is unchanged byte for byte, its rounding included. On a lead run, cost-per money displays and is checked at `unit_money_decimals` (S11, S15). When a lead `check_narrative` refuses a figure worded with a purchase word, its reason names the word and says the account converts on sign-ups.

Checks: (a) on a lead fixture run, "This estimate is still rough: ad <id> had a cost per sign-up of $3.35." passes when the cpa q50 is 3.35. (b) The same text on a purchase fixture run with "cost per order" behaves exactly as before. (d) A purchase report renders byte for byte as before J5, and a lead report never prints "order". (c) The whole existing test suite passes.

## J6. read_test_design (to build, its own spec)

The Arkwright Engineer's request of 11 Nov (`atmaos/spec/suggestions/request_to_bayesian_engine.md`), with the call signature restated on 26 Nov, is specified separately, because it is a design-time power reading and not part of the join. It is listed here so the join's spec reviewer sees it was not forgotten. The state of a live test is a separate call from `read_test_design`.

## Order and estimates

The order is J5, then J4 (J4 reuses J5's lead vocabulary), then J2 and J3. Each is one piece. By how long pieces of this size took here (L10 and L11, each a module with its tests merged within a working session), J5 is about an hour, J4 a few hours including its acceptance set, and J2 with J3 a couple of hours, each plus a blind review on a different model. The record for a checker piece is thin: G5 itself was the only one, and it took longer than its estimate.

## What this spec leaves to others

The registry of representation names is the Head Engineer's, and it holds bayes-rows-c1 by the rule in J1. The AtmaOS job that reads markers, the caller of `result_of` and `observation_evidence`, and Imani's turn are the Head Engineer's too. Arkwright's intake and its add-only check at receive are the Arkwright Engineer's. Widening the poll's re-read from 7 to 28 days is the owner's call, put to him on 26 Nov.

## Settled after the blind review of v0.1

S1 (review gap 1, undecided 1). The rows a registered result cites are kept: the live store is append-only and refuses UPDATE and DELETE on its rows (`live/store.py`, the `_no_update` and `_no_delete` triggers). Only raw recordings are pruned, and those are not the evidence. The run's own `row_keys` are now kept in its snapshot (J2), not just rebuilt at export. Check: J2 (a), plus an existing store test that a DELETE on `rows` raises.

S2 (gap 3). The posterior entry carries its pointer through `result_of` and `observation_evidence` (J2). A run-level hash alone wouldn't give a claim its pointer.

S3 (undecided 3). `dataset_hashes` takes the row hash through the new `extra_dataset_hashes` argument, not through a manifest file entry, which would be a fiction. Changing `dataset_snapshot_hash` for new live runs is intended. The Head Engineer is told with this spec.

S4 (gap 4, 5; undecided 4). The resolver recomputes from the rows themselves. It takes the rows whose `key` is in `row_keys` from any stored polls file, parses each line as JSON, re-serialises it under J1, and compares the hash. Nested objects such as `names` serialise by the same rule, keys sorted at every level, which is what `json.dumps(sort_keys=True)` does. A stored file satisfies the pointer when its rows under those keys hash to `rows_sha256`. "First stored" is only the file the claim names for convenience: the earliest one the intake received holding all the keys, recorded by the intake. Any matching file is as good. J1 check (f), added: a second implementation written from J1's text alone (the test writer's, not the reference function) gives the same hash on the fixture.

S5 (undecided 5). A posterior claim ref is checked on its quantity only. The pointer is the resolver's.

S6 (gap 6, 8; undecided 6). Markers are backfilled by `scripts/markers_backfill.py`. The lead question is read from the client config named by the refs.

S7 (gap 7; undecided 7). The return carries `value_at_rounding` whenever a quantity matched, and `should_read` only on a mismatch. Caveat aliases go in the registry, not in code.

S8 (undecided 8). A probability reads as a percent or a decimal.

S9 (undecided 9). Money compares at the precision the figure is written in, within the registry's rules.

S10 (undecided 10). Ambiguity fails, listing the candidates.

S11 (undecided 11). The lead labels are a second table chosen per run, used everywhere a label is read.

S12 (undecided 12). Markers live under `data_dir()` at write time. AtmaOS may move finished ones to `markers/done/`, and the engine never deletes them.

S13 (undecided 13). Checked: the run id is `make_id("run_", {"manifest": manifest.manifest_id, ...})` at `pipeline.py` lines 1081 to 1088, and the seed comes from `manifest_id` at line 904.

S14 (undecided 14). `versioned` returns the reads as a third value.

Review gap 9 (ad status as a data point, D54) belongs to the live-test state call beside J6, not to the join, and is recorded as a follow-up. Gap 10 needs no change.

## The Principal Architect's note on v0.2 (26 Nov)

P1. Quantities in words are figures (J4 point 1, check n).
P2. A bound spoken as the value fails (J4 point 4, check o).
P3. A stale ref must be dated (J4 point 7, check p).
P4. The loaders are parameters, so the check can later run against the Brain's copies. The limit is recorded under J4.
P5. A derived figure fails, and its reason says so, so the caller asks for the quantity (check q). The caller's repair rule is the Head Engineer's.
P6. Names in a hashed row are as of the version's first poll, and a rename is not a new version (J1 point 6, check g). This was already the export's behaviour. Now it is stated and tested.

On when an hourly run is a new version of a posterior claim (the Principal Architect's to settle under spec 42 FR3.2): his starting rule fits this series, with one change from what the series shows. When two ads are close, the leader by p_best can flip between hourly runs on a handful of clicks. A leader change should count only when the new leader's p_best is at least 0.5, or the change has held for a full account-local day. Otherwise a 24-a-day series makes a version on every flip.

S15 (the J5 test writer). "Cost-per money at `unit_money_decimals` on both" would have changed purchase rounding, which contradicts "byte for byte unchanged". The finer rounding applies to lead runs only.

## Settled after the J4 test writer (26 Nov)

S16. Names. A snapshot holds no entity names today. J4 adds `RunSnapshot.entity_names` (id to name for ads, ad sets and campaigns, as the pull read them; empty on older snapshots), and the refresh fills it. For a snapshot without names, the check reads names from the notebook source objects among the refs, then from a third loader, `load_names(client_id) -> dict[str, str]`. Its default reads the live store read-only, taking the newest name per id. A name maps to one id. A name that maps to two ids is treated as unnamed.
S17. Money precision follows the figure for every money kind, cost-per included: "$3" or "three dollars" compares at whole dollars and places on 3.35, while "$3.35" compares at cents. On a lead run, the 2-decimal display (J5) is what `should_read` and `value_at_rounding` give for cost-per.
S18. An estimated notebook quantity is treated as marginal: it needs the caveat. An observed one needs none.
S19. `R_UNREADABLE_FORM` covers a numeral the reader can't parse to one value: two decimal points ("3.3.5"), a decimal comma ("4,4%"), exponent form ("1e3"), or a scaled form ("$3k", "1.2M"). Each fails with that reason.
S20. Comparatives and causal words. With a run ref, `check_narrative`'s comparative and causal checks run on the sentence against that run's bundle, and their reasons are added as sentence-level reasons. With no run ref, a comparative or causal word whose subject is an ad fails with "a comparison needs a run ref".
S21. Newest. For a run, it's the latest `started_at` in the run record among that client's saved runs (ties broken by run id). For a release, it's the client's release with the greatest (day, n) in its id. A release named as some other release's parent is never newest.
S22. Generic money words ("spend", "spent", "budget", "cost") don't name a measure. A measure is named only by a metric alias, or by a notebook quantity's name words or its entry's tags.
S23 (the J4 test writer, second pass). (1) `value_at_rounding` is the matched quantity's value as the engine displays it for that run's kind: cents for cost-per on a lead run, the registry's rounding otherwise. It is not the precision the figure was compared at. So "$3" placed on a 3.35 cpa gives "$3.35". (2) For runs with the same `started_at`, the greater run id is newest. (3) The newest release is the greatest (day, n) among the client's releases that no other release names as its parent. (4) Under S20, only `check_narrative`'s comparative and causal reasons are added, never its number reasons, which would refuse a numeric ad id as a figure.

## J4R. Rendered figures (v0.4, in place of J4's free-text reading)

Why: two blind reviews of J4 on Sonnet found 12 and then 14 false passes of wrong figures (`tests/review/test_J4_review.py`; `tests/review/test_J4_review2.py` on review2/J4 b3e71c9). Each came from inferring, out of free prose, which number means which quantity of which ad. The Bayesian Engineer proposed this design on 26 Nov. The Head Engineer supports it, and the Principal Architect advises it under seven conditions (C1 to C7 below), all taken. The engine writes every figure, and the persona's own words carry none. The free-text `check_client_figures` is not merged, and the socket's stub keeps raising until J4R passes review.

### Slots

A slot is a Brain contract: a figure is a claim quantity in the Core (`claims`, `claim_quantities`), rendered by its producer's renderer (C2). The engine owns the renderer for Bayesian claims only. AtmaOS resolves a Core claim id to its engine item before it calls the engine, which never reads the Brain (F7). It passes the claim id along for the echo.

```
slot      := "{" kind ":" ref [ "|" form ] "}"
kind      := "fig" | "cmp" | "name" | "date"
ref       := "run/" run_id "/" quantity_id [ "#" claim_id ]          ; a posterior quantity
           | "nb/" release_id "/" entry_id "/" quantity_name [ "#" claim_id ]
           | "run/" run_id [ "#" claim_id ]                          ; cmp: that run's comparison
           | "ad/" entity_id                                         ; name: a subject's display name
           | iso_date | iso_datetime                                 ; date: passed through untouched
form      := "full" | "start"
```

`date` slots belong to the turn step. The engine leaves them as they are, and AtmaOS renders them after it (C2a). The run and notebook forms are this engine's addresses. Once posterior claims are in the Core, the Core's `{fig:<claim_id>/<quantity_id>}` resolves to them (C2b).

### Forms (C4)

Each `fig` and `cmp` slot has two forms, and the caveat, the floor wording and the "as of" date stay inside both. The labels are J5's: lead labels on a lead account. There is no form that drops the subject (C4).

| Status | `full` | `start` |
|---|---|---|
| estimable | "IMG3_TXT1's click-through rate of 4.4%" | "IMG3_TXT1's click-through rate is 4.4%" |
| marginal | "IMG3_TXT1's click-through rate of about 4.4%, still a rough estimate" | "IMG3_TXT1's click-through rate is about 4.4%, still a rough estimate" |
| below floor | "IMG3_TXT1's click-through rate, which is not knowable yet" | "IMG3_TXT1's click-through rate is not knowable yet" |
| observed (notebook) | "the account spending limit of $1,500" | "The account spending limit is $1,500" |
| not newest | the same, followed by ", as of 20 November" | the same |

`cmp` renders from the run's own comparison record, never from two figures (C5):
- full: "IMG3_TXT1, which leads on clicks with a 62% chance of being best", plus the caveat when the decision is marginal or the leader's p_best is under 0.5;
- below floor: "which ad is best, not knowable yet".

`name` renders the display name.

### The calls

`socket.client_slots(client_id: str, *, load_run=None, load_release=None, load_names=None) -> dict` is the menu (C3). It lists every slot this engine can render for the client's newest run and newest notebook release: each slot's ref, kind, the measure, the subject, status, newest, both forms rendered, and the run id or release id behind it. AtmaOS maps them to claim ids, hands the menu to the persona before she writes, and refuses any slot not on it.

`socket.render_client_text(text: str, *, load_run=None, load_release=None, load_names=None) -> dict` renders. It returns `ok`, `text`, `template` (the input, unchanged), `slots` (one row per slot: its token, `ok`, `rendered`, ref, claim id, run id or release id, quantity, status, newest, reasons), `reasons`, `lint` (comparative-word hits; see below), `engine_version`, `inputs_hash` and `checked_at`. `ok` is true only when every slot renders and the numeral rule passes. When `ok` is false, `text` is null, and the caller never sends a partial rendering. AtmaOS's ledger keeps both the template and the rendered text, with each slot's claim id and run id (C6).

### The numeral rule (the guarantee)

After every slot is removed, the text must contain none of the following:
- any character of Unicode category Nd, No or Nl (digits in every script, fraction glyphs, numeric letters);
- any word in `QUANTITY_WORDS`, an explicit, frozen list: zero to twenty, the tens, hundred, thousand, million, billion, half, halves, third, quarter, dozen, couple, few, several, handful, score, most, majority, minority, double, doubled, triple, tripled, twice, thrice, single, sole, and every one with -fold, -ly, -s and -th forms where English has them, plus "a pair of", "a number of" and "the bulk of";
- any of `%`, `‰`, `％`, `٪`, "percent", "per cent", "pct", "percentage", "basis point";
- any currency sign (Unicode category Sc), or any ISO 4217 code as a whole word.

A hit fails the call and quotes the word. Bare counts like "two ads" are forbidden; she can say "both ads" (C2). "Both", "each", "all", "every", "none", "either" and "neither" stay allowed. The guarantee covers this rule only.

### The comparative lint (not the guarantee)

A sentence that names an ad (by a `name` slot or a known name) and holds a word from the registry's comparative or causal lexicon, outside a `cmp` slot, is listed in `lint`. It also fails the call. This is a fixed word list, not a reader. It will miss phrasings, and the spec does not claim more for it (C1).

### Checks (frozen before the build)

Kept from J4: (f) below floor, (i) unreadable refs, (m) two clients, (p) staleness, P4 loaders, S16 names, S21 newest, and the J5 lead labels, each expressed as slot rendering. New checks:
- Every case in both J4 review files, re-expressed as the free text the persona might write, fails the numeral rule (C7).
- Every word in `QUANTITY_WORDS` fails.
- 50 characters sampled across Nd, No and Nl in several scripts each fail.
- Each status, in each form, renders its phrase.
- `ok` false gives `text` null.
- `client_slots` lists only the client's newest run and release, and every slot it lists renders.
- An unknown slot ref fails.
- `date` slots pass through untouched.
- "both ads" passes, and "two ads" fails.
- `cmp` renders from the comparison record, and a test proves no subtraction happens.

The code for loading refs, staleness, names and labels comes over from the unmerged J4 branch (piece/J4 at 3ebcd01).

### Accepted by the Principal Architect (26 Nov), with six additions (A1 to A6) frozen into the checks

A1. `render_client_text(text, client_id, ...)` takes the client. Any ref that doesn't belong to that client fails the call (`R_OTHER_CLIENT`). The wall doesn't rest on AtmaOS's menu check alone. Check: a template whose refs all belong to another client fails.
A2. After the slots are removed, any "{" or "}" left fails (`R_BRACE`). A `date` slot's ref is validated as a strict ISO 8601 date or datetime even though the engine doesn't render it, and anything else fails (`R_BAD_DATE`). Checks: a malformed slot fails, "{date:next week}" fails, and "{date:2026-11-26}" passes through untouched.
A3. Matching for the numeral rule: normalise to NFKC, casefold, strip Unicode category Cf, then match whole words with whitespace, hyphens and slashes as word breaks. Checks: "twenty-five", "two-thirds", and "two" with a zero-width joiner inside each fail.
A4. "None", "no", "all" and "every" state a quantity, zero or the whole. They stay allowed because she can't speak without them, and they sit outside the guarantee. The lint fails a sentence where one of them shares the sentence with a measure word (clicks, link clicks, sign-ups, leads, spend, impressions, and every J5 label and alias), with `R_ZERO_OR_ALL`. "No sign-ups yet" is a figure: where it is true, it is a slot, a count of zero rendered by the engine. Checks: "no sign-ups yet" fails, and "none of this changes your plan" passes.
A5. The "#claim_id" on a ref is attached by AtmaOS from its own mapping after the persona writes. A claim id in her template is overwritten (the Head Engineer's). `cmp` `start` form: "IMG3_TXT1 leads on clicks, with a 62% chance of being best", with the caveat or floor wording as in `full`.
A6. `QUANTITY_WORDS` stays as it is. "Only one sign-up" is a figure and must fail. The list goes into the persona's instructions (the Head Engineer's), and every refusal's reason names its word, so the words that cost retries can be counted after her acceptance turns. Check: each refusal's reason contains the word it refused.

### Settled after the J4R test writer (26 Nov)

S24. (1) "order of magnitude" joins `QUANTITY_PHRASES`, because C7 requires review 2's case to fail. Adding to the list only refuses more, so A6's freeze holds. (2) The category check (Nd, No, Nl, Sc) runs on the raw text, before NFKC, so Ⅻ and ⅰ fail. Word matching runs after NFKC, casefold and Cf stripping. (3) ISO 4217 codes match case-sensitively in upper case only, so "all", "try", "top" and "cup" stay ordinary words. (4) On a lead account, "leads" next to an ad's name is linted, even where it's a count. A false fail costs a rewording, and the lint is not the guarantee. (5) The word forms the test writer listed (`tests/acceptance/j4r_fixtures.WORD_FORMS`) are the floor for `quantity_word_forms()`. (6) `SlotOut.token` is the slot exactly as written, braces included. `ref` is the ref part, without form or claim id. The cmp caveat is joined as ", still a rough estimate".

### Settled after the J4R blind review (26 Nov, review/J4R 1e39675: 22 findings, 12 blocking)

S25. The numeral rule changes from a deny list alone to an allow list of characters plus the deny list. Both only refuse more.
(1) Characters. After the slots are removed, every character must be one of: ASCII letters; Latin letters U+00C0 to U+017F, except × (U+00D7) and ÷ (U+00F7); the space and the line feed; and the punctuation `. , ; : ! ? ' " ( ) - / &` plus `’ ‘ “ ” – — …`. Any other character fails, with "a character outside the allowed set", naming its code point. This covers invisible characters of every category, homoglyphs from other scripts, small capitals, emoji, private-use characters, controls and lone surrogates. It replaces the Nd/No/Nl/Sc check, which it contains. The A3 normalisation still runs on the word check. Cf characters are now refused as characters, never stripped.
(2) Roman numerals. A token of two or more letters that is a valid Roman numeral in either case (`^M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$`) fails. "I" alone is a word.
(3) Words joined into one. A token that splits wholly into two or more number words ("fiftyfive", "twentyone", "onehundred") fails.
(4) The word list gains:
- nought, naught, nil, once, dual, duo, trio, quartet, pair, pairs;
- the ordinals first to twentieth, plus hundredth, thousandth and millionth (with "second" in);
- trillion, quadrillion, zillion, jillion, gazillion, bazillion, umpteen, lakh, crore;
- the numbers zero to twenty, hundred and thousand in Spanish, French, German, Italian and Portuguese, less the common English words they collide with ("due", "seize", "elf", "un", "une", "una", "sept", "dos" stays in).
The list stays strict. The refusal log is what shows later which words cost retries.
(5) Rendering rounds half up (decimal ROUND_HALF_UP) everywhere: percent, money and counts. A probability that would show as 100% renders "more than 99%", and one that would show as 0% renders "less than 1%".
(6) Notebook units are a closed set:
- an ISO 4217 code, rendered with its sign where one exists and otherwise the code after the value;
- "count";
- "ratio" or "probability", which are fractions;
- "percent", where the value is already in percent;
- "days".
Any other unit fails the slot ("unit not renderable").
(7) A notebook quantity's subject is never read from the statement. The notebook format goes to bayes-notebook-1.1.0, which adds an optional `subject` to a quantity: `{"level": "account" | "campaign" | "ad_set" | "ad", "id": ...}`. Without it, the subject is the account. The renderer names the campaign, ad set or ad the subject gives.
(8) A notebook ref's conversion kind comes from the client's newest run when one exists, otherwise from the config. When neither can be read, it is "lead" if any of the client's runs says lead. If nothing can be read at all, the slot fails rather than guess the label.
(9) A display name that holds a brace, a percent sign, a currency sign, a spelled quantity word or a character outside the allowed set fails its slot, wherever it is rendered ("a name that states a figure"). Digits in a name, such as "IMG3_TXT1", are allowed only inside rendered slots, never in free text.
(10) A run's client is read from the whole file, not its head. A file whose head and body name different clients fails as unreadable.
(11) The lint's sentence splitter doesn't split after "e.g.", "i.e.", "etc." or "vs.".
(12) A zero-width or other Cf character is refused under (1), so it can't join two words into one.

### The threat model, and S26 (the Principal Architect, 27 Nov)

Threat model. The writer is Imani, composing in good faith from a menu of rendered figures, under instructions that say figures go in slots. The failure J4R guards against is an honest one: she types a figure she half remembers, or attaches a figure to the wrong ad. Honest figures come as digits or as correctly spelled words. The guarantee is exact on character classes (the allow list of S25 (1)). On words it is list-based, with folding, and it guards an honest writer, not an evasive one. Spellings made to get past a filter ("séven", "t.e.n", "sevn") are out of scope for blind review. Reviews hunt faults on honest input, and above all wrong renderings by our own code. The residue is caught where it can be seen: every template is in AtmaOS's ledger, and the refusal log counts what the rule stops. The after-acceptance check reads the sent templates for any quantity that got through outside a slot. If one does on honest writing, that word goes on the list with a test.

The recorded next step, if the count ever shows a pattern: a word allow list. Outside slots, every token must be a dictionary word or an inflection of one, with every quantity word removed and a registry list of modern and platform words added. It was proposed on 27 Nov after review2/J4R (c198467), with the examples "Xii", "fiftypercent", "twodozen", "séven", "nİne", "X.I.I", "t.e.n", "lOO" and "fiftyish". It was not adopted, because a Webster list holds quantity words of its own, so it would be a deny list again, and because it would cost retries on ordinary speech, which matters more.

S26. (1) Same slot, same text: a slot renders byte for byte the same whatever else is in the text. (2) The folds before the word check:
- NFKD, dropping combining marks;
- casefold, with İ and ı mapped to i;
- removing single separators (".", "-", "'", space) between single letters inside a run, so that "t.e.n" becomes "ten";
- glued forms, meaning a listed word preceded or followed by another listed word or by "percent", "ish", "something" or "fold".
Stop there. (3) The plain-letter Roman numeral check is dropped, because "I", "mix", "did", "civil" and "vivid" are made of Roman letters. Unicode numeral glyphs (category Nl) are refused by the character allow list. Review cases that expected "XII", "IV", "MMXXVI", "vii", "Xii" or "X.I.I" to fail now expect them to pass, and each such edit is recorded. (4) S25 (7)'s default "without it, the subject is the account" is withdrawn. A quantity with no subject fails its slot.

S27 (after review3/J4R b45930d, briefed with the threat model; 10 blocking, 4 major, 5 minor).
(1) Inside slots, per-unit money (cpa, cpc, cpm, contribution per click, and any notebook money under 100) renders at cents, whatever the account's kind. A nonzero value that would display as zero renders "less than <smallest step>".
(2) The word list gains halve, halfway, quadruple, quintuple, treble, twin, dollar, buck, penny, cent, quid and grand, with their forms.
(3) A4 gains the measure verbs (click, convert, sign up, buy), "not … any" anywhere in the sentence, and nobody, neither, whole, entire, everything and "all of".
(4) "An" before a vowel-sound figure. A name's trailing punctuation is dropped mid-sentence.
(5) cmp with the top two p_best within 0.05, or a leader under 0.5, renders "neither ad leads yet on <unit>, still a rough estimate".
(6) Duplicate quantity names in one notebook entry are refused on write and verify, and fail the slot.
(7) CR, tab and no-break spaces are normalised to LF or space before the character check. Slack's formatting marks (* _ ~ ` • >) and U+2011 are allowed.
(8) Display names fail only on a brace, a percent sign or word, a currency sign or ISO code, or a control character or line feed. S25 (9)'s quantity-word rule for names and the digit rules of the second review are withdrawn: names are the client's own data, not the persona's writing.
(9) An out-of-range value or malformed quantities fail the slot, and never raise.
The false fails on listed words and on the lint stand, and the refusal log counts them.

## Settled before the J2 and J3 build (27 Nov)

These close what the J2 and J3 text left open once the code was read. None needs the owner.

S28. `versioned(store, client_id)` reads through the `live.contracts.Store` contract (`polls(client_id, limit=...)` and `rows(poll_id)`), so the refresh, the export and the test fakes share one implementation. Only polls with status `ok` count. Row values are written in the stored text forms, as `live/store.py` writes them: amounts as `str(Decimal)`, dates as ISO text, `known_at` as the poll's `started_at.isoformat()`, `conversions_reported` as a float when not null (the column is REAL), ids and names as the dicts stored. Rows are taken in the order the export's query used: ad id, date, poll `started_at`, poll id. Check J2 (f): on a fixture SQLite store holding a rename, a restated figure, a confirmed version and a non-ASCII name, `versioned` gives byte-identical polls rows, `seen` and reads to the export's `polls()` as it stood at commit e983942, copied into the test as the oracle.

S29. The rows' `timezone` is the one distinct non-null `timezone` among the client's ok polls. Two or more raise `ValueError`. None gives `null`. The export keeps its own refusal when there is none.

S30. If `versioned` raises inside a refresh, the refresh fails (status `failed`, no run, no marker). No live run is made without its pointer.

S31. `pipeline.execute` gains three keywords: `extra_dataset_hashes: Sequence[str] = ()`, `row_keys: Sequence[str] = ()` and `rows_form: str | None = None`. `dataset_hashes` becomes `sorted([*file hashes, *extra_dataset_hashes])` on both the run record and the snapshot. `row_keys` (sorted) and `rows_form` are stored on the snapshot as given and change nothing else.

S32. Every posterior entry from `result_of`, below-floor entries included, gains `rows_form`, `rows_sha256` and `row_keys`. `rows_sha256` is the hex after `bayes-rows-c1:` in the snapshot's `dataset_hashes`, or `null` when there is none. `EVIDENCE_KEYS` doesn't change: the pointer reaches `observation_evidence` inside `result`.

S33. Markers. The JSON is canonical (keys sorted, no spaces, UTF-8) with one trailing line feed. `written_at` is UTC ISO 8601 to the second. The temporary file is `.<name>.tmp` in the same folder, moved into place with `os.replace`. A marker that already exists for the same run or release, in `markers/` or `markers/done/`, is left untouched and the write returns its path. `snapshot_path` is absolute and resolved, `snapshot_sha256` is over the file's bytes as on disk, and `client_id` is the snapshot's. When the snapshot has no `rows_form`, the marker's `rows_form`, `rows_sha256` and `row_keys` are all `null`.

S34. A marker write that fails after the run file is saved leaves the refresh `ran`, with reason `marker not written: <type>: <message>`, and the backfill writes it later. `write_release` raises if its marker can't be written; the release folder stays, and the backfill writes the marker.

S35. `scripts/markers_backfill.py` covers both kinds: every run file in `data_dir()/runs` and every release folder under the notebook root (`BAYES_NOTEBOOK_DIR`, or the repository's `notebook/`) whose `verify()` passes. A release that fails `verify()` gets no marker and is named on the standard error stream. It prints the count written per kind.

S36 (the J2 and J3 test writer, 27 Nov). (1) J1 point 7 now says what the export does: a new version whenever the figures differ from the previous version's, so a set that returns is a new key. (2) Marker files are named `<run_id>.json` and `<release_id>.json`. The ids already carry their `run_` and `nb_` prefixes, so the J3 table's `run_<run_id>` would double them. A reader that globs `run_*.json` and `nb_*.json` finds both. (3) The marker folder is `pipeline.data_dir()` at the time of the write. The refresh writes inside `data_dir_env(data_dir)`, so for a refresh that is its `data_dir` argument. (4) When S29 gives a null time zone, each read's `after_close` is null.

S37 (the J2 and J3 blind review, 27 Nov, review/J2J3 6a43ee9: nothing blocking, one minor finding, two recorded). A run file the backfill cannot read (not JSON, or no `client_id`) is named on the standard error stream and gets no marker, the same as a release that fails `verify()`; the runs after it are still marked. Recorded without change: a client whose ok polls come to hold two time zones stops running until someone looks (S29, S30, by intent), and a notebook release written without `BAYES_DATA_DIR` set puts its marker under `data/generated/markers`, so a release for a live client is written with `BAYES_DATA_DIR` pointed at the live engine folder.

## J4R.2. Ads that share a name (to build, 27 Nov; v2 after the blind spec review)

Jo's account reuses creative names across ad sets. In the newest run, VID1_TXT1 names two ads (the main ad set's video and the creative test's), and "IMG2_TXT1 – Updated." names three, once paused copies are counted. S16 leaves a name that points to two ids unnamed, so a slot can't name the wrong ad, and a slot that can't name its subject fails (S25). The result is that four of the run's seven ads, and every creative-test figure, are missing from Imani's menu. J4R.2 names those ads by their ad set. Nothing changes for a name that points to one id in every layer.

### The rule

1. Bare names. For each id, its bare name is the name given by the highest layer that names it, in S16's order: the newest run's snapshot, then the client's releases' sources, then the store. `merge_names` still runs as now. Its output is the starting set of final names.
2. Candidates. Group every id named in any layer by `norm_name` of its bare name. Every member of a group with two or more ids is a candidate, including an id that `merge_names` kept bare. A candidate is removed from the final names. Example: the snapshot names ads A and B "V" (both blocked by S16), and the store alone names ad C "V" (kept bare by `merge_names` today). A, B and C are all candidates.
3. Parent. A candidate qualifies only if it is an ad (not typed `ad_set` or `campaign` in the slot's types map) and its ad set is known. The parent comes from the first of these layers that knows it: the newest run's snapshot `entity_parents`; the `content.adset_id` of a `meta_object` source with `ref.object_type` "ad", reading the client's releases newest first; and a new loader `load_parents(client_id) -> dict[str, str]` (ad id to ad set id). The loader's default reads the live store read-only, taking the newest row per ad (`entity_ids_json`'s `ad_set`). It is injectable like the other loaders. A layer that raises is skipped, and its reason goes in `reasons`. A parent id typed `ad` or `campaign` is refused.
4. Ad set display name. It is the client's `display_names[<ad set id>]` when that is set. Otherwise it is the ad set's final name after steps 1 and 2 (so an ad set whose name is shared with any other id has none), provided that name passes the display-name rule: no brace, no percent sign or word, no currency sign, word or code, and no control character or line feed, which is the rule labels are held to in format 1.2.0. Otherwise there is none.
5. The qualified name is `<bare> (<ad set display name>)`. Each part first loses any trailing run of whitespace and `. ! ? , ; :`. An example is "IMG2_TXT1 – Updated (IMG2 test)". The parenthesis is what carries the subject. The possessive the existing forms add ("VID1_TXT1 (Creative Test)'s click-through rate"), and any a writer types after a name slot, attaches to the whole name, which is the ad. No form changes. Fig (run and notebook), name and cmp slots all render the qualified name wherever they would render a name, by the S25 to S27 rules as they stand.
6. Uniqueness, all at once. After step 5, group every final name (bare names of non-candidates at every level, and the qualified names) by `norm_name` of the rendered string. Every candidate in a group of two or more stays unnamed. Order of evaluation never decides. A candidate with no parent or no display name also stays unnamed.
7. The qualified names go into `_Names.names` like any name, so the lint's `name_words` includes them and a free-text mention counts as naming an ad.

### Configuration and snapshot

8. `ClientConfig` gains `display_names: dict[str, str] = {}`, platform id to display name. Keys must be quoted strings in YAML. A value failing the display-name rule fails the load with a message naming the key. The check uses the same function `notebook/release.py` uses, imported lazily, the way release.py does. Jovannah's config adds `"120253899504550526": "the main ad set"`.
9. Slots read it through a fourth injectable loader, `load_display_names(client_id) -> dict[str, str]`. Its default resolves the client (the `atmaos_client_id` alias included) and loads the config. If it raises, nothing is qualified (every candidate stays unnamed) and the reason goes in `reasons`. It never falls back to the Meta name. An alias whose id is typed `ad` or `campaign` is ignored, with a reason.
10. `RunSnapshot` gains `entity_parents: dict[str, str] = {}` (ad id to ad set id as the pull read them, empty on older snapshots). The refresh fills it from the poll rows, newest day winning, as it fills `entity_names`. `execute` gains `entity_parents: dict[str, str] | None = None`, stored as given. No run id, seed or config hash moves.

### Checks

(a) The live shape: a fixture holding the newest run's seven ads, their ad sets and the paused copy. All seven appear as name items on the menu. The four shared-name ones render as "VID1_TXT1 (the main ad set)", "VID1_TXT1 (Creative Test)", "IMG2_TXT1 – Updated (the main ad set)" and "IMG2_TXT1 – Updated (IMG2 test)". Each name item's subject is the ad id.
(b) A name that points to one id in every layer renders exactly as before. Every J4R and J5 test passes, and any test changed because its fixture held a shared name is listed and amended on the record.
(c) Two ads with one name in one ad set both stay unnamed, whatever the iteration order.
(d) An ad set whose Meta name fails the rule and has no alias leaves its shared-name ads unnamed. An alias wins over a passing Meta name, and the Meta name is used when there is no alias.
(e) A `display_names` value that fails the rule fails `load_client` with the key named. At the slots end a failing `load_display_names` qualifies nothing and adds a reason.
(f) The A/B/C case in step 2: all three are candidates and are qualified by their own ad sets.
(g) For each pair of parent layers that disagree, the higher wins. A raising layer is skipped with a reason.
(h) An ad set shared by name with a campaign or another ad set gives its ads no display name.
(i) Trailing punctuation: "V." and "V" in one ad set render the same after stripping, so both stay unnamed.
(j) No rendered form of a qualified subject has "'s" directly after the ad set's name. The possessive follows the closing parenthesis. This holds for run figs, notebook figs and cmp.
(k) A digit in an ad set name, such as "Test 2", renders, since names may hold digits (S27 (8)), and the numeral rule reads only the template.
(l) The comparative lint fires on a qualified-name slot as it does on a name slot.
(m) The refresh stores `entity_parents`, and a refresh on a fixed poll keeps its run id and seed.

S38 (the J4R.2 test writer, 27 Nov, tests bf1dcc7). (1) Rule 2 groups by `norm_name` of the bare name as it stands, so "V." and "V", held by one id each, aren't candidates and stay bare. Check (i) applies when both are candidates for another reason, as the tests build it. (2) A reason from `load_parents` or `load_display_names` goes in the menu's `reasons` only, never in a render's. A render whose slot names a candidate left unnamed fails as any unnamed subject does, so a flaky store or config can't refuse a text that has no shared names. (3) A parent that a layer types `ad` or `campaign` is refused for that layer, and the next layer is tried. (4) A candidate with no type in the types map counts as an ad. (5) Only the candidates in a colliding group stay unnamed; a non-candidate whose bare name equals a qualified name keeps its name, and the candidate goes unnamed.

## J7. Held status, the route on each figure, and the account's time zone (to build, 27 Nov)

The Head Engineer's dry run of the posterior caller over Jo's 448 runs, and the count that followed, found 139 status changes between consecutive runs. 105 of them came with a change of model route. In most of those, the joint NUTS model failed G3 on a single divergence (12 of the 196 runs with eight or more ads) and fell back to the per-ad conjugate model. That model is capped at marginal by §7.5. The rest came from the ad count crossing `min_ads_for_coupling`, or from a real crossing of the precision line. Imani renders the status from the newest run, so without damping she would call a figure rough one hour, plain the next, and not knowable the hour after. The Principal Architect's advice, accepted here, is to fix this at the source (his messages of 27 Nov). J8 deals with the sampler side.

### The held status

1. Status order: `below_floor` < `marginal` < `estimable`. A quantity's identity across runs is (ad id, quantity name). Its raw status is `feasibility.status` as stored. A posterior entry with no quantity (below floor) has raw status `below_floor`.
2. `held_status(run_id) -> dict[(ad id, quantity name), status]` is a pure function of the run and the client's runs that started before it. Runs are ordered by the run record's `started_at`, with ties broken by run id as S21 does. The same run always gets the same answer, however many runs come after it. The function needs nothing the engine doesn't already keep, so it gives the held status for every run ever saved, including the 448 from before J7.
3. The rule, applied per quantity in run order. At the quantity's first appearance, held equals raw. After that, a raw status below the held one sets held to raw at once. A raw status above the held one raises held to the highest level L for which every run of the quantity since a time T has had raw at least L, where T is at or before this run's start minus one calendar day in the account's time zone. One calendar day means the same local clock time on the previous date, so a daylight-saving day still counts as one day. A run where the quantity is absent neither breaks the streak nor extends it, and held carries over.
4. The account's time zone is the run's `timezone` (below). A run saved before J7 has none, so the zone is taken from the store's poll for that run (the refreshes table's `poll_id`, then `poll_outcomes.timezone`), and failing that from the one zone among the client's ok polls (S29). If no zone can be found, `held_status` raises, and `result_of` gives `held_status: null` with the reason, so no made-up value is ever given.
5. Where it shows. Each posterior entry from `result_of` gains `held_status` beside its raw `status`. The slot renderer reads the held status wherever it reads a status today, in the forms and in the menu's `status`, and the menu gains `status_raw`. The run record and the snapshot keep the raw status untouched. Nothing is dropped.
6. Cost. `held_status` on the newest run, over the live store's 448 runs, returns in under two seconds on this machine. The builder may keep a cache under `data_dir()`, but a cache entry must be what the function computes, and a test must hold that.

### The route on each figure

7. (Renamed by S39 (9): the field is `fit_route`, with `try`, and the existing `route` string stays.) Each posterior entry gains `fit_route: {"kind", "step", "try"}`. `kind` is the snapshot's `route.kind`. `step` is the fit step that produced the state (`conjugate`, `nuts_full`, `nuts_static`, `nuts_unpooled` or `fallback_conjugate`), read from `configuration["fit_step"]`. Each engine_run marker gains the same object. A marker for a pre-J7 run (the backfill) reads it from the snapshot, which already holds both.

### The time zone

8. `RunSnapshot` gains `timezone: str | None = None`: the IANA name Meta reports, from the pull the run read, null on older snapshots. Each engine_run marker gains `timezone` from the snapshot. The engine never rewrites a marker, so the 448 already written stay as they are, and the caller passes America/New_York for those (agreed with the Head Engineer).

### No allocation on the menu

9. `client_slots` lists no slot for a recommendation, an allocation or a budget share, and `render_client_text` refuses any ref to one. The allocation keeps a 10% floor for ads that can no longer spend, so the result is known to be wrong. This holds until read_test_design (J6) has landed and that floor is gone (the Principal Architect's ruling).

### Checks

(a) On a fixture series, a quantity going marginal, then estimable for 23 hours, then marginal again is never held estimable. The same series with 25 hours of estimable is held estimable from the run that completes the day. (b) A drop shows at once. (c) A run gets the same held status whether or not later runs exist. (d) The DST day: a streak across the autumn change in America/New_York counts by local clock time. (e) A pre-J7 snapshot with no `timezone` gets its zone from the store, and with no zone anywhere gives `held_status: null` and a reason. (f) `result_of` carries `held_status` and `route` on every posterior entry, the below-floor ones included. (g) The renderer's forms and the menu's `status` follow the held status, and `status_raw` the raw one. (h) The menu has no recommendation, allocation or share slot, and `render_client_text` refuses a made-up ref to one. (i) Markers carry `timezone` and `fit_route`. A backfilled marker for a pre-J7 run carries `timezone: null` and its `fit_route`. (j) The live store copy: `held_status` on the newest run takes under two seconds, and over the 448 runs the held status changes fewer times than the raw status's 139 (the count is reported, not asserted). (k) Run ids, seeds and config hashes are unchanged.

## J8. The joint model's retry, recorded (to build after J7)

10. In `inference/fallback.py`, a NUTS step whose G3 fails on divergences alone is retried up to twice before the chain moves to the next step. Each retry uses a seed drawn deterministically from the run's seed and the try number. The try that is accepted must pass G3 with `divergences_max` still 0, so the gate is never loosened. A step that fails G3 for any other reason moves on as now.
11. Every try is recorded on the run: step, try number, seed, divergence count, and whether it passed. They go in a new snapshot field, `fit_attempts`, and as one notice per retried step. Every G3-failed state is still quarantined as now. Nothing about a retry is dropped.
12. A run whose first try passes is byte-identical in its quantities to what it would have been before J8, so its run id, seed and results don't move.
13. Not in this piece, but recorded: whether the twelve divergent fits share a cause, such as an ad with few clicks or a funnel between the group scale and an ad's effect, that a non-centred parameterisation or a higher `target_accept` would remove. The Bayesian Engineer looks at that once J8 has recorded the tries on live.

Checks: (a) a step that diverges on its first try and passes on the second is accepted with zero divergences, and both tries are recorded. (b) A step that diverges three times moves to the next step, with all three recorded. (c) A G3 failure on R-hat or ESS isn't retried. (d) A first-try pass is unchanged (pinned run id and quantities). (e) The retry seeds are the same on every run of the same inputs.

## Settled after the J7 and J8 blind spec review (27 Nov)

The review found 3 blocking items, 9 major and 3 minor. Its read-only simulation over copies of Jo's 448 runs found that held is never above raw under either reading of J7 (3), and that the two readings of "since a time T" differ in 15 cells. Each point is settled below, and these settlements govern where J7 or J8 says otherwise.

S39 (J7).
1. The rise rule is the streak reading. Take the quantity's present runs (see 3), in order, up to and including this one. Held rises to level L only when this run's raw is at least L, and so is every present run back to a run R that started at or before this run's start minus one calendar day, in local time (J7 (3)). Two consecutive present runs more than one calendar day apart break the streak, and it restarts at the later one. A rise never lowers held.
2. First appearance. A quantity's held status starts at `below_floor`, so any first status above that waits a day like every other rise. This replaces J7 (3)'s "held equals raw".
3. Presence. A quantity is absent from a run when its subject is not in that run, meaning the ad is not among `variants` for an ad-level quantity. When the subject is present but the quantity isn't (the name is listed in `not_estimable`, or there is no quantity of that name), the raw status is `below_floor` for that name. This applies to every quantity name, not only the metric. An absent quantity has no entry in that run's held status, so nothing is carried over into a run it isn't in.
4. Identity: (level, subject id, quantity name, conversion kind, metric). A change of conversion kind or metric starts a new series. A change of window length or segments doesn't.
5. The comparison. The decision status (`snap.decision.status`, which `cmp` reads) is held by the same rule, with identity ("decision", conversion kind, metric). Non-ad quantities use their own level and id.
6. Signature: `held_status(run_id, *, timezone: str | None = None) -> dict`. The zone is the explicit argument, else the snapshot's `timezone`, else the store's poll for that run (`refreshes` to `poll_outcomes`), else the one zone among the client's ok polls. If two zones are found, it raises, as S29 does. A run with no refresh (CLI or replay) falls through to the last step.
7. The runs counted are the run-record entries with a saved run file in the same `data_dir()`, the same `client_id` and `synthetic` false. "Before" means a smaller `(started_at, run_id)`. If the run record can't be read, the run has no `started_at`, or a run file in the series can't be read, it raises. A record entry with no file is skipped.
8. In `result_of`, the new fields are `held_status` and, when that is null, `held_status_reason`. That happens when `held_status` raises, or when the snapshot's run isn't in the run record (an unsaved snapshot). When held is below raw, `status_reasons` gains "held at <held> until <raw> has held for a day".
9. The new route field is `fit_route: {"kind", "step", "try"}`, on each posterior entry (the below-floor ones too) and on each engine_run marker. The existing `route` string stays exactly as it is. `kind` is the snapshot's `route.kind`. `step` is `configuration["fit_step"]`, or null when that is missing. `try` is the accepted try number from J8's `fit_attempts`, or null before J8.
10. The renderer gets an injectable loader, `load_held(run_id) -> dict`, which defaults to `held_status`. If it raises or gives null, every fig and cmp slot of that run fails with that reason. It never falls back to raw. `claims/check.py` stays on raw, which is safe because held is never above raw.
11. The marker's `timezone` is `PlatformPull.timezone` of the pull the run read. The engine never reads old markers (S12, S33).
12. No cache. Loading the 448 snapshots took 0.08 s.
13. J7 (9)'s made-up ref: a fig ref whose quantity id names a recommendation id, or is a quantity id not in the run, is refused.
14. Checks added to J7: a gap of more than one day; a lower run 24 hours and 1 minute back; a streak mixing estimable and marginal, which gives marginal; a record entry with no file; an unreadable record; a tie in `started_at`; an ad in variants without the quantity, against an ad not in variants; two zones; spring-forward and fall-back; a change of conversion kind; a quantity absent for days; cmp and non-ad slots; renderer refusal when held is null. Check (j) asserts that the held status changes no more often than the raw status and reports both counts. The review's simulation gave ctr 24 held changes against 135 raw.

S40 (J8).
1. "Divergences alone" means the report's `n_divergences` is a number above `divergences_max` and every other G3 check passes. `g3` or its caller exposes that as a field, never by matching the reason text. When `n_divergences` is null, the fit isn't retried.
2. Try 1 uses exactly the run's seed, so a first-try pass is identical in state id, report ids and quantities. Try n (2 or 3) uses `int(inputs_hash({"seed": seed, "step": step, "try": n})[:8], 16)`. If that equals the run's seed or an earlier try's seed, it is salted with an extra counter until it doesn't.
3. `fit_with_fallback` returns the attempts as a fourth value, and `fit()` takes the step and try from the accepted attempt rather than the last notice. A first-try pass records one attempt. A conjugate-route run records an empty list, which is also the default for old snapshots. Every failed try is quarantined.
4. The run record's `seeds` gains `fit_accepted` only when a retry is accepted, and `fit` stays the run's seed.
5. Cost: the worst case is nine NUTS fits instead of three. Check (d) pins the clock, because a run id hashes `started_at`.
6. Checks added to J8: a divergence with an R-hat or PPC failure isn't retried; divergences on every try of every step reach the conjugate fallback with all nine tries recorded and quarantined; a null `n_divergences` isn't retried.
7. A retry accepted at zero divergences can let a state that would have fallen back reach `estimable`. It carries its try number in `fit_route.try`, so Imani's renderer and any reviewer can see it. Whether the twelve share a cause stays mine to look at once the tries are on live (J8 (13)).

S41 (the J7 test writer, 27 Nov, tests 7541947). (1) J7 (7) and check (i) now read `fit_route`, as S39 (9) settled. (2) `tests/acceptance/test_J3.py::_assert_run_marker` asserts J3's exact marker fields. J7 adds `timezone` and `fit_route`, so the builder amends that helper to J3's fields plus those two and nothing else. The change is recorded here and in the build log, as J4R.2 (b) did for its tests. (3) A present ad's quantity names are the names among this run's quantities for that ad, plus its `not_estimable` names. A name the series held earlier that is neither of those is raw `below_floor` (S39 (3)). (4) `held_status` finds the live store the way `default_load_names` does (`_refs._live_store_path`: `BAYES_LIVE_DIR`, then the folders above `data_dir()`). (5) Held carries across runs where the quantity is absent, but an absent run has no entry of its own, and a rise can't cross a gap of more than a day. Runs exactly one calendar day apart keep the streak. (6) The two-zone raise belongs only to the last step of S39 (6). A zone found earlier ends the search. (7) Check (j) doesn't pin the run count (there are 449 now). The test writer's reference gave 141 raw changes against 32 held, and for ctr 135 against 25.

S42 (the J7 blind review, 27 Nov, review/J7 75de8bb: one major finding, one minor). F1: a run saved before J5 has no `conversion_kind`, and the renderer's R9 rule reads all of a client's runs, later ones included. Used in a held key, a later lead run could change an earlier run's keys and held values. The series now takes an unstated kind from the client config, else from the latest earlier run that stated one, else "purchase", and never from a later run. A caller finds a run's entry with `held.lookup`, which matches every part of the key but the kind, so the renderer and `result_of` don't need to repeat the rule. Recorded: editing a client's `conversion_event` re-reads every unstated run under the new kind, which is right, since the config says what a conversion is. The minor finding (the test helper `raw_held` keeps the last of two duplicate keys where `held_status` keeps the lower) changes no result, because the J4R fixtures hold no duplicates.

S43 (the Principal Architect, 27 Nov, after M1's first reading). The partial day. A run's window ends today, and today is still filling in. That does little harm to a rate, because both parts of the rate are partial together. It does matter for a count or a spend said over a period that includes today. Run slots today render only rates (click-through rate, sign-up rate, cost per sign-up) and the comparison. Notebook counts carry their own dated labels, such as "21 November to midday on 27 November". So no slot words a count over today. The rule, for any count or spend slot over a run's window that is ever added: its words say the period ends "so far today", or it stops at the last closed day. If the partial day is ever found to move an estimate, that goes to the owner.

S44 (the J8 test writer, 27 Nov, tests d205ffa). (1) The fourth return value of `fit_with_fallback` (S40 (3)) breaks four tests that unpack three values: `tests/acceptance/test_P6.py` lines 99 and 119, `tests/unit/p6/test_p6_units.py` line 92 and `tests/unit/p6/test_p6_review.py` line 125. The builder amends them to unpack four, on the record, and changes nothing else in them. (2) A retry that raises counts as a failed try: it is recorded with `passed` false and `divergences` null, and the step moves on, as a raising try 1 does now. (3) A retry that fails G3 for any reason other than divergences alone isn't retried again, and the step moves on. (4) "An earlier try's seed" in S40 (2) means any earlier try in the run, not only the same step's. (5) A failed try's report stays in the reports, and so its failed G3 stays in `gate_results` beside the accepted try's pass. That's how a fallback to a later step already reads today, so anyone reading the gates reads the last G3 as the one that counted.

## J9. Every measure in result_of (to build, 27 Nov)

The Principal Architect's reading of the Head Engineer's backfill found that `result_of` carries one measure per ad. Its `posterior` holds the run's metric only, which on all 455 of Jo's runs is ctr, and `uncertainty.intervals` holds only `compare_quantity`. The engine estimates each ad's sign-up rate (cvr) and cost per sign-up (cpa) on every run and keeps them in the snapshot, so the caller had no key to claim them by. That is an engine gap against D54. The shape below is the one the Head Engineer agreed (27 Nov).

1. `result_of` gains a top-level key `quantities`: `{variant: {name: entry}}`. Every variant in `s.variants` has a key, and nothing else does.
2. A variant's names are the names among this run's quantities for its ad, plus its `not_estimable` names, plus the run's metric name (`metric_quantity(s.metric)`), so the metric is always there. Inner keys are sorted.
3. Each entry is exactly what `_posterior_entry` gives for that variant and name, with the same fields: held fields, pointer, notices and `fit_route`. A quantity present in the run gives its estimate. A name that is only in `not_estimable` gives `quantity_id` null, status `below_floor` and its reason as the notice. The metric name with neither gives the reason "not estimable", as `posterior` does now.
4. `posterior` and the rest of `result_of` are unchanged, byte for byte. For every variant, `quantities[v][metric_quantity(s.metric)]` equals `posterior[v]` except for `unit`, `label` and `attribution_window` (6, 9, 10).
5. A name is the caller's stable id for a measure, beside client and ad. A name never changes meaning. If a measure is ever redefined, it gets a new name and the old one is never reused.
6. Each entry in `quantities` carries `unit`: `{"numerator", "denominator", "currency"}`. ctr is link_click per impression, currency null. cvr is the run's conversion kind (`lead` or `purchase`) per link_click, currency null. cpa is money per the conversion kind, in `s.currency`. aov is money per the conversion kind, roas is money per money, and contribution_per_click is money per link_click, each in `s.currency`. Rates are fractions, never percent. Money is in the currency's major unit (dollars, not cents). A name the table doesn't list gets `unit` null, so a future name never raises.
7. It reads the snapshot alone, so every saved run, old ones included, gives `quantities`. A run saved before D33 that holds contribution_per_click for a lead gives it like any other quantity. Nothing is dropped.
8. A quantity whose ad isn't among `variants`, or with no ad in its scope, can't be keyed by variant. None exists in Jo's 455 runs. If one ever appears it goes in `quantities_unkeyed`, a list of entries in quantity order, so it is still not left out. The key is absent when the list would be empty.

9. Each entry carries `label`, the J5 label as Imani reads it: `claims.vocab.METRIC_LABELS_LEAD` on a lead run and `METRIC_LABELS` otherwise, so Jo's cvr is "sign-up rate" and her cpa is "cost per sign-up". A name with no label gets null. The label is for reading only. The caller keys on the name (5).
10. Each conversion-based entry (cvr, cpa, aov, roas, contribution_per_click) carries `attribution_window`, the code in force at the end of the data for the run's platform, from `s.knowability.attribution_windows`. On Jo's runs that's `1d_view_7d_click_1d_ev`: a sign-up counts within 1 day of a view, 7 days of a click, or 1 day of an engaged view. ctr gets null. When the code changed inside the data window, the run's notices already say so (`WINDOW_CHANGED`), and the entry carries the latest code.
11. A quantity below its floor keeps its estimate in the entry. The engine never leaves out a data point (D54), so `summary` is there, and `status`, `held_status` and `status_reasons` say it isn't knowable yet. The caller claims it as not knowable yet and doesn't quote the value. Only a name with no quantity (3) has `summary` null.
12. How cpa is made, for the caller's links. On the exact per-ad route (273 of Jo's first 457 runs; corrected 27 Nov, see S51), cpa has its own inverse-gamma posterior from the ad's spend and sign-up count. It shares the sign-up count with cvr, but it isn't computed from cvr. On the joint route, cpa is computed from the joint draws as cpm / (1000 · ctr · cvr), so there it does rest on cvr and ctr. The entry's `fit_route.kind` says which route a run took.

Checks: (a) `posterior` is unchanged on pinned runs. (b) `quantities[v][metric]` equals `posterior[v]` without `unit`, `label` and `attribution_window`, on every fixture run. (c) Every ad quantity in the snapshot appears exactly once, under its variant and name, with its `quantity_id`. (d) Every `not_estimable` name appears with its reason and `quantity_id` null. (e) cvr and cpa entries carry the held status that `held.lookup` gives for that name, and `held_status_reason` when it gives none. (f) The units of (6), with cpa's currency equal to `s.currency`. (g) The output is JSON-plain, and two calls give identical output. (h) A run with an unkeyed quantity gives `quantities_unkeyed`, and a run without one has no such key. (i) On a copy of Jo's live runs, every run gives `quantities` without raising, with ctr and cvr for every ad. (j) Labels and attribution windows as in (9) and (10), on a lead run and a purchase run. (k) A below-floor quantity keeps its summary.

## Settled after the J9 blind spec review (27 Nov)

The review found 2 blocking items, 7 major and 5 minor. These settlements govern where J9 says otherwise.

S45 (J9).
1. One reader for the kind. Labels (9) and units (6) take the kind from `held.run_kind(s.conversion_kind, s.synthetic, s.client_id)`, the reader the held keys and the renderer's R9 already use. 432 of Jo's 455 runs state no kind, and `run_kind` gives "lead" for every one of them from her config. A check asserts that on a None-kind lead fixture.
2. `not_estimable` is keyed by variant, as `pipeline.py` builds it (`missing.setdefault(variant, ...)`), and quantities are found by the variant's ad id. A fixture has variant labels that differ from the ad ids.
3. A variant's names are the union in (2). If a name is both a quantity of that ad and in that variant's `not_estimable`, the quantity wins and the reason goes in the entry's `notices` after the quantity's own. No such pair exists in Jo's runs.
4. `_posterior_entry` gains a keyword `name: str | None = None`, defaulting to the run's metric name, so `posterior` calls it unchanged. The `quantities` builder calls it with each name and then adds `unit`, `label` and `attribution_window`. Inside an entry, `metric` is the entry's own name, as `_posterior_entry` already writes it, so `quantities[v]["cvr"]["metric"]` is "cvr". A check asserts that.
5. `attribution_window` is the last part of `s.knowability.attribution_windows[s.platform]` split on " then ". It is null when `knowability` is missing, the platform key is absent or the string is empty. The conversion-based names are exactly {cvr, cpa, aov, roas, contribution_per_click}. Every other name gets null. A check covers a two-code string.
6. The unit table, literal strings, with K the kind from (1) ("lead" or "purchase") and C `s.currency`:

| name | numerator | denominator | currency |
|---|---|---|---|
| ctr | link_click | impression | null |
| cvr | K | link_click | null |
| cpa | money | K | C |
| aov | money | K | C |
| roas | money | money | C |
| contribution_per_click | money | link_click | C |
| any other | the whole `unit` is null | | |

7. The per-entry `synthetic` is what `_posterior_entry` gives now: the quantity's provenance when the quantity is present, else the snapshot's. Unchanged.
8. Check (h) uses a hand-built snapshot with one quantity whose ad isn't among `variants` and one with no ad in its scope. "Quantity order" is the order in `s.quantities`.
9. Check (i) asserts that `ctr` and `cvr` keys exist for every ad, whatever their status. Check (k) uses a fixture with a present below-floor cvr, whose entry keeps `summary`, and a not-estimable cpa, whose `summary` is null.
10. Check (e) asserts that, when `held.lookup` gives None for a name, the entry's `held_status_reason` is "held status not available: no held status for <name> of ad <ad>", the text `_held_fields` writes now.
11. Added check (l): every entry's `fit_route` equals the run's, so a reader can tell which route made cpa (12).

S46 (the J9 test writer, 27 Nov, tests 008f762). (1) A `quantities_unkeyed` element is the entry a keyed one would be (quantity id, own-name `metric`, summary, status, unit, label, attribution window, fit_route); with no variant there is no held lookup, so its held fields are those `_held_fields` gives for its ad id, or null with a reason when it has none. (2) A not-estimable conversion-based name carries the attribution window like an estimated one. (3) When a quantity wins over a not-estimable reason, the reason goes in `notices` only; `status_reasons` stays the quantity's. (4) `knowability` None in memory gives null windows. (5) `result_of` reads held through `claims.held.held_status` as `_held_of` does now. (6) `held_status_reason` is absent when there is a held status. (7) The posterior pins are tied to fa857ee; a later piece that changes `posterior` on purpose moves them on the record.

S47 (the J9 builder, 27 Nov). AtmaOS validates `result_of` against `BayesianResult` (`atmaos/adapters/bayesian/base.py`, copied in `tests/fakes/atmaos_base.py`), which forbids unknown top-level keys, so a top-level `quantities` would make AtmaOS reject every result (11 P11 failures). As U10 did, the new keys go under `uncertainty`: `uncertainty.quantities` and, when needed, `uncertainty.quantities_unkeyed`. Everything else in J9, S45 and S46 stands. test_J9 is amended on the record to read them there, to compare the rest of `uncertainty` byte for byte, and to validate every result against `BayesianResult`. An unkeyed quantity with no ad in its scope gets `held_status` null with the reason "held status not available: no ad in its scope".

S48 (the J9 blind review, 27 Nov, three minor findings). (1) A second quantity with the same ad and name as an earlier one in `s.quantities` order would have been dropped, against D54. The first stays the keyed entry, which is the one `posterior` already picks. Every later one goes to `quantities_unkeyed` in quantity order, with the held lookup by its ad id. None of Jo's 456 runs has a duplicate. (2) A `not_estimable` entry keyed by a variant that isn't in `variants` can't be built by `pipeline.py` and carries no estimate. It is left as is and recorded here. (3) `result_of` raises `KeyError` on a snapshot with a comparison and no variants. That's pre-J9 code, and no built snapshot has that shape, so it's recorded and not changed in J9.

## J9.1. Whether a measure applies to the account (to build, 27 Nov)

The Head Engineer's caller leaves aov, roas and contribution_per_click out of a lead account's claims, because a lead is counted and never valued (D33). Nothing structured in an entry said so, only the notice text, and 150 entries on Jo's runs saved before D33 hold an estimated contribution_per_click.

1. Each entry in `uncertainty.quantities` gains `applies` (bool). It is false exactly when the kind (S45 (1)) is "lead", the name is in `pipeline.VALUED` (aov, roas, contribution_per_click), and the run holds no quantity of that name for the variant's ad. Every other entry has `applies` true, so a below-floor quantity that could be estimated later has `applies` true.
2. Each entry in `quantities_unkeyed` gets `applies` true, since every one holds a quantity.
3. `posterior` is unchanged and gains no field.
4. J9 (4)'s equality of `quantities[v][metric]` with `posterior[v]` now leaves out `applies` too. `tests/acceptance/j9_fixtures.py` `J9_KEYS` gains "applies" on the record, which was missed in 84a51a1.

Checks: (a) on a lead run, every VALUED name with no quantity has `applies` false, and every other name true; (b) a lead run holding a contribution_per_click quantity gives it `applies` true; (c) on a purchase run every entry has `applies` true, a not-estimable aov included; (d) unkeyed entries have `applies` true; (e) `posterior` has no `applies`.

## J9.2. A measure that doesn't apply, on Imani's menu (to build after J9.1; v2 after the Principal Architect's advice, 27 Nov)

If Jo asks Imani for her return on ad spend, the true answer is that a sign-up account has none to measure. The menu gives Imani nothing to say it with today, because `client_slots` builds fig slots only from the run's quantities, and a lead's aov, roas and contribution_per_click are never quantities. The Principal Architect's advice (D676): a slot that renders a whole client-facing sentence is a script. D676 fixes the meaning and leaves the words to Imani, and this case holds no figure. So the menu carries the fact and the token renders only the measure's name.

1. A new slot kind, `na`. Token: `{na:run/<run_id>/<name>}` with an optional `|full` or `|start`. Grammar: `na:run/(?P<run>[\w-]+)/(?P<name>[\w-]+)(?:\|(?P<form>full|start))?`. It takes no `#claim`, and a token carrying one is refused with a reason, because no claim exists for it.
2. It renders the measure's plain name and nothing else: the J5 label for the run's kind (S45 (1)), lower case in `full` and with a capital in `start`, so `{na:run/r/roas|start}` renders "Return on ad spend". Imani writes the sentence around it.
3. It renders only when every variant of that run has `applies` false for that name in `uncertainty.quantities` (J9.1). Otherwise it's refused with a reason. It is account level, never per ad. If the account ever gives a sign-up a value, `applies` turns true on that run and the slot stops by the same rule.
4. The menu lists one `na` item per such name on the newest run: `{"token", "kind": "na", "measure": <name>, "subject": null, "status": null, "status_raw": null, "applies": false, "reason": <plain reason>, "newest": true, "run_id", "release_id": null, "forms": {"full", "start"}}`. The plain reasons, fixed in a table in code:

| name | reason |
|---|---|
| roas | a sign-up is given no money value |
| contribution_per_click | a sign-up is given no money value |
| aov | there are no orders |

5. The forms and the reason hold no numeral, so the numeral rule passes them.
6. AtmaOS's side (the Head Engineer, landing with J9.2): `na` in its slot pattern, menu instruction and slot audit; with an `na` item for a measure, no fig slot for that measure may appear in the turn; and a lint flags "not yet" or "too early" wording beside that measure's name.

Checks: (a) a lead run gives three `na` items, each with its reason, and each token renders the label in both forms; (b) a purchase run gives none, and an `na` token for it is refused; (c) a `#claim` on an `na` token is refused; (d) a lead run holding a contribution_per_click quantity gives no `na` item for that name, and its token is refused; (e) the rendered text and the reasons pass the numeral rule; (f) an `na` token for a run that isn't the newest renders as a fig slot for such a run does; (g) the menu's other items are unchanged.

## Settled after the J9.2 blind spec review (27 Nov)

The review found 2 blocking items, 6 major and 4 minor. These settlements govern where J9.2 says otherwise.

S49 (J9.2).
1. An `na` token may name only a name in `pipeline.VALUED` (aov, roas, contribution_per_click). It renders only when the run's kind is "lead", the run has at least one variant, and no variant's ad holds a quantity of that name. That rule decides whether or not an entry exists for the name, so a lead run saved before D46 with no D33 lines gives the same answer. Any other name is refused as "not a measure that can fail to apply".
2. The rule lives in one pure function, `claims.applies.applies(snap, kind, ad, name) -> bool`, in a new module that imports neither `slots` nor `socket`. J9.1's `applies` field in `result_of` and J9.2's renderer both call it, and the J9.2 builder moves J9.1's inline rule there without changing its output. The renderer reads the snapshot, never `result_of`.
3. An `na` slot never reads held status: it skips `ctx.held`, so a held loader that raises or gives null doesn't stop it. A check covers that.
4. No "as of" suffix, on the newest run or any other. The fact is account level and doesn't date. `newest` says whether the run is the newest, as for fig slots, and the forms are the label alone.
5. Shapes. `SlotKind` gains "na". An `na` `SlotOut` has `quantity` `{"name": <name>, "subject": "account", "status": None}`, so AtmaOS's audit can match the measure. `MenuItem` gains `applies` and `reason` as NotRequired keys, present only on `na` items, so every other item is unchanged byte for byte (check (g)). The menu entry's `subject` is null as in J9.2 (4).
6. The grammar parses an optional `#claim` so it can refuse it by name: `R_NA_CLAIM` = "an na slot carries no claim". A name that applies gives `R_NA_APPLIES` = "the measure applies to this account on that run". An unreadable run gives the fig slots' run reasons. The menu lists no `na` item when the newest run can't be read.
7. The aov reason stays "there are no orders", the Principal Architect's words: an average order value needs orders, and a sign-up account has none. roas and contribution_per_click keep "a sign-up is given no money value".
8. J9.2 (5) is reworded: slot output is outside the numeral rule, as for every slot. Check (e) asserts that the labels and reasons hold no numeral or quantity word the rule would refuse in free text, which tests the table.
9. The engine's lint doesn't read `na` slots. The "not yet" and "too early" lint and the no-fig-slot-beside-na audit are AtmaOS's, J9.2 (6).
10. The kind is `run.kind` in the renderer, which equals `held.run_kind`. A check covers a None-kind lead snapshot whose kind comes from the config.
11. Order: `na` items come after the fig and cmp items and before the name items, in `pipeline.VALUED` order. The label is J5's for the kind, already lower case, and `_start` capitalises it.

S50 (the J9.2 test writer, 27 Nov, tests 673a9b4, 56 tests). (1) S49 (4) governs J9.2 (f): a non-newest run's `na` renders with `newest` false and no "as of". (2) An `na` token on a purchase run, a synthetic None-kind run, or a lead run where any one ad holds the quantity is refused with `R_NA_APPLIES`. (3) The "not a measure that can fail to apply" refusal is checked by its text; `R_NA_CLAIM` and `R_NA_APPLIES` by name and text. (4) "Skips held" means a text whose only slot is `na` never calls `load_held`. (5) `MenuItem`'s NotRequired keys are checked through `typing.get_type_hints(include_extras=True)`. (6) An unreadable run gives an `na` token exactly the reasons a fig token for that run gets. (7) `claims.applies`'s own imports are checked for `slots` and `socket` by parsing its source.

S51 (correction, 27 Nov, found by the Head Engineer). J9 (12) first said every one of Jo's runs took the exact per-ad route. That was read off the newest run (7 ads) and is wrong. Of her 457 runs, 184 took the joint NUTS route (151 with 9 ads, 33 with 8), and 273 the conjugate route: 261 with 5 to 7 ads, and 12 with 8 or 9 ads after a fallback. On every NUTS run, cpa is samples computed from the joint draws as cpm / (1000 · ctr · cvr), since the joint model has no cpa parameter (`sampler_numpyro.PARAMS`), so it does rest on ctr and cvr. The entry's `fit_route.kind` and the quantity's own `route` (`provenance.route`) agree on all 2,512 cpa entries. The rule stands: link cpa to cvr when the route is not "conjugate".

S52 (the J9.2 builder, 27 Nov). Two frozen tests forbid what J9.2 and S49 require, so they are amended on the record and changed nowhere else. `tests/acceptance/test_J4R.py::test_J4R_menu_shape` now requires every `MenuItem` key except J9.2's NotRequired `applies` and `reason`, and allows the kind "na". `tests/acceptance/test_J7.py::test_J7_h_the_menu_lists_no_recommendation_allocation_or_share` allows the kind "na", which carries no recommendation, allocation or share. The builder added `R_NA_NAME` for S49 (1)'s "not a measure that can fail to apply".

S53 (the J9.2 blind review, 27 Nov, no finding; one gap recorded). S49 (1) looks only at the variants' ads, so a lead run holding a roas, aov or contribution_per_click quantity with no ad in its scope would still list an `na` item for that name. No run builds one: after D33 a lead's valued names are never estimated at any level, and the 150 early contribution_per_click quantities are all ad level. If an account-level valued quantity is ever built, the `na` rule must also require that the run holds no quantity of that name at any scope. That goes in the piece that builds it.
