# L10 blind review (commit c366af4 against base fdf5f0e)

Reviewer: blind, evidence only. Spec: `Mismatch_Lead_Lag_Horizon_Fix_v0.2.md` §2 (C1 to C3), §6 (S3, S4, S6, S10), D52, D53, B25, B26. Probes: `tests/review/l10/test_probes.py` on branch `review/L10`. Interpreter checked: `bayesian_marketing.__file__` is in the review worktree.

## Findings

None. No probe fails.

## What I checked and found correct

1. C1, the cap. `quantity_feasibility` lowers by `min(1, len(mismatches))`; reasons are still appended for every mismatch in `q.notices` order; the required-events projection and its reasons are untouched. Probes `test_probe_cap_shapes[1..4]` (wide width stays below_floor; estimable width with 1 to 4 mismatches is marginal with exactly that many mismatch reasons) and `test_probe_zero_median_with_mismatches` (q50 <= 0 with two mismatches is still below_floor) pass. joint_failed and platform_modeled are in `REGIME_NOTICE_KEYS`, so D26 and D28 get the same one-level treatment.
2. G2 in `status_registry/registry.py` recomputes the status with `quantity_feasibility`, so it follows the cap and does not carry its own mismatch count. No other `_downgrade` or mismatch counter exists in `src`.
3. Lead runs with no lag anywhere. `test_probe_lead_three_ads_no_lag_anywhere[ctr|cvr]` (three ads, so the other fit route, not just the two-ad fixture): every mature fraction 1.0, `configuration["lag"]` None, `LEAD_NO_LAG` once in run notices, and no text containing "lag" in any run notice (other than `LEAD_NO_LAG`), quantity notice, feasibility reason or recommendation. `fit_lag` has no other caller; `derive_all` gets `[]` for a lead, so no quantity carries `LEAD_NO_LAG` or `lag_approx` (S4). The stop path is not reached for a lead (S3), since `_immature_cohorts` sees no immature cohort.
4. Purchase runs byte for byte. I ran the same purchase run (ctr and cvr, pinned clock) under `21f1b21` (before the skeleton) and under c366af4 and diffed the dumps of run id, seed, config, config hash, run notices, route, every quantity (summary, notices, reasons, required), recommendation actions and gate results. The only differences are 12 quantity statuses going from below_floor to marginal, which is D52 itself. Run id, seed, notices and configuration are identical.
5. `_request_key` excludes `horizon_basis` for both kinds (S6); the frozen pins from 21f1b21 hold. `test_probe_lead_basis_once_and_last_ctr`: with a basis set on a lead run it is the last run notice, appears once, and appears nowhere else in the snapshot (not in route notices, not in a quantity).
6. S10 order holds for lead and purchase (fit, lag, LEAD_NOT_VALUED, WINDOW_CHANGED, basis), as the frozen tests and my read of the notice assembly agree.
7. Frozen suite: `tests/acceptance/test_L10.py` and `tests/unit/l10` give 51 passed with `BAYES_PIECES=L10`. Full-suite result with `BAYES_PIECES=all` is recorded at the foot of this file.

## Notes that are not findings (no failing test possible)

- The docstring above `REGIME_NOTICE_KEYS` in `floors/estimability.py` still says "Each downgrades the status one level". After D52 they do so together, not each. Stale wording only.
- For a lead run `fit_lag` is skipped, and with it `window_code`, which used to raise ValueError when there were no performance rows. A lead run with no rows now fails later, in assembly or earlier at G1, rather than in the lag step. No spec clause covers it.
- `horizon_basis=""` is appended as an empty notice, because the check is `is not None`. Matches "when it is set".

## Full suite

`BAYES_PIECES=all` over the whole suite: 992 passed, 36 failed. Every failure is in `tests/acceptance/test_L11.py` (L11 not built on this branch) or `tests/acceptance/test_P8.py` (recordings under `data/` not read by me and absent in the worktree). None is in a piece L10 touches.
