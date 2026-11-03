"""Out of scope (D13)."""

from __future__ import annotations

from bayesian_marketing.core import NotInScope


def long_run(*args: object, **kwargs: object) -> None:
    raise NotInScope("decision/long_run is out of scope (D13)")
