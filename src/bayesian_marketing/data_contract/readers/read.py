"""§5.1 read_export."""

from __future__ import annotations

import hashlib
import itertools
from collections import Counter, defaultdict
from collections.abc import Callable, Hashable
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
    OBJECTIVE,
    Context,
    order_row,
    performance_fields,
    site_row,
)
from bayesian_marketing.data_contract.readers.table import (
    Table,
    TableError,
    decode,
    norm,
    parse,
)

PERFORMANCE_PLATFORMS = ("meta", "google_ads", "linkedin")
REQUIRED: dict[str, tuple[str, ...]] = {
    "performance": ("date", "entity_ids.ad", "impressions", "clicks", "spend"),
    "orders": ("order_id", "ordered_at", "value", "refunded"),
    "ga4": ("date", "sessions", "purchases", "revenue"),
}
# Header rules the registry states only in comments (channels.yaml meta block). They are code
# here until the registry carries them as fields (manifest open question).
OBJECTIVE_RULES: dict[str, dict[str, str]] = {
    "meta": {"dependent": "Results", "preferred": "Purchases", "indicator": "Result indicator"}
}
PERIOD_COLUMNS: dict[str, tuple[str, str]] = {"meta": ("Reporting starts", "Reporting ends")}

Pair = tuple[list[str], Any]  # (raw cells, typed row)


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


def _quarantine(table: Table, cells: list[str], reasons: list[str]) -> QuarantinedRow:
    return QuarantinedRow(raw=table.raw(cells), reasons=reasons)


def _dedupe(
    table: Table, pairs: list[Pair], key: Callable[[Any], Hashable], label: Callable[[Any], str]
) -> tuple[list[Pair], list[QuarantinedRow]]:
    """C1 duplicates. Identical repeats keep the first; conflicting ones keep none."""
    groups: dict[Hashable, list[Pair]] = defaultdict(list)
    for p in pairs:
        groups[key(p[1])].append(p)
    kept: list[Pair] = []
    quarantined: list[QuarantinedRow] = []
    for cells, row in pairs:
        group = groups[key(row)]
        identical = all(r == group[0][1] for _, r in group)
        if len(group) == 1 or (identical and group[0][0] is cells):
            kept.append((cells, row))
            continue
        why = "identical repeat" if identical else "conflicting values"
        reason = f"duplicate {label(row)} ({why}, {len(group)} rows)"
        quarantined.append(_quarantine(table, cells, [reason]))
    return kept, quarantined


def _single_currency(
    platform: Platform, table: Table, pairs: list[Pair], currency_of: Callable[[Any], str]
) -> tuple[list[Pair], list[QuarantinedRow]]:
    """One currency per pull. Minority-currency rows are quarantined; a tie cannot be decided."""
    counts = Counter(currency_of(r) for _, r in pairs)
    if len(counts) <= 1:
        return pairs, []
    (top, n_top), (_, n_next) = counts.most_common(2)
    if n_top == n_next:
        raise TableError(f"rows split evenly across currencies {dict(sorted(counts.items()))}")
    kept = [(c, r) for c, r in pairs if currency_of(r) == top]
    quarantined = [
        _quarantine(table, c, [f"currency {currency_of(r)} differs from the pull's {top}"])
        for c, r in pairs
        if currency_of(r) != top
    ]
    return kept, quarantined


def _objective_checks(platform: Platform, table: Table) -> list[str]:
    """Meta ``Results`` is objective-dependent (channels.yaml). Flag what cannot pass silently."""
    rule = OBJECTIVE_RULES.get(platform)
    if rule is None:
        return []
    notes: list[str] = []
    dep, pref = table.find(rule["dependent"]), table.find(rule["preferred"])
    ind = table.find(rule["indicator"])
    if dep is not None and pref is not None:
        ignored = sum(table.cell(c, dep) is not None for c in table.rows)
        if ignored:
            notes.append(
                f"{platform}: conversions_reported taken from {rule['preferred']!r}; "
                f"objective-dependent {rule['dependent']!r} present and not used on {ignored} rows"
            )
    objectives: list[str] = []
    if dep is not None and ind is not None:
        objectives = sorted({v for c in table.rows if (v := table.cell(c, ind)) is not None})
        if len(objectives) > 1:
            notes.append(
                f"{platform}: mixed objectives in {rule['dependent']!r}: {', '.join(objectives)}"
            )
    if dep is not None and pref is None:
        objective = f" (objective {objectives[0]})" if len(objectives) == 1 else ""
        notes.append(
            f"{platform}: conversions_reported taken from objective-dependent "
            f"{rule['dependent']!r}{objective}"
        )
    return notes


