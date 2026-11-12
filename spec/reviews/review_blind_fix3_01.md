# Blind review 01 of Mismatch Cap, Lead Lag and Budget Horizon Fix v0.1 (D52, D53; L10 and L11)

Reviewed cold, then against the code on eng-bayes-v2. Spec line numbers are for
`spec/Mismatch_Lead_Lag_Horizon_Fix_v0.1.md`. Nothing was run; every claim is from reading code and
tests. The C5 worked example was checked by hand: 1256.24 x 8196 / 243.76 = 42,238.85, floor 42,238.

Short answers to the questions asked:

1. Is the blueprint complete? Mostly for the mismatch cap (one stacking site only). Not for the
   horizon: `decision/stopping.py` compares the remaining volume's cost with the whole test budget
   (A1), and two other default-horizon builders are neither fixed nor listed as out of scope (A2).
   The lead-lag change leaves a dead path and a stale notice route (A3, A4).
2. Frozen tests that break beyond the L9 test the spec names: six, listed in A5 to A9. The spec
   names one L9 test; a second L9 test breaks too.
3. "Unchanged byte for byte": purchase runs yes, with one real exception. Lead requests hash as the
   whole model, so the new field changes their run ids and seeds even when it is None (A10). The
   "run id equal to base when horizon_basis is None" claim is true for purchase and false for lead.
   Every live refresh run id changes by design, which breaks a pinned digest (A6).
4. Is C4/C5/C6 well defined? The store API exists (`polls(client, limit=)` plus `rows(poll_id)`).
   Not well defined on: `fmt_count` and the two `fmt_money`s, the singular for impressions, the
   mixed-currency row, `since`, the as-of poll, and the economics loader (B1 to B8).
5. Ambiguities two builders would split on: B1 to B10.

## A. Blueprint gaps

**A1. `stop_or_continue` compares the cost of the remaining volume with the whole test budget.**
`decision/stopping.py` lines 226 to 233: `cost.amount > econ.test_budget.amount` gives
`OVER_BUDGET_REQUIREMENT` ("the test cannot be finished within the budget") and `test_budget` goes
into `params`. After D53 the run's horizon is the budget left, but this check still uses the
budget as set, ignoring what is spent. A test with $243 spent and a projected need of $1,400 reads
as affordable. The path is reached only for conversion-based comparisons with immature cohorts, so
it does not touch the live ctr view today, but the spec's own premise ("the money still to be
spent") is violated one function away. Proposed: either add to out of scope in §5 with the reason
("stopping still tests against the whole budget; spent money is not passed to it"), or give
`stop_or_continue` an optional `remaining_budget: Money | None` that pipeline fills from the same
`spent`. Recommend the first, with a D53 follow-up line, since pipeline has no store.

**A2. Two other builders of the default horizon.** `atmaos/socket.py` lines 136 to 141 take the
registry's 1,000 in the metric's unit when the window carries no horizon; `simulate/replay.py`
line 91 (`_horizon`) does the same; `cli.demo_horizon` (cli.py line 309) is the third and the only
one the spec excludes. D53 (1) reads "when a request sets no horizon, the default is ...", which
covers socket. Proposed: §5 says that D53 (1) is implemented for the live refresh only, names socket
and replay as unchanged (no store, no spend), and D53's wording changes to "the live view's default".

**A3. With no lag, the lead stop path is unreachable.** `pipeline.py` line 1156 area:
`_immature_cohorts` counts cells with mature fraction below `min_maturity`; with every fraction 1.0
it is 0, so `stop_or_continue` never runs for a lead run. That is correct but it makes the lead
branches of `stop_or_continue` (D51 U1, units "leads") dead from the pipeline. Say so in §2 so
nobody "fixes" it, and see A8 for the test that exercised it.

**A4. `LEAD_NO_LAG` goes onto quantity notices as well as the run notices.** `pipeline.py` line
1065 passes `[n for n in lag_notes]` as `extra_notices` to `derive_all`, which stamps them on every
`CONVERSION_BASED` quantity (lines 746 to 748). With `lag_notes == [LEAD_NO_LAG]` every cvr and cpa
quantity carries "no lag curve: a lead is counted when it happens (D53)", and the live page and
render print quantity notices (`reporting/render.py` line 132, `live/view.py` line 374). It is not a
regime notice (`REGIME_NOTICE_KEYS`), so no downgrade. Whether that is wanted is not in the spec;
C2 says only "no `lag_approx` notice on any quantity". See B3.

