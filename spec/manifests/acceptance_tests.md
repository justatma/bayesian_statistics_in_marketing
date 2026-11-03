# Acceptance tests manifest (ENG-BAYES, spec v0.3 §15)

Written 2026-11-03 by the acceptance-test writer. Frozen: builders make these pass and do not edit them.

## Files

| Path | Contents |
|---|---|
| `tests/__init__.py`, `tests/acceptance/__init__.py`, `tests/oracle/__init__.py`, `tests/fakes/__init__.py` | package markers so `tests.fakes` and `tests.oracle` import |
| `tests/acceptance/conftest.py` | autouse `iso` fixture: tmp copy of `registries/` as `BAYES_REGISTRY_DIR`, tmp `BAYES_DATA_DIR`, cwd = tmp, `RECORD` unset, registry cache cleared; `iso.edit_yaml(name, fn)` |
| `tests/acceptance/test_S0.py` ... `test_P11.py` | one module per piece |
| `tests/oracle/north_pier.py` | §9.2 answer key, recomputed values with table values in comments |
| `tests/oracle/a1_reference.py` | frozen fixed-revenue-per-conversion reference for P5 A1 |
| `tests/fakes/builders.py` | valid core objects (pass G10 and other validators), North Pier FunnelData, `all_examples()` |
| `tests/fakes/exports.py` | canonical headers from `channels.yaml`, export writer, independent export reader for checking simulator output |
| `tests/fakes/neighbours.py` | `FakeSampler` (scripted DiagnosticsReports, fixed state), `FakeCompiler` (records specs) |
| `tests/fakes/synth.py` | seeded generators: negative dependence (12 ads, rho -0.6), A1 data, fractional conversions, lag-heavy |
| `tests/fakes/atmaos_base.py` | local copy of `BayesianResult` (frozen, extra=forbid) and the G3.4 key set |
| `tests/fixtures/exports/{meta,google_ads,linkedin,ga4,orders}_{canonical,aliases}.csv` | hand-made exports: canonical first-listed headers; alias files use other listed spellings, case and whitespace variants |

## Tests by piece

Parametrized tests are listed with their cases.

**S0** (`test_S0.py`, no piece gate: S0 has merged; see open question 1)
- `test_S0_schema_examples_validate`
- `test_S0_registry_swap_needs_no_code`
- `test_S0_G10_rejects_bad_evidence_combos` [incremental_without_holdout, realized_without_orders_pull, deterministic_class_on_conjugate_route, deterministic_route_with_posterior_class, platform_conversions_not_platform_attributed, sampled_without_diagnostics, realized_with_ga4_but_no_orders, ok_control]
- `test_S0_no_model_client_importable`
- `test_S0_extra_G10_rejects_synthetic_in_client_bundle`

**P1** (`test_P1.py`)
- `test_P1_quarantine_fuzz` (hypothesis, 500 examples, Google Ads export, 7 invalid kinds)
- `test_P1_reads_each_platform_export` [meta, google_ads, linkedin, ga4, orders] x [canonical, aliases]
- `test_P1_attribution_change_splits`
- `test_P1_conversion_typing_C8`
- `test_P1_stale_channel_blocks`
- `test_P1_extra_duplicate_order_id_quarantined`
- `test_P1_extra_no_change_no_split`
- `test_P1_extra_channel_model_from_registry`

**P2** (`test_P2.py`)
- `test_P2_ground_truth_matches_totals`
- `test_P2_exports_read_by_channel_maps` [10 scenarios]
- `test_P2_seed_reproducible`
- `test_P2_manifest_marked_synthetic` [10 scenarios]
- `test_P2_extra_all_scenarios_present`

**P3** (`test_P3.py`)
- `test_P3_oracle_ctr_day_two`
- `test_P3_oracle_cvr_day_fourteen`
- `test_P3_oracle_expected_contribution`
- `test_P3_oracle_expected_opportunity_loss`
- `test_P3_oracle_break_even`
- `test_P3_oracle_evpi_evsi`
- `test_P3_oracle_sample_size`
- `test_P3_oracle_dependence`
- `test_P3_oracle_economics`
- `test_P3_exact_and_sampled_agree`
- `test_P3_G9_without_economics` [unapproved, no_loss_tolerance]
- `test_P3_extra_funnel_state_store_immutable`
- `test_P3_extra_conjugate_quantities_valid`
- Not written: `test_P3_oracle_delivery_mix` (open question 6). Rows owned elsewhere: floors (P4), prior from cohorts (P7 `test_P7_cohort_prior_oracle`), hold (P9 `test_P9_hold_oracle`).

