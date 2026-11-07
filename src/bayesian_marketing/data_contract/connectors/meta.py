"""Meta Marketing API (Graph API) insights, read only. Facts: spec/facts/F2_meta.md."""

from __future__ import annotations

import json
from datetime import date
from typing import Any
from urllib.parse import urlencode, urlsplit

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

PLATFORM = "meta"
API_VERSION = "v26.0"  # F2 §1: latest on build day; pinned, never omitted
GRAPH = f"https://graph.facebook.com/{API_VERSION}/"
TOKEN_ENV = "META_ACCESS_TOKEN"

ENDPOINTS = (
    "https://graph.facebook.com/v26.0/",  # F2 §1
    "/act_{ad_account_id}/insights",  # F2 §2
    "/v26.0/act_{id}",  # F2 §8 ad account fields
)

INSIGHT_FIELDS = (
    "date_start",
    "date_stop",
    "account_id",
    "campaign_id",
    "adset_id",
    "ad_id",
    "impressions",
    "inline_link_clicks",  # channels.yaml maps "Link clicks" to clicks
    "spend",
    "account_currency",
    "actions",
    "action_values",
    "attribution_setting",
    # Live view §3.1 (D41, D43): names and objective, all VERIFIED on the insights edge in F2b §1-2.
    # Set by the L0 skeleton (build log B2); mapping them into the row is L1.
    "account_name",
    "campaign_name",
    "adset_name",
    "ad_name",
    "objective",
)
OBJECTIVE_REQUESTED = True  # F2b §2: objective VERIFIED as an insights field
# Live view §3.3: name, account_status, spend_cap, amount_spent VERIFIED on the ad account node
# (F2b §3). spend_cap is in minor units (VERIFIED); amount_spent INFERRED the same.
ACCOUNT_FIELDS = (
    "timezone_name",
    "currency",
    "name",
    "account_status",
    "spend_cap",
    "amount_spent",
)
# Purchase action types F2 §3 lists, in order of preference. Families overlap (omni_purchase rolls
# up pixel, app and onsite purchases), so one type is chosen per pull and never summed: the first
# in this order that appears anywhere in the pull. Which the owner's pixel reports: F2 open q. 6.
PURCHASE_ACTION_TYPES = ("omni_purchase", "purchase", "offsite_conversion.fb_pixel_purchase")
GRAPH_HOST = "graph.facebook.com"
PARAMS = ("level", "fields", "time_range", "time_increment", "access_token")
ENVELOPE = ("data", "paging", "next", "action_type", "value")
ERROR_FIELDS = ("error", "code", "error_subcode", "message")
FIELDS = INSIGHT_FIELDS + ACCOUNT_FIELDS + PARAMS + ENVELOPE + ERROR_FIELDS + PURCHASE_ACTION_TYPES

# F2 §7: retryable codes 1, 2, 4, 17, 341, 368 (VERIFIED); 613 and 80000-80014 after backoff
# (INFERRED). F2 §6: code 100 subcode 1487534 means too much data per call: narrow the range.
RETRY_CODES = frozenset({1, 2, 4, 17, 341, 368, 613, *range(80000, 80015)})
# F2 §7, §11: HTTP status on errors is UNKNOWN; key off error.code. A 429 or 5xx with no Graph
# error body is retried on status alone.
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
TOO_MUCH_DATA = (100, 1487534)


def _error(resp: Response) -> dict[str, Any]:
    body = resp.body if isinstance(resp.body, dict) else {}
    err = body.get("error")
    return err if isinstance(err, dict) else {}


def _retryable(resp: Response) -> bool:
    e = _error(resp)
    if e:
        return e.get("code") in RETRY_CODES
    return resp.status in RETRY_STATUS


def _too_much(resp: Response) -> bool:
    e = _error(resp)
    return (e.get("code"), e.get("error_subcode")) == TOO_MUCH_DATA


def _describe(resp: Response) -> str:
    e = _error(resp)
    if not e:
        return str(resp.body)[:300]
    return f"code {e.get('code')} subcode {e.get('error_subcode')}: {e.get('message')}"


def account_path(account: str) -> str:
    """``act_<numeric>`` from either form (F2 §2: the path takes the ``act_`` prefix)."""
    return account if account.startswith("act_") else f"act_{account}"


def _get(t: Transport, url: str, **kw: Any) -> Response:
    return call(t, PLATFORM, "GET", url, retryable=_retryable, describe=_describe, **kw)


def _action_types(entries: Any) -> set[str]:
    if not isinstance(entries, list):
        return set()
    return {str(e.get("action_type")) for e in entries if isinstance(e, dict)}


def purchase_type(elements: list[dict[str, Any]]) -> str | None:
    """The one purchase action type used for the whole pull, or None when none appears."""
    seen: set[str] = set()
    for el in elements:
        seen |= _action_types(el.get("actions")) | _action_types(el.get("action_values"))
    return next((a for a in PURCHASE_ACTION_TYPES if a in seen), None)


