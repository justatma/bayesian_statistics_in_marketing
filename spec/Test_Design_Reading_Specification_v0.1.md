# Reading a proposed test, read_test_design (J6), v0.1

27 November 2026, the Bayesian Engineer. This answers the AtmaOS integrator's request of 11 November (`atmaos/spec/suggestions/request_to_bayesian_engine.md`). The engine's reply of the same day, agreed in AtmaOS spec 22 AS5, set the inputs (`reply_from_bayesian_engine_2026-11-11.md`). Arkwright's third stage turns a suggestion into a test. The Creative Intelligence Engine drafts what is tried, on whom and in what form. This function reads the draft's measurable shape and says whether a test like it can give an answer for this client, and what it would take. It never changes what an arm receives or who the test is for. Its remedy is a word and a number, and it carries no free text. The state of a live test is a separate call, not this one.

## The call

`bayesian_marketing.atmaos.socket.read_test_design(design: dict) -> dict`. Plain JSON-native dicts go both ways. The engine never imports atmaos (F7). It reads no store, no run and no file, so it is a pure function of `design` and the registries. A malformed design (see "Refused") raises `ValueError` naming the field. A design that is well formed but cannot give an answer is a reading, never an error.

## Inputs

These are the request's fields, with the three the reply added. All are required unless marked "or null".

| Field | Type | Use here |
|---|---|---|
| `arms`, `control` | list of str, str | Two or more distinct keys, `control` among them. |
| `allocation` | dict str to number | One share per arm, each above 0, summing to 1 within 1e-9. |
| `unit_kind` | str | Echoed back. The engine counts units without knowing what they are. |
| `units_available` | int, 0 or more | The stock that can be enrolled now. |
| `units_per_period` | int or null | Newly eligible units per period. Null gives `periods_needed` null whenever the stock is short, and leaves `longer_run` off the table. |
| `outcome` | dict | Not read, because it is AtmaOS's rule over its records. |
| `direction` | `more` or `fewer` | The sign of the effect. |
| `horizon_days` | int, 0 or more | How long after exposure the outcome is looked for. |
| `baseline_rate` | number or null | The control's rate. Null, zero, or 1 or more is the no-outcome case. |
| `smallest_effect` | number above 0 | The relative change worth detecting. |
| `false_positive_rate`, `sensitivity` | numbers in (0, 1) | alpha and power. |
| `randomized`, `holdout` | bool | A design that isn't randomized is read as below floor (rule 7). `holdout` affects cost only. |
| `channel`, `exposure` | str | Echoed back. Not used in J6 (see "Not in J6"). |
| `unit_cost`, `currency` | number or null, str or null | The cost of exposing one unit. |
| `period_days` | int, 1 or more | The length of one period. |
| `kill_candidates` | list of str | Not read: the metric that ends a test early is named at AtmaOS's `agree`, never by the engine. |
| `economics_ref`, `value_per_outcome`, `run_id` | str or null, number or null, str or null | Accepted and echoed. Not used in J6 (see "Not in J6"). |

## The rule for the three words

The thresholds are the precision registry's, `bounds/estimability/posterior_width@v1`, so a design and a finished estimate are judged against the same two numbers. An estimate is `estimable` when its 90% relative half-width is within `rel_half_width` (0.20), and `marginal` within `caveat_rel_half_width` (0.40). For a test that hasn't run, the width is the smallest effect it could detect. That shrinks with the square root of the units. So:

1. Per comparison. Each non-control arm `a` is compared with `control`, which makes `k - 1` comparisons for `k` arms. Let p1 = `baseline_rate`, and p2 = p1 × (1 + `smallest_effect`) for `more` or p1 × (1 − `smallest_effect`) for `fewer`. Let alpha = `false_positive_rate` / (k − 1), a Bonferroni split, and power = `sensitivity`. Then n_a = `test_design.voi.sample_size_two_proportions(p1, p2, alpha, power)`, rounded up: the units per arm for equal arms.
2. Allocation. With unequal shares, the comparison of `a` is limited by its smaller arm. The total it needs is N_a = ceil(n_a / min(share_control, share_a)). `units_needed` = max over a of N_a, in `unit_kind`, across all arms together.
3. The marginal size. The detectable effect doubles when the units fall to a quarter, since the ratio of the caveat edge to the edge is 0.40/0.20 = 2, squared. So `units_needed_marginal` = ceil(`units_needed` × (`rel_half_width` / `caveat_rel_half_width`)²). Both numbers are read from the registry, never written in the code.
4. `answerable` is `estimable` when `units_available` ≥ `units_needed`, `marginal` when `units_available` ≥ `units_needed_marginal`, and `below_floor` otherwise. AtmaOS stores `below_floor` as `not_knowable_yet`.
5. No outcome. A null `baseline_rate`, a value of 0, a value of 1 or more, or a p2 outside (0, 1) gives `below_floor`, with `units_needed`, `units_needed_marginal`, `periods_needed` and `remedy` all null.
6. Zero units. `units_available` of 0 with a usable baseline gives `below_floor` with the numbers computed.
7. Not randomized. `randomized` false gives `below_floor`. The numbers are computed as if it were randomized, and the remedy is null, because the engine's only remedies are size and shape, and assignment is the CIE's and AtmaOS's to change.

AtmaOS's interim replay rule ("marginal at half") is close but not exact. The exact ratio is a quarter, taken from the registry.

## Periods