**P4** (`test_P4.py`)
- `test_P4_oracle_floors`
- `test_P4_less_data_never_improves_status` (hypothesis, 200 examples)
- `test_P4_decision_basis_governs_D9` [5, 10, 15, 20, 25 against tolerance 10]
- `test_P4_run_record_rejects_update_delete`
- `test_P4_no_provisional_template_reachable`
- `test_P4_extra_floor_edges_follow_registry`
- `test_P4_extra_no_tolerance_not_knowable`
- `test_P4_extra_decision_multiplier_from_registry`
- `test_P4_extra_status_registry_publish_and_G2`
- `test_P4_extra_published_status_immutable`

**P5** (`test_P5.py`)
- `test_P5_uncoupled_spec_rejected`
- `test_P5_small_account_routes_conjugate`
- `test_P5_A1_roas_wider_with_modeled_value`
- `test_P5_recovers_negative_dependence`
- `test_P5_fractional_uses_gamma_obs`
- `test_P5_sbc` (`@pytest.mark.slow`)
- `test_P5_extra_dynamics_needs_min_days`

**P6** (`test_P6.py`)
- `test_P6_rhat_fixture_fails_G3` [rhat, ess_bulk, ess_tail, divergences, ppc cvr, ppc ctr]
- `test_P6_each_fallback_step_emits_notice`
- `test_P6_quarantined_state_refused_by_derive`
- `test_P6_extra_G3_thresholds_from_registry`
- `test_P6_extra_fallback_stops_at_first_pass`
- `test_P6_extra_run_diagnostics_leaves_passed_unset`

**P7** (`test_P7.py`)
- `test_P7_unapproved_prior_blocks_fit`
- `test_P7_predictive_check_refuses_implausible` [cvr Beta(50,10) refused, ctr Beta(30,70) refused, cvr Beta(1,49) ok, ctr Beta(2,98) ok]
- `test_P7_cohort_prior_oracle`
- `test_P7_import_promoted_requires_id`
- `test_P7_lag_thinned_likelihood_recovers_cvr`
- `test_P7_extra_lag_default_below_min`

**P8** (`test_P8.py`)
- `test_P8_meta_replay_parses`
- `test_P8_google_ads_replay_parses`
- `test_P8_linkedin_replay_parses`
- `test_P8_ga4_replay_parses`
- `test_P8_empty_account_flagged`
- `test_P8_recordings_contain_no_secrets`
- `test_P8_fields_in_facts_pack` [meta, google_ads, linkedin, ga4]

**P9** (`test_P9.py`)
- `test_P9_hold_oracle`
- `test_P9_premature_stop_refused`
- `test_P9_below_floor_continues_or_not_knowable`
- `test_P9_every_recommendation_templated_and_approval_required`
- `test_P9_extra_unknown_switching_cost_is_costly`
- `test_P9_extra_below_floor_decision_holds`
- `test_P9_extra_allocation_floor_and_cap`
- `test_P9_extra_audit_separates_sources`
- Not written: `test_P9_survival_floor_respected` (open question 7).

**P10** (`test_P10.py`)
- `test_P10_A_ai_property` (120 bundles, 40 tiny/fractional-shaped, 5 injections each)
- `test_P10_tiny_campaign_not_knowable_block`
- `test_P10_G7_blocks_untraced`
- `test_P10_client_report_refuses_synthetic`
- `test_P10_diagnostics_appendix_real`
- `test_P10_extra_incremental_needs_holdout`
- `test_P10_extra_narrative_needs_passing_G5`

**P11** (`test_P11.py`)
- `test_P11_result_fits_BayesianResult`
- `test_P11_evidence_matches_G3_4`
- `test_P11_record_approval_G6`
- `test_P11_smoke_every_scenario` [10 scenarios]
- `test_P11_shadow_replay_writes_scores`
- `test_P11_extra_unapproved_prior_fails_G8`

