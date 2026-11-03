"""§8.7 guarantee_report.

Reads the run record (under ``BAYES_DATA_DIR``). For each recommendation with an OutcomeRecord it
compares the stated expected benefit and loss with what was realized and checks interval
coverage. Sources and evidence classes are never pooled. Every metric lives in a bucket
``"<source>.<evidence>"``: source is ``OutcomeRecord.source`` ("atmaos", "ground_truth") and
evidence is ``realized["evidence"]`` (one of EVIDENCE_KINDS), or ``unclassified`` when the outcome
names none. ``by_source["<source>"]`` holds counts only (outcomes, recommendations, skipped).
``coverage_90`` and ``regret`` are keyed by bucket.

Keys read from ``OutcomeRecord.realized`` (all optional): ``benefit`` (compared with
``expected_benefit``), ``loss`` (compared with ``expected_loss``), ``regret`` (against the true
best option), ``covered_90`` (bool), or ``interval_90`` [low, high] with ``truth`` (coverage
computed), ``not_knowable_correct`` (bool, not_knowable verdicts only), ``evidence``, and
``currency`` (ISO code of the money amounts; defaults to the recommendation's stated currency).

An outcome with an evidence value outside EVIDENCE_KINDS is skipped and counted under
``n_skipped_bad_evidence``; one whose currency differs from its recommendation's stated amounts
is skipped and counted under ``n_skipped_currency``. Money is never averaged across currencies:
scored outcomes in more than one currency raise ValueError.

n_recommendations counts the recommendations in the window that have a scored OutcomeRecord.
A recommendation is in the window when its run started on or after ``since``; when its run is not
in the record, when any of its outcomes was recorded on or after ``since``. Outcomes recorded
before ``since`` are not scored.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from statistics import fmean
from typing import Any

from bayesian_marketing.core import AuditReport, OutcomeRecord, Recommendation, RunRecord
from bayesian_marketing.decision import run_record

EVIDENCE_KINDS = ("platform_attributed", "observed", "modeled")
UNCLASSIFIED = "unclassified"


def _evidence(o: OutcomeRecord) -> str | None:
    """The outcome's evidence bucket name, or None when the value is not a known class."""
    ev = o.realized.get("evidence")
    if ev is None:
        return UNCLASSIFIED
    return ev if ev in EVIDENCE_KINDS else None


def _stated_currency(rec: Recommendation) -> str | None:
    for m in (rec.expected_benefit, rec.expected_loss):
        if m is not None:
            return m.currency
    return None


def _covered(r: dict[str, Any]) -> bool | None:
    if "covered_90" in r:
        return bool(r["covered_90"])
    if "interval_90" in r and "truth" in r:
        lo, hi = (float(x) for x in r["interval_90"])
        return lo <= float(r["truth"]) <= hi
    return None


def guarantee_report(since: date) -> AuditReport:
    runs: dict[str, RunRecord] = {
        r.run_id: r for r in run_record.read("RunRecord") if isinstance(r, RunRecord)
    }
    recs: dict[str, Recommendation] = {
        r.recommendation_id: r
        for r in run_record.read("Recommendation")
        if isinstance(r, Recommendation)
    }
    outcomes = [
        o
        for o in run_record.read("OutcomeRecord")
        if isinstance(o, OutcomeRecord) and o.recorded_at.date() >= since
    ]

    def in_window(rec: Recommendation) -> bool:
        run = runs.get(rec.run_id)
        if run is not None:
            return run.started_at.date() >= since
        return any(o.recommendation_id == rec.recommendation_id for o in outcomes)

    window = {rid: r for rid, r in recs.items() if in_window(r)}
    cols: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    counts: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    scored_by_source: dict[str, set[str]] = defaultdict(set)
    scored: set[str] = set()
    bucket_n: dict[str, int] = defaultdict(int)
    currencies: set[str] = set()
    for o in outcomes:
        rec = window.get(o.recommendation_id)
        if rec is None:
            continue
        r, summary = o.realized, counts[o.source]
        ev = _evidence(o)
        if ev is None:
            summary["n_skipped_bad_evidence"] += 1
            continue
        stated_cur = _stated_currency(rec)
        cur = r.get("currency", stated_cur)
        if cur is not None and stated_cur is not None and cur != stated_cur:
            summary["n_skipped_currency"] += 1
            continue
        if cur is not None:
            currencies.add(str(cur))
        key = f"{o.source}.{ev}"
        m = cols[key]
        bucket_n[key] += 1
        summary["n_outcomes"] += 1
        scored_by_source[o.source].add(rec.recommendation_id)
        scored.add(rec.recommendation_id)
        if "benefit" in r:
            m["realized_benefit"].append(float(r["benefit"]))
            if rec.expected_benefit is not None:
                stated = float(rec.expected_benefit.amount)
                m["stated_benefit"].append(stated)
                m["benefit_error"].append(float(r["benefit"]) - stated)
        if "loss" in r:
            m["realized_loss"].append(float(r["loss"]))
            if rec.expected_loss is not None:
                stated = float(rec.expected_loss.amount)
                m["stated_loss"].append(stated)
                m["loss_error"].append(float(r["loss"]) - stated)
        if "regret" in r:
            m["regret"].append(float(r["regret"]))
        cov = _covered(r)
        if cov is not None:
            m["coverage_90"].append(1.0 if cov else 0.0)
        if rec.action == "not_knowable" and "not_knowable_correct" in r:
            m["not_knowable_correct"].append(1.0 if r["not_knowable_correct"] else 0.0)
    if len(currencies) > 1:
        raise ValueError(f"outcomes span currencies {sorted(currencies)}; refusing to average")

    by_source: dict[str, dict[str, float]] = {}
    for source, summary in counts.items():
        by_source[source] = dict(summary) | {
            "n_outcomes": summary.get("n_outcomes", 0.0),
            "n_recommendations": float(len(scored_by_source[source])),
        }
    for key, m in cols.items():
        stats = {f"mean_{k}": fmean(v) for k, v in m.items() if v and k != "coverage_90"}
        if m.get("coverage_90"):
            stats["coverage_90"] = fmean(m["coverage_90"])
        stats["n_outcomes"] = float(bucket_n[key])
        by_source[key] = stats

    nk = [v for m in cols.values() for v in m.get("not_knowable_correct", [])]
    return AuditReport(
        since=since,
        n_recommendations=len(scored),
        by_source=by_source,
        coverage_90={k: fmean(m["coverage_90"]) for k, m in cols.items() if m.get("coverage_90")},
        regret={k: fmean(m["regret"]) for k, m in cols.items() if m.get("regret")},
        not_knowable_correct_share=fmean(nk) if nk else None,
    )
