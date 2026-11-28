# Units and window fix, v0.2

Owner, 2026-11-10: "yes - please fix", on two defects found while writing Jovannah's report 002.
Decision D51. Build protocol applies. Pieces L8 and L9.

## 1. The defects

D1, units. For a count objective (`clicks` from metric `ctr`, `orders` from `cvr`), `compare`
returns `expected_value`, `expected_loss` and `value_q05` as `Money` in the economics currency,
though the amounts are counts per horizon (D40 left "until Comparison carries a unit" open). Three
places then compare those counts with money:

1. `floors.decision_feasibility`: expected loss (clicks) against `loss_tolerance` (dollars). On
   Jovannah's run 0.39 clicks against $150 made the decision "estimable".
2. `decision.reallocation.survival_check`: `value_q05` (clicks per 1,000 impressions) against
   `survival_floor` ($1,500). Every option failed, so the recommendation was not_knowable.
3. `decision.reallocation` reallocate and hold paths: `expected_loss` against `loss_tolerance` in
   the guarantee, and expected benefit (clicks) minus `switching_cost` (dollars).

D2, window. `lag.model._CLICK_WINDOW` is `^(\d+)d_click(?:_|$)`, so it reads a click window only
when the code starts with it. Meta's insights return `attribution_setting` as
`1d_view_7d_click_1d_ev` (view, click, engaged view), so no lag curve is applied to Jovannah's
conversions and every conversion quantity carries "conversion lag not adjusted".

## 2. L8: units

C1. `core.Comparison` gains `unit: Literal["money", "clicks", "orders"] = "money"` and
`replacement_cost: Money | None = None`. `compare` sets `unit` from the objective target
(`contribution` money, `clicks` clicks, `orders` orders). Contribution comparisons are unchanged
byte for byte.

C2. Replacement cost: what one unit cost over the compared ads in the run's window, as observed:
total spend divided by total clicks (unit clicks) or total conversions (unit orders; observed
conversions where present, else reported, the per-row rule of D34 and R5), in the economics
currency. Set by `pipeline.execute` on the comparison (`model_copy`) before
`decision_feasibility` and `allocate` see it. Zero units, or spend in another currency, gives
`None`. Rationale: a lost click is valued at what it costs to buy it back. No lead or click is
given a sale value (D33).

C3. One helper, `decision.units.in_money(c: Comparison, amount: Money) -> Money | None`: unit money
returns the amount; a count unit returns `amount × replacement_cost` in the replacement cost's
currency, or None when `replacement_cost` is None. Every comparison of a Comparison amount with an
economics `Money` (tolerance, survival floor, switching cost) goes through it.

C4. `decision_feasibility`: the expected loss is converted with C3 before the tolerance test;
`available` and the reasons are in money. With no replacement cost the status is below_floor with
the reason `NO_REPLACEMENT_COST` = "no observed cost per {unit} to value a lost {unit_singular}".

C5. Survival floor: not applied to a count comparison (it is a floor on value; a count has none
under D33). `survival_check` returns no blocked options and one notice per run,
`SURVIVAL_NOT_APPLIED` = "survival floor not applied: this comparison is in {unit}, not money".

C6. Reallocate and hold: expected loss and expected benefit are converted with C3 before they meet
the tolerance or the switching cost. `Recommendation.expected_loss` and `expected_benefit` are
money. The guarantee's slots show the money amount; `params` carry `unit` and
`replacement_cost`, and the assumptions carry `VALUED_AT` = "lost {unit} valued at their observed
cost, {cost} each".

C7. Split allocation (`allocate`): the same conversions wherever it compares with tolerance,
floor or switching cost.

C8. Display (D40) unchanged: comparison values under a count objective still render as counts.

## 3. L9: window

C9. A Meta code's click window is the `<n>d_click` component wherever it sits among the
underscore-separated components (`1d_view_7d_click_1d_ev` → 7; `7d_click_1d_view` → 7;
`28d_click` → 28; `1d_view` alone names none). Two click components in one code raise ValueError.
`window_code`, `fit_lag` and the notices are otherwise unchanged.

## 4. Checks (acceptance, frozen before builders)