def _period_reasons(
    platform: Platform, table: Table, notes: list[str]
) -> Callable[[list[str]], list[str]]:
    """Meta rows dated by ``Reporting starts`` must end the same day, else they are aggregates."""
    cols = PERIOD_COLUMNS.get(platform)
    date_col = table.columns.get("date")
    if cols is None or date_col is None or norm(table.header[date_col]) != norm(cols[0]):
        return lambda cells: []
    end_col = table.find(cols[1])
    if end_col is None:
        notes.append(f"{platform}: rows dated by {cols[0]!r} with no {cols[1]!r} column")
        return lambda cells: []

    def check(cells: list[str]) -> list[str]:
        start, end = table.cell(cells, date_col), table.cell(cells, end_col)
        if end is not None and end != start:
            return [f"non-daily aggregate: {cols[0]} {start} to {cols[1]} {end}"]
        return []

    return check


def _objective_column(platform: Platform, table: Table) -> None:
    """Map the first ``objective_columns`` header present (channels.yaml, D34) to the objective
    target. A connector table already carries the target by name."""
    if OBJECTIVE in table.columns:
        return
    for header in channel_entry(platform).get("objective_columns") or []:
        col = table.find(header)
        if col is not None:
            table.columns[OBJECTIVE] = col
            return


def _performance(
    platform: Platform, table: Table, ctx: Context, cm: ChannelModel, notes: list[str]
) -> tuple[list[PerformanceRow], list[QuarantinedRow]]:
    """Rows of a performance table. Reported conversions above clicks under a view-through window
    are kept with a pull note; observed conversions above clicks are quarantined (D34)."""
    _objective_column(platform, table)
    period = _period_reasons(platform, table, notes)
    good: list[tuple[list[str], dict[str, Any]]] = []
    quarantined: list[QuarantinedRow] = []
    for cells in table.rows:
        f, reasons = performance_fields(ctx, cells)
        reasons = reasons + period(cells)
        if reasons:
            quarantined.append(_quarantine(table, cells, reasons))
        else:
            assert f is not None
            good.append((cells, f))
    # C8: copy to observed only when the field is never modeled and every value is an integer.
    copy = (
        not cm.conversion_field_may_be_modeled
        and bool(good)
        and all(f["conversions_integral"] for _, f in good)
    )
    pairs: list[Pair] = []
    above = 0
    for cells, f in good:
        f.pop("conversions_integral")
        over = f.pop("reported_above_clicks")
        observed = int(f["conversions_reported"]) if copy else None
        if observed is not None and observed > f["clicks"]:
            reason = f"observed conversions above clicks ({observed} > {f['clicks']})"
            quarantined.append(_quarantine(table, cells, [reason]))
            continue
        above += over
        pairs.append((cells, PerformanceRow(**f, conversions_observed=observed)))
    if above:
        notes.append(
            f"{platform}: reported conversions above clicks on {above} rows; kept (view-through, "
            f"multi-event counting or reporting dates) and left out of the click-trial model"
        )
    pairs, dup = _dedupe(
        table,
        pairs,
        key=lambda r: (tuple(sorted(r.entity_ids.items())), r.date),
        label=lambda r: f"ad {r.entity_ids['ad']!r} on {r.date.isoformat()}",
    )
    pairs, mixed = _single_currency(platform, table, pairs, lambda r: r.spend.currency)
    return [r for _, r in pairs], quarantined + dup + mixed


def _orders(table: Table, ctx: Context) -> tuple[list[OrderRow], list[QuarantinedRow]]:
    pairs: list[Pair] = []
    quarantined: list[QuarantinedRow] = []
    for cells in table.rows:
        row, reasons = order_row(ctx, cells)
        if row is None:
            quarantined.append(_quarantine(table, cells, reasons))
        else:
            pairs.append((cells, row))
    pairs, dup = _dedupe(
        table, pairs, key=lambda r: r.order_id, label=lambda r: f"order_id {r.order_id!r}"
    )
    pairs, mixed = _single_currency("orders", table, pairs, lambda r: r.value.currency)
    return [r for _, r in pairs], quarantined + dup + mixed


