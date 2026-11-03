"""§11.1 socket functions. Plain dicts across the boundary.

AtmaOS calls the engine; the engine never calls AtmaOS and never imports ``atmaos`` (F7). Every
value returned is JSON-native (``model_dump(mode="json")``), so a result read back from AtmaOS's
ledger compares equal to the one returned.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from bayesian_marketing import pipeline
from bayesian_marketing.claims.check import check_narrative as _check_narrative
from bayesian_marketing.core import (
    ApprovalRecord,
    CompareRequest,
    DatasetManifest,
    GateFailure,
    GateResult,
    Horizon,
    NarrativeBlock,
    OutcomeRecord,
    Recommendation,
    ReportBundle,
    inputs_hash,
    registries,
    utcnow,
)
from bayesian_marketing.decision import run_record
from bayesian_marketing.decision.guarantees import render_guarantee
from bayesian_marketing.prior_registry import registry as prior_registry
from bayesian_marketing.reporting.render import render

EVIDENCE_KEYS = (
    "tool_version",
    "dataset_snapshot_hash",
    "window",
    "metric",
    "priors",
    "configuration",
    "segments",
    "result",
    "uncertainty",
    "tool_result_id",
)
"""G3.4 (F7): exactly these keys."""

DECISIONS = ("approved", "rejected")
RATE_VERBS = (
    (re.compile(r"\bconver(?:ts|t|ted|ting)\s+at\b", re.IGNORECASE), "has a conversion rate of"),
    (
        re.compile(r"\bclick(?:s|ed)?\s+through\s+at\b", re.IGNORECASE),
        "has a click-through rate of",
    ),
)
"""Rate verbs a narrator may use, read as the metric they state (D38.6)."""
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_CLAUSE_RE = re.compile(r"\s*(?:,\s*and\b|,\s*but\b|;|\band\b|\bbut\b|\bwhile\b)\s*", re.IGNORECASE)
_IT_RE = re.compile(r"^(?:it|its|this ad|that ad)\s+", re.IGNORECASE)
_OTHER_SUBJECT_RE = re.compile(
    r"^(?:we|i|you|they|our|there|the|a|an|this|that|these|those)\b", re.IGNORECASE
)
NOT_A_PERSON = frozenset({"system", "engine", "atmaos", "auto", "automatic", "bot"})
"""decided_by values that name a process, not a person (G6, D38.6). Compared case-folded."""
REPORT_KINDS = ("client", "demo", "internal")

# §11.3 evidence-class mapping: engine class (and design) -> inventory class.
INVENTORY_CLASS = {
    "deterministic": "deterministic derived quantity",
    "observational": "model inference / prediction",
    "none": "model inference / prediction",
    "randomized": "experimental estimate (between variants; not incrementality)",
    "holdout": "experimental estimate (incremental)",
    "commercially_realized": "model inference / prediction, over commercially realized data",
    "synthetic": "simulation",
}


def inventory_class(evidence_class: str, design: str, synthetic: bool) -> str:
    """§11.3. Synthetic wins; then deterministic; then by design (holdout only for
    causally incremental); commercially realized posteriors keep their qualifier."""
    if synthetic:
        return INVENTORY_CLASS["synthetic"]
    if evidence_class == "deterministic":
        return INVENTORY_CLASS["deterministic"]
    if design == "holdout" and evidence_class == "causally_incremental":
        return INVENTORY_CLASS["holdout"]
    if design == "randomized":
        return INVENTORY_CLASS["randomized"]
    if evidence_class == "commercially_realized":
        return INVENTORY_CLASS["commercially_realized"]
    return INVENTORY_CLASS["observational"]


def _json(x: Any) -> Any:
    if hasattr(x, "model_dump"):
        return x.model_dump(mode="json")
    return x


def _g6(reasons: list[str], payload: Any) -> GateFailure:
    return GateFailure(
        GateResult(
            gate="G6",
            passed=False,
            blocking=True,
            reasons=reasons,
            inputs_hash=inputs_hash(payload),
            checked_at=utcnow(),
        )
    )


# ------------------------------------------------------------------------------- compare


def _request(
    metric: str,
    variants: list[str],
    priors: dict[str, Any],
    window: dict[str, Any],
    segments: dict[str, Any],
) -> CompareRequest:
    """Validated before anything runs (D38.2, D38.6): a D33 objective raises NotInScope naming
    its value model; an unknown metric or a horizon the metric cannot be valued at raises
    ValueError. With no horizon given, the registry's default amount is taken in the unit the
    metric needs (CTR: impressions)."""
    pipeline.compare_quantity(metric)  # NotInScope (D33) or ValueError
    for k in ("start", "end"):
        if k not in window:
            raise ValueError(f"window needs {k!r} (YYYY-MM-DD)")
    h = window.get("horizon")
    if not h:
        default = registries.resolve("decision_defaults/horizon_default@v1")
        h = {"unit": pipeline.horizon_unit(metric), "amount": default["amount"]}
    horizon = Horizon(unit=h["unit"], amount=Decimal(str(h["amount"])))
    pipeline.objective_for(metric, horizon)
    bad = {k: v for k, v in priors.items() if not isinstance(v, str)}
    if bad:
        raise ValueError(f"priors map parameter paths to prior ids; got {bad}")
    return CompareRequest(
        metric=metric,  # type: ignore[arg-type]
        variants=list(variants),
        priors=dict(priors),
        window=(date.fromisoformat(window["start"]), date.fromisoformat(window["end"])),
        horizon=horizon,
        segments=dict(segments),
    )


def compare(
    dataset_uri: str,
    *,
    metric: str,
    variants: list[str],
    priors: dict[str, Any],
    window: dict[str, Any],
    segments: dict[str, Any],
) -> dict:
    """BayesianResult-shaped dict (§11.2)."""
    request = _request(metric, variants, priors, window, segments)
    path = Path(str(dataset_uri).removeprefix("file://"))
    manifest = DatasetManifest.load(dataset_uri)
    ctx = pipeline.execute(manifest, request, manifest_dir=path.parent)
    return result_of(ctx.snapshot)


def _posterior_entry(s: pipeline.RunSnapshot, variant: str) -> dict[str, Any]:
    ad = s.variants[variant]
    name = pipeline.metric_quantity(s.metric)
    q = next(
        (x for x in s.quantities if x.name == name and x.scope.ids.get("ad") == ad),
        None,
    )
    entry: dict[str, Any] = {"entity": {s.platform: ad}, "metric": name, "synthetic": s.synthetic}
    if q is None:
        reason = s.not_estimable.get(variant, {}).get(name, "not estimable")
        return entry | {
            "quantity_id": None,
            "status": "below_floor",
            "status_reasons": [reason],
            "summary": None,
            "evidence_class": None,
            "inventory_class": None,
            "design": None,
            "notices": [reason],
            "published": False,
        }
    return entry | {
        "quantity_id": q.quantity_id,
        "summary": dict(q.estimate.summary),
        "status": q.feasibility.status,
        "status_basis": q.feasibility.basis,
        "status_reasons": list(q.feasibility.reasons),
        "evidence_class": q.evidence_class,
        "inventory_class": inventory_class(q.evidence_class, q.design, q.provenance.synthetic),
        "design": q.design,
        "route": q.provenance.route,
        "funnel_state_id": q.provenance.funnel_state_id,
        "notices": list(q.notices),
        "published": s.published.get(q.quantity_id, False),
        "synthetic": q.provenance.synthetic,
    }


def result_of(s: pipeline.RunSnapshot) -> dict:
    """§11.2 mapping from a run snapshot."""
    ad_to_variant = {ad: v for v, ad in s.variants.items()}
    c = s.comparison
    p_best: dict[str, float] = {}
    loss: dict[str, float] = {}
    if c is not None:
        p_best = {ad_to_variant[o]: float(p) for o, p in c.p_best.items()}
        loss = {ad_to_variant[o]: float(m.amount) for o, m in c.expected_loss.items()}
    intervals = {}
    for v, ad in s.variants.items():
        q = next(
            (x for x in s.quantities if x.name == s.compare_quantity and x.scope.ids["ad"] == ad),
            None,
        )
        if q is not None:
            sm = q.estimate.summary
            intervals[v] = {
                "quantity": q.name,
                "q05": sm["q05"],
                "q50": sm["q50"],
                "q95": sm["q95"],
            }
    diag = [
        {
            "report_id": d.report_id,
            "sampler": d.sampler,
            "passed": d.passed,
            "rhat_max": d.rhat_max,
            "ess_bulk_min": d.ess_bulk_min,
            "ess_tail_min": d.ess_tail_min,
            "n_divergences": d.n_divergences,
            "ppc": dict(d.ppc),
        }
        for d in s.diagnostics
    ]
    uncertainty = {
        "run_id": s.run_id,
        "recommendation_ids": [r.recommendation_id for r in s.recommendations],
        "currency": s.currency,
        "horizon": _json(s.horizon),
        "objective": None if c is None else _json(c.objective),
        "compare_quantity": s.compare_quantity,
        "method": None if c is None else c.method,
        "mc_standard_error": None if c is None else c.mc_standard_error,
        "decision_feasibility": None if s.decision is None else _json(s.decision),
        "intervals": intervals,
        "interval_level": 0.9,
        "diagnostics": diag,
        "route": _json(s.route),
        "notices": list(s.notices),
        "knowability": _json(s.knowability),
        "economics_id": s.economics_id,
        "synthetic": s.synthetic,
    }
    out = {
        "posterior": {v: _posterior_entry(s, v) for v in s.variants},
        "probability_best": p_best,
        "expected_loss": loss,
        "uncertainty": uncertainty,
        "config_hash": s.config_hash,
        "tool_version": s.tool_version,
    }
    return _plain(out)


def _plain(x: Any) -> Any:
    """JSON-native copy (dates and decimals to strings, tuples to lists)."""
    import json

    from bayesian_marketing.core import canonical_json

    return json.loads(canonical_json(x))


# ------------------------------------------------------------------------------- evidence


def observation_evidence(result: dict, tool_result_id: str) -> dict:
    """Exactly the G3.4 keys."""
    if not tool_result_id:
        raise ValueError("tool_result_id is required")
    s = pipeline.load_snapshot(result["uncertainty"]["run_id"])
    if result.get("config_hash") != s.config_hash:
        raise ValueError("result does not match the run it names (config_hash differs)")
    ev = {
        "tool_version": result["tool_version"],
        "dataset_snapshot_hash": inputs_hash(
            {"manifest": s.manifest_id, "files": s.dataset_hashes}
        ),
        "window": {
            "start": s.window[0].isoformat(),
            "end": s.window[1].isoformat(),
            "horizon": _json(s.horizon),
        },
        "metric": s.metric,
        "priors": dict(s.priors),
        "configuration": s.configuration,
        "segments": s.segments,
        "result": result,
        "uncertainty": result["uncertainty"],
        "tool_result_id": tool_result_id,
    }
    assert set(ev) == set(EVIDENCE_KEYS)
    return _plain(ev) | {"result": result, "uncertainty": result["uncertainty"]}


# ------------------------------------------------------------------------------- recommendations


def _recommendation(rid: str) -> Recommendation | None:
    got = run_record.read("Recommendation", recommendation_id=rid)
    return got[0] if got else None  # type: ignore[return-value]


def recommendations(run_id: str) -> list[dict]:
    """The run's proposed recommendations, guarantees rendered from templates (I8)."""
    recs = run_record.read("Recommendation", run_id=run_id)
    out = []
    for r in recs:
        assert isinstance(r, Recommendation)
        d = r.model_dump(mode="json")
        d["guarantee_text"] = render_guarantee(r.guarantee)
        out.append(d)
    return out


