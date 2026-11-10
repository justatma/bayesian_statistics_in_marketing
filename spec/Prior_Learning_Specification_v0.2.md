# Prior learning, v0.2: a lead prior and prior scoring

Owner's instruction, 2026-11-10: set leads with an adjusted, better-assessed prior; score the
priors against what is actually happening; use published benchmarks for a first check, the same
way first priors are estimated when there is no historical data. Jovannah is the client this is
for. Decisions D48 onward. Build protocol applies.

## 1. Why

Every run uses the framework defaults of `registries/priors/default.yaml` (D32, §14 teaching
priors). The `cvr` default, Beta(1, 49), was set for purchases (mean 2%, worth 50 clicks). Since
D46 a run knows when its conversions are leads, but the prior does not change with it. On
Jovannah's data (lead rate about 28% of link clicks) the purchase prior pulls every lead-rate
estimate down: IMG4_TXT1, 53 leads from 188 clicks, is estimated at 23%; IMG1_TXT1, 3 from 6, at 7%.
No prior has ever been scored against the data it met.

## 2. Pieces

| Piece | What | Files |
|---|---|---|
| L6 | Framework lead prior, chosen by conversion kind | `registries/priors/default.yaml` (integrator, skeleton), `prior_registry/registry.py`, `pipeline.py` |
| L7 | Prior scoring: each prior in force, and the framework alternatives, scored against the client's own data | `live/prior_score.py` (new), `cli.py` (live branch), `live/view.py`, `live/templates/live.html` |

The integrator also sets Jovannah's client priors through the existing registry (`propose`, then
`approve` by the owner), from facts pack F7. That needs no code and is not a piece.

## 3. Skeleton (integrator, before builders)

1. `registries/priors/default.yaml` gains a top-level `lead_records` table, same shape as
   `records`, with one entry, `cvr`, whose numbers and elicitation come from F7 (D48). The
   registry `version` stays `v1`: existing default prior ids are a hash of path and params and do
   not change.
2. `prior_registry.resolve(parameter_path, client_id, as_of, *, conversion_kind="purchase")`:
   signature added, body unchanged until L6.
3. `pipeline.resolve_priors(requested, client_id, synthetic, when, *, conversion_kind="purchase")`:
   signature added, passed through to `resolve`.
4. `live/prior_score.py`: the dataclasses of §5 and `score_priors` raising NotImplementedError.
5. `cli.py`: `live score-priors --client <id>` parsed, calling `score_priors`.

## 4. L6: the lead prior

C1. `resolve` with `conversion_kind="lead"`: the client hop is unchanged (a client prior is the
client's own and wins). At the default hop, a path present in `lead_records` resolves to that
record; its `resolution_path` last hop is `default:priors/default/lead_records/<path>@v1`, and its
`prior_id` is `make_id("pr_", {"default": path, "params": params, "table": "lead_records"})`, so
it can never equal a purchase default's id. A path absent from `lead_records` resolves as for
purchase.

C2. `execute` passes `request.conversion_kind` to `resolve_priors`. A requested prior id is
checked against the record the path resolves to for that kind (the existing G8 rule).

C3. Purchase runs are unchanged: same prior ids, same resolution paths, same run ids and seeds.

C4. The lead default is approved through its own `elicitation` block in the file (D32's
per-record elicitation), so G8 passes it on client data.

C5. A lead run's snapshot `priors` names the lead default's id for `cvr` when no client prior
exists.

## 5. L7: prior scoring

### Data

The client's rows from the store, one row per (ad, date) taken from the latest ok poll that has
that (ad, date), so the score covers every day ever polled, not only the poll's lookback window.
Per ad the counts are summed over those days:

| Path | Trials n | Successes k |
|---|---|---|
| `ctr` | impressions | link clicks |
| `cvr` | link clicks | `conversions_reported`, rounded to the nearest integer |

An ad with n = 0 is skipped for that path. When k > n for `cvr` (view-through, D34), the ad is
skipped for `cvr` with the reason "reported conversions above clicks (D34)".

### Candidates

For each path, the candidate priors are, deduplicated by `prior_id`, in this order:
1. `in_force`: `resolve(path, client, now, conversion_kind=kind)`, kind from
   `meta.is_lead_event(config.conversion_event.get("meta"))` as in refresh.
2. `framework_<kind>`: the framework default for the client's kind (resolve for a client id that
   has no client priors, e.g. `"__framework__"`).
3. `framework_purchase` when kind is lead.

