"""GA4 Data API runReport, read only. Facts: spec/facts/F5_ga4.md; auth per D25."""

from __future__ import annotations

import os
from datetime import date
from typing import Any

from bayesian_marketing.core import ClientConfig
from bayesian_marketing.data_contract.connectors.base import (
    Fetched,
    Record,
    text,
    to_minor_units,
    window_check,
)
from bayesian_marketing.data_contract.connectors.google_ads import access_token
from bayesian_marketing.data_contract.connectors.http import (
    ConnectorError,
    Response,
    Transport,
    call,
)

PLATFORM = "ga4"
API = "https://analyticsdata.googleapis.com/v1beta/properties/"
PROPERTY_ENV = "GA4_PROPERTY_ID"
PAGE_LIMIT = 10_000  # F5 §1: the API's default page size (max 250,000)

ENDPOINTS = ("https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport",)

DIMENSIONS = ("date", "sessionSource", "sessionMedium", "sessionCampaignName")
METRICS = ("sessions", "ecommercePurchases", "purchaseRevenue")
TARGETS = {  # dimension or metric -> SiteRow target (channels.yaml ga4 map)
    "date": "date",
    "sessionSource": "utm.source",
    "sessionMedium": "utm.medium",
    "sessionCampaignName": "utm.campaign",
    "sessions": "sessions",
    "ecommercePurchases": "purchases",
    "purchaseRevenue": "revenue",
}
BODY = (
    "dateRanges",
    "dimensions",
    "metrics",
    "limit",
    "offset",
    "currencyCode",
    "keepEmptyRows",
    "returnPropertyQuota",
    "startDate",
    "endDate",
)
RESPONSE = ("rows", "dimensionValues", "metricValues", "rowCount", "dimensionHeaders", "metadata")
# Response metadata keys the connector reads. F5 §1 names `metadata` but not its keys; the
# integrator's recording (data/recordings/ga4) shows both. Not in FIELDS: not verbatim in F5.
META_TIMEZONE, META_CURRENCY = "timeZone", "currencyCode"
# ResponseMetaData quality keys (D34). F5 §1 names `metadata` and VERIFIES only
# dataTruncationReasons; the other four are named by the D34 brief after the ResponseMetaData
# reference the data review cites (INFERRED, not verbatim in F5, so not in FIELDS).
META_SAMPLING = "samplingMetadatas"  # [{samplesReadCount, samplingSpaceSize}]
META_THRESHOLDING = "subjectToThresholding"  # bool
META_OTHER_ROW = "dataLossFromOtherRow"  # bool: some rows aggregated into "(other)"
META_RESTRICTION = "schemaRestrictionResponse"  # {activeMetricRestrictions: [...]}
META_TRUNCATION = "dataTruncationReasons"  # F5 §1 VERIFIED (changelog 2026-09-14)
QUALITY_PREFIX = "ga4_quality:"  # machine-readable prefix on a sampled or thresholded pull
FIELDS = DIMENSIONS + METRICS + BODY + RESPONSE + (META_TRUNCATION,)

RETRY_STATUS = frozenset({429, 500, 503})  # F5 §3


def _retryable(resp: Response) -> bool:
    return resp.status in RETRY_STATUS


def _describe(resp: Response) -> str:
    b = resp.body if isinstance(resp.body, dict) else {}
    e = b.get("error") if isinstance(b.get("error"), dict) else b
    return f"{e.get('status')}: {e.get('message')}" if e else str(resp.body)[:300]


def property_number(account: str) -> str:
    return account.removeprefix("properties/").strip()


def _iso(yyyymmdd: str | None) -> str | None:
    """GA4 ``date`` is YYYYMMDD (F5 §2); anything else is left for the validator."""
    if yyyymmdd and len(yyyymmdd) == 8 and yyyymmdd.isdigit():
        return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"
    return yyyymmdd


def _record(row: dict[str, Any], window: tuple[date, date], currency: str | None) -> Record:
    dims = [v.get("value") for v in row.get("dimensionValues") or [] if isinstance(v, dict)]
    mets = [v.get("value") for v in row.get("metricValues") or [] if isinstance(v, dict)]
    values: dict[str, str | None] = {"currency": None}
    for name, v in zip(DIMENSIONS, dims, strict=False):
        values[TARGETS[name]] = v if isinstance(v, str) and v != "" else None
    for name, v in zip(METRICS, mets, strict=False):
        values[TARGETS[name]] = text(v)
    values["date"] = _iso(values.get("date"))
    values["revenue"] = to_minor_units(values.get("revenue"), currency)
    reasons = window_check(values["date"], window)
    if len(dims) != len(DIMENSIONS) or len(mets) != len(METRICS):
        reasons.append(f"row has {len(dims)} dimensions and {len(mets)} metrics")
    return Record(values=values, source=row, reasons=reasons)


def _check_headers(body: dict[str, Any]) -> None:
    """Values are matched to names by position; the headers must be in request order."""
    got = [h.get("name") for h in body.get("dimensionHeaders") or [] if isinstance(h, dict)]
    if got and tuple(got) != DIMENSIONS:
        raise ConnectorError(f"ga4: dimensionHeaders {got} not in request order {list(DIMENSIONS)}")


