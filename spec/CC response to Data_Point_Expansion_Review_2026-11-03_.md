review this. 

Is it improved? /Users/atma1/gh_all/bayesian_statistics_in_marketing/spec/Data_Point_Expansion_Review_2026-11-03.md

  Searched for 1 pattern, read 1 file, ran 2 shell commands

Yes, it's a real improvement, but on a different axis from mine. My index answers one question: what can the engine accept today? The review answers a different one: what evidence would actually help ad decisions? It's broader and much sharper about what each number means. It also caught three places where my index overstates the code. I checked each against the code:

┌───────────────────────────┬─────────────────────────────────────────────────────┬────────────────────────────────────────┐
│    Review's correction    │                 What the code does                  │                Verdict                 │
├───────────────────────────┼─────────────────────────────────────────────────────┼────────────────────────────────────────┤
│ Names and                 │ The reader keeps only account, campaign, ad set and │                                        │
│ objective/result type     │  ad IDs (rows.py:28). Names are dropped. Meta       │ Right. My index overstated both.       │
│ marked "used"             │ "Results" survives only as a note on the pull.      │                                        │
├───────────────────────────┼─────────────────────────────────────────────────────┼────────────────────────────────────────┤
│ Conversions above clicks  │ Yes, at rows.py:162, and the conjugate model        │ Right, and it matters for Jo, who is   │
│ are quarantined           │ refuses them too. Meta view-through and multi-event │ on Meta.                               │
│                           │  counting can legitimately exceed clicks.           │                                        │
├───────────────────────────┼─────────────────────────────────────────────────────┼────────────────────────────────────────┤
│ "Used" lumps together     │                                                     │ Right. Its maturity ladder is better:  │
│ merged and still building │ One flag covers six different states.               │ specified, represented, ingested,      │
│                           │                                                     │ consumed, tested, verified live.       │
└───────────────────────────┴─────────────────────────────────────────────────────┴────────────────────────────────────────┘

Its points about "observed" being too strong a word, and about "required" depending on the decision, are also correct.

Most of the catalogue is a backlog, not near-term work. That covers B2B pipelines, brand surveys, saturation, carryover, media-mix and app or offline journeys. The review says so itself. Given your priority, I'd pull five items from it into the build now, because each affects the first real clients:

1. Conversion semantics. Keep rows where reported conversions exceed clicks, and route them to the platform-reported series instead of the click-based model.
2. Names and objective. Keep the campaign and ad names and the campaign objective through normalization, so reports read in plain language and mixed objectives stay visible.
3. The Objective.target gap. It only allows contribution, orders or clicks, so leads and subscriptions have nowhere to go, which blocks Lieven.
4. GA4 data quality. Record the sampling and thresholding flags GA4 already returns in its response metadata.
5. My index itself. Rewrite spec/data_points.md with the maturity ladder and the corrected statuses.

Shall I log 1–4 as P1 and P8 follow-up fixes and rewrite the index now? The review is untracked in spec/. I'd also commit it as the backlog reference.
