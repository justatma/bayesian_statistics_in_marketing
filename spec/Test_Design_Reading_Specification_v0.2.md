# Reading a proposed test, read_test_design (J6), v0.2

27 November 2026, the Bayesian Engineer. v0.2 takes the blind spec review of v0.1, which raised 11 major and 6 minor points and nothing blocking. v0.1 is in git at 491f2a8.

This answers the AtmaOS integrator's request of 11 November, `atmaos/spec/suggestions/request_to_bayesian_engine.md`. The engine's reply of the same day, `reply_from_bayesian_engine_2026-11-11.md`, set the inputs, and AtmaOS spec 22 AS5 agreed them.

Arkwright's third stage turns a suggestion into a test. The Creative Intelligence Engine drafts what is tried, on whom and in what form. This function reads the draft's measurable shape and says whether a test like that can give an answer for this client, and what it would take. It never changes what an arm receives or who the test is for. Its remedy is a word and a number, and it carries no free text. The state of a live test is a separate call.

## The call

`bayesian_marketing.atmaos.socket.read_test_design(design: dict) -> dict`. Plain JSON-native dicts go in and come out. The engine never imports atmaos (F7). The function reads no store, no run and no file other than the registries, and it never mutates `design`. A malformed design raises `ValueError` naming the field (see Refused). A design that is well formed but can't give an answer is a reading, never an error.

## Inputs

Every key below is required, and a value may be null only where the table says so. Any other key is refused, so the contract can't drift silently. Numbers are JSON numbers, never strings. A bool is never accepted as a number.

| Field | Type | Use |
|---|---|---|
| `arms`, `control` | list of str, str | Two or more distinct keys, with `control` among them. |
| `allocation` | dict str to number | One share per arm, each above 0, summing to 1 within 1e-9. |
| `unit_kind` | str | Echoed. |
| `units_available` | int ≥ 0 | The stock of units that could be enrolled now. |
| `units_per_period` | int ≥ 0, or null | The flow of newly eligible units per period. |
| `outcome` | dict | Not read. It is AtmaOS's rule over its records. |
| `direction` | `more` or `fewer` | The sign of the effect. |
| `horizon_days` | int ≥ 0 | How long after exposure the outcome is looked for. |
| `baseline_rate` | number in [0, 1], or null | The control's rate. Null, 0 or 1 means there is no usable baseline (rule 6, J6.S1). A value above 1 or below 0, or NaN, is refused. |
| `smallest_effect` | number > 0, finite | The relative change worth detecting. |
| `false_positive_rate`, `sensitivity` | numbers in (0, 1) | alpha and power. |
| `randomized`, `holdout` | bool | See rules 8 and 13. |
| `channel`, `exposure` | str | Accepted and not used in J6. |
| `unit_cost` | number ≥ 0, or null | The cost of exposing one unit. |
| `currency` | str or null | Echoed. |
| `period_days` | int ≥ 1 | The length of one period. |
| `kill_candidates` | list of str | Not read. The early-ending metric is named at AtmaOS's `agree`. |
| `economics_ref`, `value_per_outcome`, `run_id` | str, number or str, each or null | Accepted and not used in J6 (see Not in J6). |
| `baseline_measure_id` | str or null | The AtmaOS measure the baseline came from. Accepted and not used (J6.S1). |

## What "estimable" means for a design

A finished estimate is `estimable` when its 90% relative half-width is within the registry's `rel_half_width` (0.20). It is `marginal` within `caveat_rel_half_width` (0.40). Those two numbers measure an interval's width. They are not effect sizes, and a design doesn't use them as effects.

A design uses only their ratio, `caveat_rel_half_width / rel_half_width` (2 in the registry today). It is the registry's statement of how much looser than the target a reading may be and still be given with a caveat.

So for a design, `estimable` means powered to detect `smallest_effect`, the change the client said is worth detecting. `marginal` means powered only to detect a change the ratio times larger, `2 × smallest_effect` today. `below_floor` means it can't detect even that.

## The rule for the three words