**A5. Frozen test breaks: `tests/unit/p4/test_p4_units.py` lines 33 to 43
(`test_regime_notice_downgrades_one_level`).** Line 43: an estimable width with `lag_approx` and
`too_few_ads` is asserted `below_floor`. Under C1 it is `marginal`. This is the direct opposite of
D52 and needs a revision with a build-log row, like D30. `tests/unit/integrator/test_d26_fallback_cap.py`
line 24 allows marginal or below_floor, so it survives. `test_P4.py`, `test_P5.py` line 169
(`!= "estimable"`), `test_P7.py` line 144 and `test_P10.py` do not break. Proposed: change line 43
to `marginal` and add the spec's second case (marginal width, two mismatches, below_floor).

**A6. Frozen test breaks: `tests/acceptance/test_L8.py::test_L8_contribution_run_unchanged` lines
733 to 753.** It pins `BASE_RUN_ID = "run_b2053c7f"` and `BASE_REC_IDS` (lines 723, 726), computed
from a refresh-built request replayed with `Env.rerun` (lines 285 to 297, `model_copy` of
`call["request"]`). After L11 every refresh request carries `horizon_basis` (the fallback also has a
sentence, C6), so the request key gains a field and the run id and the recommendation ids change.
Proposed: in that test's rerun pass `horizon_basis=None`, which keeps the guard's purpose
(contribution output unchanged) and exercises C3's "None leaves the id equal"; record it in the
build log. Alternative: `_request_key` always excludes `horizon_basis`, but then B7 below.

**A7. Frozen test breaks: `tests/unit/l5/test_l5_lead.py::test_purchase_request_hashes_as_before_the_field`
lines 54 to 58.** `old = req.model_dump(...)` with only `conversion_kind` deleted now still holds
`"horizon_basis": None`, while `_request_key` excludes it, so the equality at line 58 fails.
Proposed: also `del old["horizon_basis"]`. The L6 twin
(`tests/acceptance/test_L6.py` lines 359 to 400) survives under the spec as written: its request
comes from refresh, `horizon_basis` is set, and its key (line 392, `model_dump(exclude=conversion_kind)`)
includes the set field exactly as `_request_key` does. It would break if `_request_key` always
excluded the field, which is a reason to keep "exclude when None".

**A8. Frozen test breaks: `tests/acceptance/test_L8.py::test_L8_lead_cvr_stop_rec_loss_is_priced`
lines 701 to 717.** It runs a lead cvr comparison with immature cohorts and demands exactly one
`stop_test` or `continue_test` recommendation (line 710 to 711). With C2 a lead run has no
immature cohort (A3), so there is none and `len(stops) == 1` fails. Proposed: the same U1 check
moves to a purchase cvr run (cvr from `config()` without the lead event, unit "orders", cost per
order from `pooled_cost(..., "orders")`); keep a lead assertion that no stop recommendation is made.

**A9. Frozen test breaks: both lead tests in `tests/acceptance/test_L9.py`.** The spec names
`test_L9_lead_run_with_the_meta_code_adjusts_for_lag` (line 266). It also breaks the "guard"
`test_L9_lead_run_with_the_usual_code_is_unchanged` (lines 281 to 292): line 289 asserts
`snap.configuration["lag"] == {"source": "registry_default", "window": "7d_click_1d_view"}` for a
lead run, which is now `None`. The guard says "passes before the build" and it will not pass after.
Proposed: §5 and the build log name both; the usual-code lead test asserts `lag` None and
`LEAD_NO_LAG` in the notices. Also note both go through `refresh`, which runs `ctr`, so "a lead
run has every mature fraction 1.0 ... and a cvr whose median sits near the raw rate" (spec §4) needs
a cvr request: use the pattern at `test_L5.py` lines 246 to 255 (`model_copy` with metric cvr and
`pipeline.horizon_unit("cvr")`).

**A10. Lead requests hash as the whole model, so the new field changes them.** `_request_key`
(pipeline.py lines 893 to 898) returns `request` itself for a lead request; `canonical_json` then
dumps every field, `horizon_basis: null` included. Lead run ids and seeds change even with None,
contradicting C3 ("every existing run id and seed is unchanged") and the §4 claim. No frozen test
pins a lead run id (the only lead key test, `test_l5_lead.py` line 60, asserts `!=`), so nothing
breaks, but the claim is false as written. Proposed: C3 states the key rule for both branches:
`exclude={"horizon_basis"}` when it is None, for purchase (also excluding `conversion_kind`) and for
lead. Add a unit test that a lead request with `horizon_basis=None` keys as it did before.

