# Blind review 01 of Units and Window Fix v0.1 (D51, L8 and L9)

Reviewed cold, then against the code on eng-bayes-v2. Spec line numbers are for
`spec/Units_and_Window_Fix_v0.1.md`. Nothing was run; every claim below is from reading code and tests.

Short answers to the questions asked:

- Is the §1 list of places where a count meets money complete? No. It misses four places (A1 to A4).
- Is replacement cost computable where the spec puts it? Yes, from `FunnelData` in `execute`, but the rule as written is wrong in three ways (A6 to A8).
- Does skipping the survival floor contradict a decision? Not a numbered decision, but it amends §8.2 C3 of the v0.3 spec and D40, and D51 must say so (A12).
- Do contribution runs stay byte-identical? Run id, seed, config hash and recommendation ids: yes, provided the new params keys are count-only (A9). Snapshot bytes: no (A10).
- Frozen tests: one existing test breaks (A5); none that construct `Comparison` break.
- Window parser: no frozen test breaks, but `lag_notices` still uses the old regex (A13).

## A. Blueprint gaps

**A1. `stopping.py` is a fourth place a count meets money, and it is reached by count comparisons.**
Spec §1 lists three places (lines 8 to 18). `decision/stopping.py::_projected_required` computes `loss = min(c.expected_loss...)`, then `loss <= tol` and `(loss / tol) ** 2` with `tol = econ.loss_tolerance.amount` (money). `stop_or_continue` also passes `c.expected_loss[best]` into `Recommendation.expected_loss` (`out(..., loss=...)`) and calls `loss_guarantee`. `pipeline.execute` calls `stop_or_continue` when `cq in CONVERSION_BASED` and cohorts are immature, and `CONVERSION_BASED` contains `cvr`, whose objective is `orders` (a count). After L9 more cohorts will be immature, so this path runs more often. C6 and C7 name reallocate, hold and allocate but not stop. Add C7b: `stop_or_continue` converts through `in_money` in `_projected_required`, in the `loss=` it passes to `out`, and in `loss_guarantee`. When the cost is None the projection returns None and the existing not_knowable branch carries `NO_REPLACEMENT_COST`.

**A2. `cli.py` formats recommendation amounts as counts.**
`cli.py` `_amount(m, target)` and `_verdict(loss, tolerance, target)` (lines 84 to 113, 209, 266 to 274) print `r.expected_loss` as "N.N clicks" and say "no money tolerance applies to a loss in clicks" whenever the comparison target is not contribution. After C6 and C7 the recommendation's loss is money, so the demo would print dollars labelled clicks. Spec C8 says "display unchanged", which is wrong for this file. `_amount` and `_verdict` must key on the thing displayed: comparison amounts by `c.unit`, recommendation amounts always money, and the verdict now runs the real tolerance test.

**A3. `reporting/render.py` has the same defect, and claims have a new checkable number.**
`render._fmt_value(r.expected_loss, _bundle_target(bundle))` (lines 194, 230, 233) formats recommendation amounts as counts when the bundle has one count objective. After C6 these are money. `_comparisons` (line 266) is fine if it keys on `c.unit`. In `claims/check.py::_index`, `money_ok` takes comparison amounts and recommendation amounts but not `c.replacement_cost`. `VALUED_AT` puts "{cost} each" in the guarantee assumptions, and `render._guarantee_prose` joins assumptions into the prose, so a narrative that quotes the cost is flagged as an unsupported figure. Add `replacement_cost` to `ix.money_ok` and add the render and CLI changes to the build list. D40 (2) ("comparisons and recommendations under a clicks or orders objective show counts") is partly superseded and D51 must say so.