1. One comparison. Each non-control arm `a` is compared with `control`, which makes `k − 1` comparisons for `k` arms. For a relative effect `e`, set p1 = `baseline_rate`. Set p2 = p1 × (1 + e) for `more`, or p1 × (1 − e) for `fewer`. Then alpha = `false_positive_rate` / (k − 1) (Bonferroni) and power = `sensitivity`. The per-arm figure is n(e) = ceil(`sample_size_two_proportions(p1, p2, alpha, power)`). That formula is two-sided, whatever the direction. The figure is defined only when p2 is strictly inside (0, 1).
2. Allocation. The comparison of `a` is sized by its smaller arm: N_a(e) = ceil(n(e) / min(share_control, share_a) − 1e-9). The 1e-9 keeps float error in a share such as 0.3 from adding a unit. This is deliberately conservative: the larger arm gets more units than the exact unequal-allocation requirement. N(e) = max over a of N_a(e), the total across all arms.
3. Sizes. `units_needed` = N(`smallest_effect`). `units_needed_marginal` = N(`smallest_effect` × ratio). The marginal size is solved from the formula at the larger effect, not scaled. Where the larger effect puts p2 outside (0, 1), `units_needed_marginal` is null and no design can be `marginal`.
4. The word. "Reaches" always means ≥. The design is `estimable` when `units_available` ≥ `units_needed`. It is `marginal` when `units_needed_marginal` is not null and `units_available` ≥ `units_needed_marginal`. Otherwise it is `below_floor`, which AtmaOS stores as `not_knowable_yet`.
5. Zero units. A `units_available` of 0, with a usable baseline, gives `below_floor` with the sizes computed.
6. No outcome. A `baseline_rate` that is null, 0 or 1, or a p2 at `smallest_effect` outside (0, 1), gives `below_floor`. Every size, `periods_needed`, `stopping_rule` and `remedy` are then null. The second case, for example `more` at a baseline of 0.9 with an effect of 0.2, has an outcome but an effect that can't be seen. The sizes can't be computed, so it reads the same way.
7. A note for AtmaOS. Its interim replay rule, "marginal at half", is close to this but not the same. Solved from the formula, the marginal size runs to about 0.24 to 0.28 of `units_needed` across common baselines and effects. The interim rule's figures for E1 change: see the AS5 section below.
8. Not randomized. `randomized` false gives `below_floor`. The sizes and periods are computed as if the design were randomized, and `remedy` is null. The engine's remedies are size and shape only, and assignment is for the CIE and AtmaOS to change.

## Periods

9. Enrolment days. They are 0 when `units_available` ≥ `units_needed`. Otherwise, with `units_per_period` above 0, they are `period_days` × ceil((`units_needed` − `units_available`) / `units_per_period`). With `units_per_period` null or 0, the size can't be reached, and `periods_needed` is null.
10. `periods_needed` = max(1, ceil((enrolment days + `horizon_days`) / `period_days`)). It is always for the estimable size, `units_needed`, including when the design is already `marginal`.

## The remedy

11. The remedy is null when the word is `estimable`, under rule 6, and under rule 8. Otherwise it is non-null for both `marginal` and `below_floor`, and it always aims at `estimable`. The first of these that applies, in this order:
    - (a) `coarser_comparison`. For m from k − 1 down to 2, the kept set is the control plus the m − 1 non-control arms with the largest shares, ties broken by arm key in code-point order, with shares renormalised over the kept arms and alpha re-split as alpha / (m − 1). The first m whose kept set is `estimable` by rules 1 to 4 with `units_available` gives `remedy_amount` = m, the number of arms to keep, the control included. Which arms to keep is not said; that is the CIE's call.
    - (b) `longer_run`. This applies when `units_per_period` is above 0 and `periods_needed` is no more than `MAX_PERIODS` (12, an engineering choice, J6.S4). `remedy_amount` = `periods_needed`, the total periods the test runs, not the extra ones.
    - (c) `larger_group`. Otherwise `remedy_amount` = `units_needed`, the total across all arms, not the shortfall.
   
   The order is deliberate. A design that two arms would answer now is told so before it is told to wait. That matches request case 5 and the interim rule. The CIE may still choose to run longer instead.

## Stopping and cost

