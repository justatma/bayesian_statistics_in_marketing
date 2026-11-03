"""§12 render.

Order: refuse a client bundle holding synthetic quantities (I13, G10 re-checked because a bundle
can be built without validation), then G7 (every quantity traces to valid provenance and, when
sampled, to a passing G3 report in the bundle; every recommendation basis id and not-knowable id
names a bundle quantity), then the HTML. Below-floor quantities appear only in the not-knowable
block, which shows available and required as integers and never the estimate. Narrative blocks
appear only when they carry a passing G5 result and pass G5 again against this bundle.
"""

from __future__ import annotations

import string
from pathlib import Path
from typing import Any

import jinja2

from bayesian_marketing.claims import vocab as V
from bayesian_marketing.claims.check import check_narrative
from bayesian_marketing.core import (
    DiagnosticsReport,
    GateFailure,
    GateResult,
    Quantity,
    Recommendation,
    RenderedReport,
    ReportBundle,
    g10_reasons,
    inputs_hash,
    lowest_evidence,
    registries,
    utcnow,
)
from bayesian_marketing.decision.reallocation import EVIDENCE_BY_TARGET
from bayesian_marketing.reporting.template import REPORT_HTML

# Report wording not yet in phrasing.yaml (manifest open question 1: proposed keys
# `no_sampler` and `approval_required`). Kept as named constants until the integrator adds them.
NO_SAMPLER = "exact conjugate model; no sampler ran"  # §12 C5
APPROVAL_TEXT = "requires human approval"  # §4.8 requires_human_approval
LEVEL_REF = "bounds/estimability/posterior_width@v1"


def _level_label() -> str:
    """The registry interval level as a percent label, e.g. "90%"."""
    level = float(registries.resolve(LEVEL_REF)["level"])
    return f"{level * 100:g}%"


def _fail(gate: str, reasons: list[str], payload: Any) -> GateFailure:
    return GateFailure(
        GateResult(
            gate=gate,
            passed=False,
            blocking=True,
            reasons=reasons,
            inputs_hash=inputs_hash(payload),
            checked_at=utcnow(),
        )
    )


def _check_client(bundle: ReportBundle) -> None:
    if bundle.kind != "client":
        return
    bad = [q.quantity_id for q in bundle.quantities if q.provenance.synthetic]
    if bad:
        raise _fail(
            "G10",
            [f"{qid}: synthetic quantity in a client report (I13)" for qid in bad],
            {"run_id": bundle.run_id, "kind": bundle.kind, "quantities": bad},
        )


def g7_reasons(bundle: ReportBundle) -> list[str]:
    """Every missing provenance link (§12 C1). Empty means G7 passes."""
    reasons: list[str] = []
    reports = {d.report_id: d for d in bundle.diagnostics}
    qids = {q.quantity_id for q in bundle.quantities}
    for q in bundle.quantities:
        p = q.provenance
        qid = q.quantity_id
        if not p.data_pull_ids:
            reasons.append(f"{qid}: provenance names no data pull")
        if p.route != "deterministic" and not p.funnel_state_id:
            reasons.append(f"{qid}: provenance names no funnel state")
        reasons += [f"{qid}: {r}" for r in g10_reasons(q)]
        bad = [k for k, v in q.estimate.summary.items() if not V.finite(v)]
        if bad:
            reasons.append(f"{qid}: non-finite summary values {bad}")
        if p.route == "nuts":
            rep = reports.get(q.diagnostics_ref or "")
            if rep is None:
                reasons.append(f"{qid}: diagnostics report {q.diagnostics_ref} not in the bundle")
            elif rep.passed is not True:
                reasons.append(f"{qid}: diagnostics report {rep.report_id} did not pass G3")
    for r in bundle.recommendations:
        for b in r.basis:
            if b not in qids:
                reasons.append(f"{b}: basis of {r.recommendation_id} is not a bundle quantity")
    for nk in bundle.knowability.not_knowable:
        if nk not in qids:
            reasons.append(f"{nk}: listed as not knowable but not a bundle quantity")
    return reasons