## Commands run

| Command | Exit | Result |
|---|---|---|
| `.venv/bin/python /private/tmp/claude-502/oracle/recompute.py` | 0 | §9.2 rows recomputed (below) |
| `.venv/bin/python /private/tmp/claude-502/oracle/floors.py` | 0 | floors widths under q50 vs mean denominators |
| `.venv/bin/python /private/tmp/claude-502/oracle/synth_check.py` | 0 | generator checks: neg-dep seeds, A1 widths, lag coverage, D10 monotonicity grid (0 non-monotone steps) |
| `.venv/bin/python -c ...a1_ads() means` | 0 | A1 frozen values |
| `.venv/bin/pytest -q` (baseline, before writing) | not captured | no tests ran |
| `BAYES_PIECES=S0 .venv/bin/pytest tests/acceptance/test_S0.py -q` (first) | 1 | 1 failed (my registry-swap test collided with the autouse fixture); fixed |
| `BAYES_PIECES=S0 .venv/bin/pytest tests/acceptance/test_S0.py -q` (final) | 0 | 12 passed |
| `.venv/bin/ruff check tests` (final) | 0 | All checks passed |
| `.venv/bin/ruff format --check tests` (final) | 0 | 25 files already formatted |
| `.venv/bin/pytest -q` (final) | 0 | 12 passed, 135 skipped |
| `BAYES_PIECES=all .venv/bin/pytest -q -x --co` | 0 | 147 tests collected |
| `BAYES_PIECES=all .venv/bin/pytest -q -p no:randomly -m "not slow"` | 1 | 134 failed, 12 passed, 1 deselected |

Failure reasons in the last run: every P1, P2 (except one), P3, P4, P5, P6, P7, P9, P10, P11 failure is `NotImplementedError` from a stub (P10 `client_report_refuses_synthetic` asserts the exception is not `NotImplementedError` and fails on that). The rest fail on missing build artifacts, not on test code: `test_P2_extra_all_scenarios_present` (no `data/scenarios/*.yaml`), P8 replay and empty-account tests (`data/recordings/<platform>/request.json` missing), `test_P8_recordings_contain_no_secrets` (no recordings), `test_P8_fields_in_facts_pack` (connector modules `connectors/<platform>.py` missing). `pytest-randomly` is not installed, so `-p no:randomly` is a no-op.

## Oracle values (recomputed with scipy 1.18.1)

| Row | Recomputed | Table | Frozen |
|---|---|---|---|
| CTR day two | means 0.020000, 0.0171429; 95% CI A 0.0144582-0.0264064, B 0.0120405-0.0231147; P(A>B) 0.754818 | 2.000%, 1.714%; 1.446-2.641%, 1.204-2.311%; 0.7548 | yes |
| CVR day fourteen | means 0.020000, 0.0487179; CI A 0.0092056-0.0348043, B 0.0296595-0.0721465; P(B>A) 0.990652 | 2.000%, 4.872%; 0.9206-3.480%, 2.966-7.215%; 0.9907 | yes |
| Floors at D10 | with q50 (the §6.1 definition): CTR A 0.2525, B 0.2733; CVR A 0.5552, B 0.3716. With mean: 0.2505, 0.2709, 0.5356, 0.3657 | 0.251, 0.271, 0.536, 0.366 | statuses only (marginal, marginal, below_floor, marginal); widths NOT frozen, discrepancy |
| Expected contribution | A -610.000, B 88.3861; P(B higher) 0.962379 | -$610.00, +$88.39; 0.9624 | yes |
| Expected opportunity loss | A 704.2109, B 5.8247 | $704.21, $5.82 | yes (±$0.01) |
| Break-even | thresholds 0.0390625, 0.0459559; P(A clears) 0.00826528, P(B clears) 0.574063 | 3.906%, 4.596%; 0.008265, 0.5741 | yes |
| EVPI, EVSI | EV now 200; EVPI 600; P(pos) 0.45; posteriors 0.666667, 0.181818; EVSI 250 | same | EV now, EVPI, EVSI tested; P(pos) and posteriors frozen as constants but no interface returns them |
| Sample size | 5300.739171 | 5,300.74 | yes (±0.01) |
| Prior from cohorts | kappa 829.508; Beta(16.5902, 812.918); discounted Beta(4.14754, 203.230); mean 0.0347284 | 829.51; Beta(16.59, 812.92); Beta(4.148, 203.23); 3.473% | yes |
| Dependence | paired 1.6, 2.0, mean 1.8; independent 1.6, 8.0, 0.4, 2.0, mean 3.0 | same | yes |
| Delivery mix | 42, 22 | 42 → 22 | constants only; no test (open question 6) |
| Economics | break-even CPA 32, ROAS 2.5 → 3.3333; extra (not in table): P(A clears) 0.000172480, P(B clears) 0.127346 at $24 contribution | $32, 2.5 → 3.333 | yes |
| Hold | 0.7×1500 + 0.3×400 − 250 = 920 < 1000 | same | yes |