12. `stopping_rule` is `{"kind": "fixed_horizon", "max_periods": periods_needed, "kill_threshold": null}` whenever `periods_needed` is not null, and null otherwise. `kill_metric_measure_id` is always null.
13. The exposed units are `units_needed`, or ceil(`units_needed` × (1 − share_control) − 1e-9) when `holdout` is true. `cost_of_test` = `unit_cost` × the exposed units, rounded half up to 2 decimals as a JSON number. It is null when `unit_cost` or `units_needed` is null. `cost_low` and `cost_high` are both equal to it, since a stated unit cost has no spread. `currency` is the input's, echoed even when the cost is null.
14. `value_of_answer` is null in J6 for every design (see Not in J6). For an outcome that is counted rather than bought, it is null by rule as well (D33).

## The reading

These are its exact keys: `answerable`, `units_needed`, `units_needed_marginal`, `periods_needed`, `kill_metric_measure_id`, `stopping_rule`, `remedy`, `remedy_amount`, `value_of_answer`, `cost_of_test`, `cost_low`, `cost_high`, `currency`, `unit_kind`, `rule_ref`, `engine_version` and `inputs_hash`.

- `rule_ref` is the list `["bounds/estimability/posterior_width@v1", "test_design/max_periods@v1"]`.
- `engine_version` is `bayesian-marketing <version>`.
- `inputs_hash` is the design's hash under the form `bayes-design-c1` (J6.S2). `core.inputs_hash` is not used, because it writes 1 and 1.0 differently and escapes non-ASCII.

Every string value is one of the closed words above, an echoed input (`unit_kind`, `currency`) or a reference.

## Refused (ValueError naming the field)

- A missing key or an unknown key.
- A wrong type, including a bool where a number is expected and a string where a number is expected.
- NaN or infinity.
- Fewer than two arms, a duplicate arm, or a `control` that isn't among `arms`.
- Allocation keys that don't equal the arms, a share of 0 or less, or shares that don't sum to 1.
- `direction` that isn't `more` or `fewer`.
- `smallest_effect` of 0 or less.
- alpha or power outside (0, 1).
- `baseline_rate` outside [0, 1].
- `period_days` below 1.
- A negative count, or a negative `unit_cost`.
- A non-string in `kill_candidates`.

## Not in J6

- Case 6, a paid-media design read against a fitted state through `voi.assess`, needs a payoff distribution per arm built from a run, and nothing builds that yet. The reply of 11 November promised `value_of_answer`, a fitted cost low and high, and `engine_stop_or_continue` for a run. J6 doesn't give them. It reads such a design as it reads case 2, `value_of_answer` is null, and `stopping_rule` is `fixed_horizon`.
- Request case 2 asks for the answer's value "where it can be had". J6 gives none, even for a bought outcome with `value_per_outcome`, because a value of information needs a prior over the effect.
- Both of these are J6.1, which has its own spec. So is any use of `channel` or `exposure`.

## For AtmaOS (AS5), to be told with this spec

The reading adds keys AS5's `BayesTestReading` doesn't name: `units_needed_marginal`, `cost_low`, `cost_high`, `rule_ref`, `inputs_hash`, `unit_kind`. The adapter should keep them, or at least accept them, and not refuse the reply.

`remedy_amount` is a total for `larger_group` and `longer_run`, not the shortfall or the extra periods.

E1's figures change.
- Two arms at 1,900 units: `units_needed` = 2 × 859 = 1,718, not 1,717.
- Five arms at 0.2, a 0.30 baseline, `fewer` at an effect of 0.2, at 1,900 units: `units_needed` 6,100 (per arm 1,220 at alpha 0.0125), `units_needed_marginal` 1,410. So the word is `marginal`, not `not_knowable_yet`, with `coarser_comparison` 2 (four arms need 4,584 and three 3,120; two need 1,718). The Arkwright Engineer worked these out and the engine's function confirms them (27 Nov).
- The cost leaves out the control when `holdout` is true.
- `periods_needed` includes the enrolment days.

## The six cases