Only Beta priors are scored; any other family is listed as not scored.

### Per (path, candidate, ad)

| Field | Definition |
|---|---|
| `n`, `k`, `raw_rate` | as above; `raw_rate = k / n` |
| `prior_q05`, `prior_q50`, `prior_q95` | Beta(a, b) quantiles |
| `tail` | mid-p tail of k under the prior predictive BetaBinomial(n, a, b): P(K < k) + 0.5 P(K = k) |
| `surprised` | `tail < 0.05 or tail > 0.95` |
| `log_score` | natural log of the BetaBinomial(n, a, b) pmf at k |
| `prior_weight` | (a + b) / (a + b + n) |
| `posterior_mean` | (a + k) / (a + b + n) |
| `shrinkage` | `posterior_mean - raw_rate` |

### Per (path, candidate)

`log_score` summed over scored ads; `n_ads`; `n_surprised`; `log_bf_vs_in_force` (this
candidate's summed log score minus the in-force candidate's, 0 for in_force itself).

### Types (skeleton)

```python
@dataclass(frozen=True)
class AdScore:
    ad_id: str; ad_name: str | None; n: int; k: int; raw_rate: float
    prior_q05: float; prior_q50: float; prior_q95: float
    tail: float; surprised: bool; log_score: float
    prior_weight: float; posterior_mean: float; shrinkage: float

@dataclass(frozen=True)
class CandidateScore:
    role: str            # "in_force" | "framework_purchase" | "framework_lead"
    prior_id: str; family: str; params: dict[str, float]; resolution: str
    ads: list[AdScore]; skipped: dict[str, str]   # ad id -> reason
    log_score: float; n_ads: int; n_surprised: int; log_bf_vs_in_force: float

@dataclass(frozen=True)
class PriorScore:
    client_id: str; scored_at: datetime; conversion_kind: str
    days: tuple[date, date] | None          # first and last date scored
    paths: dict[str, list[CandidateScore]]  # "ctr", "cvr" -> candidates in order
    not_scored: dict[str, str]              # path or prior -> reason

def score_priors(config: ClientConfig, store: Store, clock: Clock, *, data_dir: Path) -> PriorScore
def write_score(score: PriorScore, data_dir: Path) -> Path
```

`score_priors` reads the prior registry under `data_dir` (the same `BAYES_DATA_DIR` swap as
refresh) and never writes. `write_score` writes JSON to
`<data_dir>/prior_scores/<client_id>/<scored_at as %Y%m%dT%H%M%SZ>.json` and never overwrites.

### CLI

`live score-priors --client <id>` scores, writes, and prints one line per (path, candidate):
role, prior (family and params), ads scored, ads surprised, summed log score, log Bayes factor
against the prior in force. `live poll` runs the scoring after each refresh that ran, for the
same client; a scoring failure prints one line and never fails the poll.

### Page

The client page gains a section "Priors" after the engine section, from the latest score file:
per path, a table of candidates (role, prior as mean and 90% range, ads surprised of ads scored,
log Bayes factor against the prior in force) and, for the in-force prior, a row per ad (ad name,
n, k, raw rate, prior 90% range, tail, prior weight, shrinkage). Headings come from
`phrasing.yaml` `live_columns` (integrator adds the keys in the skeleton). No score file: the
section says "No prior score yet."

## 6. Checks (acceptance, frozen before builders)

L6: a lead run without client priors resolves `cvr` to the lead default (id, resolution path)
and `ctr` to the purchase default; a purchase run's prior ids, run id and seed equal the base's; a
client cvr prior wins over the lead default on a lead run; a requested purchase-default id on a
lead run fails G8.

L7: hand-computed BetaBinomial values for two ads match `tail`, `log_score`, `prior_weight`,
`shrinkage` to 1e-9; rows from two polls are merged per (ad, date) with the later poll winning;
k > n on cvr is skipped with the D34 reason; candidates are ordered and deduplicated; Bayes
factors are relative to in_force; the file is written once and never overwritten; the CLI line
format; the page section with and without a score file; a failing scorer does not fail `live
poll`.

## 7. Not in scope

Pooling across clients (one client now), vertical priors, and changing any prior automatically.
A score informs; a prior changes only by owner approval.

## 8. Settled by blind review 01 (`spec/reviews/review_blind_priors_01.md`)

Where this section and §1 to §7 differ, this section holds.

