# Integration follow-ups (not blocking merge)

- P4 status_registry `_key` is quantity name + scope only. A holdout estimate on new, non-superset pulls is refused an improvement over a platform_attributed estimate of the same name and scope. Key should include evidence_class (and design). Owner: P4 follow-up before the holdout pieces merge.
- P4 run_record: raw `DROP TABLE` recreates an empty table on next connect. Tamper-evidence (hash chain or row count check) beyond the API is open.
- P4 open questions 1-4 in spec/manifests/P4.md (attribution-change notice key; platform-modeled regime; Feasibility.available optional; decision `required` ownership).
- P3 currency travels as a base-26 float in posterior.params ("currency.code"); decode uses int() (truncates on float noise). Replace with a core field `FunnelState.currency` (integrator change) and drop the codec; until then use round().
- P3 contribution_per_click on the exact path treats observed CPC as a constant; CPC uncertainty ignored with no notice. Check against §7.2/§8.1 intent.
- P3 exact quadrature falls back to MC for InvGamma shape in (1,2] and heavy lognormals; MC SE meaningless with infinite variance. Disclose or refuse.
- P3 manifest open questions 1-8 (derive's placeholder feasibility vs P4 publish; Comparison units for CTR/CVR objectives; p_exceeds for rates; reference priors pending owner; NUTS flag keys for P5; EVSI for volume tests; too-few-ads notice from fallback; registry keys requested by P3).