L8: on a ctr comparison with known spend and clicks, `unit` and `replacement_cost` are set;
decision feasibility compares loss × cost with the tolerance (estimable, marginal and below floor
cases); a count comparison blocks no option on the survival floor and carries the notice; a
reallocate's net benefit is benefit × cost minus switching cost; zero clicks gives the
no-replacement-cost reason; contribution runs are unchanged (comparison, decision, recommendation
and run id equal the base's). Jovannah's shape (five ads, leads, ctr) gives a recommendation that
is not "every option breaches the survival floor".

L9: the C9 cases; a lead run with `1d_view_7d_click_1d_ev` rows has no "conversion lag not
adjusted" notice and uses the 7-day default curve.

## 5. Settled by blind review 01 (`spec/reviews/review_blind_units_01.md`)

Where this section and §1 to §4 differ, this section holds.

U1 (A1). `decision/stopping.py` is in scope: `_projected_required`, the `loss=` passed to `out`, and
`loss_guarantee` convert through `in_money`. With no replacement cost the projection returns None
and the existing not_knowable branch carries `NO_REPLACEMENT_COST`.

U2 (A2, A3, A5). C8 is replaced: comparison amounts display by `c.unit` (counts for a count unit);
recommendation amounts (`expected_loss`, `expected_benefit`) are money and display as money. In
scope: `cli._amount` and `_verdict` (the verdict runs the real tolerance test on the money loss),
`reporting/render._fmt_value` call sites for recommendations, and `claims/check._index` adds
`c.replacement_cost` to the checkable money values. `tests/unit/p11/test_p11_d38.py` line 143
(`"USD tolerance" not in text`) is revised to assert the money verdict; build log B23.

U3 (A4, B4). `Comparison` gets a `model_validator(mode="before")`: a stored `unit` absent is
derived from `objective.target` (contribution money, clicks clicks, orders orders); a stored unit
that contradicts the target is refused, except `leads` with target `orders` (U9).

U4 (A6, A7, A15, B1, B3). Replacement cost, pooled over the compared ads, per FunnelData cell. Unit
clicks: sum of spend over all cells divided by sum of clicks. Unit orders or leads: over cells whose
conversion count is known (observed if not None, else reported if not None), sum of spend divided
by sum of that count; cells with no known count contribute neither spend nor count. Not
lag-adjusted; the `VALUED_AT` assumption says "observed, not adjusted for late conversions". Total
units 0, total spend <= 0, or spend in another currency than the economics: None. Stored unrounded
(`Decimal(repr(float))`), rounded only for display.

U5 (A9, A10). For unit money nothing new is added to `params`, assumptions or `statement_math`, so
contribution recommendation ids are unchanged. The contribution check compares the comparison
dumped without `unit` and `replacement_cost`, the decision without `checked_at`, recommendation ids
and the run id against the base.

U6 (A11). `allocate` converts the share-weighted expected loss with `in_money` (None: `expected_loss`
None and the decision's reason). The D30 no-economics branch is unchanged. The Jovannah-shape check
asserts that `allocation.ALL_BLOCKED` is not the outcome.

U7 (A12, B5). C5 stands and amends v0.3 §8.2 C3: under a count unit the survival floor is not
tested. The notice appears once per recommendation, only when a floor is set. The justification is
that a dollar floor on value cannot be tested against a count, not D33.

U8 (A13, A14, B6). One parser, `lag.model.click_window_days(code) -> int | None`: split on `_`; a
click window is a component matching `^\d+d$` immediately followed by the component `click`; None
when there is none; ValueError for two click windows or 0 days. `_click_window_days`,
`lag_notices`, the `lag_model` path and `simulate/write.py` all use it, and `_CLICK_WINDOW` and the
generator's own regex are deleted. Off-table windows (14, 90) still raise at the registry lookup.
LinkedIn `90d_click_90d_view` keeps "conversion lag not adjusted" (no registry row); not in scope.

U9 (A16, A17, B2). `unit` Literal gains `"leads"`. `execute` sets `unit="leads"` (`model_copy`) when
`request.conversion_kind == "lead"` and the target is orders. Final strings, by unit word
(`clicks`/`click`, `orders`/`order`, `leads`/`lead`):
`NO_REPLACEMENT_COST` = "no observed cost per {singular} to value a lost {singular}";
`SURVIVAL_NOT_APPLIED` = "survival floor not applied: this comparison is in {unit}, not money";
`VALUED_AT` = "lost {unit} valued at their observed cost, {cost} per {singular} (observed, not
adjusted for late conversions)". A lead priced at its cost per lead is a cost, not a value; D46 (2)
stands. Check order in `decision_feasibility`: no tolerance (D16) first, then no replacement cost;
`available` is 0.0 when there is no money amount.

U10 (B7). `atmaos/socket.result_of` adds `unit` and `replacement_cost` under `uncertainty` as new
keys; the frozen `BayesianResult` fields are unchanged.

U11 (B8). Noted for the owner: at the default ctr horizon (1,000 impressions) the priced loss is
cents against a $150 tolerance, so a count decision is nearly always "estimable". The default horizon
for count objectives is a separate ruling.

Pieces: L8 = U1 to U7, U9, U10 (`core`, `decision/`, `floors/estimability.py`, `pipeline.py`,
`cli.py`, `reporting/render.py`, `claims/check.py`, `atmaos/socket.py`, the one unit test). L9 = U8
(`lag/model.py`, `simulate/write.py`, `pipeline.fit_lag` if needed).
