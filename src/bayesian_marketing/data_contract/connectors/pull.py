"""§5.1 pull: one platform's rows for a window, live, recorded or replayed (C2, C4, C6)."""

from __future__ import annotations

import itertools
import json
import os
from collections.abc import Callable
from datetime import date
from types import ModuleType
from typing import Any

from bayesian_marketing.channels.model import channel_ref, load_channel_model
from bayesian_marketing.core import (
    ClientConfig,
    Platform,
    PlatformPull,
    QuarantinedRow,
    inputs_hash,
    utcnow,
)
from bayesian_marketing.data_contract.connectors import ga4, google_ads, linkedin, meta
from bayesian_marketing.data_contract.connectors.base import (
    PERF_TARGETS,
    SITE_TARGETS,
    Fetched,
    Record,
)
from bayesian_marketing.data_contract.connectors.http import Transport
from bayesian_marketing.data_contract.readers.read import (
    _measurement_changes,
    _performance,
    _site,
)
from bayesian_marketing.data_contract.readers.rows import Context, performance_fields, site_row
from bayesian_marketing.data_contract.readers.table import Table

CONNECTORS: dict[str, ModuleType] = {
    "meta": meta,
    "google_ads": google_ads,
    "linkedin": linkedin,
    "ga4": ga4,
}
_SEQ = itertools.count()  # distinguishes pulls started in the same microsecond (C4)


class _Cells(list[str]):
    """Row cells that remember the API element they came from, for quarantine ``raw``."""

    source: dict[str, Any]


class _ApiTable(Table):
    def raw(self, cells: list[str]) -> dict[str, Any]:
        src = getattr(cells, "source", None)
        return dict(src) if isinstance(src, dict) else super().raw(cells)


def _table(targets: tuple[str, ...], records: list[Record]) -> _ApiTable:
    rows: list[list[str]] = []
    for rec in records:
        cells = _Cells(rec.values.get(t) or "" for t in targets)
        cells.source = rec.source
        rows.append(cells)
    return _ApiTable(header=list(targets), rows=rows, columns={t: i for i, t in enumerate(targets)})


def _split(
    targets: tuple[str, ...],
    fetched: Fetched,
    ctx_for: Callable[[_ApiTable], Context],
    check: Callable[[Context, list[str]], tuple[Any, list[str]]],
) -> tuple[_ApiTable, Context, list[QuarantinedRow]]:
    """Records failing a connector pre-check are quarantined with every reason found; the rest
    form the table the P1 validators read."""
    clean = [r for r in fetched.records if not r.reasons]
    flagged = [r for r in fetched.records if r.reasons]
    pre = _table(targets, flagged)
    ctx = ctx_for(pre)
    quarantined = [
        QuarantinedRow(raw=dict(rec.source), reasons=rec.reasons + check(ctx, cells)[1])
        for rec, cells in zip(flagged, pre.rows, strict=True)
    ]
    table = _table(targets, clean)
    return table, ctx_for(table), quarantined


def pull(platform: Platform, config: ClientConfig, window: tuple[date, date]) -> PlatformPull:
    """Pull one platform's rows for the window (§5.1).

    ``BAYES_REPLAY_DIR`` serves every exchange from a recording and opens no socket;
    ``BAYES_RECORD_DIR`` makes live calls and writes redacted exchanges plus ``request.json``
    (C6). Rows pass the P1 row validators: bad rows are quarantined, never coerced (C1). An
    account with no data returns an empty pull flagged ``empty_account`` (C6). Every pull gets a
    new ``pull_id`` (C4).
    """
    if platform not in CONNECTORS:
        raise ValueError(f"no connector for {platform!r}; connectors: {sorted(CONNECTORS)}")
    if platform not in config.accounts and platform != "ga4":
        raise ValueError(f"client config {config.client_id!r} has no {platform} account")
    if window[0] > window[1]:
        raise ValueError(f"window start {window[0]} is after its end {window[1]}")
    cm = load_channel_model(platform)
    module = CONNECTORS[platform]
    t = Transport.from_env()
    try:
        if t.record_dir is not None:
            request = {
                "config": config.model_dump(mode="json"),
                "window": [window[0].isoformat(), window[1].isoformat()],
            }
            (t.record_dir / "request.json").write_text(json.dumps(request, indent=1) + "\n")
        fetched: Fetched = module.fetch(config, window, t)
    except BaseException:
        t.discard_recording()  # a failed pull leaves the existing recording untouched
        raise
    else:
        t.commit_recording()
    finally:
        t.close()

    notes = list(fetched.notes)
    if platform == "ga4":
        targets = SITE_TARGETS

        def check(ctx: Context, cells: list[str]) -> tuple[Any, list[str]]:
            return site_row(ctx, cells)
    else:
        targets = PERF_TARGETS

        def check(ctx: Context, cells: list[str]) -> tuple[Any, list[str]]:
            return performance_fields(ctx, cells)

    def ctx_for(table: _ApiTable) -> Context:
        return Context(
            table=table,
            fallback_currency=fetched.currency,
            attribution_window=cm.default_attribution_window,
        )

    table, ctx, quarantined = _split(targets, fetched, ctx_for, check)
    changes: list[str] = []
    if platform == "ga4":
        rows, q = _site(table, ctx)
        partial = False
    else:
        rows, q = _performance(platform, table, ctx, cm, notes)
        changes = _measurement_changes(platform, rows)
        # C8: partial truth when some row lacks an observed count and no modeled share is known.
        partial = any(r.conversions_observed is None for r in rows) and all(
            r.conversions_modeled_share is None for r in rows
        )
    quarantined += q

    pulled_at = utcnow()
    account = config.accounts.get(platform) or ""
    if platform == "ga4" and not account:
        account = os.environ.get(ga4.PROPERTY_ENV, "")
    windows = sorted({w or cm.default_attribution_window for w in fetched.attribution_windows})
    payload = {
        "platform": platform,
        "account": account,
        "window": [window[0].isoformat(), window[1].isoformat()],
        "attribution_windows": windows or [cm.default_attribution_window],
        "pulled_at": pulled_at.isoformat(),
        "seq": next(_SEQ),
    }
    return PlatformPull(
        pull_id=f"pull_{platform}_{inputs_hash(payload)[:8]}",
        platform=platform,
        channel_ref=channel_ref(platform),
        account_id=account or None,
        window=window,
        rows=rows,
        quarantined=quarantined,
        partial_truth=partial,
        measurement_changes=changes,
        notes=notes,
        empty_account=fetched.n_elements == 0,
        timezone=fetched.timezone,
        pulled_at=pulled_at,
        synthetic=False,
    )