def fetch(config: ClientConfig, window: tuple[date, date], t: Transport) -> Fetched:
    prop = property_number(config.accounts.get(PLATFORM) or os.environ.get(PROPERTY_ENV, ""))
    if not prop:
        raise ConnectorError(f"ga4: no property id in the client config or {PROPERTY_ENV}")
    headers = {"Authorization": f"Bearer {access_token(t, PLATFORM)}"}
    url = f"{API}{prop}:runReport"
    rows: list[dict[str, Any]] = []
    meta: dict[str, Any] = {}
    offset = 0
    while True:
        body = {
            "dateRanges": [{"startDate": window[0].isoformat(), "endDate": window[1].isoformat()}],
            "dimensions": [{"name": d} for d in DIMENSIONS],
            "metrics": [{"name": m} for m in METRICS],
            "limit": str(PAGE_LIMIT),
            "offset": str(offset),
            "currencyCode": config.currency,  # revenue in the client currency (F5 §2)
            "keepEmptyRows": False,
            "returnPropertyQuota": True,
        }
        resp = call(
            t,
            PLATFORM,
            "POST",
            url,
            headers=headers,
            json_body=body,
            retryable=_retryable,
            describe=_describe,
        )
        data = resp.body if isinstance(resp.body, dict) else {}
        _check_headers(data)
        if not meta and isinstance(data.get("metadata"), dict):
            meta = data["metadata"]
        page = [r for r in data.get("rows") or [] if isinstance(r, dict)]
        rows += page
        offset += PAGE_LIMIT
        total = int(data.get("rowCount") or 0)
        if not page or offset >= total:  # F5 §1: loop until offset >= rowCount
            break
    tz, currency, notes = account_facts(meta, config)
    notes += quality_notes(meta)
    return Fetched(
        timezone=tz,
        currency=currency,
        records=[_record(r, window, currency) for r in rows],
        n_elements=len(rows),
        notes=notes,
    )


def account_facts(meta: dict[str, Any], config: ClientConfig) -> tuple[str, str, list[str]]:
    """Timezone and currency from the runReport metadata; the client config is the fallback."""
    notes: list[str] = []
    out: list[str] = []
    for key, label, fallback in (
        (META_TIMEZONE, "timezone", config.timezone),
        (META_CURRENCY, "currency", config.currency),
    ):
        got = meta.get(key)
        if not isinstance(got, str) or not got:
            notes.append(
                f"{PLATFORM}: response metadata has no {key}; {label} taken as {fallback} "
                f"from the client config"
            )
            got = fallback
        elif got != fallback:
            notes.append(
                f"{PLATFORM}: property {label} {got} differs from the client config's {fallback}; "
                f"using the property's"
            )
        out.append(got)
    return out[0], out[1], notes


def _count(v: Any) -> str:
    t = text(v)
    return t if t is not None else "unknown"


def quality_notes(meta: dict[str, Any]) -> list[str]:
    """Pull notes for sampling, thresholding, "(other)" aggregation, metric restrictions and
    truncation in the runReport metadata (D34). Sampled and thresholded pulls carry the
    ``ga4_quality:`` prefix so floors and reports can find them."""
    notes: list[str] = []
    sampling = meta.get(META_SAMPLING)
    if isinstance(sampling, list) and sampling:
        parts = [
            f"{_count(m.get('samplesReadCount'))} of {_count(m.get('samplingSpaceSize'))}"
            for m in sampling
            if isinstance(m, dict)
        ]
        notes.append(
            f"{QUALITY_PREFIX} sampled; samples read of sampling space per date range: "
            f"{', '.join(parts) or 'unknown'}"
        )
    if meta.get(META_THRESHOLDING) is True:
        notes.append(f"{QUALITY_PREFIX} thresholded; rows with small user counts may be withheld")
    if meta.get(META_OTHER_ROW) is True:
        notes.append(f'{PLATFORM}: some rows were aggregated into "(other)" ({META_OTHER_ROW})')
    restriction = meta.get(META_RESTRICTION)
    restricted = (
        restriction.get("activeMetricRestrictions") if isinstance(restriction, dict) else None
    )
    if isinstance(restricted, list) and restricted:
        parts = []
        for r in restricted:
            if not isinstance(r, dict):
                continue
            types = r.get("restrictedMetricTypes")
            kinds = ", ".join(str(x) for x in types) if isinstance(types, list) else ""
            parts.append(f"{r.get('metricName')}" + (f" ({kinds})" if kinds else ""))
        notes.append(f"{PLATFORM}: restricted metrics: {'; '.join(parts)}")
    truncation = meta.get(META_TRUNCATION)
    if isinstance(truncation, list):
        seen: list[str] = []
        for tr in truncation:
            if isinstance(tr, dict):
                msg = f"{tr.get('dataTruncationType')} before {tr.get('dataTruncationDate')}"
                if msg not in seen:
                    seen.append(msg)
        if seen:
            notes.append(f"{PLATFORM}: data truncated: {'; '.join(seen)}")
    return notes
