# Writer's guide for client reports, v0.1

Companion to `Client_Report_Template_v0.1.md`. The engine already runs these rules on its own
output (claims checker G5, provenance G7, floors). This guide puts them where the person writing
the report can see them, because a hand-written sentence can break a rule the engine never got to
check.

Write in Atma's voice (`/Users/atma1/gh_all/system_instructions/6_Writing Prompt (for LLM).md`),
speaking to one intelligent person who does not do statistics for a living.

## Translations

| Engine term | Plain words | Example |
|---|---|---|
| Posterior median (q50) | most likely | "most likely 4.1%" |
| 90% credible interval (q05 to q95) | very probably between | "very probably between 3.6% and 4.6%" |
| Estimable | firm enough to act on | "This one is firm enough to act on." |
| Marginal | a rough figure | "Treat this as a rough figure." |
| Below floor / not knowable | too early to say | "Too early to say. We have 8 clicks; we need about 58." |
| p_best | the chance that this ad is the best one | "a 96% chance it is the ad people click most often" |
| Expected loss | what it would cost if we are wrong | "If we are wrong, it costs about $12 over the next 1,000 clicks." |
| Prior | our starting point, from typical businesses like yours | |
| Prior weight | how much the starting point still counts | "On this ad the starting point counts for almost nothing now." |
| Shrinkage | pulled toward the starting point | "Small ads stay close to the starting point until they earn their own number." |
| Prior surprised | your numbers landed outside what we expected | "Your ads beat the figures we started from." |
| Delivery evidence | counted by Meta | |
| Platform-attributed | credited to the ads by Meta | |
| Commercially realized | what your business recorded | "from your order records" |
| View-through | people who saw the ad and acted within a day without clicking it | |
| Platform-modeled | estimated by Meta rather than observed | |
| Funnel link not estimated | we cannot yet tie clicks and sign-ups together across ads; that needs more ads | |
| Regime mismatch | the data does not meet the conditions for a firm figure yet | name the condition |
| Conjugate / joint model, R-hat, ESS | leave out of the client report | the diagnostics live in the internal page |

## Rules

1. Every number in section 3 comes from the engine's run, at the engine's rounding. Every other
   number is a count from the store or an outside figure, and says where it came from.
2. Outside information (email platform, Meta audience breakdowns, the client's own notes, what we
   saw on their site) is welcome in sections 2 and 5, labelled in the sentence or table that uses
   it. Never in section 3 (D50).
3. A quantity the engine marks too early never shows an estimate, not even "about". Say what it
   needs. Counts can still appear in section 2.
4. No ad caused anything. Meta chooses who sees which ad, so a comparison between ads is not a fair
   test. "IMG3 gets clicked more often" passes. "IMG3 drives more clicks" does not.
5. Better, best, more, ahead: only when the engine's comparison says so, and with the chance
   attached.
6. A lead or sign-up is counted, never given a dollar value (D33). No revenue, no return on spend
   for a lead client.
7. Our advice is labelled as judgment. It never borrows a number from section 3 to sound surer
   than it is.
8. When something is too early, the report says so in section 1 too, if it matters to the decision.
9. Name ads the way the client named them. Never show an id.
10. No jargon from the glossary's left column in the body. If a term is needed, use the plain words
    and put the term on the back page.

## Source labels

| Source | Label in the text |
|---|---|
| Meta impressions, clicks, spend | counted by Meta |
| Meta conversions | credited to the ads by Meta |
| Meta age, gender, placement breakdowns | Meta's breakdown |
| Email platform list or export | your Klaviyo list (or the platform's name), with the export date |
| Client's order records | your order records |
| Prior scores | our check of our starting points |
| What we saw on their page or form | what we saw on your page, with the date |
| Published benchmarks | published figures for [who], with the publisher |

## Before sending

1. Every section 3 number matches the run named in the header.
2. Every other number has its source label.
3. No estimate appears for anything marked too early.
4. No causal verb is attached to an ad.
5. Section 1 alone would not mislead.
6. Read it aloud once. Cut anything that sounds like a report instead of a person.
