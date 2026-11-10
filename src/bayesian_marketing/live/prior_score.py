"""Prior scoring (spec/Prior_Learning_Specification_v0.2.md §5 and §8). Piece L7.

Each prior in force for a client, and the framework alternatives, scored against the client's own
data from the live store: how likely each ad's counts were under the prior (BetaBinomial prior
predictive), whether the prior was surprised, how much weight it carries, and how far it pulls the
estimate. A score informs; it never changes a prior (§7).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from bayesian_marketing.core.records import ClientConfig
from bayesian_marketing.live.contracts import Clock, Store

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


def score_priors(config: ClientConfig, store: Store, clock: Clock, *, data_dir: Path) -> PriorScore:
    """Score the client's priors against every day in the store. Reads, never writes."""
    raise NotImplementedError("L7")


def write_score(score: PriorScore, data_dir: Path) -> Path:
    """``<data_dir>/prior_scores/<client_id>/<%Y%m%dT%H%M%SZ>[-N].json``; never overwrites."""
    raise NotImplementedError("L7")


def load_latest_score(client_id: str, data_dir: Path) -> PriorScore | None:
    """The lexicographically last score file for the client, or None."""
    raise NotImplementedError("L7")
