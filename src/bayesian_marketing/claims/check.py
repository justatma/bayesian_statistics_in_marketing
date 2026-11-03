"""§10 check_narrative (G5) and intake_prior_proposal.

``check_narrative`` splits the block into sentences and, per sentence, finds the option names
(entity ids known to the bundle), metric words, numbers, comparatives and causal verbs. Each
rejection reason quotes the offending token as written.

- Numbers: a percent, money amount or plain number must equal a bundle value at the registry's
  display precision. Quantities are narrowed to the options and metrics the sentence names, so a
  number that belongs to another ad does not pass. A quantity match must not be below floor, and a
  marginal one needs ``caveat_marginal`` in the same sentence. Numbers that are not quantities
  (comparison probabilities and money, guarantee slots, feasibility counts, horizon amounts) pass
  only when they match exactly; comparison probabilities are not accepted in a sentence that names
  a metric, since there a percent is a rate.
- Not-knowable items: a sentence naming a below-floor quantity's option and metric must use the
  ``not_knowable`` phrase.
- Comparatives: the options named must all sit in one bundle ``Comparison``; for better / worse /
  best wording the winner must have the higher ``p_best``; the recommendations sharing that
  comparison's economics must have a decision basis of marginal or estimable.
- Causal verbs (``phrasing.yaml`` ``causal_lexicon``): plain verbs need every quantity about the
  named options to be randomized (or holdout); "incremental" needs holdout (I11).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from bayesian_marketing.claims import vocab as V
from bayesian_marketing.core import (
    Comparison,
    ElicitationRecord,
    GateResult,
    NarrativeBlock,
    PriorRecord,
    Quantity,
    ReportBundle,
    inputs_hash,
    utcnow,
)

_NUM_RE = re.compile(
    r"(?<![\w.])(?P<cur>[$€£]\s?)?(?P<num>\d(?:[\d,]*\d)?(?:\.\d+)?)(?P<suf>%|x)?(?![\w]|[.,]\d)"
)
_SENT_RE = re.compile(r"(?<=[.!?])\s+")
_IDLIKE_RE = re.compile(r"(?<![\w-])(?=[A-Za-z]\w*[_\d])[A-Za-z]\w*(?![\w-])")
_STRONG_WIN = ("better", "best", "outperforms", "outperformed", "outperform", "beats", "beat")
_STRONG_LOSE = ("worse", "worst", "underperforms", "underperformed", "underperform")
_WEAK = ("more", "fewer", "less", "higher", "lower", "greater", "cheaper", "stronger", "weaker")
_OK_DECISION = ("estimable", "marginal")


def _word_re(w: str) -> re.Pattern[str]:
    return re.compile(r"(?<![\w-])" + re.escape(w.lower()) + r"(?![\w-])")


@dataclass
class _Bundle:
    b: ReportBundle
    vocab: set[str]
    plain_ok: set[str] = field(default_factory=set)
    money_ok: set[str] = field(default_factory=set)
    pct_ok: set[str] = field(default_factory=set)  # non-rate percents (slots, allocations)
    prob_pct: set[str] = field(default_factory=set)  # comparison probabilities as percents


def _index(bundle: ReportBundle) -> _Bundle:
    vocab: set[str] = set()
    for q in bundle.quantities:
        vocab |= V.entities_of(q)
    for c in bundle.comparisons:
        vocab |= set(c.options)
    ix = _Bundle(bundle, vocab)
    for c in bundle.comparisons:
        for p in (*c.p_best.values(), *c.p_exceeds_break_even.values()):
            ix.prob_pct.add(V.fmt_percent(p))
            ix.plain_ok.add(V.fmt_probability(p))
        for m in (*c.expected_value.values(), *c.expected_loss.values()):
            ix.money_ok.add(V.norm_number(V.fmt_amount(abs(m.amount))))
        ix.plain_ok.add(V.norm_number(V.fmt_count(float(c.objective.horizon.amount))))
    for r in bundle.recommendations:
        for m in (r.expected_benefit, r.expected_loss):
            if m is not None:
                ix.money_ok.add(V.norm_number(V.fmt_amount(abs(m.amount))))
        ix.plain_ok.add(V.norm_number(V.fmt_count(float(r.horizon.amount))))
        for slot in r.guarantee.slots.values():
            for m in _NUM_RE.finditer(slot):
                _accept_written(ix, m)
        alloc = r.params.get("allocation")
        if isinstance(alloc, dict):
            for share in alloc.values():
                if isinstance(share, int | float):
                    ix.pct_ok.add(V.fmt_percent(share))
    for q in bundle.quantities:
        f = q.feasibility
        for x in (f.available, f.required):
            if x is not None and V.finite(x):
                ix.plain_ok.add(V.norm_number(V.fmt_count(x)))
    return ix


def _accept_written(ix: _Bundle, m: re.Match[str]) -> None:
    num = V.norm_number(m.group("num"))
    if m.group("suf") == "%":
        ix.pct_ok.add(num + "%")
    elif m.group("cur"):
        ix.money_ok.add(num)
    else:
        ix.plain_ok.add(num)


@dataclass
class _Sentence:
    text: str
    low: str
    entities: list[str]  # bundle option names, in order of appearance
    metrics: set[str]


def _sentence(text: str, ix: _Bundle) -> _Sentence:
    low = text.lower()
    found: list[tuple[int, str]] = []
    for e in ix.vocab:
        m = _word_re(e).search(low)
        if m:
            found.append((m.start(), e))
    metrics = set()
    for name, aliases in V.METRIC_ALIASES.items():
        if any(_word_re(a).search(low) for a in aliases):
            metrics.add(name)
    # "conversion rate" also contains no other alias; "contribution per click" contains
    # "contribution": keep the longer reading only.
    if "contribution_per_click" in metrics:
        metrics.discard("contribution")
    return _Sentence(text, low, [e for _, e in sorted(found)], metrics)


def _relevant(s: _Sentence, quantities: list[Quantity], *, by_metric: bool) -> list[Quantity]:
    out = quantities
    if s.entities:
        named = set(s.entities)
        out = [q for q in out if V.entities_of(q) & named]
    if by_metric and s.metrics:
        out = [q for q in out if q.name in s.metrics]
    return out


def _displays(q: Quantity) -> set[str]:
    return {V.norm_number(V.fmt_value(q, v)) for v in q.estimate.summary.values() if V.finite(v)}


def _check_numbers(s: _Sentence, ix: _Bundle, phr: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    caveat = phr["caveat_marginal"].lower() in s.low
    rel = _relevant(s, ix.b.quantities, by_metric=True)
    for m in _NUM_RE.finditer(s.text):
        tok = m.group(0).strip()
        num = V.norm_number(m.group("num"))
        suf, cur = m.group("suf"), m.group("cur")
        if suf == "%":
            key, kinds = num + "%", V.RATE_NAMES
        elif cur:
            key, kinds = num, V.MONEY_NAMES
        else:
            key, kinds = num, V.MONEY_NAMES | V.RATIO_NAMES
        hits = [q for q in rel if q.name in kinds and key in _displays(q)]
        if hits:
            statuses = {q.feasibility.status for q in hits}
            if "estimable" in statuses:
                continue
            if "marginal" in statuses:
                if not caveat:
                    ids = ", ".join(q.quantity_id for q in hits)
                    reasons.append(
                        f"{tok}: marginal quantity ({ids}) quoted without the caveat "
                        f"{phr['caveat_marginal']!r} in the same sentence"
                    )
                continue
            ids = ", ".join(q.quantity_id for q in hits)
            reasons.append(
                f"{tok}: below-floor quantity ({ids}) stated as a finding; "
                f"say {phr['not_knowable']!r}"
            )
            continue
        if suf == "%":
            ok = key in ix.pct_ok or (not s.metrics and key in ix.prob_pct)
        elif cur:
            ok = key in ix.money_ok
        else:
            ok = key in ix.plain_ok or key in ix.money_ok
        if not ok:
            where = f" for {', '.join(s.entities)}" if s.entities else ""
            reasons.append(
                f"{tok}: number matches no bundle quantity{where} at the registry's rounding"
            )
    return reasons


def _check_not_knowable(s: _Sentence, ix: _Bundle, phr: dict[str, Any]) -> list[str]:
    if not s.entities or not s.metrics or phr["not_knowable"].lower() in s.low:
        return []
    nk_ids = set(ix.b.knowability.not_knowable)
    reasons = []
    for q in _relevant(s, ix.b.quantities, by_metric=True):
        if q.feasibility.status == "below_floor" or q.quantity_id in nk_ids:
            ent = ", ".join(sorted(V.entities_of(q) & set(s.entities)))
            reasons.append(
                f"{ent}: {V.METRIC_LABELS[q.name]} ({q.quantity_id}) is not knowable and may "
                f"appear only as {phr['not_knowable']!r}"
            )
    return reasons


def _comparative_word(low: str) -> tuple[str, str] | None:
    for w in _STRONG_WIN:
        if _word_re(w).search(low):
            return w, "win"
    for w in _STRONG_LOSE:
        if _word_re(w).search(low):
            return w, "lose"
    if _word_re("than").search(low):
        for w in _WEAK:
            if _word_re(w).search(low):
                return w, "weak"
    return None


def _check_comparative(s: _Sentence, ix: _Bundle) -> list[str]:
    hit = _comparative_word(s.low)
    if hit is None:
        return []
    word, direction = hit
    names = list(s.entities)
    unknown = [t for t in _IDLIKE_RE.findall(s.text) if t not in ix.vocab]
    if unknown:
        return [
            f"{', '.join(unknown)}: comparative {word!r} names an option with no comparison "
            "in the bundle"
        ]
    if not names:
        return [f"{word}: comparative names no option, so it matches no comparison"]
    comps: list[Comparison] = [c for c in ix.b.comparisons if set(names) <= set(c.options)]
    if not comps:
        covered = set().union(*(set(c.options) for c in ix.b.comparisons))
        missing = [n for n in names if n not in covered] or names
        return [
            f"{', '.join(missing)}: comparative {word!r} between {', '.join(names)} matches "
            "no comparison in the bundle"
        ]
    reasons: list[str] = []
    comp = comps[0]
    if direction in ("win", "lose"):
        first = names[0]
        others = names[1:] or [o for o in comp.options if o != first]
        for o in others:
            a, b = comp.p_best.get(first, 0.0), comp.p_best.get(o, 0.0)
            if (direction == "win" and not a > b) or (direction == "lose" and not a < b):
                reasons.append(
                    f"{first}: comparative {word!r} against {o} is not supported by the "
                    f"comparison (p_best {first} {V.fmt_probability(a)}, "
                    f"{o} {V.fmt_probability(b)})"
                )
    recs = [r for r in ix.b.recommendations if r.economics_id == comp.economics_id]
    statuses = [r.decision_feasibility.status for r in recs]
    if not statuses or any(st not in _OK_DECISION for st in statuses):
        basis = ", ".join(statuses) or "none"
        reasons.append(
            f"{', '.join(names)}: comparative {word!r} needs a decision basis of marginal or "
            f"estimable; the bundle's is {basis}"
        )
    return reasons


def _check_causal(s: _Sentence, ix: _Bundle, phr: dict[str, Any]) -> list[str]:
    lex = phr["causal_lexicon"]
    reasons: list[str] = []
    rel = _relevant(s, ix.b.quantities, by_metric=False)
    designs = sorted({q.design for q in rel}) or ["none in the bundle"]
    for w in lex["plain"]:
        m = _word_re(w).search(s.low)
        if m and (not rel or any(q.design not in ("randomized", "holdout") for q in rel)):
            tok = s.text[m.start() : m.end()]
            reasons.append(
                f"{tok}: causal verb needs a randomized design; the quantities it is about are "
                f"{', '.join(designs)}"
            )
    for w in lex["incremental"]:
        m = _word_re(w).search(s.low)
        if m and (not rel or any(q.design != "holdout" for q in rel)):
            tok = s.text[m.start() : m.end()]
            reasons.append(
                f"{tok}: 'incremental' needs a holdout design; the quantities it is about are "
                f"{', '.join(designs)}"
            )
    return reasons


def check_narrative(block: NarrativeBlock, bundle: ReportBundle) -> GateResult:
    """G5 (§10 C1). Pure function of the block, the bundle and the phrasing registry."""
    phr = V.phrasing()
    ix = _index(bundle)
    reasons: list[str] = []
    for raw in _SENT_RE.split(block.text.strip()):
        if not raw:
            continue
        s = _sentence(raw, ix)
        reasons += _check_numbers(s, ix, phr)
        reasons += _check_not_knowable(s, ix, phr)
        reasons += _check_comparative(s, ix)
        reasons += _check_causal(s, ix, phr)
    return GateResult(
        gate="G5",
        passed=not reasons,
        blocking=True,
        reasons=reasons,
        inputs_hash=inputs_hash({"block": block, "bundle": bundle}),
        checked_at=utcnow(),
    )


# --- prior proposals ------------------------------------------------------------------------

_PROPOSAL_REQUIRED = ("client_id", "parameter_path", "family", "params", "rationale", "author")
_PROPOSAL_OPTIONAL = ("evidence_refs", "created_at", "version")


def intake_prior_proposal(proposal: dict) -> str:
    """Validate an AtmaOS prior proposal and hand it to ``prior_registry.propose``.

    Keys: client_id, parameter_path, family, params (name -> number), rationale, author, and
    optionally evidence_refs, created_at (ISO 8601), version (default "v1"). Unknown keys and any
    approval field are refused: a proposal from AtmaOS is always ``source="ai_proposal"`` and
    always arrives unapproved (I10, D2). Returns the pending ``prior_id``.
    """
    from bayesian_marketing.prior_registry import registry as prior_registry

    if not isinstance(proposal, dict):
        raise TypeError("a prior proposal is a dict")
    unknown = sorted(set(proposal) - set(_PROPOSAL_REQUIRED) - set(_PROPOSAL_OPTIONAL))
    if unknown:
        raise ValueError(f"prior proposal has unknown keys {unknown}")
    missing = [k for k in _PROPOSAL_REQUIRED if proposal.get(k) in (None, "")]
    if missing:
        raise ValueError(f"prior proposal is missing {missing}")
    params = proposal["params"]
    if not isinstance(params, dict) or not params:
        raise ValueError("prior proposal params must be a non-empty mapping")
    clean: dict[str, float] = {}
    for k, v in params.items():
        if isinstance(v, bool) or not isinstance(v, int | float) or not V.finite(float(v)):
            raise ValueError(f"prior proposal param {k!r} is not a finite number")
        clean[str(k)] = float(v)
    created = proposal.get("created_at")
    created_at = datetime.fromisoformat(created) if isinstance(created, str) else utcnow()
    if created_at.tzinfo is None:
        raise ValueError("prior proposal created_at needs a timezone")
    elic = ElicitationRecord(
        source="ai_proposal",
        rationale=str(proposal["rationale"]),
        evidence_refs=[str(x) for x in proposal.get("evidence_refs") or []],
        author=str(proposal["author"]),
        created_at=created_at,
    )
    record = PriorRecord(
        prior_id="pr_00000000",  # replaced by propose's content id
        parameter_path=str(proposal["parameter_path"]),
        family=str(proposal["family"]),
        params=clean,
        elicitation=elic,
        version=str(proposal.get("version") or "v1"),
        resolution_path=[f"{prior_registry.CLIENT_PREFIX}{proposal['client_id']}"],
    )
    return prior_registry.propose(record)
