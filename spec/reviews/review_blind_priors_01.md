# Blind spec review 01: Prior_Learning_Specification_v0.1 (L6, L7)

Read-only review against the code at branch eng-bayes-v2. Spec line numbers are from the file.

## Answers to the specific questions

1. Does adding `lead_records` to default.yaml break `prior_paths()` or a frozen test? No.
   `pipeline.prior_paths()` (pipeline.py:574) reads only `records`. `_default_prior` (registry.py:271) loops
   over the two tables `records` and `pending_records` by name, so a third key is ignored until L6 adds
   it. `test_d32_structural_priors` asserts only on `pending_records` and `records`. No acceptance test
   greps the file's top-level keys. Risk is only behavioural: `_default_prior` hits `records.cvr` first,
   so the lead table is reached only if L6 puts the lead branch before that loop (see A1).
2. Statistical definitions: correct and well-defined for fixed integer n, k, with two caveats (A6, A7).
3. Merge per (ad, date) across polls with the Store protocol: possible, awkward (A4).
4. Ceiling vs a lead prior: yes, a real interaction (A2).
5. A lead run still picking up the purchase cvr prior: three paths (A1, A3, A8).

## (A) Blueprint gaps

A1. C1 (line 42-47) does not say where the lead branch sits in `_default_prior` (registry.py:271-295).
The loop returns on the first table containing the path, and `cvr` is in `records`. A builder who adds
`lead_records` to the tuple after `records` gets the purchase prior for a lead run and the L6 check fails
quietly in one build and passes in another. Also `_default_prior(parameter_path)` has no `conversion_kind`
argument (spec §3 item 2 adds it only to `resolve`), and `resolve` calls it at registry.py:339. State: the
lead table is consulted first when kind is lead, and `_default_prior` gains the argument. Also state the
`ref`/`evidence_refs` string equals `priors/default/lead_records/cvr@v1`, which `registries.resolve` must be
able to read; confirm the registry loader walks a four-part path.

A2. Plausibility ceiling (bounds.yaml `plausibility.ceiling_q99: {cvr: 0.50}`, registry.py:_ceiling keys on the
last path segment, so a lead `cvr` is held to the purchase ceiling). C4 (line 54) approves the lead default
through the file's elicitation, which skips `approve` and so skips C6, so the default is never checked. But
a client lead prior for `cvr` goes through `propose` then `approve` (spec line 25), and C6 refuses it if its
q99 exceeds 0.50. For a lead rate near 28%, any prior with weight under roughly 30 (for example Beta(5.6,
14.4), q99 about 0.52) is refused. Spec is silent. Decide whether a lead ceiling exists
(`ceiling_q99_lead`, keyed by kind, `predictive_check` needs the kind) and whether the default lead prior is
checked against it at test time.

A3. `lead run still picking up purchase cvr` inside the engine. The PriorSet from `resolve_priors` is
used by conjugate and by `plan.resolve_term` (plan.py:143), so those get the lead prior. But
`plan.resolve_term` lines 170-185 re-read `registries.load("priors/default")["records"]` for any path missing
from the PriorSet on synthetic data, always the purchase table, with prior id `make_id("pr_", {source: path,
"params": params})`. Spec C1-C5 do not address it. It cannot fire for `cvr` when `resolve_priors` supplies it,
but the lead D32 hyperprior `logit_scale_cvr` and any future path does. State that the fallback is out of
scope, or give it the kind. Add a check: on a lead run, no `PriorTerm.source` other than `prior_set` and no
`records.cvr` id in `snapshot.priors`.

A4. L7 row merge (lines 62-64) is feasible but the interface is not named. `Store` has `polls(client_id,
*, limit)` newest first, `rows(poll_id)`, `latest_poll`; no "all rows for client". A builder must call
`polls(client, limit=N)` and N is a guess; "every day ever polled" needs N large or a Store addition
(contracts.py:80-96, and the fake in tests/fakes/live must change too). Also `polls` returns error and
interrupted polls; the spec says "ok poll" but not that `status == "ok"` is filtered, nor the order key
(`started_at`, ties by `poll_id`). Also `LiveRow` has no `ad_id` field; the ad is `entity_ids["ad"]`
(refresh.py uses this); rows with no ad id (empty) are not addressed. Recommend: iterate `polls(limit=10**6)`,
keep `status == "ok"`, sort by `started_at` ascending, later overwrites, and say no Store change is made.

