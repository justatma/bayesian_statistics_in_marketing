"""Meta Graph API fakes, moved from ``tests/unit/p8`` for the live view (spec v0.2 §5 L0, D43).

UNIT FIXTURES, NOT RECORDINGS. Hand-built in the shape F2 and F2b document; values invented.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from bayesian_marketing.data_contract.connectors import meta

Handler = Callable[[httpx.Request], httpx.Response]
META_TOKEN = "EAA" + "b" * 40
ACCOUNT: dict[str, Any] = {
    "timezone_name": "America/Los_Angeles",
    "currency": "USD",
    "name": "Unit Account",
    "account_status": 1,
    "spend_cap": "150000",
    "amount_spent": "12345",
    "id": "act_111",
}


def _json(body: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body, headers={"x-app-usage": '{"call_count":1}'})


def _meta_row(ad: str, day: str, **kw: Any) -> dict[str, Any]:
    row = {
        "date_start": day,
        "date_stop": day,
        "account_id": "111",
        "campaign_id": "c1",
        "adset_id": "s1",
        "ad_id": ad,
        "impressions": "1000",
        "inline_link_clicks": "40",
        "spend": "25.50",
        "account_currency": "USD",
        "actions": [
            {"action_type": "link_click", "value": "40"},
            {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "3"},
        ],
        "action_values": [{"action_type": "offsite_conversion.fb_pixel_purchase", "value": "90"}],
        "attribution_setting": "7d_click_1d_view",
    }
    row.update(kw)
    return row


def meta_handler(
    rows: list[dict[str, Any]],
    *,
    fail_first: dict[str, Any] | None = None,
    account: dict[str, Any] | None = None,
) -> Handler:
    """A Graph API stand-in: the account node, then insights paged in three calls (F2 §5).
    ``account`` is the account node's body (default ``ACCOUNT``)."""
    account = dict(ACCOUNT if account is None else account)
    state = {"failed": False}

    def handle(req: httpx.Request) -> httpx.Response:
        url = urlsplit(str(req.url))
        q = parse_qs(url.query)
        assert q["access_token"] == [META_TOKEN]
        if url.path == "/v26.0/act_111":
            assert q["fields"] == [",".join(meta.ACCOUNT_FIELDS)]
            return _json(account)
        assert url.path == "/v26.0/act_111/insights"
        if fail_first is not None and not state["failed"]:
            state["failed"] = True
            return _json({"error": fail_first}, 400)
        tr = json.loads(q["time_range"][0]) if "time_range" in q else None
        if "after" not in q:
            assert q["level"] == ["ad"] and q["time_increment"] == ["1"]
            page = [r for r in rows if tr["since"] <= r["date_start"] <= tr["until"]]
            if not page:
                return _json({"data": []})
            nxt = f"https://graph.facebook.com/v26.0/act_111/insights?access_token={META_TOKEN}"
            nxt += f"&after=CUR1&since={tr['since']}"
            return _json({"data": page[:1], "paging": {"cursors": {"after": "CUR1"}, "next": nxt}})
        since = q["since"][0]
        page = [r for r in rows if r["date_start"] >= since][1:]
        if q["after"] == ["CUR1"]:  # an empty page that still carries next (F2 §5)
            nxt = f"https://graph.facebook.com/v26.0/act_111/insights?access_token={META_TOKEN}"
            return _json({"data": [], "paging": {"next": nxt + f"&after=CUR2&since={since}"}})
        return _json({"data": page, "paging": {"cursors": {"before": "CUR2"}}})

    return handle


META_ROWS = [
    _meta_row("a1", "2026-10-01"),
    _meta_row("a2", "2026-10-01", actions=None, action_values=None),
    _meta_row("a1", "2026-10-02"),
]
