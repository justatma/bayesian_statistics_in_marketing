"""Google Ads API over REST, read only. Facts: spec/facts/F3_google_ads.md; decisions D21, D25.

No developer token and no manager account are required (D21). ``developer-token`` and
``login-customer-id`` are sent only when their environment variables are set.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from bayesian_marketing.core import ClientConfig
from bayesian_marketing.data_contract.connectors.base import (
    Fetched,
    Record,
    micros,
    text,
    window_check,
)
from bayesian_marketing.data_contract.connectors.http import (
    ConnectorError,
    Response,
    Transport,
    call,
)

PLATFORM = "google_ads"
GOOGLE_ADS_API_VERSION = "v26"  # D21: the one constant to bump (F3 §1)
API_BASE = "https://googleads.googleapis.com"
TOKEN_URL = "https://www.googleapis.com/oauth2/v3/token"  # F3 §2
CLIENT_ID_ENV = "GOOGLE_ADS_CLIENT_ID"
CLIENT_SECRET_ENV = "GOOGLE_ADS_CLIENT_SECRET"
REFRESH_TOKEN_ENV = "GOOGLE_ADS_REFRESH_TOKEN"
DEVELOPER_TOKEN_ENV = "GOOGLE_ADS_DEVELOPER_TOKEN"
LOGIN_CUSTOMER_ENV = "GOOGLE_ADS_LOGIN_CUSTOMER_ID"

ENDPOINTS = (
    "https://googleads.googleapis.com/v26/customers/CUSTOMER_ID/googleAds:search",
    "https://www.googleapis.com/oauth2/v3/token",
)

CUSTOMER_FIELDS = ("customer.currency_code", "customer.time_zone")
# Query A of F3 §4: cost, clicks, impressions and conversion totals by day, no conversion-action
# segment (conversion-action segments do not combine with cost metrics, F3 §4 INFERRED).
AD_FIELDS = (
    "customer.id",
    "campaign.id",
    "ad_group.id",
    "ad_group_ad.ad.id",
    "segments.date",
    "metrics.impressions",
    "metrics.clicks",
    "metrics.cost_micros",
    "metrics.conversions",
    "metrics.conversions_value",
)
# FIELDS names each field as F3 spells it: the metrics row lists "metrics.cost_micros (int64),
# impressions (int64), clicks (int64)", so impressions and clicks appear without the prefix.
DOCUMENTED_AD_FIELDS = tuple(
    f.removeprefix("metrics.") if f in ("metrics.impressions", "metrics.clicks") else f
    for f in AD_FIELDS
)
ENVELOPE = ("results", "nextPageToken", "pageToken", "query")
HEADERS = ("Authorization", "login-customer-id", "developer-token")
TOKEN_FORM = ("grant_type", "refresh_token", "client_id", "client_secret")
FIELDS = CUSTOMER_FIELDS + DOCUMENTED_AD_FIELDS + ENVELOPE + HEADERS + TOKEN_FORM


def json_name(gaql: str) -> str:
    """REST JSON spells GAQL names in lowerCamelCase (F3 §3, INFERRED from proto3 JSON)."""
    return re.sub(r"_([a-z0-9])", lambda m: m.group(1).upper(), gaql)


def pick(result: dict[str, Any], gaql: str) -> Any:
    """A GAQL field from a result row: camelCase first, then snake_case as in the query."""
    for name in (json_name(gaql), gaql):
        node: Any = result
        for part in name.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if node is not None:
            return node
    return None


def _failure(resp: Response) -> dict[str, Any]:
    body = resp.body
    if isinstance(body, list) and body:  # searchStream-style arrays
        body = body[0]
    if not isinstance(body, dict):
        return {}
    return body.get("error") if isinstance(body.get("error"), dict) else body


def _error_codes(resp: Response) -> list[str]:
    """Each GoogleAdsFailure ``errorCode`` value, under the root or ``error`` (F3 §9)."""
    out: list[str] = []
    for d in _failure(resp).get("details") or []:
        if isinstance(d, dict) and str(d.get("@type", "")).endswith("GoogleAdsFailure"):
            for e in d.get("errors") or []:
                out += [str(v) for v in (e.get("errorCode") or {}).values()]
    return out


RETRY_STATUS = frozenset({429, 500, 503})


def _retryable(resp: Response) -> bool:
    """F3 §9: HTTP 429 / RESOURCE_EXHAUSTED and RESOURCE_TEMPORARILY_EXHAUSTED back off; 500 and
    503 are retried on the same schedule (review fix 7, INFERRED)."""
    codes = _error_codes(resp)
    return resp.status in RETRY_STATUS or any(
        c in ("RESOURCE_EXHAUSTED", "RESOURCE_TEMPORARILY_EXHAUSTED") for c in codes
    )


def _describe(resp: Response) -> str:
    f = _failure(resp)
    codes = _error_codes(resp)
    return f"{f.get('message') or str(resp.body)[:300]}" + (
        f" ({', '.join(codes)})" if codes else ""
    )


def _token_retryable(resp: Response) -> bool:
    return resp.status in (429, 500, 503)


def _token_describe(resp: Response) -> str:
    b = resp.body if isinstance(resp.body, dict) else {}
    return f"{b.get('error')}: {b.get('error_description')}" if b else str(resp.body)[:300]


def access_token(t: Transport, platform: str) -> str:
    """One OAuth refresh token serves Google Ads and GA4 (D25). F3 §2 token refresh."""
    form = {
        "grant_type": "refresh_token",
        "client_id": t.credential(CLIENT_ID_ENV),
        "client_secret": t.credential(CLIENT_SECRET_ENV),
        "refresh_token": t.credential(REFRESH_TOKEN_ENV),
    }
    resp = call(
        t,
        platform,
        "POST",
        TOKEN_URL,
        form=form,
        retryable=_token_retryable,
        describe=_token_describe,
    )
    tok = resp.body.get("access_token") if isinstance(resp.body, dict) else None
    if not tok:
        raise ConnectorError(f"{platform}: token refresh returned no access_token")
    return str(tok)


def customer_id(account: str) -> str:
    """Ten digits, no hyphens (F3 §2)."""
    return account.replace("-", "").strip()


@dataclass
class Auth:
    """Request headers plus whether the access token was already refreshed once (fix 7)."""

    headers: dict[str, str]
    refreshed: bool = False


def _unauthorized(resp: Response) -> bool:
    return resp.status == 401


def _search(t: Transport, cid: str, auth: Auth, query: str) -> list[dict[str, Any]]:
    url = f"{API_BASE}/{GOOGLE_ADS_API_VERSION}/customers/{cid}/googleAds:search"
    out: list[dict[str, Any]] = []
    page: str | None = None
    while True:
        body: dict[str, Any] = {"query": query}
        if page:
            body["pageToken"] = page  # F3 §9: resend the identical query with pageToken
        resp = _post(t, url, auth, body)
        data = resp.body if isinstance(resp.body, dict) else {}
        out += [r for r in data.get("results") or [] if isinstance(r, dict)]
        page = data.get("nextPageToken")
        if not page:
            return out


def _post(t: Transport, url: str, auth: Auth, body: dict[str, Any]) -> Response:
    """One search call. A 401 mid-pull (expired access token) refreshes the token once and
    retries; a second 401 fails."""
    while True:
        resp = call(
            t,
            PLATFORM,
            "POST",
            url,
            headers=auth.headers,
            json_body=body,
            retryable=_retryable,
            describe=_describe,
            accept=None if auth.refreshed else _unauthorized,
        )
        if resp.ok:
            return resp
        auth.refreshed = True
        auth.headers["Authorization"] = f"Bearer {access_token(t, PLATFORM)}"


def _record(r: dict[str, Any], window: tuple[date, date]) -> Record:
    d = text(pick(r, "segments.date"))
    return Record(
        values={
            "date": d,
            "entity_ids.account": text(pick(r, "customer.id")),
            "entity_ids.campaign": text(pick(r, "campaign.id")),
            "entity_ids.ad_set": text(pick(r, "ad_group.id")),
            "entity_ids.ad": text(pick(r, "ad_group_ad.ad.id")),
            "impressions": text(pick(r, "metrics.impressions")) or "0",
            "clicks": text(pick(r, "metrics.clicks")) or "0",
            "spend": micros(pick(r, "metrics.cost_micros")) or "0",
            "currency": None,  # the customer's currency_code, applied as the fallback
            "conversions_reported": text(pick(r, "metrics.conversions")) or "0",
            "revenue_reported": text(pick(r, "metrics.conversions_value")) or "0",
            "attribution_window": None,  # per conversion action, not in the row (channels.yaml)
        },
        source=r,
        reasons=window_check(d, window),
    )


def fetch(config: ClientConfig, window: tuple[date, date], t: Transport) -> Fetched:
    cid = customer_id(config.accounts[PLATFORM])
    headers = {"Authorization": f"Bearer {access_token(t, PLATFORM)}"}
    login = t.optional(LOGIN_CUSTOMER_ENV)
    if login:
        headers["login-customer-id"] = customer_id(login)
    dev = t.optional(DEVELOPER_TOKEN_ENV)
    if dev:
        headers["developer-token"] = dev
    auth = Auth(headers)
    cust = _search(t, cid, auth, f"SELECT {', '.join(CUSTOMER_FIELDS)} FROM customer")
    info = cust[0] if cust else {}
    notes: list[str] = []
    tz = pick(info, "customer.time_zone")
    if not tz:
        tz = config.timezone
        notes.append(f"{PLATFORM}: customer has no time_zone; dates taken as {tz} (config)")
    # Proto3 JSON leaves zero-valued int64 metrics out of a row; absent metrics read as 0.
    query = (
        f"SELECT {', '.join(AD_FIELDS)} FROM ad_group_ad WHERE segments.date BETWEEN "
        f"'{window[0].isoformat()}' AND '{window[1].isoformat()}'"
    )
    results = _search(t, cid, auth, query)
    return Fetched(
        timezone=str(tz),
        currency=pick(info, "customer.currency_code"),
        records=[_record(r, window) for r in results],
        n_elements=len(results),
        notes=notes,
    )