def _entity(q: Quantity) -> str:
    return ", ".join(q.scope.ids.values()) or q.scope.level


def _status_label(status: str, phr: dict[str, Any]) -> str:
    return phr["not_knowable"] if status == "below_floor" else status


def _finding(q: Quantity, phr: dict[str, Any]) -> dict[str, Any]:
    s = q.estimate.summary
    return {
        "entity": _entity(q),
        "label": V.METRIC_LABELS[q.name],
        "estimate": V.fmt_value(q, s["mean"]),
        "low": V.fmt_value(q, s["q05"]),
        "high": V.fmt_value(q, s["q95"]),
        "status": q.feasibility.status,
        "status_label": _status_label(q.feasibility.status, phr),
        "caveat": phr["caveat_marginal"] if q.feasibility.status == "marginal" else None,
        "evidence": phr["evidence_plain"][q.evidence_class],
        "route": phr["route_plain"][q.provenance.route],
        "notices": list(q.notices),
    }


def _fill(template: str, slots: dict[str, Any]) -> str | None:
    """Format a registry template sentence by sentence, dropping any sentence with a slot we
    have no value for. None if nothing is left."""
    parts = [p for p in template.replace("\n", " ").split(". ") if p.strip()]
    out = []
    for p in parts:
        names = {f for _, f, _, _ in string.Formatter().parse(p) if f}
        if names <= {k for k, v in slots.items() if v is not None}:
            out.append(p.format(**slots))
    if not out:
        return None
    text = ". ".join(x.rstrip(".") for x in out)
    return text + "."


def _not_knowable(q: Quantity, phr: dict[str, Any]) -> dict[str, Any]:
    f = q.feasibility
    slots = {
        "quantity": f"{V.METRIC_LABELS[q.name]} for {_entity(q)}",
        "available": V.fmt_count(f.available) if V.finite(f.available) else None,
        "required": V.fmt_count(f.required)
        if f.required is not None and V.finite(f.required)
        else None,
        "cost": None,  # the bundle carries no cost of knowing (open question 3)
    }
    return {"text": _fill(phr["not_knowable_block"], slots), "notices": list(q.notices)}


def _horizon(r: Recommendation) -> str:
    return f"{V.fmt_count(float(r.horizon.amount))} {r.horizon.unit}"


def _evidence_plain(qs: list[Quantity], phr: dict[str, Any]) -> str | None:
    """The weakest evidence class among the quantities, in plain words (§12 C4)."""
    if not qs:
        return None
    return phr["evidence_plain"][lowest_evidence([q.evidence_class for q in qs])]


def _rec_basis(r: Recommendation, bundle: ReportBundle) -> list[Quantity]:
    return [q for q in bundle.quantities if q.quantity_id in r.basis] or bundle.quantities


def _guarantee_prose(
    r: Recommendation, bundle: ReportBundle, phr: dict[str, Any], tmpl: dict[str, Any]
) -> str:
    entry = tmpl["templates"].get(r.guarantee.template_id)
    basis = _rec_basis(r, bundle)
    slots: dict[str, Any] = {
        "horizon": _horizon(r),
        "assumption": "; ".join(r.guarantee.assumptions) or None,
        "expected_loss": V.fmt_money(r.expected_loss) if r.expected_loss else None,
    }
    if basis:
        slots["evidence_plain"] = _evidence_plain(basis, phr)
        routes = sorted({q.provenance.route for q in basis})
        slots["route_plain"] = ", ".join(phr["route_plain"][x] for x in routes)
    alloc = r.params.get("allocation")
    if isinstance(alloc, dict) and alloc:
        slots["option"] = max(alloc, key=lambda k: alloc[k])
    slots.update(r.guarantee.slots)
    if entry is None:
        return r.guarantee.statement_math
    names = {f for _, f, _, _ in string.Formatter().parse(entry["text"]) if f}
    if not names <= {k for k, v in slots.items() if v is not None}:
        return r.guarantee.statement_math
    return entry["text"].format(**slots)


