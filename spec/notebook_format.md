# Account notebook format, version bayes-notebook-1.0.0

26 November 2026, Bayesian Engineer. The notebook is how what this seat knows about a client's account, beyond the engine's runs, reaches AtmaOS. It covers the account's history, what the tests showed, and what stands in the way. AtmaOS's importer reads it as claims (producer kind `bayesian`, the engine as speaker), the same way the Boswell importer reads a lean release. Owner rulings: D54 here; D676 and D677 in AtmaOS.

## Where it lives

`notebook/<client_id>/releases/<release_id>/` in the bayesian repository, committed. A release is immutable once written. A later release names its parent and replaces it whole, the way a Boswell release does. `<release_id>` is `nb_<client_id>_<YYYYMMDD>_<n>`, with n counting from 1 within the day.

## Files in a release

| File | What it holds |
|---|---|
| `catalog.json` | One object: `schema` ("bayes-notebook-1.0.0"), `release_id`, `parent_release_id` (or null), `client_id`, `created_at` (UTC ISO 8601), `engine_version`, `engine_commit` (full SHA), `n_entries`, `n_sources`. |
| `entries.jsonl` | One entry per line (fields below). Every entry still standing is repeated in each release; an entry left out of a release is withdrawn. |
| `sources.jsonl` | One copied source per line (fields below). Every source an entry cites is copied here, so each pointer can be checked without reaching this machine's live store. |
| `integrity.json` | `{"algorithm": "sha256", "files": {"<name>": "<hex>"}, "release_hash": "<hex>"}`. It lists every other file in the folder and nothing else. `release_hash` follows Boswell's rule: sha256 over `"<name> <digest>\n"` for each file, sorted by name. |

## An entry

| Field | Type | Meaning |
|---|---|---|
| `entry_id` | string | Stable across releases, `nbe_<client_id>_<nnnn>`. The same fact keeps its id when it is restated. |
| `kind` | enum | `event` (something happened in the account), `finding` (what the data shows), `figure` (a number with its basis), `constraint` (something that limits what can be done, such as the spending limit), `open` (a question not yet answered, and who answers it). |
| `statement` | string | One or two plain sentences a client could read. No personal data: no names, emails or addresses of anyone, and no end-user data. |
| `method` | enum | `observed` (read from Meta or the store) or `estimated` (a modelled figure from an engine run). |
| `date` | ISO date | The day the fact is about, in the client's time zone (from `configs/<client_id>.yaml`). |
| `date_end` | ISO date or null | The end of a period, for a fact that spans one. |
| `as_of` | UTC ISO 8601 | When the fact was last checked against its sources. |
| `quantities` | list | Optional. Each is `{name, value, unit}`. An estimated quantity adds `p05`, `p50`, `p95` and `level` (0.9), the same reading as spec 42 FR7.2's `claim_quantities`. |
| `basis` | list, at least one | Each is `{source_id, role}`, where `role` is `primary` or `context`. Each `source_id` must be in this release's `sources.jsonl`. |
| `supersedes` | string or null | The `entry_id` this entry corrects, when it changes what an earlier entry said. |
| `tags` | list of strings | Free, for search: `creative_test`, `learning_reset`, `spending_limit`, and the like. |

## A source

| Field | Type | Meaning |
|---|---|---|
| `source_id` | string | `src_<sha256 of content, first 16 hex>`. |
| `kind` | enum | `engine_run` (an engine run file), `meta_change` (one item from the ad account's change history), `meta_object` (an ad, ad set, campaign or account as read from Meta), `meta_insights` (a stated slice of Meta insights), `live_rows` (rows from the live store). |
| `ref` | object | Where it came from. For `engine_run`: `{run_id}`. For `meta_change`: `{event_type, event_time, object_id}`. For `meta_object`: `{object_type, object_id, read_at}`. For `meta_insights`: `{level, object_ids, fields, date_start, date_end, read_at}`. For `live_rows`: `{poll_id, ad_ids, date_start, date_end}`. |
| `content` | object | The copied item, canonical JSON. Person fields are removed before copying (`actor_name`, `actor_id`, any name, email or user id), and the names of the removed fields are listed in `redacted`. An engine run is copied whole. |
| `redacted` | list of strings | The fields removed, so the copy's honesty can be checked. |
| `content_sha256` | hex | sha256 of `content` serialised as canonical JSON (sorted keys, no spaces, UTF-8, `ensure_ascii` false). |

## What the importer checks

Each file against `integrity.json`, and no file that isn't listed. The release hash, recomputed. Each source's `content_sha256` against its `content`, and its `source_id` against that hash. Each entry's basis present in `sources.jsonl`. `catalog.json`'s counts. A release already imported writes nothing. A release whose parent was imported replaces the parent's run whole.

## How it maps to the record (the Head Engineer's reading, 26 Nov)

Producer kind `bayesian`. One producer run per release. One claim per entry, with the engine as speaker. Method `observed` or `estimated` as the entry states. Quantities go in `claim_quantities` at level 0.9. Evidence is an engine-item pointer per basis source, carrying `content_sha256`. No new table and no migration.