**A4. Old snapshots and old runs deserialize with the wrong unit.**
`Comparison.unit` defaults to "money" (C1). Every run snapshot already on disk for a ctr or cvr run (Jovannah's live runs, `RunSnapshot.model_validate_json`) holds counts and will load as unit "money" with no replacement cost. Anything that reads `c.unit` (render, cli, `in_money`) then treats counts as money. Fix: derive the unit from the objective, in a `model_validator(mode="before")` on `Comparison` that sets `unit` from `objective.target` when the stored unit is absent, and refuses a stored unit that contradicts the target. Better still, make `unit` a property of `objective.target` and store nothing; but C1 asks for a field, so the validator is the minimum. Without this the spec has two sources of truth.

**A5. A frozen test contradicts L8: `tests/unit/p11/test_p11_d38.py::test_demo_ctr_runs_and_a_bad_pair_stops_cleanly` line 143.**
It asserts `"USD tolerance" not in text` with the comment "a loss in clicks is not held against money". D51 holds it against money by design, so once A2 is done the demo prints "within the 150.00 USD tolerance" (or "above"). This needs a frozen-test revision with a decision-log entry (precedent: D30). No other frozen test asserts count text; the grep for "clicks"/"orders" formatting found only this one.

**A6. Replacement cost: "per-row rule of D34 and R5" is not the rule the model uses (spec line 34).**
The fitted CVR reads conversions per ad-day cell in `model_spec/plan.py` (observed if not None, else reported), and `assemble_funnel_data` writes orders-file counts into every day of any ad that has joined orders. R5 (`live/prior_score.py::_conv`) is per raw row. FunnelData has no rows, so the helper must work per cell. Write it as: for each cell of each compared ad, use observed if not None, else reported if not None, else skip the cell (and its spend, see A7).

**A7. The denominator must cover only the cells the numerator covers.**
Spec line 33: "total spend divided by total clicks or total conversions". If an ad-day has spend but a `None` conversion cell (a row missing the count), its spend is in the numerator and no conversions are in the denominator, so cost per order is overstated. Sum spend only over cells whose conversion count is known, for unit orders. For unit clicks, all cells count.

**A8. Replacement cost ignores lag maturity, but the orders it prices are lag-adjusted.**
The CVR posterior is lag-adjusted (mature_fraction); recent cells have fewer conversions than they will. Spend divided by raw observed conversions overstates cost per order on immature windows, and L9 will make more cells immature for Jovannah. The spec says "as observed" and does not say whether this is accepted. Needs a ruling (B3). It does not matter for unit clicks.

**A9. "Contribution comparisons are unchanged byte for byte" holds only if the new params and assumptions are count-only.**
`reallocation.build` hashes `params` and `guarantee.statement_math` into `make_id("rec_", payload)`, and `run_record.append(rec)` stores canonical JSON by that id. C6 says `params` carry `unit` and `replacement_cost` and the assumptions carry `VALUED_AT`. If a builder adds them for unit money too, every contribution recommendation id changes. Say: for unit money none of these three is added; for a count unit all three are. Also keep the contribution `statement_math` strings as they are. Run id (`manifest`, `request`, `at`) and `config_hash` (`configuration` dict) do not include the comparison, so they are safe.

**A10. Snapshot bytes are not unchanged, so the check wording is wrong (spec line 77).**
`RunSnapshot.comparison` serializes `Comparison`, which now gains `"unit": "money"` and `"replacement_cost": null` on every contribution run. "Comparison ... equal the base's" cannot be a byte comparison of the snapshot. Define the check as: the comparison dumped with `exclude={"unit", "replacement_cost"}` equals the base's, the decision (`Feasibility` minus `checked_at`, which is `utcnow`) equals the base's, and recommendation ids and run id are equal. State that `checked_at` is excluded. Old snapshots still load (defaults), and nothing hashes a Comparison (checked: `inputs_hash`/`make_id` are never applied to one).

**A11. `allocate` and the "no economics" path.**
C7 says "wherever it compares with tolerance, floor or switching cost". `allocate` itself compares nothing with a switching cost; it calls `decision_feasibility(c, econ)` (inside, with economics loaded from disk, separate from `execute`'s own call), calls `survival_check`, and builds `expected_loss = round(sum(share * expected_loss), 2)`. Specify: `allocate` converts the share-weighted loss with `in_money` (None gives `expected_loss=None` and the NO_REPLACEMENT_COST reason carried by the decision). The `_no_economics_feasibility` branch (D30: economics file not found) sets `available` from the raw count loss; say it stays a count there with currency unknown, or is None. Also, `execute` never calls `reallocate`; the only recommendation producers on the pipeline path are `allocate` and `stop_or_continue`. The "Jovannah's shape" check (line 80) is therefore an `allocate` check, and its text is `allocation.ALL_BLOCKED` ("every option breaches the survival floor"), not `reallocation.ALL_BREACH` (which adds "the incumbent included"). Name the string.

**A12. C5 changes a documented rule without saying so.**
§8.2 C3 of the v0.3 spec (quoted in `reallocation.py` and `allocation.py` docstrings): an option whose `value_q05` breaches the floor is never recommended. D40 (2) left the unit open. The spec's reason is "a count has none under D33", but D33 is about leads and subscriptions having no value model, not about clicks and orders; the citation does not carry the claim. The rule itself is defensible (a dollar floor on contribution value cannot be tested against a click count), but D51 must (a) state it as an amendment to §8.2 C3, (b) say a client's survival floor is silently inactive under ctr and cvr runs, with the notice as the only trace. Details left open: `survival_check(c, floor, options)` is called once per recommendation, so "one notice per run" (line 51) is really one per recommendation; and the notice must appear only when a floor is set (existing code returns `(set(), [])` for `floor is None`).

**A13. L9 leaves `lag_notices` on the old regex.**
`lag/model.py::lag_notices` calls `_CLICK_WINDOW.match(lag.attribution_window) is None` to decide whether the code "names no click window". For `1d_view_7d_click_1d_ev` the old regex does not match, so after the C9 parser change the run would gain `NO_WINDOW_DEFAULT` ("names no click window; the 7-day default curve is used"), which is false. Spec line 69 says "the notices are otherwise unchanged", which is exactly the bug. Specify one function `click_window_days(code) -> int | None` (None for no click component, ValueError for two or for 0 days), used by `_click_window_days`, `lag_notices` and the `lag_model` path, and delete `_CLICK_WINDOW` as a second source. `lag_notices` takes `lag.attribution_window`; it must treat a two-click code as "no click window" without raising (it cannot have been constructed anyway).

**A14. C9 cases against every frozen window test and registry code.**
Checked against `tests/unit/p7/test_p7_unit.py` and `test_P7.py`, `test_p11_d38.py`, and the codes in `registries/channels.yaml` and the tests:

- `7d_click_1d_view` gives 7; `28d_click_1d_view` 28; `1d_click` 1; `7d_click` 7; `28d_click` 28. All as before.
- `test_unknown_window_code_raises` must keep raising ValueError: `none`, `property_setting`, `per_conversion_action` (no click component), `1d_view` (none), `0d_click` (parsed as 0, must be rejected before the registry lookup, as now), `14d_click` and `90d_click` (parsed, then no registry median). Spec line 67 to 68 does not say a 0-day or off-table window still raises; add it.
- `per_conversion_action` with `click_window_days` stays the D38.3 path.
- LinkedIn `90d_click_90d_view` parses to 90, has no registry row, raises ValueError, and keeps "conversion lag not adjusted". Unchanged and not in scope, but name it so nobody reads L9 as covering LinkedIn.
- Parse by whole components, not substring, so `17d_click` is not read as 7 and `7d_clicks` is not a click window. Specify the regex: components split on `_`, a click window is a component matching `^\d+d$` immediately followed by the component `click`.
- `simulate/write.py` has its own `CLICK_WINDOW = ^(\d+)d_click`, used to read scenario codes. It is a different job (generator) but shares the bug for Meta's real code. Out of scope or in scope? (B6.)

**A15. `in_money` and the helper module do not say what happens on mismatch or zero.**
Spec C2 returns None for "zero units"; it does not cover zero or negative spend, which gives cost 0 and makes every loss free, so decision feasibility reports "estimable" for any count loss. Treat spend <= 0 as None. C3 returns "in the replacement cost's currency" but `decision_feasibility` and `loss_guarantee` already raise on a currency mismatch with the tolerance; say `in_money` result is then checked as before. Say whether `replacement_cost.amount` is stored unrounded (recommended, the existing `_money` uses `Decimal(repr(float))`) and that the converted loss is rounded only where it is displayed.

**A16. Text slots in C4 and C5 are not defined enough to build.**
`NO_REPLACEMENT_COST` uses `{unit}` and `{unit_singular}`; the spec does not say who computes the singular ("clicks" to "click", "orders" to "order"), and "no observed cost per clicks" is how the first half reads unless `{unit}` is the singular. Give both constants as final strings. In C4 the order of checks is not stated: the no-tolerance reason (D16, `NO_TOLERANCE_REASON`) versus `NO_REPLACEMENT_COST`; and what `available` holds when there is no money to put in it (the current code uses 0.0 for an unknown count, `estimability.py` line ~155).

**A17. The `unit` Literal has no "leads".**
D46 runs a lead cvr under `Objective(target="orders")`, so the unit is "orders", and the NO_REPLACEMENT_COST text and `VALUED_AT` would say "orders" for leads, and `compare` does not know `conversion_kind`. D46 (2) says "a lead is never valued", and the replacement cost prices a lead at its cost per lead. That is a cost, not a sale value, and the spec says so (line 37) but D51 must state it against D46 (2), and the labels need a ruling (B2).

## B. Undecided items, each with a recommended answer

**B1. Pooled or per-option replacement cost?** Spec C2 says one cost over the compared ads. Recommend pooled: a per-option cost breaks the property that choosing the best option in counts equals choosing it in money and makes `expected_loss` non-additive. Say it in C2.

**B2. Label for leads.** Recommend: unit stays "orders" internally (the compare target), and the pipeline passes the display word ("leads") into the notice and `VALUED_AT` text when `conversion_kind == "lead"`. Alternative: add "leads" to the Literal and set it in `execute` with `model_copy`. Either is fine; pick one in the spec.

**B3. Lag-adjust the replacement cost?** Recommend no for now: price at observed cost per order, say so in the `VALUED_AT` assumption ("observed, not lag-adjusted") and let the existing "waiting for late conversions" notice carry the caveat. A lag-adjusted denominator (conversions divided by mature fraction) is the better number but adds a second estimate to a rule meant to be simple.

**B4. Where the unit lives.** Recommend the validator in A4 (derive from the objective when stored absent, refuse a contradiction), and keep the field.

**B5. Survival floor under counts.** Recommend accept C5 as written, with D51 amending §8.2 C3 and D40 (2), the notice only when a floor is set, and "one notice per recommendation" as the wording.

**B6. Window parser in the generator.** Recommend leave `simulate/write.py` alone but call the shared `click_window_days` there too so a scenario can name a Meta code; one parser is the point of A13. If the owner wants L9 minimal, leave it and note it as open.

**B7. Socket reply.** `atmaos/socket.py::result_of` returns `expected_loss` as bare floats from the comparison; for ctr and cvr these are counts with no unit. Recommend adding `unit` and `replacement_cost` to `uncertainty` (new keys, not changing the frozen `BayesianResult` fields checked by `test_P11_result_fits_BayesianResult`) so a consumer is not misled.

**B8. Is the tolerance test still meaningful at the default horizon?** On a ctr run the horizon is 1,000 impressions; 0.39 clicks at a cost of about a dollar is about $0.40 against $150, so the decision stays "estimable" after the fix. The unit fix is right, but the owner should know the Jovannah decision does not flip to "marginal"; the tolerance is "per decision at its horizon" (D16) and a 1,000-impression horizon makes it vacuous. Recommend a note in D51, and a separate ruling on the default horizon for count objectives.

**B9. Decision-log entry.** D51 must list what it amends: D40 (2) (recommendations now show money), §8.2 C3 (survival floor), D9's wording ("expected loss against tolerance" now means priced loss), and the frozen-test revision in A5. Recommend writing these four lines into D51 before the build.

## Frozen-test sweep (for the builders)

- Construct `Comparison(`: only `tests/fakes/builders.py::comparison` (all default unit money, contribution objective). Unaffected.
- `B.objective("orders"/"clicks")` with `compare`: `test_P3.py`, `test_p3_review.py`; they assert amounts only. Unaffected.
- `decision_feasibility(`: `test_P4.py`, `test_p4_units.py`, `test_p9_units.py`, all contribution money. Unaffected.
- `survival_floor` and `value_q05`: `test_P9.py`, `test_p9_units.py`, contribution money; assert the text "survival floor". Unaffected as long as A9 holds.
- `test_L6.py` line 386 to 398 (run id, seed, priors equal the base's): unaffected, since run id and seed never see the comparison.
- `test_p11_d38.py` line 143: breaks (A5).
- `test_P11.py` line 107 to 108: `expected_loss` values must stay floats in the socket result; they do if `result_of` is not changed (B7).
- Window: `test_p7_unit.py` lines 151 to 166 and 175, `test_P7.py`, `test_p11_d38.py` lines 186 to 203: unaffected if A14 is followed.
- Not reached: `test_design` does not use `Comparison`; `simulate/replay.py` runs `METRIC = "contribution"` only, so `not_knowable_correct` and regret stay in money; `audit/report.py` reads `Recommendation` money, which stays money.

## Counts

Part A: 17 gaps. Part B: 9 undecided items. One frozen test breaks (A5).

Three most important:

1. A1, A2, A3: the §1 list is incomplete. `stopping._projected_required`, `cli._amount/_verdict` and `render._fmt_value` all still treat the recommendation's amounts as counts or compare counts with the tolerance, so L8 as written leaves live defects and breaks `test_demo_ctr...` line 143 (A5).
2. A13: the new parser leaves `lag_notices` on the old regex, so Jovannah's run would swap "conversion lag not adjusted" for a false "names no click window" notice.
3. A6 to A9 together: the replacement-cost rule (per-cell, denominator restricted to known cells, lag, zero spend) and the "byte for byte" guarantee (count-only params and assumptions, snapshot bytes cannot be equal) are underspecified in ways two builders would resolve differently; A4 (old snapshots loading as money) is a close fourth.