def _recommendation(r: Recommendation, bundle: ReportBundle, phr, tmpl) -> dict[str, Any]:
    alloc = r.params.get("allocation")
    alloc_txt = None
    if isinstance(alloc, dict) and alloc:
        alloc_txt = ", ".join(
            f"{k} {V.fmt_percent(float(v))}"
            for k, v in sorted(alloc.items(), key=lambda kv: -float(kv[1]))
        )
    traced = all(b in {q.quantity_id for q in bundle.quantities} for b in r.basis)
    status = r.decision_feasibility.status
    return {
        "action": r.action.replace("_", " "),
        "allocation": alloc_txt,
        "guarantee": _guarantee_prose(r, bundle, phr, tmpl),
        "status": status,
        "status_label": _status_label(status, phr),
        "benefit": V.fmt_money(r.expected_benefit) if r.expected_benefit and traced else None,
        "loss": V.fmt_money(r.expected_loss) if r.expected_loss and traced else None,
        "reversibility": r.reversibility,
        "evidence": _evidence_plain(_rec_basis(r, bundle), phr) or phr["not_knowable"],
    }


def _comparisons(bundle: ReportBundle, phr: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for c in bundle.comparisons:
        # D38.7: the label is the one for the comparison's objective, the same one its guarantee
        # states (contribution and orders: platform-credited; clicks: delivery).
        cls = EVIDENCE_BY_TARGET.get(c.objective.target)
        evidence = phr["evidence_plain"][cls] if cls else phr["not_knowable"]
        rows = [
            {
                "option": o,
                "p_best": V.fmt_percent(c.p_best.get(o, 0.0)),
                "value": V.fmt_money(c.expected_value[o]) if o in c.expected_value else "",
                "loss": V.fmt_money(c.expected_loss[o]) if o in c.expected_loss else "",
            }
            for o in c.options
        ]
        h = c.objective.horizon
        out.append(
            {
                "objective": c.objective.target,
                "horizon": f"{V.fmt_count(float(h.amount))} {h.unit}",
                "rows": rows,
                "evidence": evidence,
            }
        )
    return out


def _diag_rows(d: DiagnosticsReport, thr: dict[str, Any]) -> list[tuple[str, str, str]]:
    def num(x: float | None, fmt: str) -> str:
        return "not recorded" if x is None else format(x, fmt)

    band = thr["ppc_band"]
    rows = [
        ("R-hat, largest", num(d.rhat_max, ".4f"), f"at most {thr['rhat_max']}"),
        ("Effective sample size (bulk), smallest", num(d.ess_bulk_min, ".0f"),
         f"at least {thr['ess_bulk_min']}"),
        ("Effective sample size (tail), smallest", num(d.ess_tail_min, ".0f"),
         f"at least {thr['ess_tail_min']}"),
        ("Divergent transitions", num(d.n_divergences, "d"), f"at most {thr['divergences_max']}"),
    ]  # fmt: skip
    for stage, p in d.ppc.items():
        rows.append((f"Posterior predictive check: {stage}", f"{p:.2f}", f"{band[0]} to {band[1]}"))
    for k, v in (d.loo or {}).items():
        rows.append((f"LOO {k}", f"{v:.2f}", ""))
    return rows


def _knowability(bundle: ReportBundle, phr: dict[str, Any]) -> dict[str, Any]:
    k = bundle.knowability
    by_id = {q.quantity_id: q for q in bundle.quantities}
    nk = [
        f"{V.METRIC_LABELS[by_id[i].name]} for {_entity(by_id[i])}" if i in by_id else i
        for i in k.not_knowable
    ]
    return {
        "observed": ", ".join(k.observed),
        "platform_modeled": ", ".join(k.platform_modeled),
        "not_knowable": ", ".join(nk),
        "windows": sorted(k.attribution_windows.items()),
    }


def _window(bundle: ReportBundle) -> str | None:
    if not bundle.quantities:
        return None
    start = min(q.scope.window[0] for q in bundle.quantities)
    end = max(q.scope.window[1] for q in bundle.quantities)
    return f"{start.isoformat()} to {end.isoformat()}"


def _write_pdf(html: str, path: Path) -> str | None:
    """Optional PDF through the ``pdf`` extra. HTML is the deliverable."""
    try:
        import weasyprint  # type: ignore[import-not-found]
    except ImportError:
        return None
    weasyprint.HTML(string=html).write_pdf(str(path))
    return str(path)


def render(bundle: ReportBundle, out_dir: Path) -> RenderedReport:
    """Write the report HTML under ``out_dir`` (§12). Raises GateFailure on G10 or G7."""
    _check_client(bundle)
    reasons = g7_reasons(bundle)
    if reasons:
        raise _fail("G7", reasons, bundle)

    phr = V.phrasing()
    tmpl = registries.load("guarantee_templates")
    thr = registries.load("diagnostics")["thresholds"]
    watermark = None if bundle.kind == "client" else phr["watermark"][bundle.kind]
    h = inputs_hash(bundle)

    nk_ids = set(bundle.knowability.not_knowable)
    shown = [
        q
        for q in bundle.quantities
        if q.feasibility.status != "below_floor" and q.quantity_id not in nk_ids
    ]
    hidden = [q for q in bundle.quantities if q not in shown]
    narrative = [
        b.text
        for b in bundle.narrative_blocks
        if b.gate is not None
        and b.gate.gate == "G5"
        and b.gate.passed
        and check_narrative(b, bundle).passed
    ]
    sampled = [d for d in bundle.diagnostics if d.sampler == "numpyro_nuts"]
    conjugate = any(q.provenance.route == "conjugate" for q in bundle.quantities) or not sampled

    ctx = {
        "watermark": watermark,
        "client_id": bundle.client_id,
        "run_id": bundle.run_id,
        "kind": bundle.kind,
        "window": _window(bundle),
        "narrative": narrative,
        "recommendations": [_recommendation(r, bundle, phr, tmpl) for r in bundle.recommendations],
        "findings": [_finding(q, phr) for q in shown],
        "comparisons": _comparisons(bundle, phr),
        "not_knowable": [_not_knowable(q, phr) for q in hidden],
        "know": _knowability(bundle, phr),
        "conjugate_phrase": NO_SAMPLER if conjugate else None,
        "diagnostics": [
            {
                "report_id": d.report_id,
                "sampler": d.sampler,
                "passed": d.passed,
                "rows": _diag_rows(d, thr),
                "seeds": ", ".join(str(s) for s in d.seeds),
            }
            for d in sampled
        ],
        "provenance": [
            {
                "qid": q.quantity_id,
                "route": phr["route_plain"][q.provenance.route],
                "state": q.provenance.funnel_state_id or "none",
                "pulls": ", ".join(q.provenance.data_pull_ids),
            }
            for q in bundle.quantities
        ],
        "inputs_hash": h,
        "approval_text": APPROVAL_TEXT,
        "level": _level_label(),
    }
    env = jinja2.Environment(autoescape=True, undefined=jinja2.StrictUndefined)
    html = env.from_string(REPORT_HTML).render(**ctx)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"report_{bundle.run_id}_{bundle.kind}"
    html_path = out_dir / f"{stem}.html"
    html_path.write_text(html, encoding="utf-8")
    pdf_path = _write_pdf(html, out_dir / f"{stem}.pdf")
    return RenderedReport(
        html_path=str(html_path), pdf_path=pdf_path, inputs_hash=h, watermark=watermark
    )