def record_approval(
    recommendation_id: str, approval_ref: str, decision: str, decided_by: str, decided_at: str
) -> None:
    """G6: the approval names a person (not a system account), the recommendation exists and has
    no decision yet (D38.6: one decision per recommendation), the decision is approved or
    rejected. Accepted approvals are appended to the run record."""
    payload = {
        "recommendation_id": recommendation_id,
        "approval_ref": approval_ref,
        "decision": decision,
        "decided_by": decided_by,
        "decided_at": decided_at,
    }
    reasons = []
    if not isinstance(decided_by, str) or not decided_by.strip():
        reasons.append("the approval names no person (decided_by is empty)")
    elif decided_by.strip().casefold() in NOT_A_PERSON:
        reasons.append(f"decided_by {decided_by.strip()!r} is not a person")
    if decision not in DECISIONS:
        reasons.append(f"decision {decision!r} is not one of {DECISIONS}")
    if not isinstance(approval_ref, str) or not approval_ref.strip():
        reasons.append("approval_ref is empty")
    when: datetime | None = None
    try:
        when = datetime.fromisoformat(str(decided_at).replace("Z", "+00:00"))
        if when.tzinfo is None:
            reasons.append("decided_at carries no timezone")
    except ValueError:
        reasons.append(f"decided_at {decided_at!r} is not an ISO timestamp")
    if _recommendation(recommendation_id) is None:
        reasons.append(f"recommendation {recommendation_id!r} does not exist")
    else:
        prior = run_record.read("ApprovalRecord", recommendation_id=recommendation_id)
        if prior:
            first = prior[0]
            reasons.append(
                f"recommendation {recommendation_id!r} already has a decision "
                f"({first.decision} by {first.decided_by}, {first.approval_ref})"  # type: ignore[attr-defined]
            )
    if reasons:
        raise _g6(reasons, payload)
    run_record.append(
        ApprovalRecord(
            recommendation_id=recommendation_id,
            approval_ref=approval_ref.strip(),
            decision=decision,  # type: ignore[arg-type]
            decided_by=decided_by.strip(),
            decided_at=when,  # type: ignore[arg-type]
        )
    )


