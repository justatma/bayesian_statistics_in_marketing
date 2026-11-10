"""Prior scoring (spec/Prior_Learning_Specification_v0.2.md §5 and §8). Piece L7.

Each prior in force for a client, and the framework alternatives, scored against the client's own
data from the live store: how likely each ad's counts were under the prior (BetaBinomial prior
predictive), whether the prior was surprised, how much weight it carries, and how far it pulls the
estimate. A score informs; it never changes a prior (§7).
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from scipy import stats

from bayesian_marketing.core import PriorRecord, registries
from bayesian_marketing.core.records import ClientConfig
from bayesian_marketing.data_contract.connectors import meta
from bayesian_marketing.live.contracts import Clock, LiveRow, Store
from bayesian_marketing.live.refresh import data_dir_env
from bayesian_marketing.prior_registry import registry as prior_registry

PATHS = ("ctr", "cvr")
ROLES = ("in_force", "framework_lead", "framework_purchase")
FRAMEWORK_CLIENT = "__framework__"
SCORES_DIR = "prior_scores"

# Skip reasons (R5, R6, R12)
NO_TRIALS = "no trials"
NO_CONVERSION_ROWS = "no rows with conversions"
CLICKS_ABOVE_IMPRESSIONS = "clicks above impressions"
CONVERSIONS_ABOVE_CLICKS = "reported conversions above clicks (D34)"
NO_ADS_WITH_DATA = "no ads with data"
NEGATIVE_COUNTS = "negative counts"  # B21 F1


@dataclass(frozen=True)
class AdScore:
    ad_id: str
    ad_name: str | None
    n: int
    k: int
    raw_rate: float
    prior_q05: float
    prior_q50: float
    prior_q95: float
    tail: float
    surprised: bool
    log_score: float
    prior_weight: float
    posterior_mean: float
    shrinkage: float


@dataclass(frozen=True)
class CandidateScore:
    role: str  # one of ROLES
    prior_id: str
    family: str
    params: dict[str, float]
    resolution: str  # the record's resolution path, joined with " > ", verbatim
    ads: list[AdScore]
    skipped: dict[str, str]  # ad id -> reason
    log_score: float
    n_ads: int
    n_surprised: int
    log_bf_vs_in_force: float


@dataclass(frozen=True)
class PriorScore:
    client_id: str
    scored_at: datetime
    conversion_kind: str
    days: tuple[date, date] | None
    paths: dict[str, list[CandidateScore]]
    not_scored: dict[str, str]


_FILE = re.compile(r"^(\d{8}T\d{6}Z)(?:-(\d+))?\.json$")
_ALL_POLLS = 10**6  # R4


def score_priors(config: ClientConfig, store: Store, clock: Clock, *, data_dir: Path) -> PriorScore:
    """Score the client's priors against every day in the store. Reads, never writes."""
    now = clock.now()
    kind = "lead" if meta.is_lead_event(config.conversion_event.get("meta")) else "purchase"
    merged = _merged_rows(store, config.client_id)
    thr = float(registries.load("bounds")["prior_scoring"]["surprise_tail"])  # R17

    paths: dict[str, list[CandidateScore]] = {}
    not_scored: dict[str, str] = {}
    used_days: set[date] = set()
    with data_dir_env(data_dir):  # R10
        records = {path: _candidates(path, config.client_id, now, kind) for path in PATHS}
    for path in PATHS:
        counts, skipped, days = _counts(path, merged)
        if not counts:
            not_scored[path] = NO_ADS_WITH_DATA  # R12
            continue
        used_days |= days
        cands: list[CandidateScore] = []
        base: float | None = None
        for role, rec in records[path]:
            if rec.family != "beta":
                not_scored[f"{path}:{rec.prior_id}"] = f"family {rec.family}"  # §5, R12
                if role == "in_force":
                    break  # nothing to compare against: the path carries no candidates
                continue
            cand = _score(role, rec, counts, skipped, thr, base)
            if role == "in_force":
                base = cand.log_score
            cands.append(cand)
        if cands:
            paths[path] = cands
    return PriorScore(
        client_id=config.client_id,
        scored_at=now,
        conversion_kind=kind,
        days=(min(used_days), max(used_days)) if used_days else None,
        paths=paths,
        not_scored=not_scored,
    )


