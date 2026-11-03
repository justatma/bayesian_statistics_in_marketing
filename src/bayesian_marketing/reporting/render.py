"""§12 render."""

from __future__ import annotations

from pathlib import Path

from bayesian_marketing.core import RenderedReport, ReportBundle


def render(bundle: ReportBundle, out_dir: Path) -> RenderedReport:
    raise NotImplementedError("P10")