| Case | Reading |
|---|---|
| 1. 180 members | `below_floor` unless 180 reaches the marginal size, with `units_needed` and the remedy by rule 11 |
| 2. Not ad spend | The word, the sizes, the periods when there is a flow, and the cost when `unit_cost` is given. The value is null (Not in J6) |
| 3. No baseline, or zero | `below_floor`, with the sizes, periods, stopping rule and remedy null |
| 4. Marginal | `marginal`, as itself, with a remedy that aims at `estimable` |
| 5. More than two arms | `coarser_comparison` with the number of arms to keep, when fewer arms reach `estimable` |
| 6. Paid media with a fitted state | Read as case 2. The value and the fitted cost come in J6.1 |

## Checks

(a) Goldens through the full path. A 3% control against 4%, two equal arms, alpha 0.05, power 0.8: `units_needed` = 2 × ceil(5,300.74) = 10,602. A 0.30 baseline with `fewer` at an effect of 0.2: 2 × ceil(858.27) = 1,718.

(b) Boundaries. At exactly `units_needed`: `estimable`. One fewer: `marginal` or `below_floor`. At exactly `units_needed_marginal`: `marginal`. One fewer: `below_floor`.

(c) The marginal size equals N at `smallest_effect × ratio` from the formula, and lies within 0.22 to 0.30 of `units_needed` for baselines 0.03 to 0.5 and effects 0.1 to 0.4. When the larger effect leaves p2 outside (0, 1), it is null and the word is never `marginal`.

(d) No outcome. A baseline of null or 0, and p2 outside (0, 1) at `smallest_effect` (`more` at 0.9 with 0.2; `fewer` at an effect of 1), give `below_floor` with every size, the periods, the stopping rule and the remedy null.

(e) Bonferroni. The same shares need more units at k = 3 than at k = 2.

(f) Allocation. A control at 0.8 and an arm at 0.2 give ceil(n / 0.2). Shares of 0.7 and 0.3 give no extra unit from float error.

(g) The remedy order and amounts. A three-arm design that two arms answer gives `coarser_comparison` with 2. Four arms where three answer gives 3, with unequal shares choosing the largest non-control arms and ties broken by key. A design with a flow inside `max_periods` gives `longer_run` with the total periods. At `max_periods` + 1 it gives `larger_group` with `units_needed`. A `marginal` design carries a remedy.

(h) Periods. A shortfall of 250 at 100 a period, with `period_days` 7 and `horizon_days` 14, gives ceil((21 + 14) / 7) = 5. A shortfall with a null or 0 flow gives null. No shortfall with `horizon_days` 0 gives 1.

(i) Cost. With `holdout` it leaves out the control's share. A null unit cost gives a null cost with `currency` still echoed. Rounding is half up to cents.

(j) Rules 5 and 8. Zero units give the sizes computed. Not randomized gives `below_floor`, the sizes and no remedy.

(k) Refusals. Each item in Refused raises `ValueError` naming the field.

(l) Shape. The reading has exactly the listed keys, every value is JSON-native, and every string is a closed word, an echo or a reference. The design is not mutated. Equal designs give equal readings. `inputs_hash` doesn't change with key order or with an int against an equal float.

(m) The registry. A fixture registry with another ratio changes `units_needed_marginal` through rule 3, and another `max_periods` moves the `longer_run` edge.

(n) The function reads no file under `data_dir()`, no store and no notebook.

## Settled after the Arkwright Engineer's reading (27 Nov)

J6.S1.
1. `baseline_measure_id` (str or null) is accepted and not used. AtmaOS sends every request field, so it joins the contract. The adapter then doesn't have to strip it, and the unknown-key refusal still guards against drift.
2. A `baseline_rate` of exactly 1 reads like 0, as no usable baseline: at p1 = 1, p1(1 − p1) = 0 and the formula's variance is zero.
3. `stopping_rule` is never sent with `max_periods` null. It is null as a whole whenever `periods_needed` is null (rule 12).
4. AtmaOS rounds cost half up to cents, as rule 13 does.
5. AtmaOS stores `units_needed_marginal`, `rule_ref` and `inputs_hash`, and leaves out `cost_low`, `cost_high` and `unit_kind`, which in J6 only repeat what it holds. That is AtmaOS's choice, and it changes nothing here.

