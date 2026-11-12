# L11 blind review (branch piece/L11, ff228c1 against fdf5f0e)

Probes: `tests/review/l11/test_probes.py`. 14 probes, 12 pass, 2 fail (F1, F2). Acceptance
`tests/acceptance/test_L11.py` with `BAYES_PIECES=L11`: 30 pass, 4 fail (the expected L10 refresh
tests only).

## Findings

F1 (low). Rows with no `ad` id are merged. Clause: C4, S12 ("per (ad, date)"). `spend_to_date`
keys `(r.entity_ids.get("ad", ""), r.date)`, so two rows of one poll with no ad id on one date
(different ad sets) collapse to one and the total is undercounted. Probe
`test_probe_rows_without_ad_id_are_not_merged`, output:
`assert (Money(amount=Decimal('10'), currency='USD') is not None and Decimal('10') == Decimal('15'))`.
Reach: `SqliteStore` has `PRIMARY KEY (poll_id, ad_id, date)` and writes `r.entity_ids["ad"]`, so
the real store cannot hold such a row. It shows with `FakeStore` only. A fix is to skip such rows
or key them by the full entity ids.

F2 (low). Two rows for the same (ad, date) in one poll: only the first is counted. Clause: C4 (the
winner is a poll, and its rows for the key all belong to it). `rank > held[0]` is false for the
second row of the same poll, so it is dropped. Probe
`test_probe_duplicate_ad_date_rows_within_one_poll`, same output as F1 (10 against 15). Same reach
note: the sqlite primary key forbids it, so FakeStore only. The spec is silent on duplicates, so
"first wins" may be accepted; if so, say it in the code.

No blocking finding.

## Checked and found correct (probe or acceptance test passes)

- Supersession by newer ok polls, older dates kept, earliest date, error and interrupted polls
  ignored, other platform ignored, polls after `as_of` ignored (inclusive), tie to the greater
  `poll_id` in both insertion orders, other clients ignored (acceptance tests and
  `test_probe_other_client_not_counted`).
- Currency: mixed currencies give `(None, None)`; a superseded EUR row does not poison the total
  (the currency set is taken after supersession); a budget in a currency other than the spend or
  window rows gives the currency fallback (`test_probe_spend_mixed_currency_gives_none_pair`,
  `test_probe_superseded_other_currency_row_does_not_poison`,
  `test_probe_budget_in_other_currency_than_window_but_same_as_spent`).
- Amount: `math.floor(Fraction(remaining) * units / Fraction(cost))`, exact. 0.6 / 0.1 gives 6 and
  10 / (10/9) gives 9; Jovannah's shape gives 42,238 with exponent 0
  (`test_probe_floor_is_exact_for_repeating_cost`, `test_probe_amount_is_integer_decimal`).
- Fallback order with every later condition also true (C6 table, S13 sentence), exact sentences,
  singulars, default via the registry; clicks sentence with `fmt_unit_cost` money
  (`test_probe_fallback_order_all_conditions_true`, `test_probe_clicks_unit_exact_sentence`).
- Money uses `decision.units.fmt_unit_cost`, counts `claims.vocab.fmt_count`, including in the
  fallback sentence (B26 (1)).
- Refresh: `_budget_horizon` sits inside the existing `try`, so refresh still never raises when
  `store.polls` raises or `pipeline._economics` raises (both give a record:
  `test_probe_refresh_never_raises_when_store_polls_raises`,
  `test_probe_refresh_economics_exception_falls_back`). No economics path still skips before any
  load (`test_probe_refresh_skipped_paths_unchanged`). `_economics` None or any exception gives the
  S8 fallback and pipeline then skips or fails as before (acceptance tests pass). `spent` and
  `since` are both set or both None. Refresh passes `"meta"` and `poll_rec.started_at` (S12).
- `horizon_basis` is passed to `CompareRequest`; `_horizon` is kept as the fallback builder.

## Not judged

The four failing refresh acceptance tests need L10 (basis into the run's notices), as stated.
A store failure inside `spend_to_date` turns a would-be run into `failed` instead of a fallback;
the spec says nothing either way, so it is not a finding.
