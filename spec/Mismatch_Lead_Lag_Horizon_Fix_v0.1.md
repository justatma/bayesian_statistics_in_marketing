# Mismatch cap, lead lag and budget horizon fix, v0.1

Owner, 2026-11-11: "One level cap, no lag curve for lead conversions, and the horizon taken from
the remaining budget." Decisions D52 and D53. Build protocol applies. Pieces L10 and L11.

## 1. The defects

E1, stacking. `floors.estimability.quantity_feasibility` lowers a quantity's status one level per
regime-mismatch notice (`_downgrade(width_status, len(mismatches))`). Jovannah's conversion
quantities carry `too_few_ads`, `platform_modeled` and `lag_approx`, so an estimable width ends at
below_floor and can never leave it. D26 and D28 (1) say "at best marginal".

E2, lead lag. Since L9 parses `1d_view_7d_click_1d_ev`, `pipeline.fit_lag` gives a lead run the
7-day default purchase curve. Immature cohorts scale the lead counts up: IMG3's lead rate came out
56% against a raw 57 of 174 (33%), cost per lead $0.83 against $1.62. A lead is counted when it
happens; Meta's lead count tracked Jovannah's Klaviyo list hour by hour (D47).

E3, horizon. `live.refresh._horizon` always uses the registry's 1,000 (unit made impressions for
ctr), about $30 of Jovannah's spend. The expected loss is priced over that and compared with a
$150 tolerance meant for a decision, so the tolerance test is not about the money at stake.

## 2. L10: engine

C1 (E1). In `quantity_feasibility` the status is lowered by `min(1, number of mismatches)` levels.
Every mismatch reason is still appended to `reasons`, in the order of `q.notices`. Nothing else in
the function changes (the required-events projection and its reasons are as before).

C2 (E2). In `pipeline.execute`, when `request.conversion_kind == "lead"`, `fit_lag` is not called:
`lag` is None and `lag_notes` is `[LEAD_NO_LAG]`, with
`LEAD_NO_LAG = "no lag curve: a lead is counted when it happens (D53)"` in `pipeline`. Downstream
this gives mature fraction 1 for every cell (the existing `lag is None` path), no `lag_approx`
notice on any quantity, `configuration["lag"]` None, and the run's notices carry `LEAD_NO_LAG` in
place of any lag notice. Purchase runs are unchanged byte for byte.

C3 (E3, plumbing). `core.records.CompareRequest` gains `horizon_basis: str | None = None`: how the
horizon was chosen, in words. `pipeline._request_key` excludes it when None, so every existing run
id and seed is unchanged. When it is set, `execute` appends it to the run's notices once, after the
lag notices. The skeleton adds the field; L10 does the rest.

## 3. L11: live horizon

C4. New module `live/horizon.py`:

```python
def spend_to_date(store: Store, client_id: str) -> tuple[Money | None, date | None]:
    """Total spend in the store for the client: for each (ad, account-local date), the row from
    the newest poll with status "ok" that carries it, summed. Returns (total, earliest date), or
    (None, None) when the store has no such row. Rows in more than one currency: (None, None)."""

def budget_horizon(
    test_budget: Money | None,
    spent: Money | None,
    since: date | None,
    window_rows: list[LiveRow],
    unit: str,
) -> tuple[Horizon, str]:
    """D53: the horizon is the budget left, converted to ``unit`` at the observed cost per unit
    pooled over ``window_rows``. Returns the horizon and its basis sentence."""
```

C5. `budget_horizon`. `unit` is `impressions` or `clicks`. Cost per unit is the sum of
`spend.amount` over `window_rows` divided by the sum of that unit's count over the same rows.
Remaining is `test_budget.amount - spent.amount`. The amount is `floor(remaining / cost per unit)`
as an integer `Decimal`. The basis is

`HORIZON_FROM_BUDGET = "horizon: {amount} {unit}, the {remaining} left of the {budget} test budget
(spend counted since {since}) at {per_1000} per 1,000 {unit}"`

with money by `fmt_money`, the amount by `fmt_count`, `since` as ISO date.

C6. Fallback. The horizon is the registry's `decision_defaults/horizon_default@v1` amount in `unit`
(as `_horizon` builds it today), and the basis is
`HORIZON_FALLBACK = "horizon: the default {amount} {unit}, because {why}"`, when, in this order:

| Condition | why |
|---|---|
| `test_budget` None | "no test budget is set in the economics file" |
| `spent` None | "no spend to date could be read from the store" |
| `spent` or any window row in another currency than `test_budget` | "the budget and the spend are in different currencies" |
| remaining <= 0 | "the test budget is spent" |
| unit count or spend over `window_rows` <= 0 | "no {unit} in the window to price the budget" |
| amount < 1 | "less than one {singular} of budget is left" |

C7. `live.refresh._outcome` loads the economics file it already requires (`config.economics_path`
under `config_root`, as `pipeline` loads it; a load failure falls under the existing exception
handling), calls `spend_to_date` and `budget_horizon` with `unit = pipeline.horizon_unit(METRIC)`
and the poll's rows, and passes `horizon=` and `horizon_basis=` to `CompareRequest`. `_horizon`
stays as the fallback's builder.

## 4. Checks (acceptance, frozen before builders)

L10: a quantity with an estimable width and two or three mismatch notices is marginal, with every
mismatch reason present; one with a marginal width and two mismatches is below_floor; one mismatch
behaves as before. A lead run (Meta code `1d_view_7d_click_1d_ev`) has every mature fraction 1.0,
`configuration["lag"]` None, `LEAD_NO_LAG` in the run notices, no `lag_approx` notice on any
quantity, and a cvr whose median sits near the raw rate; a purchase run with the same code still
applies the 7-day curve (L9's check moves to the purchase run). `horizon_basis` None leaves the run
id equal to the base's; set, it appears once in the notices.

L11: `spend_to_date` takes the newest ok poll's row per (ad, date), ignores error polls, sums across
dates no longer in the latest poll's window, and returns the earliest date. `budget_horizon` on
Jovannah's shape ($1,500 budget, $243.76 spent, 8,196 impressions for $243.76) gives 42,238
impressions with the C5 sentence; each C6 row gives the default and its sentence. A refresh with a
test budget stores a run whose horizon is the budget horizon and whose notices carry the basis; one
without a test budget runs at the default with the fallback basis.

## 5. Scope

L10: `floors/estimability.py`, `pipeline.py`, revised `tests/acceptance/test_L9.py` (lead-lag case
moved to a purchase run; build log row), unit tests. L11: `live/horizon.py`, `live/refresh.py`,
unit tests. Skeleton (integrator): `CompareRequest.horizon_basis`, `live/horizon.py` stubs raising
`NotImplementedError`, the constants.

Not in scope: a daily-budget horizon (needs the ad-set budget and a review date, neither polled);
budget periods (all spend in the store counts against the test budget); showing the basis on the
live page (it is in the run's notices); `cli.demo_horizon`.
