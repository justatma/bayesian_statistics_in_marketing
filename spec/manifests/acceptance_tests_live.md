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