J6.S2 (the Arkwright Engineer and the Principal Architect, 27 Nov).

1. The hash form `bayes-design-c1`. Only this rule decides it, so the replay desk computes the same hash.
   - (a) The value is the design as received, a JSON object.
   - (b) Normalise every value, at every depth:
     - A bool stays a bool, and is never treated as a number.
     - A number that is a whole value is written as an integer, so 1, 1.0 and 1e0 are all `1`.
     - Any other number is written in the shortest form that reads back as the same IEEE-754 double. That is Python's `repr(float)` as `json.dumps` writes it: 0.2 as `0.2`, 1e-05 as `1e-05`.
     - NaN and infinity never occur, because they are refused.
     - null stays null.
     - A string stays as it is.
     - A list keeps its order.
     - An object is normalised in the same way.
   - (c) Serialise with keys sorted by Unicode code point at every level, with separators `,` and `:` and no spaces, and with non-ASCII left as it is (no `\u` escapes). This is Python's `json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)` applied to the normalised value.
   - (d) `inputs_hash` is the lowercase hex SHA-256 of those UTF-8 bytes.

   The reference implementation is `bayesian_marketing.test_design.reading.design_hash`. Checks:
   - A fixture design with a non-ASCII `unit_kind`, nested `outcome`, an int and an equal float has a stated hash, and the test holds that hash.
   - A second implementation written from this text alone gives the same hash.
   - Key order and int against float don't change it.
2. The call path and the rule's values. AtmaOS calls the engine's interpreter as its slot bridge does: `python -I`, JSON on stdin and stdout, an environment of `BAYES_DATA_DIR`, `HOME` and `PATH`. J6 needs nothing more than that. It reads only the registries, which it finds from the package as the slot calls do.

   A second socket call, `read_test_design_rule() -> dict`, gives AtmaOS's equality test everything it needs without reaching into registry paths:
   - `rel_half_width` and `caveat_rel_half_width` (from `bounds/estimability/posterior_width@v1`);
   - `ratio`, the second divided by the first;
   - `max_periods` (from `test_design/max_periods@v1`, in `registries/test_design.yaml`);
   - `rule_ref`, the same list the reading carries;
   - `hash_form`, which is "bayes-design-c1";
   - `engine_version`.

   Check: its values equal the registries', and `rule_ref` equals a reading's.

J6.S3 (the Arkwright Engineer, 27 Nov). How cost is rounded, exactly. `cost_of_test` = `(Decimal(repr(unit_cost)) * exposed_units).quantize(Decimal("0.01"), ROUND_HALF_UP)`, where `exposed_units` is the integer from rule 13, sent as a JSON number (`float` of that Decimal). `repr` gives the shortest decimal that reads back as the unit cost's double, which is the figure the sender meant. The product with an integer is then exact, so a half-cent edge rounds as written. Rounding the float product instead differs at such edges: 0.155 × 3 is 0.46499999999999997 as floats, and that would give 0.46 where the rule gives 0.47. Check: (i) gains 0.155 × 3 = 0.47 and 0.015 × 3 = 0.05.

J6.S4 (the integrator, 27 Nov). `max_periods` lives in code, not in a new registry file. `core.registries.versions()` lists every YAML file under `registries/`, and every run's config hash includes that list. A new `registries/test_design.yaml` would therefore change every run's config hash once, for a design-reading policy that no run uses, so the value goes in code instead.
- It is `bayesian_marketing.test_design.reading.MAX_PERIODS = 12`, an engineering choice.
- The reading's `rule_ref` becomes `["bounds/estimability/posterior_width@v1", "engine:test_design.reading.MAX_PERIODS@<engine_version>"]`.
- `read_test_design_rule()` still returns `max_periods`, so AtmaOS's equality test reads it from there as before.
- Rule 11 (b) and check (m) read `MAX_PERIODS`. Check (m)'s second half patches the constant instead of a fixture registry.
- Check: adding J6 leaves `registries.versions()` unchanged, and so leaves every run's config hash unchanged.
