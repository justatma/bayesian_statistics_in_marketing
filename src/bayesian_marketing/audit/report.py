"""§8.7 guarantee_report.

Reads the run record (under ``BAYES_DATA_DIR``). For each recommendation with an OutcomeRecord it
compares the stated expected benefit and loss with what was realized and checks interval
coverage. Sources are never pooled: ``by_source`` has one entry per ``OutcomeRecord.source``
("atmaos", "ground_truth"); an outcome whose ``realized`` names an evidence class goes under
``"<source>.<evidence>"`` instead, so platform-attributed, observed and modeled results stay apart.

Keys read from ``OutcomeRecord.realized`` (all optional, amounts in the account currency):
``benefit`` (compared with ``expected_benefit``), ``loss`` (compared with ``expected_loss``),
``regret`` (against the true best option), ``covered_90`` (bool), or ``interval_90`` [low, high]
with ``truth`` (coverage computed), ``not_knowable_correct`` (bool, not_knowable verdicts only),
``evidence`` (one of EVIDENCE_KINDS).

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


def _source_key(o: OutcomeRecord) -> str:
    ev = o.realized.get("evidence")
    if ev is None:
        return o.source
    if ev not in EVIDENCE_KINDS:
        raise ValueError(f"outcome evidence {ev!r} is not one of {EVIDENCE_KINDS}")
    return f"{o.source}.{ev}"


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
    scored: dict[str, set[str]] = defaultdict(set)
    n_out: dict[str, int] = defaultdict(int)
    for o in outcomes:
        rec = window.get(o.recommendation_id)
        if rec is None:
            continue
        key = _source_key(o)
        m, r = cols[key], o.realized
        scored[key].add(rec.recommendation_id)
        n_out[key] += 1
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

    by_source: dict[str, dict[str, float]] = {}
    for key, m in cols.items():
        stats = {f"mean_{k}": fmean(v) for k, v in m.items() if v and k != "coverage_90"}
        if m.get("coverage_90"):
            stats["coverage_90"] = fmean(m["coverage_90"])
        stats["n_outcomes"] = float(n_out[key])
        stats["n_recommendations"] = float(len(scored[key]))
        by_source[key] = stats

    nk = [v for m in cols.values() for v in m.get("not_knowable_correct", [])]
    return AuditReport(
        since=since,
        n_recommendations=len(window),
        by_source=by_source,
        coverage_90={k: fmean(m["coverage_90"]) for k, m in cols.items() if m.get("coverage_90")},
        regret={k: fmean(m["regret"]) for k, m in cols.items() if m.get("regret")},
        not_knowable_correct_share=fmean(nk) if nk else None,
    )
