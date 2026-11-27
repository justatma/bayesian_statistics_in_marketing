# Brain join specification, v0.1

26 November 2026, the Bayesian Engineer. This spec covers the engine's side of joining the engine to AtmaOS and to Imani Brooks, the AtmaOS team member who explains the engine's work to the client. It follows spec 42 FR7.2 in the AtmaOS repository and the owner's rulings: D54 here, and D676 and D677 in AtmaOS. Pieces already built are listed so the rest can be read against them. Each piece below that has a status of "to build" has an interface and checks. Nothing in it is built until the blind spec review's undecided list is answered.

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
6. Keys are `meta:<ad id>:<YYYY-MM-DD>:v<n>`. `n` counts the distinct figure sets for that ad and day in the order the live store first saw them, starting at 1 and taken over the full history. A stored key never changes content, and a changed figure is a new key, `v<n+1>`. Arkwright's intake refuses any export that breaks this, at receive.

The reference implementation is `rows_sha256()` in `scripts/export_history.py`.

Checks: (a) a fixture of three rows with known bytes gives a stated hash, and the test holds that hash. (b) The hash doesn't depend on the order the rows are given in. (c) Changing any one value in any row changes the hash. (d) Two exports of the same store give identical `polls.jsonl` and identical `rows_sha256` for every run. (e) A row with a non-ASCII ad name hashes over its UTF-8 bytes, not over `\u` escapes.

## J2. Row hashes in the engine's own run record (to build)

Today a live run's `dataset_hashes` is empty, and its manifest id hashes the client and the poll id, not the content. After J2 the live refresh puts the bayes-rows-c1 hash of the rows the run read into `RunRecord.dataset_hashes` and `RunSnapshot.dataset_hashes`, as `"bayes-rows-c1:<hex>"`. The run file, the export's `runs.jsonl` and the stored copy then all name the same digest.

The `manifest_id` stays as it is. It feeds the seed and the run id (`pipeline.py`, `_seed` and `make_id("run_", ...)`), so changing it would change every result. The engine computes the rows' bayes-rows-c1 form from `LiveRow`s by the same rule and key numbering as the export. For this, the version numbering moves from the export script into one function in `live/` that both call.

Interface: `bayesian_marketing.live.rows.versioned(store, client_id) -> (rows: list[dict], seen: dict[poll_id, list[key]])` and `bayesian_marketing.live.rows.rows_sha256(rows) -> str`. `export_history.py` imports them in place of its own copies.

Checks: (a) for every run in the live store after J2, `dataset_hashes` holds exactly one `bayes-rows-c1:` entry, equal to that run's `rows_sha256` in a fresh export. (b) Runs made before J2 are not rewritten. Their `dataset_hashes` stay empty, and the export still gives their `rows_sha256`. (c) The seed and run id of a refresh on a fixed poll are unchanged by J2. (d) The whole existing test suite passes.

## J3. Hand-off markers (to build)

These are the Head Engineer's shape of 26 Nov. A marker is one small JSON file in `$BAYES_DATA_DIR/markers/`, written to a temporary name and then renamed, so a reader never sees a half-written file. There are two kinds:

