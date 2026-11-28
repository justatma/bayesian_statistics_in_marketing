"""LinkedIn Marketing API adAnalytics, read only. Facts: spec/facts/F4_linkedin.md."""

from __future__ import annotations

from datetime import date
from typing import Any

from bayesian_marketing.core import ClientConfig
from bayesian_marketing.data_contract.connectors.base import (
    Fetched,
    Record,
    halves,
    text,
    window_check,
)
from bayesian_marketing.data_contract.connectors.http import (
    ConnectorError,
    Response,
    Transport,
    call,
)

PLATFORM = "linkedin"
LINKEDIN_VERSION = "202610"  # F4 §1: latest on build day; there is no default version
REST = "https://api.linkedin.com/rest/"
TOKEN_ENV = "LINKEDIN_ACCESS_TOKEN"
TIMEZONE = "UTC"  # F4 §2: adAnalytics dates are UTC, start and end inclusive
ELEMENT_CAP = 15_000  # F4 §2: no pagination; a response holds at most 15,000 elements

ENDPOINTS = (
    "https://api.linkedin.com/rest/",
    "/rest/adAnalytics",
    "/rest/adAccounts/{id}",
)

METRICS = (
    "impressions",
    "clicks",
    "costInLocalCurrency",
    "externalWebsiteConversions",
    "conversionValueInLocalCurrency",
    "dateRange",
    "pivotValues",
)
# F4 §2 q=statistics takes up to three pivots; pivotValues follow this order. channels.yaml maps
# LinkedIn campaign group -> campaign, campaign -> ad_set, creative -> ad.
PIVOTS = ("CAMPAIGN_GROUP", "CAMPAIGN", "CREATIVE")
QUERY = ("q", "statistics", "pivots", "timeGranularity", "DAILY", "accounts", "fields")
HEADERS = ("Authorization", "Linkedin-Version", "X-Restli-Protocol-Version")
URNS = ("urn:li:sponsoredAccount", "urn:li:sponsoredCampaign", "urn:li:sponsoredCreative")
ENVELOPE = ("elements", "currency", "message", "status")
# Names (D34): the ad account element's `name` is VERIFIED (F4 §3). Campaign group, campaign and
# creative names need the adCampaigns / adCreatives listings, whose shapes F4 leaves UNKNOWN, and
# F4 lists no objective field: those stay None (manifest D34 open questions).
ACCOUNT_FIELDS = ("name",)
FIELDS = ACCOUNT_FIELDS + METRICS + PIVOTS + QUERY + HEADERS + URNS + ENVELOPE

RETRY_STATUS = frozenset({429, 500, 503, 504})  # F4 §5; 400, 401, 403 are not retried


def _retryable(resp: Response) -> bool:
    return resp.status in RETRY_STATUS


def _describe(resp: Response) -> str:
    b = resp.body if isinstance(resp.body, dict) else {}
    if not b:
        return str(resp.body)[:300]
    return f"{b.get('code') or b.get('serviceErrorCode')}: {b.get('message')}"


def account_number(account: str) -> str:
    """The numeric id from ``123`` or ``urn:li:sponsoredAccount:123``."""
    return account.rsplit(":", 1)[-1].strip()


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Linkedin-Version": LINKEDIN_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
    }


def _restli_date(d: date) -> str:
    return f"(year:{d.year},month:{d.month},day:{d.day})"  # unpadded (F4 §2)


def analytics_url(account: str, window: tuple[date, date]) -> str:
    """Rest.li 2.0 query: parentheses, colons and commas literal, URN colons encoded (F4 §2)."""
    urn = f"urn%3Ali%3AsponsoredAccount%3A{account}"
    return (
        f"{REST}adAnalytics?q=statistics&pivots=List({','.join(PIVOTS)})&timeGranularity=DAILY"
        f"&dateRange=(start:{_restli_date(window[0])},end:{_restli_date(window[1])})"
        f"&accounts=List({urn})&fields={','.join(METRICS)}"
    )


def _day(dr: Any, key: str) -> str | None:
    d = dr.get(key) if isinstance(dr, dict) else None
    if not isinstance(d, dict):
        return None
    try:
        return date(int(d["year"]), int(d["month"]), int(d["day"])).isoformat()
    except (KeyError, TypeError, ValueError):
        return None


def _id(urn: Any) -> str | None:
    return urn.rsplit(":", 1)[-1] if isinstance(urn, str) and urn else None


def _record(
    el: dict[str, Any], account: str, window: tuple[date, date], account_name: str | None = None
) -> Record:
    start = _day(el.get("dateRange"), "start")
    end = _day(el.get("dateRange"), "end")
    pv = el.get("pivotValues") or []
    pv = pv if isinstance(pv, list) else []
    reasons = window_check(start, window)
    if end is not None and end != start:
        reasons.append(f"non-daily aggregate: dateRange {start} to {end}")
    if len(pv) != len(PIVOTS):
        reasons.append(f"pivotValues: expected {len(PIVOTS)} URNs, got {len(pv)}")
    return Record(
        values={
            "date": start,
            "entity_ids.account": account,
            "entity_ids.account_name": account_name,
            "entity_ids.campaign": _id(pv[0]) if len(pv) > 0 else None,
            "entity_ids.ad_set": _id(pv[1]) if len(pv) > 1 else None,
            "entity_ids.ad": _id(pv[2]) if len(pv) > 2 else None,
            "impressions": text(el.get("impressions")) or "0",
            "clicks": text(el.get("clicks")) or "0",
            "spend": text(el.get("costInLocalCurrency")) or "0",
            "currency": None,  # the ad account currency, applied as the fallback
            "conversions_reported": text(el.get("externalWebsiteConversions")) or "0",
            "revenue_reported": text(el.get("conversionValueInLocalCurrency")),
            "attribution_window": None,  # set per conversion rule; registry default
        },
        source=el,
        reasons=reasons,
    )


def _analytics(
    t: Transport, account: str, token: str, window: tuple[date, date]
) -> list[dict[str, Any]]:
    resp = call(
        t,
        PLATFORM,
        "GET",
        analytics_url(account, window),
        headers=_headers(token),
        retryable=_retryable,
        describe=_describe,
    )
    body = resp.body if isinstance(resp.body, dict) else {}
    elements = [el for el in body.get("elements") or [] if isinstance(el, dict)]
    if len(elements) >= ELEMENT_CAP:  # possibly truncated: split the range (F4 §2)
        parts = halves(window)
        if parts is None:
            raise ConnectorError(f"{PLATFORM}: {len(elements)} elements for one day; truncated")
        return _analytics(t, account, token, parts[0]) + _analytics(t, account, token, parts[1])
    return elements


def fetch(config: ClientConfig, window: tuple[date, date], t: Transport) -> Fetched:
    account = account_number(config.accounts[PLATFORM])
    token = t.credential(TOKEN_ENV)
    acct = call(
        t,
        PLATFORM,
        "GET",
        f"{REST}adAccounts/{account}",
        headers=_headers(token),
        retryable=_retryable,
        describe=_describe,
    )
    info = acct.body if isinstance(acct.body, dict) else {}
    elements = _analytics(t, account, token, window)
    name = info.get("name")
    name = (name.strip() or None) if isinstance(name, str) else None
    return Fetched(
        timezone=TIMEZONE,
        currency=info.get("currency"),
        records=[_record(el, account, window, name) for el in elements],
        n_elements=len(elements),
        notes=[
            f"{PLATFORM}: dates are UTC days (F4 §2) and may differ from the account's "
            f"Campaign Manager day (F4 §2 UNKNOWN)"
        ],
    )