def _site(table: Table, ctx: Context) -> tuple[list[SiteRow], list[QuarantinedRow]]:
    pairs: list[Pair] = []
    quarantined: list[QuarantinedRow] = []
    for cells in table.rows:
        row, reasons = site_row(ctx, cells)
        if row is None:
            quarantined.append(_quarantine(table, cells, reasons))
        else:
            pairs.append((cells, row))
    pairs, mixed = _single_currency("ga4", table, pairs, lambda r: r.revenue.currency)
    return [r for _, r in pairs], quarantined + mixed


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
    """Row dates; for orders, the UTC calendar date of ``ordered_at``."""
    days = [r.ordered_at.date() if isinstance(r, OrderRow) else r.date for r in rows]
    return (min(days), max(days)) if days else None


def _timezone(kind: str, table: Table | None) -> str | None:
    """Zone the row dates are in, where the file states it: orders are normalized to UTC (C2);
    a date header naming UTC (LinkedIn "Start Date (in UTC)") is UTC. Otherwise unknown."""
    if kind == "orders":
        return "UTC"
    col = None if table is None else table.columns.get("date")
    if table is None or col is None:
        return None
    words = norm(table.header[col]).replace("(", " ").replace(")", " ").split()
    return "UTC" if "utc" in words else None


def read_export(
    platform: Platform, path: Path, manifest: DatasetManifest, *, as_of: date | None = None
) -> PlatformPull:
    """Read one export file into a PlatformPull (§5.1 C1 to C8; G1).

    G1: a stale channel model (judged at ``as_of``, default today UTC), a file not listed in the
    manifest, or a file that cannot be read as a table raises ``GateFailure``. Bad rows are
    quarantined with reasons. A 0-byte file, or a header with no data rows, is an empty pull
    flagged ``empty_account`` (C6).
    """
    path = Path(path)
    cm = channel_model(platform, as_of or utcnow().date())  # stale -> G1, this platform only
    entry = channel_entry(platform)
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    payload = {"platform": platform, "sha256": sha, "manifest_id": manifest.manifest_id}
    kind = _kind(platform)

    if not any(f.sha256 == sha and f.platform == platform for f in manifest.files):
        raise _g1_fail(
            platform, [f"{path.name} (sha256 {sha[:8]}) is not in the manifest"], payload
        )

    rows: list[Any] = []
    quarantined: list[QuarantinedRow] = []
    changes: list[str] = []  # C5 only
    notes: list[str] = []  # other reader disclosures (D24)
    table: Table | None = None
    try:
        text = decode(data)
        if not text.strip():
            notes.append(f"{platform}: {path.name} is empty ({len(data)} bytes); no rows read")
        else:
            table = parse(text, entry)
            missing = [t for t in REQUIRED[kind] if t not in table.columns]
            if missing:
                raise TableError(f"no column for {', '.join(missing)}")
            if table.summary_rows:
                notes.append(f"{platform}: dropped {len(table.summary_rows)} summary rows")
            ctx = Context(
                table=table,
                fallback_currency=_fallback_currency(platform, manifest, path),
                attribution_window=manifest.attribution_window.get(platform)
                or cm.default_attribution_window,
            )
            if kind == "performance":
                rows, quarantined = _performance(platform, table, ctx, cm, notes)
                notes += _objective_checks(platform, table)
                changes = _measurement_changes(platform, rows)
            elif kind == "orders":
                rows, quarantined = _orders(table, ctx)
            else:
                rows, quarantined = _site(table, ctx)
    except TableError as e:
        raise _g1_fail(platform, [f"{path.name}: {e}"], payload) from e

    empty = table is None or not table.rows
    if kind == "performance":
        # C8: partial truth when some row lacks an observed count and no modeled share is known.
        partial = any(r.conversions_observed is None for r in rows) and all(
            r.conversions_modeled_share is None for r in rows
        )
        accounts = {r.entity_ids.get("account") for r in rows}
        account_id = next(iter(accounts)) if len(accounts) == 1 else None
    else:
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
        notes=notes,
        empty_account=empty,
        timezone=_timezone(kind, table),
        pulled_at=utcnow(),
        synthetic=manifest.synthetic,
    )