def record_outcome(recommendation_id: str, realized: dict) -> None:
    """An outcome AtmaOS observed after acting (source "atmaos")."""
    if _recommendation(recommendation_id) is None:
        raise KeyError(f"recommendation {recommendation_id!r} does not exist")
    if not isinstance(realized, dict):
        raise ValueError("realized must be a dict")
    run_record.append(
        OutcomeRecord(
            recommendation_id=recommendation_id,
            source="atmaos",
            realized=realized,
            recorded_at=utcnow(),
        )
    )


def approve_prior(prior_id: str, approver: str) -> dict:
    """G8 approval through the prior registry, after its predictive check (§5.3 C6)."""
    if not isinstance(approver, str) or not approver.strip():
        raise ValueError("approve_prior needs an approver")
    return prior_registry.approve(prior_id, approver.strip()).model_dump(mode="json")


# ------------------------------------------------------------------------------- narrative, report


def bundle_of(s: pipeline.RunSnapshot, kind: str, blocks: list[NarrativeBlock]) -> ReportBundle:
    if kind not in REPORT_KINDS:
        raise ValueError(f"report kind {kind!r} is not one of {REPORT_KINDS}")
    return ReportBundle(
        kind=kind,  # type: ignore[arg-type]
        client_id=s.client_id,
        run_id=s.run_id,
        quantities=s.quantities,
        recommendations=s.recommendations,
        comparisons=[s.comparison] if s.comparison is not None else [],
        gate_results=s.gate_results,
        diagnostics=s.diagnostics,
        knowability=s.knowability,
        narrative_blocks=blocks,
    )