8. Enrolment. If `units_available` ≥ `units_needed`, enrolment takes 0 days. Otherwise, with `units_per_period` above 0, it takes `period_days` × ceil((`units_needed` − `units_available`) / `units_per_period`) days. With `units_per_period` null or 0 it can't be reached, and `periods_needed` is null.
9. `periods_needed` = ceil((enrolment days + `horizon_days`) / `period_days`), and 1 at least. Each enrolled unit is watched for `horizon_days`.

## The remedy

10. When `answerable` is `estimable`, `remedy` and `remedy_amount` are null. Otherwise, the first of these that applies:
    - (a) `coarser_comparison`, when keeping fewer arms reaches `estimable` with `units_available` now. `remedy_amount` is the largest m, with 2 ≤ m < k, for which some set of m arms that includes control, with shares renormalised from `allocation`, reaches `estimable` by rules 1 to 4. Which arms to keep is not said: that is the CIE's.
    - (b) `longer_run`, when `units_per_period` is above 0 and the `periods_needed` of rule 9 is no more than the registry's `test_design.max_periods` (new: 12, an engineering choice). `remedy_amount` is `periods_needed`.
    - (c) `larger_group` otherwise, with `remedy_amount` = `units_needed`.
    - A design under rules 5 or 7 has no remedy.

## Stopping, value and cost

11. `stopping_rule` is `{"kind": "fixed_horizon", "max_periods": periods_needed, "kill_threshold": null}`, or null when `periods_needed` is null. `kill_metric_measure_id` is always null.
12. `cost_of_test` = `unit_cost` × the exposed units at `units_needed`, which is all units, or all but the control's share when `holdout` is true. It is in `currency`, and null when `unit_cost`, `currency` or `units_needed` is null. `cost_low` and `cost_high` equal it, because a stated unit cost has no spread.
13. `value_of_answer` is null in J6 (see "Not in J6"). For an outcome that is counted, not bought, it stays null by rule (D33). AtmaOS's render already says so in words.

## The reading

These keys, and no others: `answerable`, `units_needed`, `units_needed_marginal`, `periods_needed`, `kill_metric_measure_id`, `stopping_rule`, `remedy`, `remedy_amount`, `value_of_answer`, `cost_of_test`, `cost_low`, `cost_high`, `currency`, `unit_kind`, `rule_ref` ("bounds/estimability/posterior_width@v1" with "test_design@v1"), `engine_version`, `inputs_hash` (of `design` canonicalised). No value is free text: every string is one of the closed words above, an echoed input, or a reference.

## Refused (ValueError naming the field)

A missing required field, or one of the wrong type. Fewer than two arms, a duplicate arm, `control` not in `arms`. Allocation keys not equal to the arms, a share of 0 or less, or shares not summing to 1. `direction` not `more` or `fewer`. `smallest_effect` of 0 or less. alpha or power outside (0, 1). `period_days` below 1. A negative count.

## Not in J6

Case 6, a paid-media design read against a fitted state through `voi.assess`, needs a payoff distribution per arm built from a run, which nothing yet builds. J6 reads it like case 2: `run_id` is echoed, and `value_of_answer` is null. That is J6.1, its own spec. Using `channel` and `exposure` (for example, repeated exposure's dependence between periods) is also later.

## The six cases

| Case | Reading |
|---|---|
| 1. 180 members, referral offer | `below_floor` unless 180 reaches the marginal size; `units_needed` given; remedy by rule 10 |
| 2. Not ad spend | The three words, the units, the periods when there is a flow, and the cost when `unit_cost` is given |
| 3. No baseline, or zero | `below_floor`, with the numbers and the remedy null |
| 4. Marginal | `marginal`, as itself |
| 5. More than two arms | `coarser_comparison` with the number of arms to keep, when fewer arms reach `estimable` |
| 6. Paid media with a fitted state | Read as case 2 in J6. The value and the fitted cost are J6.1 |

## Checks

(a) Case 1: 180 units, baseline 0.10, effect 0.20, alpha 0.05, power 0.80, two equal arms gives `below_floor`, with `units_needed` equal to 2 × ceil(the two-proportion n), and `larger_group`. (b) The same design with `units_available` = `units_needed` gives `estimable`, and with `units_needed_marginal` gives `marginal`. One unit fewer gives the next word down. (c) Case 3: a baseline of null, 0, 1, 1.2, and a `fewer` effect taking p2 to 0, each give `below_floor` with null numbers and remedy. (d) Case 5: three arms where two reach `estimable` and three don't give `coarser_comparison` with amount 2. Four arms where three reach it give 3. (e) The Bonferroni split: the same per-arm figures with k = 3 need more units than with k = 2. (f) Unequal allocation: control 0.8 and arm 0.2 give N = ceil(n / 0.2). (g) Periods: a shortfall of 250 at 100 a period, with `period_days` 7 and `horizon_days` 14, gives ceil((21 + 14) / 7) = 5. Null flow gives null. The `longer_run` remedy holds up to `max_periods` and falls to `larger_group` above it. (h) Cost: with `holdout` it leaves out the control's share. Null unit cost gives null. (i) Not randomized gives `below_floor` and no remedy. (j) Refusals: each malformed field raises `ValueError` naming it. (k) The reading has exactly the listed keys and every value is JSON-native. Two calls on equal designs give equal readings, `inputs_hash` included. (l) The thresholds are read from the registry: a fixture registry with other `rel_half_width` and `caveat_rel_half_width` changes `units_needed_marginal` by rule 3. (m) The function reads no file under `data_dir()`, no store and no notebook.
