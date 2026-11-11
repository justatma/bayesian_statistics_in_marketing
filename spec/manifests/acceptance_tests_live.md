# Acceptance tests: live view L1 to L4

## Files written

- tests/acceptance/test_L1.py (10 tests)
- tests/acceptance/test_L2.py (10 tests)
- tests/acceptance/test_L3.py (42 tests as collected; 37 functions, 2 parametrized: unlimited cap x2, budget words x4, engine skipped/failed x2)
- tests/acceptance/test_L4.py (7 tests)
- tests/fixtures/live/ created, empty (no fixture files needed: data is built in the test files; L3 engine tests generate a real ctr snapshot from data/scenarios/north_pier_day14.yaml at test time).

## Tests, spec item, reason it fails today

### test_L1.py
| test | spec item | fails today because |
|---|---|---|
| test_L1_entity_names_fill_four_keys | L1 check 1, B4 | entity_names is {} (the connector does not map the four name fields) |
| test_L1_objective_filled_when_requested | L1 check 2, §3.1 | objective is None (not mapped) |
| test_L1_lead_event_counts_lead_and_never_values_it | L1 check 3 and 5, §3.2 | conversions_reported is 2.0 (purchase order), not 5.0 from `lead` |
| test_L1_lead_string_containing_lead_is_a_lead_event | L1 §3.2 | conversion_event ignored, conversions_reported 0.0 not 3.0 |
| test_L1_lead_event_absent_gives_zero_rows_and_note | L1 check 4 | revenue_reported is not None and the note `conversion event lead not seen in this pull` is absent |
| test_L1_non_lead_event_takes_count_and_value_from_its_type | L1 §3.2 [2.5] | the note `conversion event omni_purchase used` is absent |
| test_L1_account_fields_land_as_text | L1 check 6, §3.3 | PlatformPull.account is {} |
| test_L1_missing_account_key_is_absent_not_blank | L1 §3.3 | PlatformPull.account is {} (KeyError on amount_spent) |
| test_L1_meta_empty_replays_empty_with_account_fields | L1 check 7 | account is {} on replay (empty_account part already holds) |
| test_L1_p8_meta_tests_unchanged_and_new_recording_carries_names | L1 check 8, B7 | meta P8 tests pass in the child process; the 7-day recording replays with entity_names {} |

### test_L2.py (all fail at SqliteStore.open: NotImplementedError "L2")
| test | spec item |
|---|---|
| test_L2_poll_stores_nine_rows_and_one_ok_poll | L2 check 1, C1, §2 poll id |
| test_L2_auth_error_stores_error_poll_without_token | L2 check 2, C3 |
| test_L2_error_text_redacts_access_token_pairs | L2 C3 [2.25] |
| test_L2_update_and_delete_raise_append_only_on_each_table | L2 check 3, C2, §4.1 |
| test_L2_second_poll_stores_second_set_and_is_latest | L2 check 4, C2 |
| test_L2_poll_without_outcome_reads_interrupted | L2 check 5, §4.1 |
| test_L2_window_ends_on_account_local_date | L2 check 7, C1 |
| test_L2_prune_removes_exactly_the_old_directories | L2 check 6, C4 |
| test_L2_poll_records_to_per_poll_directory_and_prunes | L2 C1 (BAYES_RECORD_DIR context), C4 |
| test_L2_no_credential_value_in_store_or_recordings | L2 check 8, C6 |

### test_L3.py (all fail with NotImplementedError "L3" from view.render, view.render_index or make_server)
| test | spec item |
|---|---|
| test_L3_h1_and_five_h2_strings | L3 check 1, C1, intro (refresh meta, no script) |
| test_L3_header_names_account_zone_currency_and_poll_times | L3 C1 |
| test_L3_no_poll_says_so_and_nothing_below_the_header | L3 C1 |
| test_L3_error_banner_with_the_message | L3 check 4 |
| test_L3_no_error_banner_when_latest_poll_is_ok | L3 C1 |
| test_L3_stale_banner_at_7201_seconds_and_not_at_7199 | L3 check 5 (also 7200 exact) |
| test_L3_interrupted_banner | L3 check 6 |
| test_L3_banners_in_order_error_interrupted_stale | L3 C1 order |
| test_L3_account_cap_and_spend_from_minor_units | L3 check 9, C2 |
| test_L3_unlimited_account_shows_no_limit[0], [None] | L3 check 8, C2 |
| test_L3_zero_exponent_currency_is_not_divided | L3 C2 |
| test_L3_unknown_account_status_code_shows_the_code | L3 C2 |
| test_L3_delivery_one_row_per_ad_with_names_and_ids | L3 C3, B5 |
| test_L3_ctr_cell_shows_percent_with_counts | L3 check 3, C3 |
| test_L3_zero_denominator_shows_none_yet | L3 C3 |
| test_L3_periods_use_account_local_dates | L3 C3 [2.16] |
| test_L3_evidence_text_once_before_each_table_and_platform_count | L3 check 2, C3, C4 |
| test_L3_objective_per_campaign_or_missing | L3 C3 |
| test_L3_conversions_default_event_word_attribution_and_not_reported | L3 C4, check 7 (not_shown) |
| test_L3_lead_client_has_lead_sentence_provisional_and_no_revenue | L3 check 7, C4 |
| test_L3_budget_words_at_the_floors[16, 17, 67, 68] | L3 check 10, C5 |
| test_L3_budget_conversions_have_their_own_word_and_not_reported | L3 C5 |
| test_L3_engine_none_yet | L3 check 11, C6 |
| test_L3_engine_skipped_and_failed_sentences[skipped, failed] | L3 check 11, C6 |
| test_L3_engine_renders_finding_lines_from_the_snapshot | L3 check 11, C6 |
| test_L3_engine_without_diagnostics_says_so | L3 C6 |
| test_L3_every_percentage_shows_its_counts | L3 C7 |
| test_L3_no_banned_phrase_in_page_or_templates | L3 check 12, C7 |
| test_L3_footer_carries_the_internal_watermark | L3 C7 |
| test_L3_page_strings_are_not_literal_template_leftovers | L3 C7 |
| test_L3_index_lists_each_client_with_link_and_last_good_poll | L3 C8 (index) |
| test_L3_server_health_is_json | L3 check 13, C8 |
| test_L3_server_client_page_and_index | L3 C8 |
| test_L3_server_unknown_client_and_path_are_404 | L3 check 13, C8 |
| test_L3_server_other_methods_are_405 | L3 check 13, C8 |
| test_L3_server_ignores_query_strings | L3 check 13, C8 |
| test_L3_server_logs_one_line_per_request | L3 C8 |