**A11. Old behaviour on a missing economics file changes.** Today pipeline's `_economics`
(pipeline.py lines 283 to 287) returns None on `FileNotFoundError`, and the run ends as a G9
`GateFailure`, so refresh says `skipped` with the gate's reasons (L4 spec C2). C7 loads economics
inside refresh, "a load failure falls under the existing exception handling", which is
`failed: FileNotFoundError`. `tests/unit/l4/test_review_l4.py` line 117 accepts either, so it
survives, but the status and the live page text change. Proposed: refresh calls
`pipeline._economics(manifest, config_root)` (or a public wrapper) and treats None as "no test
budget", so a missing file still reaches the gate. See B6.

## B. Ambiguities

**B1. `fmt_money` and `fmt_count` are not one function each.** `fmt_count` exists only in
`claims/vocab.py` line 80 (`round(x)` with thousands separators). `fmt_money` exists in
`decision/reallocation.py` line 94, `claims/vocab.py` line 67 and as a local in `cli.py` line 110;
all print "1,256.24 USD", but the spec's own example uses "$1,500". Proposed: name
`claims.vocab.fmt_money` and `claims.vocab.fmt_count`, and write the C5 sentence out for the
worked example: "horizon: 42,238 impressions, the 1,256.24 USD left of the 1,500.00 USD test
budget (spend counted since 2026-11-07) at 29.74 USD per 1,000 impressions".

**B2. `{per_1000}` is undefined.** It is not said whether it is cost per unit times 1,000, nor its
rounding. 243.76 / 8196 x 1000 = 29.7413...; `fmt_money` gives 29.74, `fmt_unit_cost` (decision/units.py
line 46, `unit_money_decimals`) gives more decimals. For clicks it would be four digits. Proposed:
`fmt_money(Money(cost_per_unit * 1000, currency))`, unrounded until printed, and the horizon
amount computed from the unrounded cost (as C5 reads), so a reader cannot reproduce the amount
from the printed rate exactly; say so in a comment.

**B3. Is `LEAD_NO_LAG` a quantity notice?** See A4. Two builders will differ: one keeps
`lag_notes=[LEAD_NO_LAG]` and passes it to `derive_all`, one passes `[]` to `derive_all` and appends
only to the run notices. Proposed: run notices only (the quantities simply have no lag notice), so
the pass to `derive_all` is `[]` for a lead; state it in C2 and add "no quantity carries
`LEAD_NO_LAG`" to the check. If the owner wants it on the page, say so instead.

**B4. Order of run notices.** Today `notices = [*fit_notices, *lag_notes]`, then `LEAD_NOT_VALUED`
(line 1164), then `WINDOW_CHANGED` (line 1167). C3 says `horizon_basis` is appended "after the lag
notices". Before or after `LEAD_NOT_VALUED` and `WINDOW_CHANGED`? Proposed: last of all, after
`WINDOW_CHANGED`, and the test asserts `notices[-1]`. Also C2 "`LEAD_NO_LAG` in place of any lag
notice" is clear only if `fit_lag` is skipped, which it is; the `window_code` read in `fit_lag`
(line 1015) is skipped too, so a lead run with no performance rows no longer fails there.

**B5. Singular for impressions.** C6's last row uses `{singular}`; `decision/units.py` line 18
`SINGULAR` covers clicks, orders, leads, not impressions. Proposed: spec the map
`{"impressions": "impression", "clicks": "click"}` (a new constant in `live/horizon.py`, not an edit
to `SINGULAR`, which L8 tests pin), and the ordinary exact sentence for the row.

**B6. The economics loader.** C7 says "`config.economics_path` under `config_root`, as `pipeline`
loads it". Pipeline does not load by path: it loads by id, `config_root/economics/<stem>.json`
first and then `BAYES_CONFIG_DIR` or the repo's `configs/` (`core/records.py` lines 174 to 188),
and the economics_path's directory part is ignored. Proposed: `load_economics(stem, config_root)`
exactly as `pipeline._economics`, with FileNotFoundError mapped to "no test budget" (A11), and the
other errors (bad JSON) falling to the existing `failed` handling.

**B7. When `horizon_basis` is set, what is in the key?** C3 includes the sentence in the hash. Every
poll's budget horizon differs anyway, so identity is unaffected, but the fallback basis is a
constant string and still changes ids against the pre-L11 refresh runs (A6). Decide and write it:
exclude only when None (the spec) or never include (simpler, and a reproducibility argument: the
basis is derived text, the horizon amount is already in the key). Either is workable; the spec
picks the first, so A6 and A7 follow from it.