def _purchase(entries: Any, action_type: str | None) -> str | None:
    """The default-window ``value`` of the chosen purchase action; absent list or entry means 0."""
    if not entries or action_type is None:
        return "0"
    for e in entries:
        if isinstance(e, dict) and e.get("action_type") == action_type:
            return text(e.get("value"))
    return "0"


def _clicks(el: dict[str, Any], absent: list[str]) -> str | None:
    """Absent ``inline_link_clicks`` beside present impressions reads as 0, like Google Ads and
    LinkedIn (F2 §2 does not say zero metrics are omitted; recorded in a pull note)."""
    v = text(el.get("inline_link_clicks"))
    if v is None and text(el.get("impressions")) is not None:
        absent.append("inline_link_clicks")
        return "0"
    return v


def _record(
    el: dict[str, Any], window: tuple[date, date], action_type: str | None, absent: list[str]
) -> Record:
    start, stop = el.get("date_start"), el.get("date_stop")
    reasons = window_check(start, window)
    if stop is not None and stop != start:
        reasons.append(f"non-daily aggregate: date_start {start} to date_stop {stop}")
    return Record(
        values={
            "date": start,
            "entity_ids.account": text(el.get("account_id")),
            "entity_ids.campaign": text(el.get("campaign_id")),
            "entity_ids.ad_set": text(el.get("adset_id")),
            "entity_ids.ad": text(el.get("ad_id")),
            "impressions": text(el.get("impressions")),
            "clicks": _clicks(el, absent),
            "spend": text(el.get("spend")),
            "currency": el.get("account_currency"),
            "conversions_reported": _purchase(el.get("actions"), action_type),
            "revenue_reported": _purchase(el.get("action_values"), action_type),
            "attribution_window": el.get("attribution_setting"),
        },
        source=el,
        reasons=reasons,
    )


def _insights(
    t: Transport, act: str, token: str, window: tuple[date, date]
) -> list[dict[str, Any]]:
    params = {
        "level": "ad",
        "time_increment": "1",
        "time_range": json.dumps(
            {"since": window[0].isoformat(), "until": window[1].isoformat()},
            separators=(",", ":"),
        ),
        "fields": ",".join(INSIGHT_FIELDS),
        "access_token": token,
    }
    url: str | None = f"{GRAPH}{act}/insights?{urlencode(params)}"
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    while url:
        if url in seen:
            raise ConnectorError(f"{PLATFORM}: paging.next repeats a page; stopping")
        seen.add(url)
        resp = _get(t, url, accept=_too_much)
        if _too_much(resp):
            parts = halves(window)
            if parts is None or out:
                raise ConnectorError(f"{PLATFORM}: {_describe(resp)} on a single-day request")
            return _insights(t, act, token, parts[0]) + _insights(t, act, token, parts[1])
        body = resp.body if isinstance(resp.body, dict) else {}
        out += [el for el in body.get("data") or [] if isinstance(el, dict)]
        url = (body.get("paging") or {}).get("next")  # F2 §5: follow until absent
        if url is not None:
            check_next(url)
    return out


def check_next(url: Any) -> None:
    """paging.next is followed only on the Graph API host over https."""
    parts = urlsplit(url) if isinstance(url, str) else None
    if parts is None or parts.scheme != "https" or parts.hostname != GRAPH_HOST:
        raise ConnectorError(f"{PLATFORM}: paging.next is not a {GRAPH_HOST} https URL; stopping")


def fetch(config: ClientConfig, window: tuple[date, date], t: Transport) -> Fetched:
    act = account_path(config.accounts[PLATFORM])
    token = t.credential(TOKEN_ENV)
    acct = _get(
        t, f"{GRAPH}{act}?{urlencode({'fields': ','.join(ACCOUNT_FIELDS), 'access_token': token})}"
    )
    info = acct.body if isinstance(acct.body, dict) else {}
    notes: list[str] = []
    tz = info.get("timezone_name")
    if not tz:
        tz = config.timezone
        notes.append(f"{PLATFORM}: account has no timezone_name; dates taken as {tz} (config)")
    elements = _insights(t, act, token, window)
    action_type = purchase_type(elements)
    absent: list[str] = []
    records = [_record(el, window, action_type, absent) for el in elements]
    if elements:
        if action_type is None:
            notes.append(
                f"{PLATFORM}: conversions and revenue are 0 because no purchase action "
                f"({', '.join(PURCHASE_ACTION_TYPES)}) was reported"
            )
        else:
            notes.append(f"{PLATFORM}: conversions and revenue from action_type {action_type}")
    if absent:
        notes.append(f"{PLATFORM}: inline_link_clicks absent on {len(absent)} rows, read as 0")
    unlabelled = sum(not el.get("attribution_setting") for el in elements)
    if unlabelled:
        notes.append(
            f"{PLATFORM}: attribution_setting absent on {unlabelled} rows; their window label "
            f"is the registry default, not confirmed by the API (F2 §2 UNKNOWN)"
        )
    return Fetched(
        timezone=tz,
        currency=info.get("currency"),
        records=records,
        n_elements=len(elements),
        notes=notes,
        attribution_windows=sorted({el.get("attribution_setting") or "" for el in elements}),
    )
