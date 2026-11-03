"""§10 check_narrative (G5) and intake_prior_proposal, with the D29 and D31 rulings.

``check_narrative`` splits the block into sentences, and sentences into clauses. Each rejection
reason quotes the offending token as written.

- Numbers (D29.1, D29.4, D29.5, D31.4, D31.5). Every number token is resolved: digits with a
  currency sign or code, %, percent, per cent, x, or a spelled-out number ("nine point nine
  percent"). Abbreviated or scaled figures (k, m, bn, thousand, pct, bps, pp, ...) are rejected
  even when exact, and any digit or percent sign no token covers is rejected (fail closed). A
  quantity number must match a quantity whose option and metric the clause (or, failing that,
  the sentence) names, at the written precision. A quantity match must not be below floor; a
  marginal one needs ``caveat_marginal`` in the same sentence. Allowed without a quantity:
  comparison probabilities and recommendation allocation shares (as a percent or a probability
  at ``probability_decimals``; not in a sentence naming a metric), comparison and recommendation
  money, guarantee slot values, feasibility available/required and ``n_events``, horizon amounts,
  number of ads, days in the window, ISO dates inside the bundle window, this run id, and the
  registry interval level written as "<level>% interval" or "<level>% range".
- Not-knowable items: a sentence naming a below-floor quantity's option and metric must use the
  ``not_knowable`` phrase.
- Comparatives and superlatives (D29.3, D31.1, D31.3, ``comparative_lexicon``): a hit counts only
  when an option is named in its clause (a pronoun there stands for the last option named before);
  ``generic_phrases`` never count. The clause subject (first option; "Compared with X," adds X as
  the other side) must sit with the other options in one Comparison, agree with its ``p_best``
  order, and have a decision basis of marginal or estimable.
- Causal words (D29.2, D31.1, D31.2, ``causal_lexicon``): single words by stem across inflections,
  phrases as written, entries with ".*" as patterns, case-insensitive, scoped to clauses naming an
  option. Only a registry ``negation_frames`` entry earlier in the claim's scope negates it. Plain
  causal words need every quantity about the named options randomized (or holdout); incremental
  words need holdout (I11).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
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
    registries,
    utcnow,
)

# --- tokenizing ------------------------------------------------------------------------------

_SUFFIX = (
    r"(?P<suf>\s?[%\uff05\u2030]|\s?(?:percent|per\s+cent|percentage\s+points?|per\s+mille|"
    r"pct|pc|pp|bps|bp|basis\s+points?|thousand|million|billion)(?![\w])|(?:k|m|bn|x)(?![\w]))?"
)
# D31.5: abbreviated and scaled figures never resolve; the narrator writes full figures.
_ABBREVIATIONS = frozenset(
    {"pct", "pc", "pp", "bps", "bp", "basis points", "basis point", "percentage points",
     "percentage point", "per mille", "\u2030", "\uff05", "k", "m", "bn", "thousand", "million",
     "billion"}
)  # fmt: skip
_CODE = r"(?P<code>\s?(?:usd|eur|gbp|dollars?|euros?|pounds?)(?![\w]))?"
_NUM_RE = re.compile(
    r"(?<![\w.])(?P<cur>[$€£]\s?)?(?P<num>\d(?:[\d,]*\d)?(?:\.\d+)?)" + _SUFFIX + _CODE
    + r"(?![\w]|[.,]\d)",
    re.IGNORECASE,
)  # fmt: skip
_UNITS = {
    w: i
    for i, w in enumerate(
        [
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
            "sixteen",
            "seventeen",
            "eighteen",
            "nineteen",
        ]
    )
}
_TENS = {
    w: 10 * (i + 2)
    for i, w in enumerate(
        ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
    )
}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 1_000_000, "billion": 1_000_000_000}
_NUMWORD = "|".join(sorted([*_UNITS, *_TENS, "hundred"], key=len, reverse=True))
_UNITWORD = "|".join(sorted(_UNITS, key=len, reverse=True))
_SPELLED_RE = re.compile(
    rf"(?<![\w-])(?P<cur>[$€£]\s?)?(?P<words>(?:{_NUMWORD})(?:(?:\s+|-)(?:and\s+)?(?:{_NUMWORD}))*"
    rf"(?:\s+point(?:\s+(?:{_UNITWORD}))+)?)(?![\w-])" + _SUFFIX + _CODE + r"(?![\w])",
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"(?<![\w-])\d{4}-\d{2}-\d{2}(?![\w-])")
_RUN_RE = re.compile(r"(?<![\w-])run_\w+", re.IGNORECASE)
_SENT_RE = re.compile(r"(?<=[.!?])\s+|(?<=[a-z%)\]][.!?])(?=[A-Z])|\n+")
_CLAUSE_RE = re.compile(
    r"\s*[;:]\s*|,\s+(?=(?:and|but|while|whereas|so|yet)\b)|\s+(?:and|while|whereas)\s+",
    re.IGNORECASE,
)
# D31.1: the clause a causal or comparative word belongs to (its option must be named there).
_HIT_CLAUSE_RE = re.compile(
    r"[,;:]|\s+(?:but|and|while|whereas|though|although|yet)\s+", re.IGNORECASE
)
# D31.2: how far a negation frame reaches (across "and" without a comma, not past "but").
_NEG_SCOPE_RE = re.compile(
    r"[;:]|,?\s+but\s+|,\s+(?:and|while|whereas|though|although|yet)\s+", re.IGNORECASE
)
_PRONOUN_RE = re.compile(r"(?<![\w-])(?:it|its|they|them|their|which|who)(?![\w-])", re.I)
# D31.3: "Compared with X, Y has the higher ..." names X as the other option.
_COMPARED_RE = re.compile(
    r"^\s*(?:compared\s+(?:with|to)|versus|vs\.?|relative\s+to|against|unlike)\b", re.IGNORECASE
)
_IDLIKE_RE = re.compile(r"(?<![\w-])(?=[A-Za-z]\w*[_\d])[A-Za-z]\w*(?![\w-])")
_INTERVAL_AFTER_RE = re.compile(r"^\s*(?:credible\s+)?(?:interval|range)\b", re.IGNORECASE)
_INFLECT = r"(?:e|es|ed|ing|s|en|d)?"
_OK_DECISION = ("estimable", "marginal")

# Direction of comparative_lexicon entries: +1 means the first named option is the stronger one.
# Lexicon entries missing here still need a matching Comparison, with no direction check.
_POLARITY = {
    **dict.fromkeys(
        [
            "better",
            "higher",
            "stronger",
            "more",
            "cheaper",
            "outperform",
            "beat",
            "best",
            "highest",
            "strongest",
            "cheapest",
            "winner",
            "leader",
            "lead",
            "leading",
            "win",
            "won",
            "ahead",
            "superior",
            "first",
        ],
        1,
    ),
    **dict.fromkeys(
        [
            "ahead of",
            "superior to",
            "wins against",
            "top performer",
            "the leader",
            "top ad",
            "top campaign",
        ],
        1,
    ),
    **dict.fromkeys(["trail", "inferior", "lose", "lost", "loser", "last"], -1),
    **dict.fromkeys(
        [
            "worse",
            "lower",
            "weaker",
            "fewer",
            "less",
            "underperform",
            "behind",
            "worst",
            "lowest",
            "weakest",
        ],
        -1,
    ),
    **dict.fromkeys(["more expensive", "inferior to", "loses to", "bottom performer"], -1),
}
_SIZE_WORDS = frozenset({"higher", "lower", "more", "fewer", "less", "highest", "lowest"})
_COST_METRICS = frozenset({"cpa", "cpc", "cpm"})


def _word_re(w: str) -> re.Pattern[str]:
    return re.compile(r"(?<![\w-])" + re.escape(w.lower()) + r"(?![\w-])")


def _lex_re(entry: str) -> re.Pattern[str]:
    """A lexicon entry: an entry with ".*" is a pattern (".*" spans words within a clause),
    other phrases match as written (any whitespace), single words by stem."""
    words = entry.lower().split()
    if ".*" in entry:
        body = r"\s+".join(r"[^,;:.!?]*?" if w == ".*" else re.escape(w) for w in words)
        return re.compile(r"(?<![\w-])" + body + r"(?![\w-])", re.IGNORECASE)
    if len(words) > 1:
        return re.compile(
            r"(?<![\w-])" + r"\s+".join(map(re.escape, words)) + r"(?![\w-])", re.IGNORECASE
        )
    w = words[0]
    base = w[:-1] if w.endswith("e") else w
    return re.compile(r"(?<![\w-])" + re.escape(base) + _INFLECT + r"(?![\w-])", re.IGNORECASE)


@dataclass
class _Tok:
    text: str
    value: Decimal
    kind: str  # pct (percent units) | money | plain | ratio | abbrev
    end: int
    start: int = 0


def _spelled_value(words: str) -> Decimal | None:
    parts = re.split(r"\s+point\s+", words.lower(), maxsplit=1)
    total = current = 0
    for w in re.split(r"[\s-]+", parts[0]):
        if w == "and" or not w:
            continue
        if w in _UNITS:
            current += _UNITS[w]
        elif w in _TENS:
            current += _TENS[w]
        elif w == "hundred":
            current = (current or 1) * 100
        elif w in _SCALES:
            total += (current or 1) * _SCALES[w]
            current = 0
        else:
            return None
    s = str(total + current)
    if len(parts) > 1:
        s += "." + "".join(str(_UNITS[w]) for w in parts[1].split())
    return Decimal(s)


def _resolve(
    num: Decimal, suf: str | None, cur: str | None, code: str | None
) -> tuple[str, Decimal]:
    s = re.sub(r"\s+", " ", (suf or "").strip().lower())
    if s in _ABBREVIATIONS:
        return "abbrev", num
    if s in ("%", "percent", "per cent"):
        return "pct", num
    if s == "x":
        return "ratio", num
    return ("money" if cur or code else "plain"), num


def _tokens(text: str) -> list[_Tok]:
    out: list[_Tok] = []
    for m in _NUM_RE.finditer(text):
        try:
            num = Decimal(V.norm_number(m.group("num")))
        except InvalidOperation:
            num = Decimal("NaN")
        kind, val = _resolve(num, m.group("suf"), m.group("cur"), m.group("code"))
        out.append(_Tok(m.group(0).strip(), val, kind, m.end(), m.start()))
    for m in _SPELLED_RE.finditer(text):
        words = m.group("words")
        if words.lower() == "one" and not (m.group("suf") or m.group("cur") or m.group("code")):
            continue  # "one of the ads": a pronoun far more often than a count
        num = _spelled_value(words)
        if num is None:
            continue
        kind, val = _resolve(num, m.group("suf"), m.group("cur"), m.group("code"))
        out.append(_Tok(m.group(0).strip(), val, kind, m.end(), m.start()))
    return out


def _leftover_numbers(text: str, toks: list[_Tok]) -> list[str]:
    """Words holding a digit or a percent-like sign that no token covers (fail closed)."""
    covered = [(t.start, t.end) for t in toks]
    covered += [m.span() for m in _IDLIKE_RE.finditer(text)]
    out = []
    for m in re.finditer(r"\S*[\d%\uff05\u2030]\S*", text):
        signs = "%\uff05\u2030"
        pos = [i for i, ch in enumerate(m.group(0), m.start()) if ch.isdigit() or ch in signs]
        if any(not any(a <= p < b for a, b in covered) for p in pos):
            out.append(m.group(0).strip(".,;:()"))
    return out


def _dec(s: str) -> Decimal:
    return Decimal(V.norm_number(s).rstrip("%"))


# --- bundle index ----------------------------------------------------------------------------


class _Exact(set):
    """Decimals compared as written: equal value and equal precision ("2%" is not "2.0%")."""

    def add(self, d: Any) -> None:
        super().add(str(d))

    def __contains__(self, d: object) -> bool:
        return super().__contains__(str(d))


@dataclass
class _Bundle:
    b: ReportBundle
    vocab: dict[str, str]  # lower-case -> as in the bundle
    displays: dict[str, _Exact] = field(default_factory=dict)  # quantity_id -> values
    plain_ok: _Exact = field(default_factory=_Exact)
    money_ok: _Exact = field(default_factory=_Exact)
    pct_ok: _Exact = field(default_factory=_Exact)
    probs: list[float] = field(default_factory=list)
    window: tuple[date, date] | None = None
    level_pct: Decimal | None = None


def _accept_slot(ix: _Bundle, text: str) -> None:
    for t in _tokens(text):
        if t.kind != "abbrev":
            {"pct": ix.pct_ok, "money": ix.money_ok}.get(t.kind, ix.plain_ok).add(t.value)


def _index(bundle: ReportBundle) -> _Bundle:
    vocab: dict[str, str] = {}
    ads: set[str] = set()
    for q in bundle.quantities:
        for e in V.entities_of(q):
            vocab[e.lower()] = e
        if "ad" in q.scope.ids:
            ads.add(q.scope.ids["ad"])
    for c in bundle.comparisons:
        for o in c.options:
            vocab[o.lower()] = o
    ix = _Bundle(bundle, vocab)
    for q in bundle.quantities:
        shown = ix.displays[q.quantity_id] = _Exact()
        for v in q.estimate.summary.values():
            if V.finite(v):
                shown.add(_dec(V.fmt_value(q, v)))
        f = q.feasibility
        # D31.4: the raw counts the bundle carries for a quantity. Quantity has only n_events
        # (D22); clicks, impressions and spend are not in the bundle (open question).
        for x in (f.available, f.required, q.n_events):
            if x is not None and V.finite(x):
                ix.plain_ok.add(_dec(V.fmt_count(x)))
    for c in bundle.comparisons:
        ix.probs += [*c.p_best.values(), *c.p_exceeds_break_even.values()]
        for m in (*c.expected_value.values(), *c.expected_loss.values()):
            ix.money_ok.add(_dec(V.fmt_amount(abs(m.amount))))
        ix.plain_ok.add(_dec(V.fmt_count(float(c.objective.horizon.amount))))
        ads |= set(c.options)
    for p in ix.probs:
        ix.plain_ok.add(Decimal(V.fmt_probability(p)))
    for r in bundle.recommendations:
        for m in (r.expected_benefit, r.expected_loss):
            if m is not None:
                ix.money_ok.add(_dec(V.fmt_amount(abs(m.amount))))
        ix.plain_ok.add(_dec(V.fmt_count(float(r.horizon.amount))))
        for slot in r.guarantee.slots.values():
            _accept_slot(ix, slot)
        alloc = r.params.get("allocation")
        if isinstance(alloc, dict):
            for share in alloc.values():
                if isinstance(share, int | float):  # D31.4: checked like a probability
                    ix.probs.append(float(share))
                    ix.plain_ok.add(Decimal(V.fmt_probability(share)))
    if bundle.quantities:
        start = min(q.scope.window[0] for q in bundle.quantities)
        end = max(q.scope.window[1] for q in bundle.quantities)
        ix.window = (start, end)
        ix.plain_ok.add(Decimal((end - start).days + 1))
    if ads:
        ix.plain_ok.add(Decimal(len(ads)))
    level = registries.resolve("bounds/estimability/posterior_width@v1")["level"]
    ix.level_pct = Decimal(str(level)) * 100
    return ix


# --- sentences -------------------------------------------------------------------------------


@dataclass
class _Ctx:
    text: str
    low: str
    entities: list[str]  # bundle option names, in order of appearance
    metrics: set[str]


def _ctx(text: str, ix: _Bundle) -> _Ctx:
    low = text.lower()
    found: list[tuple[int, str]] = []
    for key, e in ix.vocab.items():
        m = _word_re(key).search(low)
        if m:
            found.append((m.start(), e))
    metrics = set()
    for name, aliases in V.METRIC_ALIASES.items():
        if any(_word_re(a).search(low) for a in aliases):
            metrics.add(name)
    if "contribution_per_click" in metrics:
        metrics.discard("contribution")
    return _Ctx(text, low, [e for _, e in sorted(found)], metrics)


def _about(entities: list[str], metrics: set[str], quantities: list[Quantity]) -> list[Quantity]:
    """Quantities whose option and metric are both named (D29.4: no fallback)."""
    named = set(entities)
    return [q for q in quantities if V.entities_of(q) & named and q.name in metrics]


def _prob_match(v: Decimal, ix: _Bundle) -> bool:
    for p in ix.probs:
        if v == _dec(V.fmt_percent(p)) or v / 100 == Decimal(V.fmt_probability(p)):
            return True
    return False


def _check_dates_and_runs(s: _Ctx, ix: _Bundle) -> list[str]:
    reasons = []
    for m in _DATE_RE.finditer(s.text):
        try:
            d = date.fromisoformat(m.group(0))
        except ValueError:
            d = None
        if d is None or ix.window is None or not ix.window[0] <= d <= ix.window[1]:
            reasons.append(f"{m.group(0)}: date is outside the bundle's data window")
    for m in _RUN_RE.finditer(s.text):
        if m.group(0).lower() != ix.b.run_id.lower():
            reasons.append(f"{m.group(0)}: not this bundle's run id ({ix.b.run_id})")
    return reasons


def _check_numbers(s: _Ctx, ix: _Bundle, phr: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    caveat = phr["caveat_marginal"].lower() in s.low
    masked = _RUN_RE.sub(" ", _DATE_RE.sub(" ", s.text))
    for clause in _CLAUSE_RE.split(masked):
        if not clause or not clause.strip():
            continue
        c = _ctx(clause, ix)
        entities = c.entities or s.entities
        metrics = c.metrics or s.metrics
        rel = _about(entities, metrics, ix.b.quantities)
        toks = _tokens(clause)
        for t in toks:
            if t.kind == "abbrev":
                reasons.append(
                    f"{t.text}: abbreviated or scaled figure; write the full figure (D31.5)"
                )
                continue
            reasons += _check_token(t, clause, rel, metrics, entities, caveat, ix, phr)
        for word in _leftover_numbers(clause, toks):
            reasons.append(f"{word}: number written in a form the checker cannot read")
    return reasons


def _check_token(
    t: _Tok,
    clause: str,
    rel: list[Quantity],
    metrics: set[str],
    entities: list[str],
    caveat: bool,
    ix: _Bundle,
    phr: dict[str, Any],
) -> list[str]:
    kinds = {
        "pct": V.RATE_NAMES,
        "money": V.MONEY_NAMES,
        "plain": V.MONEY_NAMES | V.RATIO_NAMES,
        "ratio": V.RATIO_NAMES,
    }[t.kind]
    hits = [q for q in rel if q.name in kinds and t.value in ix.displays[q.quantity_id]]
    if hits:
        ids = ", ".join(q.quantity_id for q in hits)
        statuses = {q.feasibility.status for q in hits}
        if "estimable" in statuses:
            return []
        if "marginal" in statuses:
            if caveat:
                return []
            return [
                f"{t.text}: marginal quantity ({ids}) quoted without the caveat "
                f"{phr['caveat_marginal']!r} in the same sentence"
            ]
        return [
            f"{t.text}: below-floor quantity ({ids}) stated as a finding; "
            f"say {phr['not_knowable']!r}"
        ]
    if t.kind == "pct":
        after = clause[t.end :]
        ok = (not metrics and (t.value in ix.pct_ok or _prob_match(t.value, ix))) or (
            t.value == ix.level_pct and bool(_INTERVAL_AFTER_RE.match(after))
        )
    elif t.kind == "money":
        ok = t.value in ix.money_ok
    elif t.kind == "plain":
        ok = t.value in ix.plain_ok or t.value in ix.money_ok
    else:
        ok = False
    if ok:
        return []
    named = []
    if entities:
        named.append(", ".join(entities))
    if metrics:
        named.append(", ".join(V.METRIC_LABELS[m] for m in sorted(metrics)))
    where = f" for {' / '.join(named)}" if named else ""
    return [f"{t.text}: number matches no bundle value{where} at the registry's rounding"]


def _check_not_knowable(s: _Ctx, ix: _Bundle, phr: dict[str, Any]) -> list[str]:
    if not s.entities or not s.metrics or phr["not_knowable"].lower() in s.low:
        return []
    nk_ids = set(ix.b.knowability.not_knowable)
    reasons = []
    for q in _about(s.entities, s.metrics, ix.b.quantities):
        if q.feasibility.status == "below_floor" or q.quantity_id in nk_ids:
            ent = ", ".join(sorted(V.entities_of(q) & set(s.entities)))
            reasons.append(
                f"{ent}: {V.METRIC_LABELS[q.name]} ({q.quantity_id}) is not knowable and may "
                f"appear only as {phr['not_knowable']!r}"
            )
    return reasons


def _lex_hits(low: str, entries: list[str]) -> list[tuple[int, int, str]]:
    hits = []
    for e in entries:
        for m in _lex_re(e).finditer(low):
            hits.append((m.start(), m.end(), e))
    # drop a hit inside a longer one ("more" inside "more expensive")
    return [
        h
        for h in hits
        if not any(o != h and o[0] <= h[0] and h[1] <= o[1] and o[1] - o[0] > h[1] - h[0]
                   for o in hits)
    ]  # fmt: skip


def _spans(text: str, rx: re.Pattern[str]) -> list[tuple[int, int]]:
    out, pos = [], 0
    for m in rx.finditer(text):
        out.append((pos, m.start()))
        pos = m.end()
    out.append((pos, len(text)))
    return out


def _span_at(spans: list[tuple[int, int]], pos: int) -> tuple[int, int]:
    for a, b in spans:
        if a <= pos < b:
            return a, b
    return spans[-1]


def _options(text: str, ix: _Bundle) -> list[tuple[str, bool]]:
    """Options named in ``text`` in order of appearance: (name, known to the bundle). An id-like
    token the bundle does not know (e.g. ``ad_z``) counts as an unknown option."""
    low = text.lower()
    found: dict[str, tuple[int, bool]] = {}
    for key, e in ix.vocab.items():
        m = _word_re(key).search(low)
        if m:
            found[e] = (m.start(), True)
    for m in _IDLIKE_RE.finditer(text):
        t = m.group(0)
        if t.lower() not in ix.vocab and not _RUN_RE.fullmatch(t) and t not in found:
            found[t] = (m.start(), False)
    return [(n, k) for n, (_, k) in sorted(found.items(), key=lambda kv: kv[1][0])]


def _scoped_hits(
    s: _Ctx, ix: _Bundle, entries: list[str], generic: list[str]
) -> list[tuple[int, int, str, list[tuple[str, bool]]]]:
    """Hits with an option in their clause (D31.1); generic phrases never count."""
    gen = _lex_hits(s.low, generic)
    spans = _spans(s.text, _HIT_CLAUSE_RE)
    out = []
    for start, end, entry in sorted(_lex_hits(s.low, entries)):
        if any(g0 <= start and end <= g1 for g0, g1, _ in gen):
            continue
        a, b = _span_at(spans, start)
        opts = _options(s.text[a:b], ix)
        if not opts and _PRONOUN_RE.search(s.text[a:b]):
            # "ad_b did not fail; it caused orders": a pronoun stands for the last option
            # named earlier in the sentence
            earlier = _options(s.text[:a], ix)
            opts = earlier[-1:]
        if opts:
            out.append((start, end, entry, opts))
    return out


def _compared_with(s: _Ctx, ix: _Bundle, before: int) -> list[str]:
    """Options in earlier clauses of the form "Compared with X," (D31.3)."""
    names = []
    for a, b in _spans(s.text, _HIT_CLAUSE_RE):
        if b <= before and _COMPARED_RE.match(s.text[a:b]):
            names += [n for n, known in _options(s.text[a:b], ix) if known]
    return names


def _check_comparatives(s: _Ctx, ix: _Bundle, phr: dict[str, Any]) -> list[str]:
    lex = phr["comparative_lexicon"]
    generic = lex.get("generic_phrases", [])
    sup_entries = set(lex["superlative"])
    hits = _scoped_hits(s, ix, [*lex["comparative"], *lex["superlative"]], generic)
    reasons: list[str] = []
    cost_metric = bool(s.metrics & _COST_METRICS)
    decision_checked = False
    for start, end, entry, opts in hits:
        word = s.text[start:end]
        unknown = [n for n, known in opts if not known]
        if unknown:
            reasons.append(
                f"{', '.join(unknown)}: {word!r} names an option with no comparison in the bundle"
            )
            continue
        clause_names = [n for n, _ in opts]
        subject = clause_names[0]  # D31.3: the clause's subject
        others_named = [
            n
            for n in dict.fromkeys(clause_names[1:] + _compared_with(s, ix, start))
            if n != subject
        ]
        names = [subject, *others_named]
        comps: list[Comparison] = [c for c in ix.b.comparisons if set(names) <= set(c.options)]
        if not comps:
            covered = set().union(*(set(c.options) for c in ix.b.comparisons))
            missing = [n for n in names if n not in covered] or names
            reasons.append(
                f"{', '.join(missing)}: {word!r} about {', '.join(names)} matches no comparison "
                "in the bundle"
            )
            continue
        comp = comps[0]
        polarity = _POLARITY.get(entry.lower())
        if polarity is not None and cost_metric and entry.lower() in _SIZE_WORDS:
            polarity = -polarity  # a lower cost per order is the stronger option
        if entry in sup_entries or not others_named:
            others = [o for o in comp.options if o != subject]
        else:
            others = others_named
        if polarity is not None:
            for o in others:
                a, b = comp.p_best.get(subject, 0.0), comp.p_best.get(o, 0.0)
                if (polarity > 0 and not a > b) or (polarity < 0 and not a < b):
                    reasons.append(
                        f"{subject}: {word!r} against {o} disagrees with the comparison "
                        f"(p_best {subject} {V.fmt_probability(a)}, {o} {V.fmt_probability(b)})"
                    )
        if not decision_checked:
            decision_checked = True
            recs = [r for r in ix.b.recommendations if r.economics_id == comp.economics_id]
            statuses = [r.decision_feasibility.status for r in recs]
            if not statuses or any(st not in _OK_DECISION for st in statuses):
                basis = ", ".join(statuses) or "none"
                reasons.append(
                    f"{', '.join(names)}: {word!r} needs a decision basis of marginal or "
                    f"estimable; the bundle's is {basis}"
                )
    return reasons


def _negated(s: _Ctx, pos: int, frames: list[str]) -> bool:
    """D31.2: a registry negation frame earlier in the claim's scope governs it."""
    a, _ = _span_at(_spans(s.text, _NEG_SCOPE_RE), pos)
    before = s.low[a:pos]
    return any(_lex_re(f).search(before) for f in frames)


