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
7. Keys are `meta:<ad id>:<YYYY-MM-DD>:v<n>`. `n` counts the distinct figure sets for that ad and day in the order the live store first saw them, starting at 1 and taken over the full history. A stored key never changes content, and a changed figure is a new key, `v<n+1>`. Arkwright's intake refuses any export that breaks this, at receive.

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