def _block(block: dict) -> NarrativeBlock:
    d = dict(block)
    d.setdefault("block_id", inputs_hash(d.get("text", ""))[:12])
    d.setdefault("author", "atmaos")
    d.pop("gate", None)  # the gate is the engine's to set
    return NarrativeBlock.model_validate(d)


def _bundle_kind(s: pipeline.RunSnapshot) -> str:
    return "demo" if s.synthetic else "internal"


def _aliases(s: pipeline.RunSnapshot) -> list[tuple[re.Pattern[str], str]]:
    """How a narrator may name an option: "Ad B" or "variant B" for variant B (and the variant
    key itself when it is not a bare letter), each read as the report's option name, the ad id."""
    out = []
    for v, ad in s.variants.items():
        names = [f"ad {v}", f"variant {v}"]
        if len(v) > 2 and v.lower() != ad.lower():
            names.append(v)
        for n in names:
            out.append((re.compile(rf"(?<![\w-]){re.escape(n)}(?![\w-])", re.IGNORECASE), ad))
    return out


def explicit_claims(text: str, s: pipeline.RunSnapshot) -> str:
    """The block with its claims spelled out for G5 (D38.6): variant names read as the report's
    option names, rate verbs as the metric they state, and a clause that drops its subject
    ("... and caused sales") given the option named before it, as a sentence of its own."""
    for pat, ad in _aliases(s):
        text = pat.sub(ad, text)
    for pat, repl in RATE_VERBS:
        text = pat.sub(repl, text)
    ads = sorted(s.variants.values(), key=len, reverse=True)
    named = re.compile("|".join(rf"(?<![\w-]){re.escape(a)}(?![\w-])" for a in ads), re.IGNORECASE)
    out: list[str] = []
    for sentence in _SENTENCE_RE.split(text.strip()):
        last: str | None = None
        for clause in _CLAUSE_RE.split(sentence.strip().rstrip(".!?")):
            clause = clause.strip()
            if not clause:
                continue
            hits = named.findall(clause)
            if not hits and last is not None:
                if _IT_RE.match(clause):
                    clause = _IT_RE.sub(last + " ", clause, count=1)
                elif not _OTHER_SUBJECT_RE.match(clause):
                    clause = f"{last} {clause}"
            elif hits:
                last = hits[-1]
            out.append(clause + ".")
    return " ".join(out)


