# P11 review fixes (D38)

Branch: `piece/P11` (worktree of your own; check it out). Files: `src/bayesian_marketing/pipeline.py`, `cli.py`, `atmaos/**`, `simulate/replay.py`, `lag/model.py` (only for D38 item 3), `reporting/**` (only for D38 item 7), `tests/unit/p11/**`.
Read: spec/decisions.md D38 (the ruling), D16, D27, D30, D33; spec v0.3 §9.4, §11, §13.2; the review findings below.
Findings to fix (reviewer's probes in /private/tmp/claude-502/-Users-atma1-gh-all-bayesian-statistics-in-marketing/1574367d-98a5-4bbc-9cbb-81210630bc59/scratchpad/p11/):
F1 pipeline.py:117,760 G9 sentence stamped on every not_knowable and reason duplicated (tiny_campaign demo).
F2 pipeline.py:789-794,968 metric/horizon mismatch found after fit/save/publish; `cli demo --metric ctr` tracebacks; contribution with a days horizon too. Validate first; demo chooses impressions for ctr.
F3 pipeline.py:519-537 + lag/model.py: per_conversion_action → empirical lag from orders' first_click_at when enough, else 28-day default with notice. lag_heavy must then refuse a premature stop or continue the test.
F4 cli.py:111-146 Narrator: show not-knowable quantities, negative expected values, the recommended action's expected loss (the allocation's loss, matching the report's "Expected loss"), the true route including nuts_static/nuts_unpooled, the tolerance verdict for the same option the loss refers to, and the report's option names (ad_a/ad_b, not A/B).
F5 replay.py:111-113 not_knowable_correct must be scored against truth at the tolerance (§9.4).
F6 replay `since` = the run's own id/time, not utcnow().date(); note G1 freshness basis in the manifest.
F7 socket: D33 objectives → NotInScope naming the value model; check_narrative must check against the run's bundle ("ad_b converts at 99% and caused sales." must fail); record_approval refuses a second decision on the same recommendation and refuses decided_by "system".
F8 lag source label distinguishes orders file vs platform lag report.
Also (D38.7): the comparisons table evidence label follows the objective (contribution → "what the ad platform credited to the ads").
Gate: `BAYES_PIECES=P11 .venv/bin/pytest -q tests/acceptance/test_P11.py` passes; full suite; ruff check and format. Run the demo on north_pier_day14, tiny_campaign, negative_dependence, lag_heavy and paste the stage lines in the manifest. Commit to piece/P11; add "Review fixes (D38)" to spec/manifests/P11.md; final message as in `_common.md`.