**B8. Which polls does `spend_to_date` read, and as of when?** C4 reads the whole store, so
refreshing an older poll (as `tests/acceptance/test_L4.py` line 214 seeds two polls) counts spend
polled after it, and a repeat refresh gives a different horizon. Proposed: add `as_of: datetime |
None = None` (poll `started_at` bound, inclusive), which refresh passes as `poll_rec.started_at`;
"newest ok poll" then means newest at or before it. Also state the tie-break when two polls share
`started_at` (poll_id order), the platform filter (all platforms summed, or `poll_rec.platform`
only), and that undercount is possible for dates no poll's rolling `lookback_days` window covered
(`live/poll.py` lines 33 to 39) with a sentence in the basis or the decision log.

**B9. Mixed currency gives the wrong reason.** C4 returns `(None, None)` for rows in more than one
currency, and C6 row 2 then says "no spend to date could be read from the store" instead of row 3's
"different currencies". Row 3's `spent` clause can only fire for one currency that differs from the
budget's. Proposed: `spend_to_date` returns `(None, None)` only for no rows; for several currencies
it returns `(None, earliest)`, and `budget_horizon` treats `spent is None and since is not None` as
the currency row (checked before row 2). Or add a third return value. Pick one in the spec.

**B10. `since` when `spent` is set but `since` is None, and the amount type.** The signature allows
`since` None; the sentence needs a date. Proposed: both or neither, assert it. Also say the amount
is `Decimal(int(floor(...)))` (so `Horizon.amount` prints as 42238 and not 42238.0000), the floor
uses `Decimal` division with the default context, and a `window_rows` empty list lands on row 5
("no impressions in the window"). C6's "amount < 1" row is also reachable only for tiny budgets;
no cap for huge ones (a $1,500 budget at $0.0001 per impression is 15 million) is stated, so say
"no cap".

**B11. Rows for ads outside the comparison.** In the refresh path the comparison takes every ad in
the poll (`variants=ads`, refresh.py line 94), so `window_rows` equals the compared ads and the
question does not arise there; `spend_to_date` does include ads from older polls that are gone from
the latest window, which is wanted. The L8 test at line 576 ("ad_c is in the poll but not compared")
is a pipeline rerun with a variants subset, not a refresh. Proposed: one sentence in C5 that
`window_rows` is the poll's rows, all ads, and that the pooled cost therefore differs from the
replacement cost (compared ads only, D51) when they are not the same set.

**B12. Cost of reading the store.** `spend_to_date` reads `rows()` of every ok poll on every
refresh; with hourly polls that grows linearly per refresh and quadratically over a campaign (31
polls in a day for Jovannah, D47). Fine now; say so, or add a `Store` method later. It cannot stop
early at the newest polls since older dates are only in older polls.

**B13. D53 and §1 E3 say "about $30 of Jovannah's spend", "1,000 clicks vs impressions".** The
text is right (refresh builds impressions for ctr, refresh.py lines 131 to 135) and D53 records the
correction; no action beyond keeping §1 and D53 in step.

## Checked, no finding

- Only one place stacks mismatches: `floors/estimability.py` lines 131 to 134. The docstring at
  lines 37 to 39 ("Each downgrades the status one level") must change with C1. `_inherited`
  (pipeline.py line 692) takes the worst input status and does not count notices; the signed
  quantities are unaffected. `decision_feasibility` does not read regime notices.
- `lag_approx` is stamped only in `derive._notices` (derive.py line 237) when the state's
  `flag.lag_adjusted` is set (conjugate.py line 210), which needs a mature fraction below 1; with
  `lag is None` (pipeline.py lines 491 to 492) it never is. C2's "no `lag_approx` notice" holds.
- `CompareRequest` is `Frozen` with defaults, so adding `horizon_basis: str | None = None` is
  safe for every existing constructor and for stored snapshots.
- `quantity_feasibility` after C1 keeps the required-events projection: `required` depends on
  `width_status`, not `status` (estimability.py lines 148 to 160).
- Store API: `polls(client_id, limit=10**9)` (prune.py line 29 uses it) and `rows(poll_id)` exist on
  `SqliteStore` and `FakeStore`; interrupted polls read back with status "interrupted" and are
  excluded by an `ok` filter.
- `test_L8`'s `B.economics()` default has `test_budget=None` (tests/fakes/builders.py line 202), so
  refresh-based tests fall to the fallback with the default amount of 1,000 and unit impressions;
  `tests/acceptance/test_L4.py` line 200 (`snap.horizon.unit == "impressions"`) holds.
