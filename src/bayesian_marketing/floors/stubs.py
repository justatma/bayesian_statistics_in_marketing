"""Out of scope (D13)."""

from __future__ import annotations

from bayesian_marketing.core import NotInScope


def detectability(*args: object, **kwargs: object) -> None:
    raise NotInScope("floors/detectability is out of scope (D13)")


def path_barriers(*args: object, **kwargs: object) -> None:
    raise NotInScope("floors/path_barriers is out of scope (D13)")