A5. `k` definition (line 71). "`conversions_reported`, rounded to the nearest integer" is ambiguous on two
points: round per row or per ad total (the engine does not round; conjugate.py:137 sums floats), and a row
whose `conversions_reported` is None (not stated; conjugate skips it, so n must exclude that row's clicks or
the rate is biased low). Also Python `round` is half-to-even. Pick: sum the floats per ad over rows that
have a value, n counts only those rows' clicks, round the total half-up; if no row has a value the ad is
skipped for `cvr` with a stated reason. `conversions_observed`, when present, should win as in conjugate.py
(`obs if obs is not None else reported`); spec ignores it.

A6. Tail (line 93) and `surprised` are defined correctly (mid-p, two-sided cut at 0.05/0.95), but the two
sides are not symmetric to a user: `tail` near 0 means the prior put too much mass above the data. Say the
direction in the page text. For k = 0 and n large, mid-p is about 0.5 P(0); fine. Edge: computing
`P(K<k)` needs `betabinom.cdf(k-1)`, which is 0 for k = 0; say so (a builder using `cdf(k)` minus half the
pmf gets the same number, but `1 - sf` forms lose precision; check to 1e-9 is fine either way).

A7. `log_bf_vs_in_force` (line 102) sums per-ad marginal log likelihoods, each ad scored on its own against
the same fixed prior. That is the product of independent marginals, which is not the Bayes factor of the
hierarchical model the engine actually fits (ads share a prior, not independent draws, only when a
hyperprior is fixed; with a fixed prior the product is right for the conjugate route). It is correct as
stated for conjugate and misleading for the joint route. Name it "log predictive score difference" or state
the conjugate caveat on the page; "Bayes factor" invites a reading the number does not have. Also `n_ads`
may differ between candidates (not if the same data, but `skipped` is per candidate and could differ only
by prior family); state that all candidates for a path score the identical ad set, so sums compare.

A8. Candidate dedup and roles (lines 76-85). For `ctr`, the lead kind resolves to the purchase default, so
`in_force`, `framework_lead` and `framework_purchase` collapse to one candidate named `in_force`; fine, but
the spec does not say role precedence on a collision (it says "in this order", so first wins). For `cvr` on
a purchase client with no client prior, `in_force == framework_purchase`, and there is no
`framework_lead` candidate: the owner cannot see how the lead prior would have scored on a purchase
client. Decide whether the lead alternative is always shown (recommend yes on cvr, it costs one row; it
means three roles on any client). Resolving "framework" for client id `"__framework__"` calls
`_latest_client_prior`, which reads events.jsonl and returns None; fine, but it records a hop string
`client:__framework__:none` into `resolution`; state that the resolution string is carried verbatim.

A9. `score_priors` "reads the prior registry under data_dir (the same BAYES_DATA_DIR swap as refresh)"
(line 133). `prior_registry._root()` reads the env var at call time (registry.py:57); the swap is the private
`refresh._data_dir` context manager. Say the builder imports it (rename to public) or copies it, and that
`score_priors` runs inside it; two builders will otherwise differ, and a test that sets only `data_dir=` and
not the env var passes or fails by accident.

A10. File name (line 135): `%Y%m%dT%H%M%SZ` has one-second resolution. Two scorings in one second (poll plus
a manual `score-priors`) collide with "never overwrites", and behaviour on collision is not stated (raise,
suffix, skip). Recommend suffix `-2`, `-3`, never raise from `live poll`. Also there is no reader
interface: the page needs `load_latest_score(client_id, data_dir) -> PriorScore | None` (JSON to dataclass
round trip, date and datetime encoding, frozen dataclasses with `list` fields). "Latest" by lexicographic
filename should be stated. Add the JSON schema (`dataclasses.asdict`, ISO dates) or the view test cannot be
written blind.

A11. `PriorScore.days` and `skipped` keys (lines 119, 125). `days` is a tuple of dates but the spec never says
whether it spans the ad data for the path or all rows. `skipped: dict[str, str]` is keyed by ad id; an ad
with n = 0 on a path is skipped with an unspecified reason (the D34 reason is the only one given). Give the
reason strings, since checks compare them. `not_scored` keys "path or prior" is ambiguous; use
`"<path>:<prior_id>"` for non-Beta, or `"<path>"` for a path with no ads.

A12. C2 / G8 on lead runs (lines 49-51). `resolve_priors` raises G8 when `config.priors` carries an id that is
not the one the path resolves to. A client whose config already names the purchase default id for `cvr`
(allowed today) now fails G8 on a lead run, silently turning every refresh to "skipped". Also, as
written, the check at spec line 164 (a requested purchase-default id fails G8 on a lead run) is the intended
behaviour, but the config loader (`live/config.py`) is not mentioned as needing a check or a message.
Recommend naming it in a release note and testing that a skip reason reads clearly.

