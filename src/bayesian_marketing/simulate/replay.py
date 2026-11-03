"""§9.4 shadow replay. Piece P11.

The scenario is generated with its seed under ``<BAYES_DATA_DIR>/replay/``, read once through G1,
and cut into one pull per day (each day's pull id hashes the source pull and the day). Day k's run
sees the pulls of days ``start..k``, so each day's data pulls strictly extend the day before's and
a status may improve with the new data (I5). Each run compares every variant on the scenario's one
ad platform under the contribution objective at the registry's default horizon.

Each recommendation gets ``OutcomeRecord(source="ground_truth")`` rows, one per variant:

- ``covered_90``: the variant's true contribution per click lies in the 90% interval of its
  compared quantity;
- ``regret`` (first row only): for an allocation, the true contribution per click of the best
  variant minus the allocation's share-weighted true value, times the horizon, in the economics'
  currency;
- ``not_knowable_correct`` (first row only, not_knowable verdicts): true when the verdict came
  from a compared quantity the data could not yet estimate for some variant (no events), i.e.
  the truth could not be resolved with the data seen; a verdict from missing or unapproved
  economics is not scored.

``evidence`` is ``observed`` when the compared quantity rests on the orders file, else
``platform_attributed``. Scores come from ``audit.guarantee_report`` since the replay began.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from bayesian_marketing import pipeline
from bayesian_marketing.audit.report import guarantee_report
from bayesian_marketing.core import (
    AuditReport,
    CompareRequest,
    DatasetManifest,
    GroundTruth,
    Horizon,
    OrderRow,
    OutcomeRecord,
    PerformanceRow,
    PlatformPull,
    Quantity,
    Recommendation,
    inputs_hash,
    registries,
    utcnow,
)
from bayesian_marketing.decision import run_record
from bayesian_marketing.simulate.generate import MANIFEST_NAME, generate

TRUE_QUANTITY = "contribution_per_click"
METRIC = "contribution"


def _day_of(row: Any) -> date:
    if isinstance(row, PerformanceRow):
        return row.date
    if isinstance(row, OrderRow):
        return row.ordered_at.date()
    return row.date


def split_by_day(pull: PlatformPull) -> dict[date, PlatformPull]:
    """One pull per day of rows. Ids stay ``pull_<platform>_<sha8>`` (D18)."""
    days: dict[date, list[Any]] = {}
    for r in pull.rows:
        days.setdefault(_day_of(r), []).append(r)
    out = {}
    for d, rows in sorted(days.items()):
        sha = inputs_hash({"source": pull.pull_id, "day": d.isoformat()})[:8]
        out[d] = pull.model_copy(
            update={
                "pull_id": f"pull_{pull.platform}_{sha}",
                "rows": rows,
                "window": (d, d),
                "quarantined": [],
                "measurement_changes": [c for c in pull.measurement_changes if d.isoformat() in c],
            }
        )
    return out


def _horizon() -> Horizon:
    h = registries.resolve("decision_defaults/horizon_default@v1")
    return Horizon(unit=h["unit"], amount=h["amount"])


def _compared(s: pipeline.RunSnapshot, ad: str) -> Quantity | None:
    return next(
        (q for q in s.quantities if q.name == s.compare_quantity and q.scope.ids["ad"] == ad),
        None,
    )


def _outcomes(
    rec: Recommendation, s: pipeline.RunSnapshot, gt: GroundTruth
) -> list[dict[str, Any]]:
    tq = gt.true_quantities
    truth = {v: float(tq[f"{v}.{TRUE_QUANTITY}"]) for v in s.variants}
    h = float(s.horizon.amount)
    qs = {v: _compared(s, ad) for v, ad in s.variants.items()}
    realized_class = {q.evidence_class for q in qs.values() if q is not None}
    evidence = "observed" if realized_class == {"commercially_realized"} else "platform_attributed"
    head: dict[str, Any] = {"evidence": evidence, "currency": s.currency}
    if rec.action == "allocate":
        shares = rec.params.get("allocation") or {}
        ad_to_v = {ad: v for v, ad in s.variants.items()}
        value = sum(float(share) * truth[ad_to_v[ad]] for ad, share in shares.items())
        head["regret"] = round((max(truth.values()) - value) * h, 6)
    elif rec.action == "not_knowable":
        if any(q is None for q in qs.values()):
            head["not_knowable_correct"] = True
    rows = []
    for i, (v, q) in enumerate(qs.items()):
        row = dict(head) if i == 0 else {"evidence": evidence, "currency": s.currency}
        row |= {"variant": v, "truth": truth[v], "true_best": gt.true_best.get(METRIC)}
        if q is not None:
            sm = q.estimate.summary
            row["interval_90"] = [sm["q05"], sm["q95"]]
        rows.append(row)
    return rows


def replay(scenario_path: Path, seed: int, start: date, end: date) -> AuditReport:
    """Feed the pipeline one day at a time from ``start`` to ``end``, write ground-truth
    outcomes for every recommendation, and score them (§9.4)."""
    if end < start:
        raise ValueError("replay end is before its start")
    since = utcnow().date()
    out = pipeline.data_dir() / "replay" / f"{Path(scenario_path).stem}_{seed}"
    gt = generate(Path(scenario_path), seed, out)
    manifest = DatasetManifest.load(out / MANIFEST_NAME)
    variants = sorted(manifest.entity_map)
    platform = pipeline.comparison_platform(manifest, variants)
    pulls, _ = pipeline.read_pulls(manifest, out, platform, end)
    by_day: dict[date, list[PlatformPull]] = {}
    for p in pulls:
        for d, dp in split_by_day(p).items():
            by_day.setdefault(d, []).append(dp)

    horizon = _horizon()
    day = start
    while day <= end:
        seen = [p for d, ps in sorted(by_day.items()) if d <= day for p in ps]
        has_perf = any(p.platform == platform and p.window[0] >= start for p in seen)  # type: ignore[index]
        if has_perf:
            request = CompareRequest(
                metric=METRIC,
                variants=variants,
                priors={},
                window=(start, day),
                horizon=horizon,
            )
            ctx = pipeline.execute(manifest, request, manifest_dir=out, pulls=seen)
            for rec in ctx.result.recommendations:
                for realized in _outcomes(rec, ctx.snapshot, gt):
                    run_record.append(
                        OutcomeRecord(
                            recommendation_id=rec.recommendation_id,
                            source="ground_truth",
                            realized=realized,
                            recorded_at=utcnow(),
                        )
                    )
        day += timedelta(days=1)
    return guarantee_report(since)
