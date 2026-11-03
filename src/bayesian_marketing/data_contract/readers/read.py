"""§5.1 read_export."""

from __future__ import annotations

import hashlib
import itertools
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from bayesian_marketing.channels.model import channel_entry, channel_model, channel_ref
from bayesian_marketing.core import (
    ChannelModel,
    DatasetManifest,
    GateFailure,
    GateResult,
    OrderRow,
    PerformanceRow,
    Platform,
    PlatformPull,
    QuarantinedRow,
    SiteRow,
    inputs_hash,
    load_economics,
    utcnow,
)
from bayesian_marketing.data_contract.readers.currencies import NO_CURRENCY
from bayesian_marketing.data_contract.readers.rows import (
    Context,
    order_row,
    performance_fields,
    site_row,
)
from bayesian_marketing.data_contract.readers.table import Table, TableError, decode, parse

PERFORMANCE_PLATFORMS = ("meta", "google_ads", "linkedin")
REQUIRED: dict[str, tuple[str, ...]] = {
    "performance": ("date", "entity_ids.ad", "impressions", "clicks", "spend"),
    "orders": ("order_id", "ordered_at", "value", "refunded"),
    "ga4": ("date", "sessions", "purchases", "revenue"),
}


def _kind(platform: Platform) -> str:
    return "performance" if platform in PERFORMANCE_PLATFORMS else platform


def _g1_fail(platform: Platform, reasons: list[str], payload: dict[str, Any]) -> GateFailure:
    return GateFailure(
        GateResult(
            gate="G1",
            passed=False,
            blocking=True,
            reasons=[f"{platform}: {r}" for r in reasons],
            inputs_hash=inputs_hash(payload),
            checked_at=utcnow(),
        )
    )


def _fallback_currency(platform: Platform, manifest: DatasetManifest, path: Path) -> str | None:
    """Currency for an export that carries none (D22 item 13): manifest, then economics.

    GA4 alone falls back further to ISO 4217 ``XXX`` (no currency) rather than inventing one;
    a spend or order row with no currency is quarantined instead.
    """
    if manifest.currency:
        return manifest.currency
    try:
        return load_economics(manifest.economics_id, path.parent).currency
    except (FileNotFoundError, ValueError):
        pass
    return NO_CURRENCY if platform == "ga4" else None


def _performance_rows(
    table: Table, ctx: Context, cm: ChannelModel
) -> tuple[list[PerformanceRow], list[QuarantinedRow]]:
    fields: list[dict[str, Any]] = []
    quarantined: list[QuarantinedRow] = []
    for cells in table.rows:
        f, reasons = performance_fields(ctx, cells)
        if f is None:
            quarantined.append(QuarantinedRow(raw=table.raw(cells), reasons=reasons))
        else:
            fields.append(f)
    # C8: copy to observed only when the field is never modeled and every value is an integer.
    copy = (
        not cm.conversion_field_may_be_modeled
        and bool(fields)
        and all(f["conversions_integral"] for f in fields)
    )
    rows = []
    for f in fields:
        integral = f.pop("conversions_integral")
        observed = int(f["conversions_reported"]) if copy and integral else None
        rows.append(PerformanceRow(**f, conversions_observed=observed))
    return rows, quarantined


def _order_rows(table: Table, ctx: Context) -> tuple[list[OrderRow], list[QuarantinedRow]]:
    parsed: list[tuple[list[str], OrderRow]] = []
    quarantined: list[QuarantinedRow] = []
    for cells in table.rows:
        row, reasons = order_row(ctx, cells)
        if row is None:
            quarantined.append(QuarantinedRow(raw=table.raw(cells), reasons=reasons))
        else:
            parsed.append((cells, row))
    # C1: a duplicate order_id. Identical repeats keep the first; conflicting ones keep none.
    by_id: dict[str, list[tuple[list[str], OrderRow]]] = defaultdict(list)
    for cells, row in parsed:
        by_id[row.order_id].append((cells, row))
    rows: list[OrderRow] = []
    for cells, row in parsed:
        group = by_id[row.order_id]
        if len(group) == 1:
            rows.append(row)
            continue
        identical = all(r == group[0][1] for _, r in group)
        first = group[0][0] is cells
        if identical and first:
            rows.append(row)
            continue
        why = "identical repeat" if identical else "conflicting values"
        quarantined.append(
            QuarantinedRow(
                raw=table.raw(cells),
                reasons=[f"duplicate order_id {row.order_id!r} ({why}, {len(group)} rows)"],
            )
        )
    return rows, quarantined