def _merged_rows(store: Store, client_id: str) -> dict[tuple[str, date], LiveRow]:
    """R4: ok polls oldest first; a later poll's row replaces an earlier one per (ad, date)."""
    polls = [p for p in store.polls(client_id, limit=_ALL_POLLS) if p.status == "ok"]
    polls.sort(key=lambda p: (p.started_at, p.poll_id))
    merged: dict[tuple[str, date], LiveRow] = {}
    for p in polls:
        for r in store.rows(p.poll_id):
            ad = r.entity_ids.get("ad")
            if ad:
                merged[(ad, r.date)] = r
    return merged


@dataclass(frozen=True)
class _Count:
    name: str | None
    n: int
    k: int


def _counts(
    path: str, merged: dict[tuple[str, date], LiveRow]
) -> tuple[dict[str, _Count], dict[str, str], set[date]]:
    """Per ad (n, k) for the path, the skip reasons (R5, R6), and the dates the scored ads used."""
    by_ad: dict[str, list[LiveRow]] = {}
    for (ad, _day), r in sorted(merged.items()):
        by_ad.setdefault(ad, []).append(r)
    counts: dict[str, _Count] = {}
    skipped: dict[str, str] = {}
    days: set[date] = set()
    for ad, rows in by_ad.items():
        name = None
        for r in rows:  # date order: the latest name wins
            name = r.entity_names.get("ad") or name
        if path == "ctr":
            used = rows
            n = sum(r.impressions for r in used)
            k = sum(r.clicks for r in used)
            over = CLICKS_ABOVE_IMPRESSIONS
        else:
            used = [r for r in rows if _conversions(r) is not None]
            if not used:
                skipped[ad] = NO_CONVERSION_ROWS  # R5
                continue
            n = sum(r.clicks for r in used)
            k = math.floor(sum(_conversions(r) or 0.0 for r in used) + 0.5)  # R5: half-up once
            over = CONVERSIONS_ABOVE_CLICKS
        if n < 0 or k < 0:
            skipped[ad] = NEGATIVE_COUNTS  # B21 F1: no -inf or NaN reaches a score
        elif n == 0:
            skipped[ad] = NO_TRIALS  # R6
        elif k > n:
            skipped[ad] = over  # R6
        else:
            counts[ad] = _Count(name=name, n=n, k=k)
            days.update(r.date for r in used)
    return counts, skipped, days


def _conversions(r: LiveRow) -> float | None:
    """R5: observed when not None, else reported."""
    if r.conversions_observed is not None:
        return float(r.conversions_observed)
    if r.conversions_reported is not None:
        return float(r.conversions_reported)
    return None


def _candidates(
    path: str, client_id: str, now: datetime, kind: str
) -> list[tuple[str, PriorRecord]]:
    """R9: in_force, framework_lead (cvr only, B18), framework_purchase; first role wins an id."""
    wanted: list[tuple[str, str, str]] = [("in_force", client_id, kind)]
    if path == "cvr":
        wanted.append(("framework_lead", FRAMEWORK_CLIENT, "lead"))
    wanted.append(("framework_purchase", FRAMEWORK_CLIENT, "purchase"))
    out: list[tuple[str, PriorRecord]] = []
    seen: set[str] = set()
    for role, who, k in wanted:
        rec = prior_registry.resolve(path, who, now, conversion_kind=k)
        if rec.prior_id in seen:
            continue
        seen.add(rec.prior_id)
        out.append((role, rec))
    return out