## Contract assumptions

All pieces (`tests/acceptance/conftest.py`)
1. Every persistent store (run record SQLite, funnel states, status registry, prior proposals and approvals) lives under `BAYES_DATA_DIR`; every registry read goes through `core.registries`, so `BAYES_REGISTRY_DIR` redirects it.

P1
2. G1 staleness in `read_export` is judged against today's date; a stale channel raises `GateFailure` (gate "G1") for that platform only. `channel_model` for a stale as-of either returns a model with `is_stale` True or raises G1.
3. With no attribution column, rows take `manifest.attribution_window[platform]`.
4. A row currency that is not ISO 4217 ("QQQ") is an unknown currency and is quarantined.
5. Meta "Attribution setting" values pass through unchanged as `attribution_window`.
6. Export dates are ISO in fixtures; order timestamps with offsets are normalized to UTC.

P2
7. Scenarios are `data/scenarios/<name>.yaml` for the ten §9.1 names.
8. `generate` writes exactly one DatasetManifest JSON (any name) besides `ground_truth.json`; `ManifestFile.path` is relative to `out_dir`.
9. North Pier scenarios reproduce Manuscript totals for any seed (day 2: 2,000/40 and 2,000/34; day 14: clicks 400 and 340, conversions 8 and 18 as the platform column or 26 order rows).
10. Exports may carry `ignored_columns`; every other header is the canonical one.

P3
11. `fit_conjugate` takes the PriorSet keyed by the default registry paths (`ctr`, `cvr`, `conversions_per_dollar`), and that is sufficient.
12. `derive` picks the ad by `scope.ids["ad"]` (= FunnelData entity id).
13. `Comparison.options[i]` names `options[i]`; per-option dicts use those names.
14. CTR compare uses `Objective("clicks", impressions horizon)`, CVR uses `Objective("orders", clicks horizon)`, money rows compare `derive("contribution_per_click")` under `Objective("contribution", 1,000 clicks)`; `p_exceeds_break_even` = P(contribution per click > 0).
15. `compare` raises `GateFailure` (gate "G9") for unapproved economics or no loss tolerance.
16. A samples DistributionSpec for one Quantity is a parquet with a single column; rows align across quantities.
17. A sampled FunnelState's parquet has columns `<entity>.<parameter>` (ctr, cvr, cpm in $ per 1,000 impressions, aov) plus global columns (P5: `rho`).
18. DecisionProblem sample payoffs read the column named after the option; a signal-type TestDesign signals positive with probability `sensitivity` on draws where the arm's payoff > 0, else `false_positive_rate`.
19. `funnel_state.save` of a different state under an existing id raises.

P4
20. `quantity_feasibility` result target is 0.20 (registry); test builds PrecisionTarget from `bounds.yaml`.
21. Decision L = expected loss of the option with the lowest expected loss.
22. No tolerance: `decision_feasibility` raises G9 or returns below_floor with reason "no loss tolerance set".
23. Run record is one SQLite file under `BAYES_DATA_DIR` (.sqlite/.sqlite3/.db); `read(kind, **filters)` takes the class name as kind and field-equality filters.
24. `Guarantee.slots` carries placeholders by name; `render_guarantee` raises for a template id outside the four kinds or marked provisional.
25. `status_registry.publish` raises G2 for an unresolvable bound_ref; republishing a better status without new data raises.