### test_L4.py (all fail with NotImplementedError "L4" from refresh)
| test | spec item |
|---|---|
| test_L4_approved_economics_and_prior_run_ctr_for_each_ad | L4 check 1, C1, C3, C4, §2 refresh id |
| test_L4_two_ok_polls_give_two_refreshes | L4 check 6, C3 |
| test_L4_no_loss_tolerance_is_skipped_with_the_reason | L4 check 2, C2 |
| test_L4_unapproved_prior_is_skipped_with_the_g8_text | L4 check 3, C2 |
| test_L4_one_ad_is_skipped | L4 check 5, C2 |
| test_L4_no_economics_path_is_skipped | L4 C2 |
| test_L4_a_raising_pipeline_is_failed_and_never_raises | L4 check 4, C2 (the one allowed monkeypatch: pipeline.execute) |

## Commands and exit codes

All from /Users/atma1/gh_all/atmaos/bayesian.

- `BAYES_PIECES=L1,L2,L3,L4 .venv/bin/python -m pytest -q -p no:cacheprovider tests/acceptance/test_L1.py`: exit 1, 10 failed
- same for test_L2.py: exit 1, 10 failed (NotImplementedError L2)
- same for test_L3.py: exit 1, 42 failed (NotImplementedError L3)
- same for test_L4.py: exit 1, 7 failed (NotImplementedError L4)
- `.venv/bin/ruff format tests/acceptance/test_L*.py`: exit 0
- `.venv/bin/ruff check tests/acceptance tests/fixtures`: exit 0 ("All checks passed!") after `ruff check --fix --select I001` on the four new files (import order only)
- `.venv/bin/python -m pytest -q -p no:cacheprovider tests/acceptance/test_L1.py ... test_L4.py` without BAYES_PIECES: exit 0, 69 skipped
- `BAYES_PIECES=P8 .venv/bin/python -m pytest -q -p no:cacheprovider tests/acceptance/test_P8.py` (before writing, to learn the baseline): 3 failed, 7 passed (google_ads and linkedin recordings missing, recordings secrets scan). Not L1's.
- `.venv/bin/python -m pytest -q -p no:cacheprovider tests/acceptance -x`: 150 passed, 81 skipped, exit 0 (integrator's run with tests/unit/l0, 2026-11-07, after B8).
- Validation of the tests themselves: throwaway reference implementations of store, poll, prune, view, serve and refresh were written outside the repo (in the session scratchpad) and loaded as pytest plugins. With them, test_L2.py, test_L3.py and test_L4.py pass in full (59 passed). The reference code is not part of the repo and was not saved to it. L1 has no such reference, so its pass conditions are checked by reading the existing meta.py only.

## Facts assumed

### Verified
- Piece gate, ruff and exit codes above were run.
- Every L2, L3, L4 test fails on NotImplementedError today (the first call into the unbuilt body). Every L1 test fails on an assertion about behaviour not built (empty entity_names, objective None, account {}, conversion_event ignored).
- `meta.OBJECTIVE_REQUESTED` is True, so the objective test runs; it skips if L1 ever sets it False.
- The re-recorded data/recordings/meta_jovannah_7d and meta_empty carry the new fields (account has six keys, rows carry account_name etc.).
- `event_floor("marginal") == 17` and `event_floor("estimable") == 68` (already implemented by L0); the test asserts this.
- Default CTR prior in registries/priors/default.yaml is approved; a client CTR prior is proposed with `prior_registry.propose` and approved with `prior_registry.approve(id, "owner")` under the BAYES_DATA_DIR that is current at call time; its unapproved form makes `pipeline.resolve_priors` raise G8 with a reason containing "not approved".
- `pipeline.execute` writes `<BAYES_DATA_DIR>/runs/<run_id>.json` and returns a context with `.snapshot`; a ctr run over `data/scenarios/north_pier_day14.yaml` yields marginal and below_floor quantities and one conjugate DiagnosticsReport.
- The acceptance conftest isolates BAYES_DATA_DIR and BAYES_REGISTRY_DIR per test; L3 and L4 pass `data_dir` values different from it so only the code under test can point the run at them.
- `SqliteStore` schema constant `SCHEMA` makes a usable database with sqlite3 alone (used to seed the L3 server tests without L2's body).
- `PlatformPull.notes` is where the connector notes land; `ClientConfig` has the three new fields.

### Inferred (not checked against any implementation)
- A "pull note" is an entry of `PlatformPull.notes`, matched by substring.
- The poll's `started_at` equals `clock.now()` at the start of the call; `finished_at` is not asserted.
- `poll_id` hashes `started_at.isoformat()` of that same value (the clock is set with non-zero microseconds so an isoformat with or without forced microseconds agrees).
- `config_root` for `make_server` and `refresh` is the configs directory itself (client YAML at `<config_root>/<id>.yaml`, economics at `<config_root>/economics/`).
- `/health` `last_poll` value is an ISO string for the latest ok poll (its date is asserted, not the exact instant) and null when the client has no ok poll.
- Page times are found by "HH:MM" substrings (UTC 17:30, local 12:30, next expected 18:30); no other time format is assumed.
- CTR cells appear in the order today, yesterday, last 7 days within a delivery row; a CTR cell is the one containing "%".
- Delivery and conversions tables are html tables with one `td` row per ad; the Budget, Account, Engine sections are found by their h2 text; the sections run to the next h2.
- Money on the page for USD is `$` plus thousands separators at 0 decimals (the spec's `$1,500`); for JPY only "150,000" is asserted.
- The budget section shows, for one ad, the label of clicks and the label of conversions; for None conversions it shows `not_reported` and no status word.
- Quantities with `feasibility.status == "below_floor"` get `not_knowable_lines`; others get `finding_lines`; the page shows `label`, `estimate`, `low`, `high`, `status_label` text of each.
- `refresh` sets `RefreshRecord.at = clock.now()` and stores the record through `store.add_refresh` for every outcome including skipped and failed.
- A skipped or failed reason is exact for the one-ad and no-economics-path cases (constants from refresh.py, also literal in the spec), substring for the gate cases and `RuntimeError: boom` exact for the failure.

## Open questions where the spec left a choice

1. `event_not_seen` (L3 C4: "when the poll's note says so"): PollRecord has no notes field, so the page cannot read a note from the store. No test for it. Choice: untested.
2. Cost and CPC values: money at 0 decimals makes a $0.50 CPC render as $1 or $0; the spec does not say. Choice: no test asserts a CPC or cost-per-conversion amount, only `none yet` and `not reported`.
3. Thousands separators in impression counts (`2.0% (20 / 1000)` in the spec shows none). Choice: exact equality only where counts are under 1000 or exactly 1000 as the spec prints it; 7-day cells are checked by prefix; the "every percentage shows counts" test accepts digits with optional commas.
4. Whether `(provisional)` shows when no `conversion_event` is configured (default `purchases`). Choice: untested; tested only for an unconfirmed configured event and its confirmed counterpart.
5. Diagnostics wording (C6 "in words"): only the empty-list case (`no_diagnostics`) is asserted; the non-empty case asserts nothing about the words.
6. Budget windows: which period the clicks are counted over is not specified. Choice: the budget fixtures put all rows on one day so any window gives the same count.
7. L3 C8 SIGTERM and L4 C3 "none after an error poll" (a CLI/caller rule, not a `refresh` behaviour) are not tested. The `METHOD PATH STATUS MSms` line is tested with a tolerant regex on stdout (not in the Checks paragraph, in C8).
8. The P8 "passes unchanged" check (L1 check 8): P8 has three failures unrelated to L1 today (google_ads and linkedin recordings, secrets scan). Choice: the test runs only the two meta P8 tests (`-k "meta_replay or empty_account"`) in a child process. It is merged with an assertion about the new 7-day recording's names so that the test fails today instead of passing as a bare regression guard.
9. L1 "no conversion_event gives omni_purchase" would pass today as a bare check; it is folded into the lead-event test (second pull on the same elements) to keep every test failing.
10. L2 does not assert `PollRecord.account` content, because that depends on L1 landing; it asserts `timezone` instead.
11. L4 "unapproved prior": the prior is a client prior proposed but not approved, because every default CTR prior is approved. The reason is matched on "not approved".
12. The server tests seed SQLite directly from `SCHEMA` rather than via `SqliteStore`, so L3 does not depend on L2's body; this means they assume the row layout of §4.1 only.

## Final line

- `.venv/bin/python -m pytest -q -p no:cacheprovider tests/acceptance -x` (no BAYES_PIECES): 139 passed, 79 skipped, 725 s; the captured output lost the exit status through a pipe, but pytest reports no failure, so it exited 0.
- After this manifest was written, the integrator edited `registries/phrasing.yaml`, the spec and `spec/live_build_log.md` (B8) and added two tests to `test_L3.py` (now 44 collected, including the `event_not_seen` and unit-cost cases that open questions 1 and 2 left untested). Those edits are not mine and are not covered by the failure-reason table above.

## Freeze (integrator, 2026-11-07)

Two tests added to `test_L3.py` by the integrator before the freeze (build log B8): `test_L3_unit_costs_at_two_decimals`, `test_L3_event_not_seen_when_configured_event_sums_to_zero`. Both fail today on NotImplementedError.

Frozen files, sha256 (the merge gate refuses any branch that changes them):

| File | sha256 |
|---|---|
| `tests/acceptance/test_L1.py` | `065643ed6a2bd549e06add99d8d92e12b7ce3ebd5bcdffd524f45b90ebd4ec53` |
| `tests/acceptance/test_L2.py` | `366cf3d61032fe1447b60c11cefd4a468032456f38fbfb7c9f4ca97426b14ab8` |
| `tests/acceptance/test_L3.py` | `a5d18a05ac8f727cbdeea02cb2262fb95c229108f016b2eeafdf37ffc15f686a` |
| `tests/acceptance/test_L4.py` | `afafa8598b6c78581a933af59c59f9b6f1db6dd7afc434f2aacbc343fcfb70b0` |

## L5 freeze (integrator, 2026-11-09, D46)

`tests/acceptance/test_L5.py`, written by the integrator (not the builder). Before the fix: 12 failed, 1 passed. The passing test (`test_L5_purchase_run_is_unchanged`) guards the default. Each failure is the bug or the missing contract: `LEAD_NOT_VALUED` and `CompareRequest.conversion_kind` absent, `contribution_per_click` derived from leads, non-rate metrics not refused.

| File | sha256 |
|---|---|
| `tests/acceptance/test_L5.py` | `f76d293671cb20820d3fd11d1ffe5c1d310998a6becc7bcb85cebe76763aa8c9` |

L5 amendment (integrator, 2026-11-09): line 207 read `Recommendation.notices`, a field the model does not have, so `test_L5_lead_run_derives_no_value` could not pass on any code (builder's open question 1). It now checks the recommendation's JSON for `contribution_per_click` and "contribution per click". Still 12 failed, 1 passed on the unfixed code. New hash replaces the one above:

| File | sha256 |
|---|---|
| `tests/acceptance/test_L5.py` | `1b3497809df2636b64d67d150fec865f274534ab3bd0492208aae4ffe5196eed` |

## L6 and L7 (prior learning spec v0.2, §6 as amended by §8), written 2026-11-10

Files: `tests/acceptance/test_L6.py` (17 tests as collected: 15 functions, one parametrized x3), `tests/acceptance/test_L7.py` (26 tests). Both read the lead record (`lead_records.cvr`) and the purchase records from `registries/priors/default.yaml`, the ceilings from `bounds.yaml` and the surprise tail from `bounds.yaml` `prior_scoring` at test time; none of their numbers is in the tests. A test that needs the lead record calls `pytest.fail` with a plain message when the table is absent, so collection never errors. Expected scores are computed in the test with `scipy.stats.betabinom` and `scipy.stats.beta`, with the log pmf cross-checked against the closed form.

Run before the build, `BAYES_PIECES=L6,L7`: L6 8 failed, 9 passed; L7 25 failed, 1 passed. Every passing test is a deliberate guard, marked "Guard" in its docstring or below. Without `BAYES_PIECES` all 43 skip. `ruff check` and `ruff format --check` pass on both files.

### test_L6.py
| test | spec clause | before the build |
|---|---|---|
| test_L6_lead_cvr_resolves_to_the_lead_default | C1 id formula with `"table": "lead_records"`, resolution path last hop, R1 evidence ref, C4 approved by its own elicitation | fails: `resolve` body unchanged, returns the purchase id |
| test_L6_paths_absent_from_lead_records_resolve_as_purchase [ctr, conversions_per_dollar, cpm_impressions_per_dollar] | C1 last sentence | passes, guard |
| test_L6_purchase_cvr_id_is_pinned_to_the_base_formula | R15, C3 | passes, guard |
| test_L6_client_cvr_prior_wins_over_the_lead_default_in_the_registry | C1 client hop unchanged | passes, guard |
| test_L6_resolve_priors_lead_without_client_priors | C2, C4 (G8 passes on client data), R2 | fails: unchanged resolve body |
| test_L6_requested_purchase_default_id_on_a_lead_run_fails_g8 | §6 L6, C2, R13 | fails: no G8, the purchase id still resolves |
| test_L6_requested_lead_default_id_on_a_lead_run_passes_g8 | C2 | fails: G8 refuses the lead id |
| test_L6_purchase_resolve_priors_unchanged | C3, R15 | passes, guard |
| test_L6_lead_run_snapshot_names_the_lead_default | §6 L6, C5, R2 (no `records.cvr` id in the snapshot) | fails: snapshot `priors["cvr"]` is the purchase id |
| test_L6_client_cvr_prior_wins_on_a_lead_run | §6 L6, C1 | passes, guard |
| test_L6_lead_run_requesting_the_purchase_default_is_skipped_by_g8 | R13 through `refresh` | fails: the run is `ran`, not `skipped` |
| test_L6_purchase_run_ids_and_seed_equal_the_base | §6 L6, C3, R15: run id, seed and prior ids equal with `conversion_kind` explicit and left at default, at a frozen `utcnow`, and equal to the base formulas | passes, guard |
| test_L6_lead_default_passes_the_predictive_check_under_the_lead_ceiling | R3 | fails: `predictive_check` ignores the kind, ceiling 0.5 not 0.8 |
| test_L6_purchase_predictive_check_keeps_the_purchase_ceiling | R3, C3 | passes, guard |
| test_L6_client_lead_prior_between_the_ceilings_approved_only_as_lead | R3: Beta(4, 8), q99 0.66, refused with the default kind, approved with `conversion_kind="lead"` | fails: `approve` ignores the kind and refuses |

### test_L7.py
| test | spec clause | before the build |
|---|---|---|
| test_L7_two_ads_match_hand_computed_betabinomial_values | §6 L7, §5 per-ad table, R7 tail, R17, sums, log BF vs in_force, R12 days | fails: NotImplementedError (`score_priors`) |
| test_L7_tail_at_k_zero_is_half_the_pmf | R7 (cdf term is 0 at k = 0), R6 cvr no trials, R12 | fails: NotImplementedError |
| test_L7_rows_merge_per_ad_and_date_with_the_later_ok_poll_winning | R4: later poll wins per (ad, date), polls inserted out of order, error poll rows and interrupted poll ignored, rows with no ad id ignored; R12 days | fails: NotImplementedError |
| test_L7_cvr_prefers_observed_drops_none_rows_and_rounds_half_up | R5: observed preferred, None rows and their clicks dropped, 2.5 rounds to 3, "no rows with conversions" | fails: NotImplementedError |
| test_L7_skip_reasons_for_ctr_and_cvr | R6 three strings, R8 same ad set for every candidate | fails: NotImplementedError |
| test_L7_purchase_client_candidates_ordered_and_deduplicated | R9 order, framework_lead for cvr always, dedup; resolution verbatim | fails: NotImplementedError |
| test_L7_lead_client_candidates_ordered_and_deduplicated | R9 first role wins on a collision, kind from `meta.is_lead_event` | fails: NotImplementedError |
| test_L7_client_priors_give_every_role_and_bayes_factors_against_in_force | R9 three roles, R8 log BF relative to in_force | fails: NotImplementedError |
| test_L7_equal_params_with_different_ids_are_both_shown | R9 last sentence | fails: NotImplementedError |
| test_L7_score_reads_the_registry_under_data_dir_and_writes_nothing | R10, §5 "never writes" | fails: NotImplementedError |
| test_L7_non_beta_prior_is_listed_as_not_scored | §5 only Beta scored, R12 `"<path>:<prior_id>"` key | fails: NotImplementedError |
| test_L7_path_with_no_scored_ads_is_in_not_scored | R12 `"<path>"` key, "no ads with data" | fails: NotImplementedError |
| test_L7_no_rows_gives_empty_paths_and_reasons | R18, R12 | fails: NotImplementedError |
| test_L7_write_score_names_the_file_from_scored_at | §5, R11 name and JSON (ISO strings), R8 key `log_bf_vs_in_force` | fails: NotImplementedError (`write_score`) |
| test_L7_write_score_never_overwrites_and_suffixes_collisions | §6 L7, R11 `-2`, `-3` | fails: NotImplementedError |
| test_L7_write_score_leaves_a_foreign_file_in_place | R11, §5 never overwrites | fails: NotImplementedError |
| test_L7_load_latest_score_round_trips | R11 `load_latest_score`, dataclasses rebuilt, None when absent | fails: NotImplementedError |
| test_L7_empty_score_round_trips | R18 file written with empty paths | fails: NotImplementedError |
| test_L7_cli_score_priors_writes_a_file_and_prints_a_line_per_candidate | §5 CLI, §6 line format | fails: NotImplementedError through `cli.main` |
| test_L7_cli_score_priors_with_no_data_writes_and_exits_zero | R18 CLI | fails: NotImplementedError |
| test_L7_live_poll_runs_the_scoring_after_refresh | §5 CLI, R18 (scores after a skipped refresh) | fails: `live poll` never calls the scorer, no file |
| test_L7_a_failing_scorer_never_fails_live_poll | §6 L7, R18 | fails: the scorer is never called (`calls == []`) |
| test_L7_page_without_a_score_file_says_so | §5 Page, R16 `no_prior_score` | fails: no Priors heading on the page |
| test_L7_page_with_a_score_file_shows_candidates_and_in_force_ads | §5 Page headings from `live_columns`, R8 note, R7 tail_low and tail_high, R16 scored_at | fails: NotImplementedError (`write_score`) |
| test_L7_page_marks_a_score_older_than_the_latest_ok_poll_stale | R16 stale mark | fails: NotImplementedError (`write_score`) |
| test_L7_constants_match_the_spec | R5, R6, R9, R12, R17 names and strings in the skeleton | passes, guard |

### How the tests drive the code

`score_priors` runs on `FakeStore` and `FixedClock` with client priors proposed only under a temp `data_dir`, so R10 is checked by the client prior being found. The non-Beta case edits `records.ctr` in the isolated registry copy (`iso.edit_yaml`), because `approve` refuses a non-Beta prior on a rate path. `write_score`, `load_latest_score` and the page tests use a hand-built `PriorScore`, so they depend on neither `score_priors` nor L6. The CLI tests set `BAYES_LIVE_DIR`, `BAYES_CONFIG_DIR` and `BAYES_DATA_DIR` to temp directories and seed a `SqliteStore`. `live poll` runs without network: `live.poll.poll` is replaced by a fake that writes one ok poll, and the config has no economics path so the real `refresh` is skipped quickly. The failing scorer is patched on `live.prior_score` (and on `cli` if a builder imports it there).

The L7 files were checked against a throwaway reference implementation kept outside the repo: 37 of 43 pass on it (the 6 others are the CLI, poll and page tests, which it does not implement). That run found and fixed one test that assumed `paths["cvr"]` exists when cvr has no scored ad.

### Open points for the integrator

1. Dependency: every L7 test that names `framework_lead` or the lead id needs L6. Build L7 on top of L6 or merge L6 first.
2. Frozen L3 conflict: `test_L3_h1_and_five_h2_strings` asserts exactly five h2 headings, and §5 Page adds a Priors section after the engine section. The L7 page tests accept the Priors title as an h2 or an h3 heading after the Engine h2, so an h3 keeps the frozen L3 test passing; an h2 breaks it.
3. R11 order: `20261110T180000Z-2.json` sorts before `20261110T180000Z.json` (`-` is below `.`), so "lexicographically last" picks the unsuffixed file over its later collision. The tests do not pin which of two same-second files is latest; they use distinct seconds.
4. Not fixed by the spec, and so accepted either way by the tests: whether a path with no scored ad is absent from `paths` or present with empty candidates; which role name the ctr purchase default carries when a client ctr prior is in force (`framework_lead` comes first in R9 and resolves ctr to the purchase default); the CLI line's number formats (the test checks path, role key or its `live_columns` label, family, ads scored and ads surprised on a distinct line per candidate); the page's number formats and the scored_at format (ISO, or `%Y-%m-%d %H:%M` UTC).
5. R18 "a scoring failure prints one line": the test asks for the exception's message in the output, not a format.
6. The lead default now in the file, Beta(2.2, 22), has q99 of about 0.28, under the purchase ceiling as well. The predictive check test therefore tells the kinds apart by the ceiling it reports (0.80), and the R3 approval test uses its own Beta(4, 8) client prior, whose q99 sits between the two ceilings.

| File | sha256 (before any freeze) |
|---|---|
| `tests/acceptance/test_L6.py` | `9afaf3fa3cf38554b7a31bb812f3991f712a587044f4f5281b2482df174e143d` |
| `tests/acceptance/test_L7.py` | `70273f0b4169bb09ea7eabfdf07abe5aa01be4d639ea7d618b21f3e84bb90126` |

## L6 and L7 freeze (integrator, 2026-11-10)

Checked by the integrator: 33 failed, 10 passed before the build; every failure is the unchanged `resolve` and `predictive_check` bodies, NotImplementedError in `prior_score`, or the missing scorer call and page section; the 10 passes are the guards the writer lists. Rulings on the writer's open points are build log B18.

| File | sha256 |
|---|---|
| `tests/acceptance/test_L6.py` | `9afaf3fa3cf38554b7a31bb812f3991f712a587044f4f5281b2482df174e143d` |
| `tests/acceptance/test_L7.py` | `70273f0b4169bb09ea7eabfdf07abe5aa01be4d639ea7d618b21f3e84bb90126` |

# Acceptance tests: units and window fix L8, L9 (D51)

Spec `spec/Units_and_Window_Fix_v0.2.md`; §5 (U1 to U11) holds over §1 to §4. Written against the skeleton at f7b2d28.

## Files written

- tests/acceptance/test_L8.py (59 tests as collected; 36 functions; 43 fail before the build, 16 pass as guards)
- tests/acceptance/test_L9.py (35 tests as collected; 13 functions; 25 fail before the build, 10 pass as guards)

Run with `BAYES_PIECES=L8,L9`: 68 failed, 26 passed. `ruff check` and `ruff format --check` are clean on both.

### test_L8.py
| test | spec clause | before the build |
|---|---|---|
| test_L8_final_strings | U9 final strings, `SINGULAR` | passes, guard (skeleton carries them) |
| test_L8_in_money_passes_money_through | C3 unit money | fails: NotImplementedError (`in_money`) |
| test_L8_in_money_prices_a_count_at_the_replacement_cost [clicks, orders, leads] | C3 amount x cost | fails: NotImplementedError |
| test_L8_in_money_is_in_the_replacement_costs_currency | C3 "in the replacement cost's currency" | fails: NotImplementedError |
| test_L8_in_money_is_none_without_a_replacement_cost [x3] | C3 None | fails: NotImplementedError |
| test_L8_absent_unit_is_derived_from_the_target [x3] | U3 derive, incl. an old snapshot's JSON with no `unit` key | passes, guard (skeleton validator) |
| test_L8_contradicting_unit_is_refused [x7] | U3 refuse | passes, guard |
| test_L8_leads_is_allowed_with_target_orders | U3, U9 | passes, guard |
| test_L8_feasibility_estimable_on_the_priced_loss [x3] | C4: 0.5 x $2 = $1, `available` in money | fails: `available` is the raw count 0.5 |
| test_L8_feasibility_marginal_on_the_priced_loss [x3] | C4: 100 x $2 = $200 in (150, 300] | fails: raw 100 reads estimable |
| test_L8_feasibility_below_floor_on_the_priced_loss [x3] | C4: 0.5 x $1000 = $500 > 300 | fails: raw 0.5 reads estimable |
| test_L8_feasibility_without_a_replacement_cost [x3] | C4, U9 `NO_REPLACEMENT_COST`, `available` 0.0 | fails: estimable, no reason |
| test_L8_feasibility_no_tolerance_is_checked_first | U9 order: D16 first; `available` 0.0 with no money | fails: `available` is the raw count 3.0 |
| test_L8_feasibility_no_tolerance_with_a_cost_reports_the_money_loss | C4 `available` in money under D16 | fails: `available` 3.0, not $6 |
| test_L8_survival_floor_not_applied_to_a_count [x3] | C5, U7: no block, one `SURVIVAL_NOT_APPLIED` | fails: both options blocked |
| test_L8_survival_notice_only_when_a_floor_is_set | U7 | passes, guard |
| test_L8_survival_floor_still_applies_to_money | §8.2 C3 unchanged for money | passes, guard |
| test_L8_reallocate_net_benefit_is_priced_benefit_minus_switching_cost | §4 "benefit x cost minus switching cost", C6 slots, params, `VALUED_AT`, U7 once | fails: not_knowable (every option breaches the floor) |
| test_L8_hold_when_the_priced_benefit_does_not_cover_switching | C6 hold, loss in money | fails: reallocates on the raw 20 clicks |
| test_L8_stop_test_loss_is_priced | U1 `loss=` and `loss_guarantee`, params, `VALUED_AT` | fails: expected loss 0.5, not $50 |
| test_L8_stop_projection_uses_the_priced_loss | U1 `_projected_required` | fails: raw 2 is within tolerance, not_knowable |
| test_L8_stop_without_a_replacement_cost_is_not_knowable | U1 None projection carries `NO_REPLACEMENT_COST` | fails: text absent |
| test_L8_ctr_run_sets_unit_and_pooled_cost_over_compared_ads | C2, U4 clicks pooled over compared ads only (a third ad in the poll is left out), stored unrounded (1/3), set before `decision_feasibility` | fails: `replacement_cost` None |
| test_L8_cvr_cost_skips_cells_with_no_known_count [purchase -> orders, lead -> leads] | U4 cells with no known count drop their spend; U9 unit leads | fails: `replacement_cost` None; lead run unit is orders |
| test_L8_zero_clicks_gives_no_replacement_cost | §4 zero clicks, C4 reason, U6 None loss and the decision's reason | fails: decision estimable |
| test_L8_zero_spend_gives_no_replacement_cost | U4 spend <= 0 | fails: decision estimable, no reason |
| test_L8_lead_ctr_run_is_in_clicks | U9 leads only for target orders | fails: `replacement_cost` None |
| test_L8_jovannah_shape_allocates | §4 Jovannah shape, U6 not `allocation.ALL_BLOCKED`, U7 notice once in params and assumptions, U6 share-weighted loss x cost, C6 params and `VALUED_AT` | fails: `replacement_cost` None (and today the run is not_knowable, ALL_BLOCKED) |
| test_L8_no_survival_notice_without_a_floor | U7 | passes, guard |
| test_L8_lead_cvr_stop_rec_loss_is_priced | U1 where the pipeline reaches it (lead cvr, immature cohorts), U9 | fails: unit orders, not leads |
| test_L8_contribution_run_unchanged | U5 | passes, guard (see below) |
| test_L8_socket_result_carries_unit_and_cost | U10, frozen floats kept | fails: KeyError `unit` |
| test_L8_socket_result_money_unit | U10 | fails: KeyError `unit` |
| test_L8_cli_demo_ctr_states_the_money_verdict | U2 `_amount`, `_verdict` runs the real test | fails: "no money tolerance applies to a loss in clicks" |
| test_L8_render_recommendation_money_comparison_counts | U2 render: recommendations money, comparisons in unit | fails: the recommendation shows "5.0 clicks" |
| test_L8_claims_accept_the_replacement_cost | U2 `claims/check._index` money value | fails: "$1 matches no bundle value" |

### test_L9.py
| test | spec clause | before the build |
|---|---|---|
| test_L9_click_window_days [15 codes] | C9, U8: Meta code 7, `7d_click_1d_view` 7, `28d_click` 28, `1d_click` 1, `1d_view` None, `per_conversion_action` None, `17d_click` 17, `7d_clicks` None, 14 and 90 parsed, LinkedIn 90 | fails: NotImplementedError |
| test_L9_click_window_days_refuses [`0d_click`, two click components x2] | U8 ValueError | fails: NotImplementedError is not a ValueError |
| test_L9_old_regex_is_gone | U8 `_CLICK_WINDOW` and the generator's `CLICK_WINDOW` deleted | fails: both exist |
| test_L9_meta_code_takes_the_seven_day_default_curve | C9 through `_click_window_days` and `lag_model` | fails: ValueError "names no click window" |
| test_L9_off_table_and_windowless_codes_still_raise [x5] | U8, A14: 14, 90, 0, `1d_view`, `7d_clicks` raise at `lag_model` | passes, guard |
| test_L9_per_conversion_action_keeps_the_d38_path | D38.3 | passes, guard |
| test_L9_lag_notices_on_the_meta_code | U8, A13: no false "names no click window" | fails: the notice is there |
| test_L9_lag_notices_consults_the_shared_parser | U8 `lag_notices` uses the one parser | fails: the old regex is used, the replaced parser is never called |
| test_L9_generator_reads_the_meta_code | U8 `simulate/write.py` | fails: ValueError "needs click_window_days" |
| test_L9_generator_keeps_the_codes_it_read [x3] | U8 | passes, guard |
| test_L9_generator_refuses_a_code_with_no_click_window | U8 whole components (`7d_clicks`) | fails: old regex reads 7 |
| test_L9_lead_run_with_the_meta_code_adjusts_for_lag | §4 L9: no "conversion lag not adjusted", no "names no click window", 7-day default curve in the FunnelData | fails: "conversion lag not adjusted" |
| test_L9_lead_run_with_the_usual_code_is_unchanged | regression | passes, guard |

### How the tests drive the code

Direct checks build comparisons through the `Comparison` constructor, so the U3 validator runs, and call `in_money`, `decision_feasibility`, `survival_check`, `reallocate` and `stop_or_continue`. The switching cost for the reallocate tests is set in the isolated registry copy (`iso.edit_yaml("channels", ...)`). Pipeline checks run `refresh` on `FakeStore` with real economics as in test_L5, wrapping `pipeline.execute` to keep each `RunContext`; a rerun with another metric, a subset of variants or a pinned clock goes to its own data dir. Each expected replacement cost is computed twice: by hand in the test, and from first principles over the `FunnelData` cells the run used (`pooled_cost`, U4 as written).

U5 base expectation. The contribution test runs the purchase poll, then the captured request again with metric contribution, `pipeline.utcnow` pinned at 2026-11-07T18:30Z, a survival floor of $1 so the money floor path runs, into a fresh data dir. The four pins were taken on the unmodified checkout at f7b2d28 by a scratch pytest file outside the repo that imported this test's `Env` and printed: `run_id`; sha256 of `json.dumps(comparison.model_dump(mode="json", exclude={"unit", "replacement_cost"}), sort_keys=True)`; the same for the decision without `checked_at`; the recommendation ids (`rec_367ec186` allocate, `rec_56105a71` the not_knowable stop). The test also recomputes each id from the base `make_id("rec_", ...)` payload and checks no `unit`, `replacement_cost`, `VALUED_AT` or survival notice appear. The comparison digest holds floats from exact integration; it was taken on darwin, Python 3.13, the project venv.

Both files were also run against a throwaway prototype of L8 and L9 in a scratch worktree outside the repo (never committed, removed): 94 of 94 pass on it. That run found and fixed three test errors: the registry rounds money to 0 decimals, so expected strings now come from `fmt_money`/`fmt_amount` rather than "x.00 USD"; and the parser spy built its lag model after replacing the parser.

### Open points for the integrator

1. Frozen conflict, known: `tests/unit/p11/test_p11_d38.py` line 143 asserts "USD tolerance" not in the ctr demo; `test_L8_cli_demo_ctr_states_the_money_verdict` asserts the money verdict. U2 and B23 revise line 143.
2. `VALUED_AT` `{cost}` has no format in the spec. With `money_decimals: 0` a cost per click of $0.62 reads "1 USD per click". The tests accept any precision and check the shown number is the cost rounded to the decimals it is written with. The owner may want two decimals for a per-unit cost.
3. `params["replacement_cost"]` has no stated form; the tests accept Money, `{"amount": ...}`, a string or a number. Same for `uncertainty["replacement_cost"]` in the socket reply.
4. The allocate loss under a count unit may be rounded before or after pricing; the tests allow 0.006.
5. Not pinned: `Comparison.replacement_cost` for unit money (U5 excludes it from the check); whether `NO_REPLACEMENT_COST` follows the D16 reason when both apply (only `reasons[0]` is pinned); which field of the stop not_knowable carries `NO_REPLACEMENT_COST` (the test searches the recommendation's JSON).
6. Read as in scope: `unit`, `replacement_cost` and `VALUED_AT` on stop recommendations too. C6 names reallocate and hold, U1 names only the loss; the request for these tests said recommendations generally.
7. Not tested: spend in another currency than the economics gives None (U4), because the pipeline refuses mixed currencies before compare; `lag_notices` on a two-click code not raising (A13 asked for it, U8 does not say it).
8. `test_L9_lag_notices_consults_the_shared_parser` needs `lag_notices` to look up `lag.model.click_window_days` when called, not through an alias bound at import. `lag_model` has a parameter of the same name, so the builder will need a module-level route to the function; the test does not touch `lag_model`'s route.
9. The generator tests call the private `simulate.write._windows`; there is no public seam short of writing a full scenario.
10. U11 stands as the owner's note: on the Jovannah shape the priced loss is cents, the decision stays estimable, and the test does not assert the decision status.

| File | sha256 (before any freeze) |
|---|---|
| `tests/acceptance/test_L8.py` | `56256fc345df2b02cdcf7c28ba6c13c9ab5e4d2d64828d3ffdb7e3620ea31f43` |
| `tests/acceptance/test_L9.py` | `d0118bc9b619156102a8282bc6892e0d459f7ad07e69398ec73e62a45ff24631` |

## L8 and L9 freeze (integrator, 2026-11-10)

Checked by the integrator: 68 failed, 26 passed before the build; the failures are NotImplementedError in the stubs, counts tested against money, and Meta's window code refused; the 26 passes are the writer's marked guards. Rulings on the writer's points: build log B23.

| File | sha256 |
|---|---|
| `tests/acceptance/test_L8.py` | `56256fc345df2b02cdcf7c28ba6c13c9ab5e4d2d64828d3ffdb7e3620ea31f43` |
| `tests/acceptance/test_L9.py` | `d0118bc9b619156102a8282bc6892e0d459f7ad07e69398ec73e62a45ff24631` |