def _site_rows(table: Table, ctx: Context) -> tuple[list[SiteRow], list[QuarantinedRow]]:
    rows: list[SiteRow] = []
    quarantined: list[QuarantinedRow] = []
    for cells in table.rows:
        row, reasons = site_row(ctx, cells)
        if row is None:
            quarantined.append(QuarantinedRow(raw=table.raw(cells), reasons=reasons))
        else:
            rows.append(row)
    return rows, quarantined


def _measurement_changes(platform: Platform, rows: list[PerformanceRow]) -> list[str]:
    """C5: an attribution-window change inside the window, per entity, reported once per
    (from, to, first day). Rows keep their own window, so the series is split by it."""
    by_entity: dict[str, list[PerformanceRow]] = defaultdict(list)
    for r in rows:
        by_entity[r.entity_ids["ad"]].append(r)
    changes: dict[tuple[str, str, date], set[str]] = defaultdict(set)
    for ad, series in by_entity.items():
        series.sort(key=lambda r: r.date)
        for prev, cur in itertools.pairwise(series):
            if cur.attribution_window != prev.attribution_window:
                changes[(prev.attribution_window, cur.attribution_window, cur.date)].add(ad)
    return [
        f"{platform}: attribution window changed from {old} to {new} on {day.isoformat()} "
        f"for ads {', '.join(sorted(ads))}"
        for (old, new, day), ads in sorted(changes.items(), key=lambda kv: (kv[0][2], kv[0]))
    ]


def _window(rows: list[Any]) -> tuple[date, date] | None:
    days = [r.ordered_at.date() if isinstance(r, OrderRow) else r.date for r in rows]
    return (min(days), max(days)) if days else None


def read_export(platform: Platform, path: Path, manifest: DatasetManifest) -> PlatformPull:
    """Read one export file into a PlatformPull (§5.1 C1 to C5, C7, C8; G1).

    G1: a stale channel model, a file not listed in the manifest, or a file that cannot be read
    as a table raises ``GateFailure``. Bad rows are quarantined with reasons.
    """
    path = Path(path)
    cm = channel_model(platform, utcnow().date())  # stale -> GateFailure G1, this platform only
    entry = channel_entry(platform)
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    payload = {"platform": platform, "sha256": sha, "manifest_id": manifest.manifest_id}

    if not any(f.sha256 == sha and f.platform == platform for f in manifest.files):
        raise _g1_fail(
            platform, [f"{path.name} (sha256 {sha[:8]}) is not in the manifest"], payload
        )
    try:
        table = parse(decode(data), entry)
    except TableError as e:
        raise _g1_fail(platform, [f"{path.name}: {e}"], payload) from e
    kind = _kind(platform)
    missing = [t for t in REQUIRED[kind] if t not in table.columns]
    if missing:
        raise _g1_fail(platform, [f"{path.name}: no column for {', '.join(missing)}"], payload)

    ctx = Context(
        table=table,
        fallback_currency=_fallback_currency(platform, manifest, path),
        attribution_window=manifest.attribution_window.get(platform)
        or cm.default_attribution_window,
    )
    changes: list[str] = []
    rows: list[Any]
    if kind == "performance":
        rows, quarantined = _performance_rows(table, ctx, cm)
        changes = _measurement_changes(platform, rows)
        # C8: partial truth when some row lacks an observed count and no modeled share is known.
        partial = any(r.conversions_observed is None for r in rows) and all(
            r.conversions_modeled_share is None for r in rows
        )
        accounts = Counter(r.entity_ids.get("account") for r in rows)
        account_id = next(iter(accounts)) if len(accounts) == 1 else None
    elif kind == "orders":
        rows, quarantined = _order_rows(table, ctx)
        partial, account_id = False, None
    else:
        rows, quarantined = _site_rows(table, ctx)
        partial, account_id = False, None

    return PlatformPull(
        pull_id=f"pull_{platform}_{inputs_hash(payload)[:8]}",
        platform=platform,
        channel_ref=channel_ref(platform),
        account_id=account_id,
        window=_window(rows),
        rows=rows,
        quarantined=quarantined,
        partial_truth=partial,
        measurement_changes=changes,
        timezone=None,
        pulled_at=utcnow(),
        synthetic=manifest.synthetic,
    )
