"""J4: the figure check a persona runs on a sentence before she says it to the client
(spec/Brain_Join_Specification_v0.3.md, J4, with S5 to S10 and P1 to P5).

Pure apart from the two loaders, which are parameters so the same check can later run against the
Brain's stored copies (P4). Fails closed: a figure no ref places, or places ambiguously, fails with
a reason and never passes silently. Reports only; repairing a sentence is the caller's.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, TypedDict

# --- the call's shapes (J4 "Return"); every value JSON-native -------------------------------

RefKind = Literal["run", "notebook_entry", "claim"]


class RunRef(TypedDict):
    kind: Literal["run"]
    run_id: str


class EntryRef(TypedDict):
    kind: Literal["notebook_entry"]
    release_id: str
    entry_id: str


class ClaimRef(TypedDict):
    kind: Literal["claim"]
    claim_id: str
    engine_item: dict[str, str]  # {"release_id", "entry_id"} or {"run_id", "quantity_id"}


class QuantityOut(TypedDict):
    name: str
    subject: str
    status: str | None  # "estimable" | "marginal" | "below_floor" | None for an observed figure


class FigureOut(TypedDict):
    text: str
    placed: bool
    ref: dict[str, Any] | None
    quantity: QuantityOut | None
    value_at_rounding: str | None
    should_read: str | None
    caveat_required: bool
    caveat_present: bool
    reasons: list[str]


class RefOut(TypedDict):
    ref: dict[str, Any]
    newest: bool
    window_end: str | None  # a run's window end; None for a notebook ref
    saved_at: str | None  # a run's saved time or a release's created_at


class Result(TypedDict):
    passed: bool
    figures: list[FigureOut]
    refs: list[RefOut]
    reasons: list[str]
    engine_version: str
    inputs_hash: str
    checked_at: str


#: A loader returns a run snapshot (``pipeline.RunSnapshot``) by run id.
LoadRun = Callable[[str], Any]
#: A loader returns ``(catalog, entries, sources)`` of a verified release by release id, or raises.
LoadRelease = Callable[[str], tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]]
#: A loader returns id -> name for a client's ads, ad sets and campaigns (S16).
LoadNames = Callable[[str], dict[str, str]]

# --- the fixed reason texts (J4 points 1 to 7; the acceptance set may assert them) ------------

R_UNREADABLE_FORM = "figure in a form the checker cannot read"
R_WORDS = "a quantity in words the checker cannot place; state the figure"
R_NOT_FOUND = (
    "not found in the refs given; if it is derived (a difference, a total, a change), ask the "
    "engine for that quantity rather than rewording"
)
R_AMBIGUOUS = "fits more than one figure in the refs; name the ad or the measure"
R_LONE_BOUND = "a bound of the estimate spoken as its value"
R_NOT_KNOWABLE = "not knowable yet"
R_CAVEAT = "a rough estimate quoted without saying so"
R_STALE = "the ref is not the newest; date the figure or use the newest"
R_PURCHASE_WORD = "this account converts on sign-ups, not orders"
R_TWO_CLIENTS = "the refs name more than one client"
R_NEEDS_RUN = "a comparison needs a run ref"


def check_client_figures(
    text: str,
    refs: list[dict[str, Any]],
    *,
    load_run: LoadRun | None = None,
    load_release: LoadRelease | None = None,
    load_names: LoadNames | None = None,
) -> Result:
    """J4. ``load_run`` defaults to ``pipeline.load_snapshot``; ``load_release`` to reading
    ``notebook.root()/<client>/releases/<release_id>`` after ``notebook.verify``; ``load_names``
    to the live store, read only, newest name per id (S16). A ref that cannot be read fails the
    call with a reason naming it; only a wrong argument type raises."""
    raise NotImplementedError
