"""The canonical row form bayes-rows-c1 and the version numbering over a client's full history
(Brain join J1, J2; S28, S29). One implementation, used by the live refresh and by
``scripts/export_history.py``."""

from __future__ import annotations

from typing import Any

from bayesian_marketing.live.contracts import Store

ROWS_FORM = "bayes-rows-c1"
HASH_PREFIX = ROWS_FORM + ":"
MEASURES = (
    "impressions",
    "clicks",
    "spend_amount",
    "spend_currency",
    "conversions_reported",
    "conversions_observed",
    "revenue_amount",
    "revenue_currency",
    "attribution_window",
    "objective",
)
"""A version is cut when any of these changes for an ad and day (J1 point 6)."""

Versioned = tuple[list[dict[str, Any]], dict[str, list[str]], list[dict[str, Any]]]


def canonical(obj: Any) -> bytes:
    """J1 point 3: keys sorted at every level, separators "," and ":", UTF-8, no ASCII escaping."""
    raise NotImplementedError


def rows_sha256(rows: list[dict[str, Any]]) -> str:
    """J1 points 4 and 5: canonical row plus a line feed, rows in ``key`` order, lowercase hex
    SHA-256. An empty list hashes the empty string."""
    raise NotImplementedError


def versioned(store: Store, client_id: str) -> Versioned:
    """J1 point 7, S28, S29, S14: ``(rows, seen, reads)``.

    ``rows``: every version of every ad-day the client's ok polls hold, as export polls rows,
    in the order first seen. ``seen``: poll id to the sorted keys of the versions that poll read.
    ``reads``: one row per poll per ad-day, as the export's ``reads.jsonl`` rows (unsorted)."""
    raise NotImplementedError


def pointer(
    rows: list[dict[str, Any]], seen: dict[str, list[str]], poll_id: str
) -> tuple[list[str], str]:
    """The run pointer for a poll: ``(row_keys, rows_sha256)`` over the versions that poll read.
    A poll with no rows gives ``([], sha256(b""))``."""
    raise NotImplementedError
