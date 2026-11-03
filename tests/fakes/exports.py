"""Export-file helpers built from the channel export maps in ``registries/channels.yaml`` (D20).

The canonical header for a field is the FIRST header listed for it in that platform's map.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from bayesian_marketing.core import registries

CURRENCY_SLOT = "{currency}"


def channel_entry(platform: str) -> dict[str, Any]:
    return registries.load("channels")["channels"][platform]


def canonical_headers(platform: str) -> dict[str, str]:
    """field -> first-listed header."""
    out: dict[str, str] = {}
    for header, field in channel_entry(platform)["export_map"].items():
        out.setdefault(field, header)
    return out


def header_matches(header: str, known: str) -> bool:
    """Case-insensitive, trimmed match; ``{currency}`` matches any 3-letter code (D20)."""
    h, k = header.strip().lower(), known.strip().lower()
    if CURRENCY_SLOT in k:
        pattern = re.escape(k).replace(re.escape(CURRENCY_SLOT), "[a-z]{3}")
        return re.fullmatch(pattern, h) is not None
    return h == k


def field_of(platform: str, header: str) -> str | None:
    for known, field in channel_entry(platform)["export_map"].items():
        if header_matches(header, known):
            return field
    return None


def write_export(
    path: Path,
    platform: str,
    rows: list[dict[str, Any]],
    *,
    currency: str = "USD",
    headers: dict[str, str] | None = None,
    preamble: list[str] | None = None,
) -> Path:
    """Write rows keyed by target field, using canonical headers unless ``headers`` overrides."""
    canon = {**canonical_headers(platform), **(headers or {})}
    fields = list(rows[0]) if rows else list(canon)
    cols = [canon[f].replace(CURRENCY_SLOT, currency) for f in fields]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        for line in preamble or []:
            fh.write(line + "\n")
        w = csv.writer(fh)
        w.writerow(cols)
        for r in rows:
            w.writerow(["" if r.get(f) is None else r[f] for f in fields])
    return path


def read_table(path: Path, platform: str) -> list[dict[str, str]]:
    """Rows of an export keyed by target field (skips '#' lines and a preamble before the header;
    drops 'Total' rows). Independent of P1, for checking simulator output."""
    lines = [ln for ln in path.read_text().splitlines() if not ln.startswith("#")]
    reader = list(csv.reader(lines))
    for i, row in enumerate(reader):
        if sum(field_of(platform, c) is not None for c in row) >= 3:
            header, body = row, reader[i + 1 :]
            break
    else:
        raise AssertionError(f"no header row found in {path}")
    out = []
    for r in body:
        if not r or r[0].strip().lower().startswith("total"):
            continue
        out.append({field_of(platform, h) or h: v for h, v in zip(header, r, strict=False)})
    return out


def header_row(path: Path, platform: str) -> list[str]:
    lines = [ln for ln in path.read_text().splitlines() if not ln.startswith("#")]
    for row in csv.reader(lines):
        if sum(field_of(platform, c) is not None for c in row) >= 3:
            return row
    raise AssertionError(f"no header row found in {path}")