def _g5(nb: NarrativeBlock, s: pipeline.RunSnapshot, bundle: ReportBundle) -> GateResult:
    """G5 against the run's own bundle, on the block as written and on its explicit reading;
    a claim failing either way fails (never looser than the claims checker alone)."""
    res = _check_narrative(nb, bundle)
    alt = explicit_claims(nb.text, s)
    if alt == nb.text:
        return res
    more = _check_narrative(nb.model_copy(update={"text": alt}), bundle)
    extra = [r for r in more.reasons if r not in res.reasons]
    if not extra:
        return res
    return res.model_copy(update={"passed": False, "reasons": [*res.reasons, *extra]})


def check_narrative(block: dict, run_id: str) -> dict:
    """G5 result for one narrative block against the run's own bundle (D38.6)."""
    s = pipeline.load_snapshot(run_id)
    nb = _block(block)
    return _g5(nb, s, bundle_of(s, _bundle_kind(s), [])).model_dump(mode="json")


def render_report(run_id: str, kind: str, narrative_blocks: list[dict]) -> str:
    """Path to the rendered HTML (PDF beside it when the pdf extra is installed). A narrative
    block renders only with a passing G5; a client report is refused for synthetic data."""
    s = pipeline.load_snapshot(run_id)
    if kind == "client" and s.synthetic:
        raise GateFailure(
            GateResult(
                gate="G10",
                passed=False,
                blocking=True,
                reasons=["a client report cannot be built from synthetic data (I13)"],
                inputs_hash=inputs_hash({"run": run_id, "kind": kind}),
                checked_at=utcnow(),
            )
        )
    probe = bundle_of(s, kind, [])
    blocks = []
    for b in narrative_blocks:
        nb = _block(b)
        blocks.append(nb.model_copy(update={"gate": _g5(nb, s, probe)}))
    bundle = bundle_of(s, kind, blocks)
    out = pipeline.data_dir() / "reports" / run_id
    return render(bundle, out).html_path