def _check_causal(s: _Ctx, ix: _Bundle, phr: dict[str, Any]) -> list[str]:
    lex = phr["causal_lexicon"]
    frames = lex.get("negation_frames", [])
    reasons: list[str] = []
    for entries, allowed, need in (
        (lex["plain"], ("randomized", "holdout"), "a randomized design"),
        (lex["incremental"], ("holdout",), "a holdout design"),
    ):
        for start, end, _, opts in _scoped_hits(s, ix, entries, []):
            named = {n for n, known in opts if known}
            rel = [q for q in ix.b.quantities if V.entities_of(q) & named]
            if rel and len(named) == len(opts) and all(q.design in allowed for q in rel):
                continue
            if _negated(s, start, frames):
                continue
            designs = ", ".join(sorted({q.design for q in rel})) or "none in the bundle"
            tok = s.text[start:end]
            reasons.append(
                f"{tok}: causal wording needs {need}; the quantities it is about are {designs}"
            )
    return reasons


def _sentences(text: str) -> list[str]:
    return [p for p in _SENT_RE.split(text.strip()) if p and p.strip()]


def check_narrative(block: NarrativeBlock, bundle: ReportBundle) -> GateResult:
    """G5 (§10 C1, D29). Pure function of the block, the bundle and the registries."""
    phr = V.phrasing()
    ix = _index(bundle)
    reasons: list[str] = []
    for raw in _sentences(block.text):
        s = _ctx(raw, ix)
        reasons += _check_dates_and_runs(s, ix)
        reasons += _check_numbers(s, ix, phr)
        reasons += _check_not_knowable(s, ix, phr)
        reasons += _check_comparatives(s, ix, phr)
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