P5
26. `compile_model` raises `UncoupledFunnelError` even for a spec built with `model_construct`; raises ValueError for random_walk on fewer than `min_days_for_dynamics` days.
27. The joint model is fitted with the PriorSet of every record in `registries/priors/default.yaml`.
28. NUTS state parquet has `<entity>.<parameter>` columns and `rho` for the CTR/CVR correlation.
29. Negative-dependence, A1 and fractional data come from `tests/fakes/synth.py`, not P2.
30. SBC: `inference.sampler_numpyro.sbc_ranks(spec, priors, n_ads, n_fits, n_draws, seed) -> dict[str, list[int]]` (ranks 0..n_draws). The test uses 6 ads, 100 fits, 199 draws, 20 bins, chi-square p > 0.01 / n_params.
31. A1 is checked as: ROAS 90% width > 1.1 × (CVR 90% width × frozen mean order value × clicks/spend), both from the same NUTS state.

P6
32. `g3` returns (report with passed set, GateResult) without raising; failing reasons name the metric or PPC stage.
33. `fit_with_fallback` looks up `model_spec.compile.compile_model` and `sampler_numpyro.NumpyroSampler` at call time so fakes can stand in; step 4 uses the real conjugate route.
34. `derive` refuses a quarantined state with an exception other than NotImplementedError; `funnel_state.load` still returns it.

P7
35. A proposed PriorRecord names its client in `resolution_path[0]` as `client:<id>`.
36. `resolve` raises G8 for an unapproved client prior; falls back to the default with hops recorded, last hop naming "default".
37. `approve` refuses implausible priors by raising; approved records carry `approved_by` and a `predictive_check`.
38. `prior_from_cohorts(rates, discount)` returns the discounted (a, b); discount 1.0 means none.
39. `import_promoted` takes a PriorRecord JSON dump; empty or None promotion id raises ValueError.
40. `lag_model` estimates whole-day lags from `ordered_at - first_click_at`; `mature_fraction` is `cdf[a]`, `cdf[-1]` beyond the curve. Lag-heavy data from `tests/fakes/synth.py`.

P8
41. Recordings in `data/recordings/<platform>/` and `data/recordings/meta_empty/`, each with `request.json` = {config: ClientConfig, window: [start, end]}.
42. `BAYES_REPLAY_DIR` set → `pull` replays from it and opens no socket (sockets are blocked in the tests).
43. Each connector module `connectors/<platform>.py` defines `ENDPOINTS` and `FIELDS`; each string appears in facts pack F2 (meta), F3 (google_ads), F4 (linkedin), F5 (ga4).

P9
44. In `reallocate`, `options[0]` is the incumbent; switching cost from ChannelModel; the hold test sets $250 (`{amount: "250", currency: USD}`) on every ad platform.
45. Notices on a Recommendation appear somewhere in its JSON dump.
46. `stop_or_continue` cites every (entity, day) cell with clicks > 0 for the compared options.
47. A below-floor decision's `required` is volume in the horizon unit, priced via test_design and compared with `test_budget`.
48. `allocate` puts the split in `params["allocation"]`.
49. `guarantee_report` reads run_record and keys `by_source` by OutcomeRecord.source.

P10
50. G5 matches percents against every bundle quantity's summary values at `percent_decimals: 1`.
51. Narrative names options by `Comparison.options` strings; "X is better than Y" is a comparative; its decision basis comes from the bundle's recommendations.
52. A rejecting GateResult names the injected claim in a reason (number as written, verb, or option name).
53. The 120 property bundles are built from fakes shaped like the scenarios, not from P2 + P11.
54. `render` writes HTML at `html_path`; G7 failure raises `GateFailure("G7")` listing quantity ids; a client bundle with synthetic quantities (built without validation) is refused.
55. The not-knowable block shows `available` and `required` as integers and does not show the estimate.

P11
56. Datasets come from P2 `generate`; `dataset_uri = "file://" + manifest path`; window = min/max export date.
57. `priors={}` means defaults; an unknown or unapproved prior id raises G8.
58. `posterior[variant]["quantity_id"]`; `uncertainty` has `currency`, `run_id`, `recommendation_ids`.
59. `observation_evidence` keys are snake_case G3.4 names (`tool_version`, `dataset_snapshot_hash`, `window`, `metric`, `priors`, `configuration`, `segments`, `result`, `uncertainty`, `tool_result_id`).
60. `recommendations(run_id)` dicts carry `recommendation_id`, `requires_human_approval`, `guarantee_text`; every run proposes at least one.
61. `record_approval` raises G6 for empty `decided_by`, unknown id, or a decision outside approved/rejected.
62. `replay` writes ground-truth OutcomeRecords readable via `run_record.read("OutcomeRecord", source="ground_truth")`.

