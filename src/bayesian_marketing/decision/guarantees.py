"""§8.5 guarantee rendering from templates only (I8). Piece P4."""

from __future__ import annotations

from bayesian_marketing.core import Guarantee


def render_guarantee(g: Guarantee, locale: str = "en") -> str:
    raise NotImplementedError("P4")