def _score(
    role: str,
    rec: PriorRecord,
    counts: dict[str, _Count],
    skipped: dict[str, str],
    thr: float,
    base: float | None,
) -> CandidateScore:
    params = {k: float(v) for k, v in rec.params.items()}
    a, b = params["a"], params["b"]
    prior = stats.beta(a, b)
    q05, q50, q95 = (float(prior.ppf(q)) for q in (0.05, 0.50, 0.95))
    ads: list[AdScore] = []
    for ad_id, c in counts.items():
        bb = stats.betabinom(c.n, a, b)
        tail = (float(bb.cdf(c.k - 1)) if c.k > 0 else 0.0) + 0.5 * float(bb.pmf(c.k))  # R7
        post = (a + c.k) / (a + b + c.n)
        raw = c.k / c.n
        ads.append(
            AdScore(
                ad_id=ad_id,
                ad_name=c.name,
                n=c.n,
                k=c.k,
                raw_rate=raw,
                prior_q05=q05,
                prior_q50=q50,
                prior_q95=q95,
                tail=tail,
                surprised=tail < thr or tail > 1 - thr,  # R17
                log_score=float(bb.logpmf(c.k)),
                prior_weight=(a + b) / (a + b + c.n),
                posterior_mean=post,
                shrinkage=post - raw,
            )
        )
    total = sum(x.log_score for x in ads)
    return CandidateScore(
        role=role,
        prior_id=rec.prior_id,
        family=rec.family,
        params=params,
        resolution=" > ".join(rec.resolution_path),
        ads=ads,
        skipped=dict(skipped),
        log_score=total,
        n_ads=len(ads),
        n_surprised=sum(x.surprised for x in ads),
        log_bf_vs_in_force=0.0 if base is None else total - base,  # §5, R8
    )


# ------------------------------------------------------------------ files (R11)


def _folder(client_id: str, data_dir: Path) -> Path:
    return data_dir / SCORES_DIR / client_id


def _json_default(v: Any) -> str:
    if isinstance(v, date | datetime):
        return v.isoformat()
    raise TypeError(f"not JSON serialisable: {type(v).__name__}")


def write_score(score: PriorScore, data_dir: Path) -> Path:
    """``<data_dir>/prior_scores/<client_id>/<%Y%m%dT%H%M%SZ>[-N].json``; never overwrites."""
    folder = _folder(score.client_id, data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = score.scored_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    text = json.dumps(asdict(score), default=_json_default, indent=2, sort_keys=True) + "\n"
    n = 1
    while True:
        path = folder / (f"{stamp}.json" if n == 1 else f"{stamp}-{n}.json")
        try:
            with path.open("x", encoding="utf-8") as f:
                f.write(text)
        except FileExistsError:
            n += 1
            continue
        return path


def load_latest_score(client_id: str, data_dir: Path) -> PriorScore | None:
    """The score file with the greatest (timestamp, N), no suffix counting as 1 (B18), or None."""
    folder = _folder(client_id, data_dir)
    if not folder.is_dir():
        return None
    best: tuple[tuple[str, int], Path] | None = None
    for p in folder.iterdir():
        m = _FILE.match(p.name)
        if m is None or not p.is_file():
            continue
        key = (m.group(1), int(m.group(2) or 1))
        if best is None or key > best[0]:
            best = (key, p)
    if best is None:
        return None
    return _from_dict(json.loads(best[1].read_text(encoding="utf-8")))


def _from_dict(d: dict[str, Any]) -> PriorScore:
    days = d["days"]
    return PriorScore(
        client_id=d["client_id"],
        scored_at=datetime.fromisoformat(d["scored_at"]),
        conversion_kind=d["conversion_kind"],
        days=None if days is None else (date.fromisoformat(days[0]), date.fromisoformat(days[1])),
        paths={
            path: [CandidateScore(**{**c, "ads": [AdScore(**a) for a in c["ads"]]}) for c in cands]
            for path, cands in d["paths"].items()
        },
        not_scored=dict(d["not_scored"]),
    )