A13. D45 (Jovannah runs on the framework default priors, owner: "for right now, we start with the defaults")
is modified by this spec without being superseded. Spec line 3 says "Decisions D48 onward"; make the first
decision state D45 is amended for lead runs by D48 and the owner instruction is dated 2026-11-10. Also D47
is the latest in decisions.md? (spec says D48 onward; confirm no D48 exists). `decisions.md` D32 ties the
seven structural priors to the framework approval; C4 gives the lead record its own `elicitation` but the
author/source/rationale for F7 are not given, and F7 does not exist yet: the skeleton cannot be built
before it.

A14. C3 (line 52) says purchase run ids and seeds are unchanged. True only if `_default_prior`'s id
(registry.py:294) stays `make_id("pr_", {"default": path, "params": params})`, which C1's lead id
deliberately differs from by an added `"table"` key. State the purchase id formula is not touched and add a
check that the `records.cvr` id equals the value in a pinned constant. Lead run ids do change (the config
hash includes prior ids, pipeline.py:1152-1156): previously stored Jovannah lead runs keep their old ids,
and `latest_refresh` runs will not match; state this is accepted.

A15. L7 page (lines 146-152). `phrasing.yaml` has `live_columns` (headings) and `live:` (sentences, e.g.
`lead_sentence`). The section title "Priors" and the empty-state "No prior score yet." are sentences, not
columns, and belong under `live`; the spec puts both under `live_columns`. Also `view.render` reads only
`store` and `data_dir`; it has no clock for "scored at"; show the file's own `scored_at`. A score file
older than the latest poll is not marked stale; say whether it is.

A16. L7 data (line 70): ctr uses `impressions` and `clicks`, but `LiveRow.clicks` is link clicks only on Meta
(spec 1 says "link clicks") while the engine's CTR may use link clicks too; keep the same. `k > n` is guarded
only for `cvr`; for `ctr`, `clicks > impressions` is not. Add the same skip with a reason.

## (B) Undecided items, with recommended answers

B1. Lead default numbers and source: left to facts pack F7. Recommend the spec state the form (Beta, mean
near the published lead-gen benchmark, weight 10 to 20 clicks, a weak prior) and that the owner approves
the numbers before L6 merges, since I10 says approval is the owner's.

B2. Ceiling for lead cvr (A2). Recommend a separate key `ceiling_q99_lead: {cvr: 0.80}` in bounds.yaml,
keyed by kind, with `predictive_check(record, kind)`, and apply it to the lead default at test time.

B3. Show `framework_lead` on purchase clients (A8): yes for `cvr` only.

B4. Name "log Bayes factor" (A7): rename to "log score difference" in the page and keep the JSON key.

B5. Key for rounding and `None` handling of `conversions_reported` (A5): sum per ad, skip None rows, round
half-up the total.

B6. `surprised` thresholds 0.05 and 0.95: keep; put them in `bounds.yaml` (`prior_scoring.surprise_tail:
0.05`) rather than in code, since the repo moves numbers to registries (bounds.yaml header: changing a value
is a version bump).

B7. Store access for all polls (A4): no Store change; use `polls(limit=10**6)`.

B8. Score-file collision (A10): numeric suffix, no raise.

B9. Scoring on a client with fewer than one scored ad: write a file with empty `paths` and one `not_scored`
entry; print one line; exit 0.

B10. Whether `live poll` scoring runs when the refresh was `skipped` (line 140 says only "ran"): keep "ran";
a skipped refresh (one ad, no economics) still polls fine but the owner may want the score; recommend also
scoring after `skipped`, since scoring needs only rows and the registry. Ask the owner.

B11. Dedupe key by prior_id means a client prior equal in params to the default but with a different id
is shown twice: acceptable, state it.

## Counts

(A) 16 gaps. (B) 11 undecided items.

## Three most important

1. A1 with A3: the lead branch location in `_default_prior` and the `plan.resolve_term` synthetic fallback,
   where a lead run can still read `records.cvr`. A frozen check on the snapshot priors would catch it.
2. A2: the `ceiling_q99.cvr = 0.50` bound is applied by the last path segment, so a client lead prior near
   28% with weight under about 30 is refused at `approve`; the default lead prior skips the check entirely.
3. A4 with A5: row merge and `k` definition. The Store has no "all rows" call, polls and rows need an
   explicit `status == "ok"` filter and ordering, and `conversions_reported` rounding and None handling are
   undefined, so two builders will score different numbers on the same data.
