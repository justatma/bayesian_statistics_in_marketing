"""Variational inference: out of scope (D13)."""

from __future__ import annotations

from bayesian_marketing.core import NotInScope


def fit_vi(*args: object, **kwargs: object) -> None:
    raise NotInScope("VI is out of scope for this build (D13)")
