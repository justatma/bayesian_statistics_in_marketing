# Live view build: report

Build protocol step 13. Spec `spec/Live_View_Specification_v0.2.md`, decisions D41 to D45,
build log `spec/live_build_log.md` (B1 to B15). Branch `eng-bayes-v2`.

## What was built

| Piece | What it does |
|---|---|
| L0 | Contracts, registry `registries/live.yaml`, store schema, CLI stubs, launchd templates and `scripts/live/` (keys file loaded at run time, never copied into a job) |
| L1 | Meta connector carries names, objective, the account read and the client's conversion type |
| L2 | Append-only SQLite store, poll with redacted error text, recording prune |
| L3 | Internal page, index and loopback server on 127.0.0.1:8765 |
| L3b | Readable headings for the engine, diagnostics and floors tables |
| L4 | Engine refresh after each ok poll, through the existing gates |

The 71 frozen acceptance tests for L1 to L4 pass, unchanged from their recorded hashes. The full suite
passes on the merged branch: 714 passed, 10 skipped. The skips and the missing Google Ads and
LinkedIn recordings predate this build.

## What the reviewers caught

Each finding came with a failing test and is fixed.

| Piece | Finding |
|---|---|
| L1 | Ad names and account values were rewritten as numbers by the text cleaner; an empty pull lost its note |
| L2 | Foreign keys were declared but not enforced |
| L3 | Not reported was decided on the wrong rows; a count could cross a floor its status word did not; 16.96 showed as 17.0; a data directory race under the threaded server; client ids not percent-encoded; rejected requests not logged (B14) |
| L4 | A refresh ran after an error poll; gate reasons carried a prefix (B12) |

## What the smoke run showed

| Check | Result |
|---|---|
| Manual poll of Jovannah's account | ok, 10 rows, refresh ran |
| Secrets in `data/live/` | token value in none of 9 files. One shape match sat in a parquet file's base64 schema block, by chance |
| launchd | both jobs loaded; token absent from job files and logs |
| Server | `/health` 200, bound to 127.0.0.1 only, client page renders |
| Hourly cadence | scheduled poll at 2026-11-09 01:07 UTC, one interval after install, ok, refresh ran |

## Decisions

D41 to D45 in `spec/decisions.md`. D45 records the owner's ruling that Jovannah runs on the
framework's default priors.

## Open questions, each with a recommendation

1. The engine table names ads by id while the tables above it use names. Should it use the names?
   Recommended: yes, a small page change through the same review.
2. Her pixel counted 53 leads from 180 link clicks over 7 days, about 29%. Do those match the
   Klaviyo form's submissions? Recommended: ask Jo for that count. If it matches, set
   `conversion_event_confirmed: {meta: true}`. If it does not, add a Lead fired on the Klaviyo
   submit, which is a change to her live site and needs her yes.
3. The client-facing view waits on the customer-experience work (D41). No action recommended
   until that spec exists.
