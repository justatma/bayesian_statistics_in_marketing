# modules/reporting.py
"""
Self‑contained PDF builder for Bayesian ad‑performance studies.
Compatible with Python 3.11, ReportLab 4.x, Matplotlib 3.x, SciPy 1.x.
"""

from __future__ import annotations
import os, tempfile, math
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import beta as beta_dist, gamma as gamma_dist, lognorm
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer,
    Table, TableStyle, Image, PageBreak
)

# ---------------------------------------------------------------------
#                       ­‑‑­­ Low‑level helpers ­­­‑‑
# ---------------------------------------------------------------------

_STYLES = getSampleStyleSheet()


def _posterior_xy(dist_name: str, p1: float, p2: float) -> tuple[np.ndarray, np.ndarray]:
    """Return x,y arrays for a named two‑parameter distribution."""
    if dist_name == "beta":
        x = np.linspace(0, 1, 300)
        y = beta_dist.pdf(x, p1, p2)
    elif dist_name == "gamma":
        scale = p2
        x = np.linspace(0, gamma_dist.ppf(0.995, p1, scale=scale), 300)
        y = gamma_dist.pdf(x, p1, scale=scale)
    elif dist_name == "lognorm":
        s = p2
        x = np.linspace(0, lognorm.ppf(0.995, s, scale=math.e**p1), 300)
        y = lognorm.pdf(x, s, scale=math.e**p1)
    else:
        raise ValueError(f"Unknown dist: {dist_name}")
    return x, y


def _make_plot(
    dist_name: str, p1: float, p2: float,
    label: str, out_dir: Path
) -> Path:
    """Save a single posterior density plot and return its file path."""
    x, y = _posterior_xy(dist_name, p1, p2)
    plt.figure(figsize=(5, 2.5))
    plt.plot(x, y, lw=2)
    plt.title(label)
    plt.tight_layout()
    path = out_dir / f"{label.replace(' ', '_')}.png"
    plt.savefig(path, dpi=144)
    plt.close()
    return path


# ---------------------------------------------------------------------
#                        ­‑‑­­ Public interface ­­­‑‑
# ---------------------------------------------------------------------

def create_pdf_report(
    narrative: str,
    summary_tables: Mapping[str, pd.DataFrame],
    posteriors: Mapping[str, Mapping[str, tuple[str, float, float]]],
    diagnostics: Sequence[dict[str, str]] | None,
    output_path: str | os.PathLike
) -> None:
    """
    Parameters
    ----------
    narrative
        Plain‑text commentary you generated with GPT or by hand.
    summary_tables
        Dict keyed by metric name -> DataFrame (already aggregated).
    posteriors
        Dict::  metric -> { item_label : (dist_name, p1, p2) }
        e.g. { 'CTR': {'Ad A': ('beta', 25, 75), …}, 'CPA': … }
    diagnostics
        Optional sequence of {'title','img_path','explanation'}.
    output_path
        Where to write the PDF.
    """
    output_path = Path(output_path)    
    # This is the corrected line for reporting.py
    doc = SimpleDocTemplate(str(output_path), pagesize=letter)
    story = []

    # ---------- Title & narrative ----------
    story.append(Paragraph("Client Marketing Report", _STYLES["Title"]))
    story.append(Spacer(1, 12))
    for para in narrative.split("\n\n"):
        story.append(Paragraph(para, _STYLES["BodyText"]))
        story.append(Spacer(1, 12))

    # ---------- Summary tables + posterior sections ----------
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)

        for metric, df in summary_tables.items():
            # --- table ---
            story.append(Paragraph(metric, _STYLES["Heading2"]))
            tbl = Table([list(df.columns)] + df.values.tolist())
            tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.black),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]))
            story.append(tbl)
            story.append(Spacer(1, 18))

            # --- posteriors for this metric ---
            posterior_specs = posteriors.get(metric, {})
            if posterior_specs:
                for label, (dist_name, p1, p2) in posterior_specs.items():
                    img_path = _make_plot(dist_name, p1, p2, label, tmpdir)
                    story.append(Paragraph(f"{metric} Posterior – {label}", _STYLES["Heading3"]))
                    story.append(Image(str(img_path), width=400, height=180))
                    story.append(Spacer(1, 12))
            story.append(PageBreak())

        # ---------- diagnostics appendix ----------
        if diagnostics:
            story.append(Paragraph("Appendix – Model Diagnostics", _STYLES["Heading1"]))
            story.append(Spacer(1, 12))
            for d in diagnostics:
                story.append(Paragraph(d["title"], _STYLES["Heading2"]))
                story.append(Image(d["img_path"], width=400, height=180))
                if d.get("explanation"):
                    story.append(Paragraph(d["explanation"], _STYLES["BodyText"]))
                story.append(Spacer(1, 18))

        # build while images still live in tmpdir
        doc.build(story)