R1 (A1). `_default_prior(parameter_path, *, conversion_kind="purchase")`. When the kind is lead
and the path is in `lead_records`, that table is read first and returned; otherwise the existing
loop over `records`, `pending_records` runs unchanged. `resolve` passes the kind. The evidence ref
is `priors/default/lead_records/<path>@v1`.

R2 (A3). `plan.resolve_term`'s synthetic fallback stays out of scope: it fires only for paths
missing from the PriorSet, and `resolve_priors` always supplies `cvr`. Check added: on a lead run
the snapshot's `priors["cvr"]` is the lead default id and no `records.cvr` id appears.

R3 (A2, B2). `bounds.yaml` gains `plausibility.ceiling_q99_lead: {cvr: 0.80}` (engineering
choice). `predictive_check(record, *, conversion_kind="purchase")` uses the lead table for a lead
kind; `approve(prior_id, approver, *, conversion_kind="purchase")` passes it. A test checks the
lead default against the lead ceiling.

R4 (A4, B7). No Store change. L7 calls `store.polls(client_id, limit=10**6)`, keeps
`status == "ok"`, orders by `started_at` ascending then `poll_id`, reads `rows(poll_id)` for each,
and a later poll's row replaces an earlier one for the same (`entity_ids["ad"]`, date). Rows with
no ad id are ignored.

R5 (A5, B5). Per ad and path, over the merged rows: for `cvr`, a row's conversions are
`conversions_observed` when not None, else `conversions_reported`; rows where both are None are
left out and so are their clicks. `k` is the sum, rounded half-up once (`floor(x + 0.5)`). An ad
with no usable row for a path is skipped with "no rows with conversions". For `ctr`, k = link
clicks, n = impressions.

R6 (A16). `ctr` with k > n is skipped with "clicks above impressions"; `cvr` with k > n with
"reported conversions above clicks (D34)"; n = 0 with "no trials".

R7 (A6). `tail` = `betabinom.cdf(k - 1)` (0 when k = 0) + 0.5 × `betabinom.pmf(k)`. Low tail
means the data came in below what the prior expected; high means above. The page says which.

R8 (A7, B4). The JSON key stays `log_bf_vs_in_force`; the page heading says "log score against
the prior in force", with a note that it treats ads as independent under a fixed prior (exact for
the per-ad model, approximate for the joint model). All candidates for a path score the same set
of ads: the skip rules depend on data only.

R9 (A8, B3, B11). Roles in order `in_force`, `framework_lead` (for `cvr` always, whatever the
client's kind), `framework_purchase`; first role wins on an id collision. Resolution strings are
carried verbatim. Candidates with equal params but different ids are both shown.

R10 (A9). `refresh._data_dir` becomes public as `live.refresh.data_dir_env` (rename; refresh uses
it). `score_priors` runs inside it.

R11 (A10, B8). File name `<scored_at %Y%m%dT%H%M%SZ>.json`; if taken, `-2`, `-3`, and so on.
`load_latest_score(client_id, data_dir) -> PriorScore | None` reads the lexicographically last
file. JSON is `dataclasses.asdict` with dates and datetimes as ISO strings; `load` rebuilds the
dataclasses.

R12 (A11). `days` spans the dates of the merged rows used for any path. `skipped` is keyed by ad
id with the R5 and R6 reason strings. `not_scored` keys are `"<path>:<prior_id>"` for a non-Beta
prior and `"<path>"` for a path with no scored ads ("no ads with data").

R13 (A12). A requested id that no longer matches on a lead run fails G8, as intended; Jovannah's
config names no priors. No config check added.

R14 (A13, B1). D48 records the owner's instruction of 2026-11-10 and amends D45 for lead runs.
The lead default's numbers and elicitation come from facts pack F7 and are set in the skeleton.

R15 (A14). The purchase default id formula is untouched; a check pins the `records.cvr` id to its
value on the base. Lead run ids change, which is accepted: stored runs keep their own ids.

R16 (A15). The section title and empty-state sentence are under `phrasing.yaml` `live`
(`priors_title`, `no_prior_score`), headings under `live_columns`. The page shows the score's own
`scored_at` and marks it stale when older than the latest ok poll.

R17 (B6). `bounds.yaml` gains `prior_scoring: {surprise_tail: 0.05}`; surprised means
`tail < 0.05 or tail > 0.95`.

R18 (B9, B10). With no scored ad the file is still written, `paths` empty, `not_scored` saying
why; the CLI prints one line and exits 0. `live poll` scores after any refresh that ran or was
skipped, since scoring needs only rows and the registry; a scoring failure prints one line and
never fails the poll.