| Kind | File | Fields |
|---|---|---|
| `engine_run` | `run_<run_id>.json` | `kind`, `client_id`, `run_id`, `snapshot_path` (absolute), `snapshot_sha256` (of the run file's bytes), `rows_form`, `rows_sha256`, `written_at` (UTC) |
| `notebook_release` | `nb_<release_id>.json` | `kind`, `client_id`, `release_id`, `release_path` (absolute), `release_hash`, `written_at` |

The refresh writes an `engine_run` marker as its last step after a run is saved. `write_release` writes a `notebook_release` marker after its own verify passes. The engine never reads, moves or deletes markers. AtmaOS's job reads them and is idempotent on `run_id` or `release_id`. A failed refresh writes no marker.

Checks: (a) a refresh that saves a run leaves exactly one marker naming it, and its `snapshot_sha256` matches the file. (b) A refresh that is skipped or fails leaves none. (c) A marker never exists without its run file. In the test, the write is interrupted before the rename and no marker is left. (d) A new release leaves a marker whose `release_hash` equals `verify()`'s.

## J4. check_client_figures (to build)

This is the check Imani runs on a sentence before she says it to the client. It is separate from `check_narrative`, which stays as it is for reports apart from the bug fix in J5.

Signature: `bayesian_marketing.atmaos.socket.check_client_figures(text: str, refs: list[dict]) -> dict`. AtmaOS imports the socket at call time, and the engine never imports atmaos (F7). Both directions use JSON-native dicts.

`refs` lists what the sentence rests on. Each ref is one of these:

| Ref | Fields | What the engine reads |
|---|---|---|
| run | `{"kind": "run", "run_id"}` | The run's snapshot file. |
| notebook entry | `{"kind": "notebook_entry", "release_id", "entry_id"}` | The entry in `notebook/<client>/releases/<release_id>/entries.jsonl`, after `verify()` passes on the release. |
| claim | `{"kind": "claim", "claim_id", "engine_item": {...}}` | `engine_item` is the engine pointer the AtmaOS claim's evidence holds: for a notebook claim the release id and entry id, for a posterior claim the run id and quantity id. The engine checks against its own files and echoes the claim id back. AtmaOS resolves a claim id to its engine item, because the engine can't read the Brain. |

Reading the sentence:

1. **Figures.** Every number in the text is a figure, except dates, times of day, years, and run, release and entry ids. That covers percentages, money (with `$` or a currency code), plain counts and ratios. A figure written in a form the reader can't parse fails, with the reason "figure in a form the checker cannot read".
2. **Subjects.** An ad is named by its id or its name. Names are read from the run's entity names or the notebook source objects. Matching ignores case, and treats an en dash, hyphen and spaces in a name as equal. An ad set or campaign is named the same way, and "the account" names the account.
3. **Metric words.** The existing aliases apply, plus lead vocabulary when the ref's conversion kind is lead (`conversion_event` in the client config is a lead event). On a lead account, "sign-up", "sign-ups", "lead" and "leads" name the conversion, "cost per sign-up" and "cost per lead" name `cpa`, "sign-up rate" names `cvr`, and the words "order" and "purchase" fail with the reason "this account converts on sign-ups, not orders". "Link clicks", "click rate" and "click-through rate" name `ctr` or the link-click count. "Spend", "spent" and "budget" name money.
4. **Matching.** A figure is placed when one quantity among the refs has the same unit kind (percent, money, count or probability), the same subject if the sentence names one, the same metric if the sentence names one, and a value whose display at the registry's rounding equals the figure. Rounding is percent 1 decimal, cost-per money 2 decimals (`unit_money_decimals`), other money 2 decimals when the figure shows cents and 0 when it doesn't, counts whole, and probability as a percent at 1 decimal. An estimated quantity also accepts its q05 and q95, as an interval, and its q50 or mean.
5. **Status.** A figure placed on an `estimable` quantity passes. One placed on a `marginal` quantity passes only if the sentence also says that it is still an estimate. The required phrase is the registry's `caveat_marginal`, or "still rough" or "a rough estimate", anywhere in the same sentence, since a clause split must not cut it off. A figure placed on a `below_floor` quantity fails, with the reason that the quantity is "not knowable yet" and the registry's `not_knowable` wording. An observed notebook quantity has no status and passes when placed.
6. **Unplaced.** A figure no ref places fails, with the reason "not found in the refs given". It never passes silently. When a quantity of the same unit, subject and metric exists but its value differs, the result gives that quantity's value as `should_read`.
7. **Comparatives and causal words.** These are checked as `check_narrative` checks them, against the refs' comparison, if a run ref carries one.

Return:

```json
{
  "passed": false,
  "figures": [
    {"text": "4.4%", "placed": true, "ref": {"kind": "claim", "claim_id": "..."},
     "quantity": {"name": "ctr", "subject": "120253899504590526", "status": "marginal"},
     "should_read": "4.4%", "caveat_required": true, "caveat_present": true, "reasons": []},
    {"text": "$1,600", "placed": false, "ref": null, "quantity": null, "should_read": null,
     "caveat_required": false, "caveat_present": false, "reasons": ["not found in the refs given"]}
  ],
  "reasons": ["$1,600: not found in the refs given"],
  "engine_version": "bayesian-marketing ...",
  "inputs_hash": "<sha256 over text and refs>",
  "checked_at": "<UTC ISO 8601>"
}
```

`passed` is true only if every figure is placed and passes and no sentence-level reason exists. A text with no figures passes with an empty `figures` list. A ref that can't be read (a missing run, a release that fails `verify()`, an unknown entry) makes the call fail with a reason naming the ref. It doesn't raise. Only a wrong argument type raises.

Checks are the acceptance tests, frozen before the build. Each runs against fixture runs and a fixture notebook release, never the live store:
(a) "IMG3_TXT1 had a click-through rate of 4.4%, but it is still a rough estimate." with a run ref passes when IMG3's ctr is marginal at 4.4%.
(b) The same sentence without the caveat fails, naming the caveat.
(c) "Cost per sign-up for IMG3_TXT1 was $3.35, a rough estimate." passes on a lead account. "Cost per order" in the same sentence fails, naming sign-ups.
(d) "The account spending limit is $1,500." passes with a notebook entry ref holding that quantity, and fails with only a run ref.
(e) "$1,600" with refs holding $1,500 fails, with `should_read` "$1,500.00" when the subject and metric match.
(f) A figure on a below_floor quantity fails, saying "not knowable yet".
(g) A claim ref whose engine item points at a notebook entry is checked exactly like that entry, and its claim id is echoed.
(h) A text with a date ("26 November"), a run id and no figures passes.
(i) An unreadable ref fails, naming it, and doesn't raise.
(j) Ad names with an en dash ("IMG2_TXT1 – Updated.") match with a hyphen or spaces.

## J5. The lead path in check_narrative (to build, a fix)

On a lead account, `check_narrative` labels `cpa` "cost per order" and rounds it to whole dollars. That made it refuse a correct "$3.35" on 26 Nov. The fix: when the run's `conversion_kind` is lead, `cpa` is labelled "cost per sign-up" (aliases: "cost per lead", "cost per conversion", "cpa"), and cost-per money displays at `unit_money_decimals`. A purchase run is unchanged.

Checks: (a) on a lead fixture run, "This estimate is still rough: ad <id> had a cost per sign-up of $3.35." passes when the cpa q50 is 3.35. (b) The same text on a purchase fixture run with "cost per order" behaves exactly as before. (c) The whole existing test suite passes.

## J6. read_test_design (to build, its own spec)

The Arkwright Engineer's request of 11 Nov (`atmaos/spec/suggestions/request_to_bayesian_engine.md`), with the call signature restated on 26 Nov, is specified separately, because it is a design-time power reading and not part of the join. It is listed here so the join's spec reviewer sees it was not forgotten. The state of a live test is a separate call from `read_test_design`.

## Order and estimates

The order is J5, then J4 (J4 reuses J5's lead vocabulary), then J2 and J3. Each is one piece. By how long pieces of this size took here (L10 and L11, each a module with its tests merged within a working session), J5 is about an hour, J4 a few hours including its acceptance set, and J2 with J3 a couple of hours, each plus a blind review on a different model. The record for a checker piece is thin: G5 itself was the only one, and it took longer than its estimate.

## What this spec leaves to others

The registry of representation names is the Head Engineer's, and it holds bayes-rows-c1 by the rule in J1. The AtmaOS job that reads markers, the caller of `result_of` and `observation_evidence`, and Imani's turn are the Head Engineer's too. Arkwright's intake and its add-only check at receive are the Arkwright Engineer's. Widening the poll's re-read from 7 to 28 days is the owner's call, put to him on 26 Nov.
