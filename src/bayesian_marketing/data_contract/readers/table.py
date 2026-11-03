"""File-level parsing: encoding, preamble, header detection, summary rows, header mapping.

Every header spelling, preamble rule and ignored column comes from the platform's entry in
``registries/channels.yaml`` (§5.1 C3, D20).
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any

CURRENCY_SLOT = "{currency}"
DELIMITERS = (",", "\t", ";")
_EXCEL_TEXT = re.compile(r'^="(.*)"$', re.DOTALL)  # Google Ads id cells: ="123" (F1 G6)
SUMMARY_SEPARATORS = (":", " -", " \u2013")  # "Total: Account", "Total - ..." (F1 G5)


class TableError(ValueError):
    """The file cannot be read as a table (encoding, no header row, missing required column)."""


def _decode(data: bytes, codec: str) -> str:
    try:
        return data.decode(codec)
    except UnicodeDecodeError as e:
        raise TableError(f"file does not decode as {codec}: {e}") from e


def decode(data: bytes) -> str:
    """Bytes to text. UTF-16 by BOM (F1 G6) or by NUL pattern; UTF-8 (with or without BOM).

    Any decoding failure (truncated UTF-16, odd byte count, invalid UTF-8) is a TableError.
    """
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return _decode(data, "utf-16")
    if data.startswith(b"\xef\xbb\xbf"):
        return _decode(data, "utf-8-sig")
    if len(data) >= 4 and data[1:4:2] == b"\x00\x00" and data[0:4:2] != b"\x00\x00":
        return _decode(data, "utf-16-le")
    if len(data) >= 4 and data[0:4:2] == b"\x00\x00" and data[1:4:2] != b"\x00\x00":
        return _decode(data, "utf-16-be")
    return _decode(data, "utf-8")


def clean_cell(cell: str) -> str:
    """Trim, and unwrap an Excel text cell ``="123"`` to ``123``."""
    s = cell.strip()
    m = _EXCEL_TEXT.match(s)
    return m.group(1).strip() if m else s


def norm(s: str) -> str:
    return s.strip().lower()


def header_field(header: str, export_map: dict[str, str]) -> tuple[str, int, str | None] | None:
    """(target field, alias rank, currency from a ``{currency}`` slot) for one header, or None.

    Match is case-insensitive after trimming (D20). A ``{currency}`` slot matches any three
    letters and yields them upper-cased (validated later as ISO 4217).
    """
    h = norm(clean_cell(header))
    for rank, (known, target) in enumerate(export_map.items()):
        k = norm(known)
        if CURRENCY_SLOT in k:
            pattern = re.escape(k).replace(re.escape(CURRENCY_SLOT), "([a-z]{3})")
            m = re.fullmatch(pattern, h)
            if m:
                return target, rank, m.group(1).upper()
        elif h == k:
            return target, rank, None
    return None


def is_summary_row(first_cell: str, prefix: str) -> bool:
    """A summary row: first cell exactly ``prefix`` or ``prefix`` then ``:`` / `` -``.

    "Total Eclipse" is data; "Total", "Total: Account" and "Total - Campaign" are summaries.
    """
    c, p = norm(first_cell), norm(prefix)
    return c == p or any(c.startswith(p + sep) for sep in SUMMARY_SEPARATORS)


@dataclass
class Table:
    """A parsed export: header cells, data rows (raw cells), and column -> field mapping."""

    header: list[str]
    rows: list[list[str]]
    columns: dict[str, int] = field(default_factory=dict)  # target field -> chosen column
    candidates: dict[str, list[int]] = field(default_factory=dict)  # field -> all its columns
    header_currency: str | None = None
    unmapped: list[str] = field(default_factory=list)
    summary_rows: list[list[str]] = field(default_factory=list)  # dropped Total rows

    def find(self, header: str) -> int | None:
        """Column index of a header by case-insensitive, trimmed name."""
        want = norm(header)
        for i, h in enumerate(self.header):
            if norm(h) == want:
                return i
        return None

    def cell(self, cells: list[str], col: int | None) -> str | None:
        if col is None or col >= len(cells) or cells[col] == "":
            return None
        return cells[col]

    def raw(self, cells: list[str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for i, h in enumerate(self.header):
            out[h if h not in out else f"{h}#{i}"] = cells[i] if i < len(cells) else None
        for j in range(len(self.header), len(cells)):
            out[f"_extra_{j}"] = cells[j]
        return out


def _is_header(row: list[str], export_map: dict[str, str], detect: re.Pattern[str] | None) -> bool:
    cells = [clean_cell(c) for c in row]
    if detect is not None:
        return any(detect.fullmatch(c) for c in cells if c)
    return any(header_field(c, export_map) is not None for c in cells if c)


def parse(text: str, entry: dict[str, Any]) -> Table:
    """Parse export text into a Table using the platform registry entry.

    The csv module reads the decoded text directly, so quoted cells spanning lines stay whole.
    Rows whose first cell starts with the registry's ``comment_prefix`` are skipped.
    """
    export_map: dict[str, str] = entry["export_map"]
    preamble: dict[str, Any] = entry.get("preamble") or {}
    comment = preamble.get("comment_prefix")
    detect_src = preamble.get("detect_header_by")
    detect = re.compile(detect_src, re.IGNORECASE) if detect_src else None
    drop_prefix = preamble.get("drop_rows_starting_with")

    for delim in DELIMITERS:
        try:
            rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delim))
        except csv.Error as e:
            raise TableError(f"not a delimited table: {e}") from e
        if comment:
            rows = [r for r in rows if not (r and r[0].lstrip().startswith(comment))]
        for i, row in enumerate(rows):
            if len(row) > 1 and _is_header(row, export_map, detect):
                return _build(rows[i], rows[i + 1 :], export_map, drop_prefix)
    raise TableError("no header row matching the channel export map was found")


def _build(
    header: list[str],
    body: list[list[str]],
    export_map: dict[str, str],
    drop_prefix: str | None,
) -> Table:
    header = [clean_cell(h) for h in header]
    best: dict[str, tuple[int, int]] = {}  # field -> (alias rank, column)
    candidates: dict[str, list[int]] = {}
    currencies: set[str] = set()
    unmapped: list[str] = []
    for col, h in enumerate(header):
        hit = header_field(h, export_map)
        if hit is None:
            unmapped.append(h)
            continue
        target, rank, cur = hit
        candidates.setdefault(target, []).append(col)
        if cur is not None:
            currencies.add(cur)
        if target not in best or rank < best[target][0]:
            best[target] = (rank, col)
    if len(currencies) > 1:
        raise TableError(f"header names more than one currency: {sorted(currencies)}")
    rows: list[list[str]] = []
    summary: list[list[str]] = []
    for r in body:
        cells = [clean_cell(c) for c in r]
        if not any(cells):
            continue
        if drop_prefix and is_summary_row(cells[0], drop_prefix):
            summary.append(cells)
            continue
        rows.append(cells)
    return Table(
        header=header,
        rows=rows,
        columns={f: col for f, (_, col) in best.items()},
        candidates=candidates,
        header_currency=next(iter(currencies), None),
        unmapped=unmapped,
        summary_rows=summary,
    )
