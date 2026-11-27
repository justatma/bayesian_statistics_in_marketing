# Blind review of Brain join spec v0.1

Reviewer: Sonnet, blind (spec, blueprint sources and code only). 26 November 2026. Taken in v0.2 as S1 to S14.

1. Gaps between blueprint and spec

1. Blocking. FR7.2: "the rows a registered result cites are kept and hashed one by one, and pruning spares them." The spec does not say what "kept" means (J1, J2). The posterior claim's pointer is `row_keys` plus `rows_sha256`, and the intake keeps the file. Nothing says the engine's own store must retain those rows. Nothing says pruning spares them, or that a run's `row_keys` are stored with the run. J2 puts only the hash in `dataset_hashes`. `export_history.py:84-125` rebuilds `row_keys` at export time from `rows` joined to `polls`, so they are not recorded with the run.

2. Blocking. FR7.2: "snapshot is brought into the artifact store." J3 writes `snapshot_path` (absolute, local) and `snapshot_sha256` into a marker. Who copies the snapshot is left to "AtmaOS's job". Nothing says the engine's snapshot stays on disk and unchanged until that job runs, or that the file can't be pruned or moved before then.

3. Major. FR7.2: "Each posterior entry is a claim: percentiles at 0.9 in `claim_quantities`, the rest in engine detail." The spec only touches `result_of` and `observation_evidence` in its closing section, where it leaves them to the Head Engineer. `result_of` (`socket.py:210`) and `_posterior_entry` (`socket.py:172`) are the engine's side of that mapping. The spec makes no check that the posterior entry carries `row_keys`, `rows_form` and `rows_sha256`. J2's run-level hash does not give a claim its pointer.

4. Major. Agreement (a): "named, versioned and exact enough that the Brain's resolver can recompute the hash itself." J1 gives the rule, but not the resolver's inputs. It does not say whether the resolver gets rows by `key` from the stored file or hashes the file lines as stored. It does not say how a row's `names`, a nested dict, serialises (it is covered only by the sorted-keys rule). J1 check (a) holds one fixture hash but doesn't require a second, independent implementation.

5. Major. Agreement (a): "the stored file named is the first holding the keys." J1 repeats this and defines no tie-break. It doesn't say what "first" is ordered by, or who records which stored file it was.

6. Major. Agreement (b): the marker carries run id, client id, snapshot path, its hash. J3 adds `rows_form` and `rows_sha256` and `kind`, which is fine. The temp-name-then-rename write is stated. "Written last" is stated. A crash between the run file and the marker leaves a run with no marker, and nothing says who backfills it. The check for a failed refresh passes trivially for runs made before J3.

7. Major. Agreement (c): "per figure the quoted text, ref matched, value at the registry's rounding, caveat required and reasons." J4's return gives `should_read` only when a figure differs, or the matched quantity's value when it matches. The spec has a `should_read` of "4.4%" for a match in its example. It never defines "value at the registry's rounding" as a separate field, so the contract is ambiguous.

8. Major. Agreement (c): "ads by name and id, lead vocabulary on lead accounts." Lead vocabulary in J4 point 3 is keyed on "the ref's conversion kind." Only notebook entries and runs are refs, and `conversion_kind` is on `CompareRequest` (`core/records.py:155`), not on a ref. The spec doesn't say where `check_client_figures` reads the account's kind from.

9. Minor. D54: "Whether an ad can still take money is itself a data point (its status)." J1's row key list has no ad status field. Not a join item, but the spec's closing section says nothing about it.

10. Minor. D676/D677: a persona needs no owner release. The spec correctly adds none. It does not say the check is the persona's own care, which D676 states. J4 says "the check Imani runs before she says it", which fits.

2. Undecided

1. Does the engine keep `row_keys` per run in its own run record, or does the export keep recomputing them? Options: (a) add `row_keys` to the snapshot; (b) leave them derived and add a pruning guard test; (c) neither.
2. Who copies the snapshot into the artifact store, and what holds the engine's file until then? Options: engine copies; the AtmaOS job copies and verifies `snapshot_sha256`; the marker embeds the snapshot.
3. How does the engine put `bayes-rows-c1:<hex>` into `dataset_hashes`? Today `pipeline.py:1193` builds it as `sorted(f.sha256 for f in manifest.files)` and `refresh._manifest` passes `files=[]` (`refresh.py:167-170`), so J2 must either invent a manifest file entry or change `pipeline.py`. Also, `observation_evidence` (`socket.py:301-304`) hashes `dataset_hashes` into `dataset_snapshot_hash`. J2 therefore changes that value for new runs. Does the Head Engineer accept that, and is J2 check (c) enough to cover it?
4. What does "first stored file holding the keys" mean when two stored exports overlap? Options: earliest received; earliest `known_at`; lowest file name.
5. What does a claim ref's `engine_item` look like for a posterior (run id plus quantity id)? Is the row hash checked in `check_client_figures`, or only the quantity? Options: check pointer too; check the quantity only.
6. Is the lead decision per account from config (`_conversion_kind`, `refresh.py:108`), per run, or per ref? A notebook ref carries no kind. Options: read the client config; add a `conversion_kind` field to the refs; require the caller to pass it.
7. Which phrase is the caveat? The registry's `caveat_marginal` is "this estimate is still rough" (`phrasing.yaml:13`). J4 point 5 also accepts "still rough" and "a rough estimate", which are not in the registry. Add them to the registry, or accept only the registry's?
8. Probability rounding. J4 point 4 says probability as a percent at 1 decimal. The registry has `probability_decimals: 2` and shows probability as a bare decimal (`vocab.py:fmt_probability`). Which governs?
9. Other money rounding. J4 says 2 decimals when the figure shows cents, 0 otherwise. The registry has `money_decimals: 0`. Is "shows cents" the rule, or the registry's 0?
10. A figure with no subject or metric named in the sentence: does it match any ref quantity of the right unit, which makes false placement likely? Nothing says whether ambiguity (two quantities match) passes, fails, or reports both.
11. J5 changes `cpa`'s label in `claims/vocab.py:25` (`METRIC_LABELS`), which the report renderer also uses. Is the lead label a lead-only branch in the checker, or a change to the shared label table? Options: per-call override; a new lead table.
12. Where do markers go when `BAYES_DATA_DIR` is overridden by `data_dir_env`, and who prunes them? The spec says the engine never deletes them.
13. The existing-code fact to check: the spec says the manifest id "feeds the seed and the run id (`_seed` and `make_id("run_", ...)`)". `_seed` does use `manifest_id` (`pipeline.py:903-904`). I did not confirm `make_id("run_", ...)` in `pipeline.py`. Verify before build.
14. The spec says `export_history.py` imports `versioned` and `rows_sha256` from `live/rows.py` in place of its own. In the code, `polls()` also fills the module global `POLL_READS` (`export_history.py:123`). The interface `versioned(...) -> (rows, seen)` drops this, so the reads output has no owner.
15. The spec says rows have exactly the listed keys, and lists `account`, `campaign`, `ad_set`, `ad`. The code's `polls()` row has `names`, `link_clicks`, the ids and the `MEASURES` except `clicks`. That agrees. The spec also lists `observed` in `ROWS` as `conversions_observed`, which is in `MEASURES`. No contradiction found here.