## Open questions for the integrator

1. S0 is not in `tests/merged_pieces.txt`, so a `piece("S0")` gate would skip the S0 tests in the default run. `test_S0.py` carries no gate. If S0 is added to `merged_pieces.txt`, the gate can be restored.
2. §9.2 floors row: the table widths (0.251, 0.271, 0.536, 0.366) use a mean denominator; §6.1 says q50 (0.2525, 0.2733, 0.5552, 0.3716). Which definition stands? Statuses agree either way; widths are not frozen.
3. `FunnelState` has no `data_pull_ids`, so `derive(name, state, scope, econ)` cannot fill `Provenance.data_pull_ids`, and G10's platform-conversion rule then has nothing to act on.
4. `registries/priors/default.yaml` holds only ctr, cvr and conversions_per_dollar. The conjugate route also models CPM and order value, and the joint model needs LKJ, scale and value priors. Where do approved defaults for those come from (I10)?
5. `quantity_feasibility(q, target)` has no event count input, yet `available`/`required` are defined as event counts (D10). Not asserted.
6. Delivery-mix row (42 → 22): no interface computes a click-mix-weighted rate from per-ad rates (a FunnelState carries no click weights). `test_P3_oracle_delivery_mix` not written.
7. §8.2 C3 survival floor: `reallocate(c, decision, econ, run_id)` and `allocate(c, run_id)` receive a Comparison with expected values only, no 5th-percentile contribution. `test_P9_survival_floor_respected` not written until Comparison (or the signature) carries per-option quantiles.
8. No interface turns PlatformPulls into FunnelData (pipeline internal). P5/P7 tests build FunnelData directly.
9. How does `DatasetManifest.economics_id` resolve to ClientEconomics (no store or loader is specified)? P11 tests depend on it.
10. `reallocate` gets no platform or scope, so it cannot pick a ChannelModel for the switching cost or set `Recommendation.scope.platform`.
11. EVSI row: P(pos) and the two posteriors are not returned by any §6.3 function; only EVPI and EVSI are tested.
12. Facts packs F3, F4, F5 do not exist yet in `spec/facts/`; `test_P8_fields_in_facts_pack` fails for google_ads, linkedin and ga4 until they do.
13. GA4 exports carry no currency; `SiteRow.revenue` needs one. Source unspecified (ClientConfig?). Not asserted.
14. The registry YAML format for a non-null `learning_phase_switching_cost` is unspecified; the P9 hold test writes `{amount: "250", currency: USD}`.

## Left undone

Nothing within scope beyond the two tests withheld as open questions 6 and 7.

## Addendum (D22)

Tests added (answering open questions 6 and 7):
- `tests/acceptance/test_P3.py::test_P3_oracle_delivery_mix`
- `tests/acceptance/test_P9.py::test_P9_survival_floor_respected`

Contract assumptions (also in the test files)
- `mix_weighted_rate(rates, clicks)` is sum(rate x clicks) / sum(clicks), keyed by ad id.
- An option whose `Comparison.value_q05` is below `ClientEconomics.survival_floor` is never recommended. `reallocate` reads the floor from `econ`. `allocate` takes no economics, so it resolves `c.economics_id` through `core.load_economics` (`configs/economics/<id>.json` under `BAYES_CONFIG_DIR`). A blocked option has share 0 or is absent from `params["allocation"]`; a blocked switch target means action is not "reallocate"; the Recommendation JSON contains "survival floor" (case-insensitive).

Commands run
- `.venv/bin/ruff format tests` exit 0; `.venv/bin/ruff check tests` exit 0
- `BAYES_PIECES=P3,P9 .venv/bin/pytest -q <the two ids>` exit 1 (2 failed, both NotImplementedError, as required)
- `.venv/bin/pytest -q` exit 0 (12 passed, 137 skipped)
