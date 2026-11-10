# Client report template, v0.1

For a client who runs ads with us and wants to know what is going on and how sure we are. One
report covers one window of their account. The writer's guide (`Writers_Guide_v0.1.md`) holds the
plain-words translations and the rules every sentence has to pass. Decision D50 governs outside
information; G5 and G7 govern everything the engine says.

The order of sections never changes, so a client learns where to look. The header and sections
1, 2, 3 and 7 appear in every report. Section 4 runs long in a client's first report and short
after that. Sections 5 and 6 can say "nothing new this time" in one line, but they are never
dropped.

## Header

Client name, report number, the window it covers (start and end, with the time and time zone of
the last read), and who wrote it. One line under it: "Numbers from Meta are what Meta counted or
credited. Numbers from elsewhere say where they came from."

## 1. Where things stand

| | |
|---|---|
| Does | Gives a busy reader the truth in under a minute |
| Beats | What was spent; what came in; the one thing worth knowing; the one decision or request |
| Length | Four or five sentences, no table |
| Numbers from | Store counts (spend, sign-ups or sales), engine statuses |
| Voice | Plain, direct, warm. Lead with the most useful fact, not the most flattering one |

Pattern, to be rewritten in the writer's own words each time:

> Since [start], your ads have been shown [impressions] times and brought [n] [sign-ups/sales] for
> [spend]. [The one thing worth knowing, said simply.] [What is still too early to say.] [The one
> thing we need from you, or the one decision.]

A reader who stops here must not be misled. If the most important fact is that something is too
early to call, say that here.

## 2. What happened

| | |
|---|---|
| Does | The record, before any interpretation |
| Beats | One table per platform; one short paragraph on anything odd in it; outside sources that confirm or contradict it |
| Numbers from | Store rows (Meta counted or credited), each column labelled; outside sources allowed (D50), each labelled |
| Voice | Flat and exact. No adjectives on numbers |

The table, one row per ad, with a total row:

| Ad | Shown (impressions) | Link clicks | Spent | [Sign-ups/Purchases] credited by Meta |
|---|---|---|---|---|

Under it, the source line: "Shown, clicks and spend: counted by Meta. Sign-ups: credited to the ads
by Meta, including people who saw an ad and signed up within a day without clicking it."

Then outside confirmation when we have it, labelled: "Your Klaviyo list received 74 sign-ups on
the same days (Klaviyo export, 10 November)." A day-by-day line is optional; use it when the days
differ in a way the client would want to see.

## 3. What we can say, and how sure we are

| | |
|---|---|
| Does | Every estimate the engine stands behind, with how sure it is; every question it cannot answer yet, with what it needs |
| Beats | Firm or rough findings first; then the comparison between ads; then the "too early to say" list |
| Numbers from | Engine quantities only (G7). Nothing from outside sources in this section (D50) |
| Voice | Careful, but not timid. Say the number, then the range, then how firm it is |

A finding the engine calls estimable:

> [Ad]'s click rate is most likely [q50], and very probably between [q05] and [q95].

A finding the engine calls marginal adds the reason in plain words:

> Treat this as a rough figure: [plain reason].

A comparison, only when the engine's comparison supports it:

> There is a [p_best] chance that [ad] is the ad people click most often.

Below-floor quantities never show an estimate. They go in a short "too early to say" list, each
with what it needs:

> How often a click turns into a sign-up, for [ad]: too early to say. We have [available]; we
> need about [required].

If the reason is not the amount of data (a regime mismatch, for example Meta estimating part of
the count), say that instead of a number needed.

## 4. How we work this out

| | |
|---|---|
| Does | Explains the method once, with the client's own numbers, so later reports can be short |
| Beats | The problem with taking small numbers at face value; the starting point from typical businesses; how their data takes over; what we refuse to say |
| Numbers from | The client's own counts and engine figures already shown above |
| Voice | Conversational. One example, theirs. No formulas, no "Bayesian" in the first paragraph |

First-report version (adapt the examples to the client):

> Say an ad gets eight clicks and three of them sign up. On paper that ad converts better than
> anything else you are running. Nobody should believe it. Eight clicks is a coin tossed eight
> times.
>
> So we start somewhere sensible. Before your ads ran, we looked up what is typical: how often
> people click ads like yours, and how often a click turns into a sign-up, from published figures
> for thousands of advertisers. That is our starting point. Every click and sign-up you get pulls
> our estimate away from it and toward what is really happening in your account. An ad with eight
> clicks barely moves off the starting point. An ad with two hundred clicks has mostly left it
> behind.
>
> This is called Bayesian statistics, and it does one thing very well: it tells you how sure to be.
> Every figure we give you comes with a range, and we only call something firm when the range is
> narrow enough to act on. When it is not, we say "too early to say" and tell you how much more
> data it would take.
>
> One more thing we will not do. Meta decides who sees which ad, so your ads are not a fair
> contest. We can tell you which ad is doing better. We cannot tell you that the ad caused it.

Later-report version: two or three sentences reminding the reader that small numbers stay close
to the starting point, ranges say how sure we are, and "too early to say" means exactly that.

## 5. What we are learning

| | |
|---|---|
| Does | What this window taught us about their customers, their ads and our own assumptions |
| Beats | How our starting points held up (prior scores); who is responding (outside sources); anything we got wrong |
| Numbers from | Prior score files; outside sources, each labelled (D50) |
| Voice | Curious, honest, specific. This is where the report can have some personality |

How our starting points held up, in plain words:

> Your ads are beating the typical figures we started from. [Example.] We have widened our
> starting point so your own numbers take over faster.

Audience and behaviour, labelled with the source in the sentence: "Meta's breakdown of the people
who signed up", "your Klaviyo list", "what we saw on your page". Never mix these into section 3.

When we got something wrong, say so here, plainly, and what changed.

## 6. What we recommend

| | |
|---|---|
| Does | What to do next, what it costs if we are wrong, and what needs their yes |
| Beats | Engine recommendations (with the expected cost of being wrong and its approval status); then our advice, labelled as judgment |
| Numbers from | Engine recommendations; our advice carries no statistics |
| Voice | Decisive. One recommendation per paragraph. Say what happens if they say no |

An engine recommendation:

> Move [share] of the budget to [ad]. If we are wrong, the expected cost over the next [horizon]
> is about [loss]. This needs your yes.

When the engine makes none, say so in one line and why, in plain words. Our advice follows,
introduced as "Our advice, which is judgment rather than a statistical result:".

## 7. What we need from you

A short numbered list of concrete asks, each with why it matters. Things a client can do in a
sitting.

## Back page: words we use

The glossary in the writer's guide, trimmed to the words this report used.
