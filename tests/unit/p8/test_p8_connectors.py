"""P8 unit tests: record mode against mocked HTTP, then replay with sockets blocked.

UNIT FIXTURES, NOT RECORDINGS. Every response below is hand-built in the shape the facts packs
document (F2 Meta, F3 Google Ads, F4 LinkedIn, F5 GA4). Values and ids are invented. Real
recordings are captured by the integrator with record mode (data/recordings/README.md).
"""

from __future__ import annotations

import datetime as dt
import json
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from tests.acceptance.test_P8 import SECRET_KEYS, SECRET_PATTERNS

from bayesian_marketing import core as C
from bayesian_marketing.data_contract.connectors import http as H
from bayesian_marketing.data_contract.connectors.pull import pull

WINDOW = (dt.date(2026, 10, 1), dt.date(2026, 10, 2))
META_TOKEN = "EAA" + "b" * 40
GOOGLE_ACCESS = "ya29." + "c" * 40
GOOGLE_REFRESH = "1//" + "d" * 40
GOOGLE_SECRET = "GOCSPX-" + "e" * 20
LINKEDIN_TOKEN = "AQ" + "f" * 80
CONFIG = C.ClientConfig(
    client_id="unit_client",
    timezone="Europe/London",
    currency="USD",
    accounts={
        "meta": "act_111",
        "google_ads": "123-456-7890",
        "linkedin": "555",
        "ga4": "399",
    },
)

Handler = Callable[[httpx.Request], httpx.Response]
REAL_CLIENT = httpx.Client


def _json(body: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body, headers={"x-app-usage": '{"call_count":1}'})


@pytest.fixture
def creds(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in (H.REPLAY_ENV, H.RECORD_ENV, "GOOGLE_ADS_DEVELOPER_TOKEN", "GA4_PROPERTY_ID"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", raising=False)
    monkeypatch.setenv("META_ACCESS_TOKEN", META_TOKEN)
    monkeypatch.setenv("GOOGLE_ADS_CLIENT_ID", "1234-unit.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_ADS_CLIENT_SECRET", GOOGLE_SECRET)
    monkeypatch.setenv("GOOGLE_ADS_REFRESH_TOKEN", GOOGLE_REFRESH)
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", LINKEDIN_TOKEN)
    monkeypatch.setattr(H, "BACKOFF_BASE_S", 0.0)


def _mock(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> list[httpx.Request]:
    seen: list[httpx.Request] = []
    real = REAL_CLIENT

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(
        H.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(wrapped), **kw)
    )
    return seen


def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access during replay")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def _record(
    monkeypatch: pytest.MonkeyPatch, tmp: Path, platform: str, handler: Handler
) -> tuple[C.PlatformPull, list[httpx.Request]]:
    seen = _mock(monkeypatch, handler)
    monkeypatch.setenv(H.RECORD_ENV, str(tmp))
    p = pull(platform, CONFIG, WINDOW)
    monkeypatch.delenv(H.RECORD_ENV)
    return p, seen


def _replay(monkeypatch: pytest.MonkeyPatch, d: Path, platform: str) -> C.PlatformPull:
    """The frozen test's replay, against a unit-fixture recording directory."""
    _block_network(monkeypatch)
    for k in ("META_ACCESS_TOKEN", "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("LINKEDIN_ACCESS_TOKEN", raising=False)
    req = json.loads((d / "request.json").read_text())
    config = C.ClientConfig.model_validate(req["config"])
    window = tuple(dt.date.fromisoformat(x) for x in req["window"])
    monkeypatch.setenv(H.REPLAY_ENV, str(d))
    p = pull(platform, config, window)
    assert p.platform == platform
    assert p.pull_id.startswith(f"pull_{platform}_")
    assert p.window == window
    assert p.account_id == config.accounts[platform]
    assert p.timezone
    return p


def _assert_parses(monkeypatch: pytest.MonkeyPatch, d: Path, platform: str) -> C.PlatformPull:
    p = _replay(monkeypatch, d, platform)
    assert p.rows and p.empty_account is False
    kind = C.SiteRow if platform == "ga4" else C.PerformanceRow
    assert all(isinstance(r, kind) for r in p.rows)
    if kind is C.PerformanceRow:
        assert all(r.attribution_window for r in p.rows)
        assert all(p.window[0] <= r.date <= p.window[1] for r in p.rows)
    again = _replay(monkeypatch, d, platform)
    assert again.pull_id != p.pull_id
    assert [r.model_dump() for r in again.rows] == [r.model_dump() for r in p.rows]
    return p


def _assert_no_secrets(d: Path) -> None:
    leaks = []
    for f in d.rglob("*"):
        text = f.read_text()
        for secret in (META_TOKEN, GOOGLE_ACCESS, GOOGLE_REFRESH, GOOGLE_SECRET, LINKEDIN_TOKEN):
            if secret in text:
                leaks.append(f"{f.name}: literal credential")
        leaks += [f"{f.name}: {p.pattern}" for p in SECRET_PATTERNS if p.search(text)]
        for m in SECRET_KEYS.finditer(text):
            if m.group(2).strip().upper() not in ("REDACTED", "<REDACTED>", "***", "NULL", ""):
                leaks.append(f"{f.name}: {m.group(1)} not redacted")
    assert not leaks, leaks


# --------------------------------------------------------------------------- Meta (F2)


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
    rows: list[dict[str, Any]], *, fail_first: dict[str, Any] | None = None
) -> Handler:
    state = {"failed": False}

    def handle(req: httpx.Request) -> httpx.Response:
        url = urlsplit(str(req.url))
        q = parse_qs(url.query)
        assert q["access_token"] == [META_TOKEN]
        if url.path == "/v26.0/act_111":
            assert q["fields"] == ["timezone_name,currency"]
            return _json({"timezone_name": "America/Los_Angeles", "currency": "USD"})
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


def test_meta_record_then_replay(
    creds: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    live, seen = _record(monkeypatch, tmp_path, "meta", meta_handler(META_ROWS))
    assert len(seen) == 4  # account, insights, empty page with next, last page
    assert live.timezone == "America/Los_Angeles"
    assert len(live.rows) == 3 and live.quarantined == []
    _assert_no_secrets(tmp_path)
    p = _assert_parses(monkeypatch, tmp_path, "meta")
    assert [r.model_dump() for r in p.rows] == [r.model_dump() for r in live.rows]
    a2 = next(r for r in p.rows if r.entity_ids["ad"] == "a2")
    assert a2.conversions_reported == 0.0 and a2.revenue_reported.amount == 0
    a1 = next(r for r in p.rows if r.entity_ids["ad"] == "a1")
    assert a1.spend == C.Money(amount="25.50", currency="USD")
    assert a1.conversions_reported == 3.0 and a1.conversions_observed is None  # may be modeled
    assert a1.attribution_window == "7d_click_1d_view"
    assert a1.entity_ids == {"account": "111", "campaign": "c1", "ad_set": "s1", "ad": "a1"}
    assert p.partial_truth is True


def test_meta_empty_account(creds: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _record(monkeypatch, tmp_path, "meta", meta_handler([]))
    p = _replay(monkeypatch, tmp_path, "meta")
    assert p.rows == [] and p.empty_account is True and p.quarantined == []


def test_meta_retry_is_recorded_and_replayed(
    creds: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    err = {"message": "User request limit reached", "code": 17, "error_subcode": 2446079}
    live, seen = _record(monkeypatch, tmp_path, "meta", meta_handler(META_ROWS, fail_first=err))
    assert len(seen) == 5
    assert len(live.rows) == 3
    assert len(_assert_parses(monkeypatch, tmp_path, "meta").rows) == 3


def test_meta_bad_token_not_retried(
    creds: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    err = {"message": "Error validating access token", "type": "OAuthException", "code": 190}
    seen = _mock(monkeypatch, meta_handler(META_ROWS, fail_first=err))
    with pytest.raises(H.ConnectorError, match="code 190") as e:
        pull("meta", CONFIG, WINDOW)
    assert META_TOKEN not in str(e.value)
    assert len(seen) == 2


def test_meta_too_much_data_splits_window(
    creds: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    err = {"message": "Please reduce the amount of data", "code": 100, "error_subcode": 1487534}
    calls: list[dict[str, Any]] = []

    def handle(req: httpx.Request) -> httpx.Response:
        q = parse_qs(urlsplit(str(req.url)).query)
        if "time_range" not in q:
            return _json({"timezone_name": "UTC", "currency": "USD"})
        tr = json.loads(q["time_range"][0])
        calls.append(tr)
        if tr["since"] != tr["until"]:
            return _json({"error": err}, 400)
        return _json({"data": [r for r in META_ROWS if r["date_start"] == tr["since"]]})

    _mock(monkeypatch, handle)
    p = pull("meta", CONFIG, WINDOW)
    assert len(p.rows) == 3
    assert [c["since"] for c in calls] == ["2026-10-01", "2026-10-01", "2026-10-02"]


def test_meta_quarantine_keeps_api_element(
    creds: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bad = _meta_row("a3", "2026-10-01", inline_link_clicks="5000")
    agg = _meta_row("a4", "2026-10-01", date_stop="2026-10-02")

    def handle(req: httpx.Request) -> httpx.Response:
        if "time_range" not in str(req.url):
            return _json({"timezone_name": "UTC", "currency": "USD"})
        return _json({"data": [META_ROWS[0], bad, agg]})

    _mock(monkeypatch, handle)
    p = pull("meta", CONFIG, WINDOW)
    assert len(p.rows) == 1 and p.empty_account is False
    by_ad = {q.raw["ad_id"]: q.reasons for q in p.quarantined}
    assert any("clicks above impressions" in r for r in by_ad["a3"])
    assert any("non-daily aggregate" in r for r in by_ad["a4"])


# --------------------------------------------------------------------------- Google Ads (F3)


def google_token(req: httpx.Request) -> httpx.Response | None:
    if str(req.url) != "https://www.googleapis.com/oauth2/v3/token":
        return None
    form = parse_qs(req.content.decode())
    assert form["grant_type"] == ["refresh_token"]
    assert form["refresh_token"] == [GOOGLE_REFRESH]
    assert form["client_secret"] == [GOOGLE_SECRET]
    return _json({"access_token": GOOGLE_ACCESS, "expires_in": 3599, "token_type": "Bearer"})


def _gads_row(ad: str, day: str, cost: str, conv: float) -> dict[str, Any]:
    return {
        "customer": {"resourceName": "customers/1234567890", "id": "1234567890"},
        "campaign": {"resourceName": "customers/1234567890/campaigns/9", "id": "9"},
        "adGroup": {"resourceName": "customers/1234567890/adGroups/8", "id": "8"},
        "adGroupAd": {"ad": {"id": ad}},
        "segments": {"date": day},
        "metrics": {
            "impressions": "2000",
            "clicks": "50",
            "costMicros": cost,
            "conversions": conv,
            "conversionsValue": 120.5,
        },
    }


def gads_handler(req: httpx.Request) -> httpx.Response:
    tok = google_token(req)
    if tok is not None:
        return tok
    assert str(req.url) == (
        "https://googleads.googleapis.com/v26/customers/1234567890/googleAds:search"
    )
    assert req.headers["authorization"] == f"Bearer {GOOGLE_ACCESS}"
    body = json.loads(req.content)
    if "FROM customer" in body["query"]:
        return _json(
            {"results": [{"customer": {"currencyCode": "EUR", "timeZone": "Europe/Berlin"}}]}
        )
    assert "FROM ad_group_ad" in body["query"]
    assert "segments.date BETWEEN '2026-10-01' AND '2026-10-02'" in body["query"]
    if "pageToken" not in body:
        return _json(
            {"results": [_gads_row("71", "2026-10-01", "1500000", 1.5)], "nextPageToken": "P2"}
        )
    assert body["pageToken"] == "P2"
    row = _gads_row("71", "2026-10-02", "2000000", 2.0)
    del row["metrics"]["clicks"]  # proto3 JSON drops zero values
    del row["metrics"]["conversions"]
    return _json({"results": [row], "fieldMask": "x"})


def test_google_ads_record_then_replay(
    creds: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    live, seen = _record(monkeypatch, tmp_path, "google_ads", gads_handler)
    assert all("developer-token" not in r.headers for r in seen)  # D21
    assert all("login-customer-id" not in r.headers for r in seen)
    _assert_no_secrets(tmp_path)
    p = _assert_parses(monkeypatch, tmp_path, "google_ads")
    assert p.timezone == "Europe/Berlin"
    assert [r.model_dump() for r in p.rows] == [r.model_dump() for r in live.rows]
    d1, d2 = sorted(p.rows, key=lambda r: r.date)
    assert d1.spend == C.Money(amount="1.5", currency="EUR")
    assert d1.conversions_reported == 1.5 and d1.conversions_observed is None
    assert d1.attribution_window == "per_conversion_action"
    assert d2.clicks == 0 and d2.conversions_reported == 0.0
    assert d1.entity_ids == {"account": "1234567890", "campaign": "9", "ad_set": "8", "ad": "71"}


def test_google_ads_optional_headers_sent_when_set(
    creds: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOOGLE_ADS_DEVELOPER_TOKEN", "devtok-unit-000000")
    monkeypatch.setenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "999-888-7777")
    seen = _mock(monkeypatch, gads_handler)
    pull("google_ads", CONFIG, WINDOW)
    search = [r for r in seen if "googleAds:search" in str(r.url)]
    assert all(r.headers["login-customer-id"] == "9998887777" for r in search)
    assert all(r.headers["developer-token"] == "devtok-unit-000000" for r in search)


def test_google_ads_quota_error_retried(creds: None, monkeypatch: pytest.MonkeyPatch) -> None:
    failure = {
        "error": {
            "code": 429,
            "message": "Resource has been exhausted",
            "status": "RESOURCE_EXHAUSTED",
            "details": [
                {
                    "@type": "type.googleapis.com/google.ads.googleads.v26.errors.GoogleAdsFailure",
                    "errors": [{"errorCode": {"quotaError": "RESOURCE_EXHAUSTED"}, "message": "x"}],
                }
            ],
        }
    }
    state = {"n": 0}

    def handle(req: httpx.Request) -> httpx.Response:
        if "googleAds:search" in str(req.url) and state["n"] == 0:
            state["n"] += 1
            return _json(failure, 429)
        return gads_handler(req)

    _mock(monkeypatch, handle)
    assert len(pull("google_ads", CONFIG, WINDOW).rows) == 2


# --------------------------------------------------------------------------- LinkedIn (F4)


def _li_el(creative: str, day: int, cost: str) -> dict[str, Any]:
    d = {"year": 2026, "month": 10, "day": day}
    return {
        "impressions": 5000,
        "clicks": 30,
        "costInLocalCurrency": cost,
        "externalWebsiteConversions": 2,
        "conversionValueInLocalCurrency": "150.0",
        "dateRange": {"start": d, "end": d},
        "pivotValues": [
            "urn:li:sponsoredCampaignGroup:70",
            "urn:li:sponsoredCampaign:71",
            f"urn:li:sponsoredCreative:{creative}",
        ],
    }


def linkedin_handler(req: httpx.Request) -> httpx.Response:
    assert req.headers["authorization"] == f"Bearer {LINKEDIN_TOKEN}"
    assert req.headers["linkedin-version"] == "202610"
    assert req.headers["x-restli-protocol-version"] == "2.0.0"
    url = str(req.url)
    if url == "https://api.linkedin.com/rest/adAccounts/555":
        return _json({"id": 555, "currency": "GBP", "status": "ACTIVE", "test": False})
    assert url.startswith("https://api.linkedin.com/rest/adAnalytics?q=statistics")
    assert "pivots=List(CAMPAIGN_GROUP,CAMPAIGN,CREATIVE)" in url
    assert "dateRange=(start:(year:2026,month:10,day:1),end:(year:2026,month:10,day:2))" in url
    assert "accounts=List(urn%3Ali%3AsponsoredAccount%3A555)" in url
    els = [_li_el("900", 1, "19.91833"), _li_el("900", 2, "20.5")]
    return _json({"elements": els, "paging": {"count": 10, "links": [], "start": 0}})


def test_linkedin_record_then_replay(
    creds: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    live, _ = _record(monkeypatch, tmp_path, "linkedin", linkedin_handler)
    _assert_no_secrets(tmp_path)
    p = _assert_parses(monkeypatch, tmp_path, "linkedin")
    assert p.timezone == "UTC"
    assert [r.model_dump() for r in p.rows] == [r.model_dump() for r in live.rows]
    r = min(p.rows, key=lambda r: r.date)
    assert r.entity_ids == {"account": "555", "campaign": "70", "ad_set": "71", "ad": "900"}
    assert r.spend == C.Money(amount="19.91833", currency="GBP")
    assert r.attribution_window == "90d_click_90d_view"


# --------------------------------------------------------------------------- GA4 (F5)


def ga4_handler(req: httpx.Request) -> httpx.Response:
    tok = google_token(req)
    if tok is not None:
        return tok
    assert str(req.url) == "https://analyticsdata.googleapis.com/v1beta/properties/399:runReport"
    body = json.loads(req.content)
    assert body["currencyCode"] == "USD"
    rows = [
        ("20261001", "google", "cpc", "brand", "120", "4", "310.25"),
        ("20261001", "(direct)", "(none)", "(not set)", "80", "1", "40"),
        ("20261002", "google", "cpc", "brand", "100", "2", "99.5"),
    ]
    page = rows[int(body["offset"]) :][: int(body["limit"])]
    return _json(
        {
            "dimensionHeaders": [{"name": d["name"]} for d in body["dimensions"]],
            "metricHeaders": [{"name": m["name"], "type": "TYPE_INTEGER"} for m in body["metrics"]],
            "rows": [
                {
                    "dimensionValues": [{"value": v} for v in r[:4]],
                    "metricValues": [{"value": v} for v in r[4:]],
                }
                for r in page
            ],
            "rowCount": len(rows),
            "kind": "analyticsData#runReport",
        }
    )


def test_ga4_record_then_replay_with_paging(
    creds: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from bayesian_marketing.data_contract.connectors import ga4

    monkeypatch.setattr(ga4, "PAGE_LIMIT", 2)
    live, seen = _record(monkeypatch, tmp_path, "ga4", ga4_handler)
    assert len(seen) == 3  # token, two pages
    _assert_no_secrets(tmp_path)
    p = _assert_parses(monkeypatch, tmp_path, "ga4")
    assert [r.model_dump() for r in p.rows] == [r.model_dump() for r in live.rows]
    first = p.rows[0]
    assert first.date == dt.date(2026, 10, 1)
    assert first.utm == {"source": "google", "medium": "cpc", "campaign": "brand"}
    assert first.revenue == C.Money(amount="310.25", currency="USD")
    assert p.timezone == "Europe/London" and p.notes


# --------------------------------------------------------------------------- modes


def test_replay_miss_and_no_exchanges(
    creds: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _record(monkeypatch, tmp_path, "meta", meta_handler(META_ROWS))
    _block_network(monkeypatch)
    monkeypatch.setenv(H.REPLAY_ENV, str(tmp_path))
    with pytest.raises(H.ReplayMiss):
        pull("meta", CONFIG, (dt.date(2026, 9, 1), dt.date(2026, 9, 2)))
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv(H.REPLAY_ENV, str(empty))
    with pytest.raises(H.ReplayMiss):
        pull("meta", CONFIG, WINDOW)


def test_live_without_credential_fails_before_network(
    creds: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _block_network(monkeypatch)
    monkeypatch.delenv("LINKEDIN_ACCESS_TOKEN")
    with pytest.raises(H.MissingCredential, match="LINKEDIN_ACCESS_TOKEN"):
        pull("linkedin", CONFIG, WINDOW)


def test_record_and_replay_together_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(H.REPLAY_ENV, str(tmp_path))
    monkeypatch.setenv(H.RECORD_ENV, str(tmp_path))
    with pytest.raises(H.ConnectorError, match="only one"):
        pull("meta", CONFIG, WINDOW)


def test_redaction_rules() -> None:
    url = f"https://graph.facebook.com/v26.0/x?access_token={META_TOKEN}&after=C"
    assert META_TOKEN not in H.redact_url(url)
    assert "after=C" in H.redact_url(url)
    obj = {"error": {"code": 190, "message": "bad"}, "access_token": "abc", "n": [GOOGLE_ACCESS]}
    out = H.redact_obj(obj)
    assert out["error"] == {"code": 190, "message": "bad"}
    assert out["access_token"] == "REDACTED" and out["n"] == ["REDACTED"]
    assert H.redact_headers({"Authorization": "Bearer x", "Linkedin-Version": "202610"}) == {
        "Authorization": "REDACTED",
        "Linkedin-Version": "202610",
    }


# --------------------------------------------------------------------------- review fixes


def _meta_simple(rows: list[dict[str, Any]], *, next_url: str | None = None) -> Handler:
    def handle(req: httpx.Request) -> httpx.Response:
        if "time_range" not in str(req.url):
            return _json({"timezone_name": "UTC", "currency": "USD"})
        body: dict[str, Any] = {"data": rows}
        if next_url is not None:
            body["paging"] = {"next": next_url}
        return _json(body)

    return handle


def test_fix2_ga4_timezone_and_currency_from_metadata(
    creds: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handle(req: httpx.Request) -> httpx.Response:
        tok = google_token(req)
        if tok is not None:
            return tok
        return _json(
            {
                "metadata": {"currencyCode": "JPY", "timeZone": "Asia/Tokyo"},
                "rows": [
                    {
                        "dimensionValues": [{"value": v} for v in ("20261001", "g", "cpc", "b")],
                        "metricValues": [{"value": v} for v in ("10", "1", "1234.5000000001")],
                    }
                ],
                "rowCount": 1,
            }
        )

    _mock(monkeypatch, handle)
    p = pull("ga4", CONFIG, WINDOW)
    assert p.timezone == "Asia/Tokyo"
    assert p.rows[0].revenue == C.Money(amount="1235", currency="JPY")
    assert any("timezone Asia/Tokyo differs" in n for n in p.notes)
    assert any("currency JPY differs" in n for n in p.notes)


def test_fix13_revenue_rounded_to_minor_units() -> None:
    from bayesian_marketing.data_contract.connectors.base import to_minor_units

    assert to_minor_units("310.25000000000006", "USD") == "310.25"
    assert to_minor_units("0.1", "KWD") == "0.100"
    assert to_minor_units("12.5", "JPY") == "13"
    assert to_minor_units("1.23456", "XXX") == "1.23456"
    assert to_minor_units("abc", "USD") == "abc"


def test_fix3_meta_absent_clicks_read_as_zero(creds: None, monkeypatch: pytest.MonkeyPatch) -> None:
    row = _meta_row("a5", "2026-10-01", actions=None, action_values=None)
    del row["inline_link_clicks"]
    _mock(monkeypatch, _meta_simple([row]))
    p = pull("meta", CONFIG, WINDOW)
    assert p.rows[0].clicks == 0
    assert any("inline_link_clicks absent on 1 rows, read as 0" in n for n in p.notes)


def test_fix4_meta_one_purchase_type_no_double_count(
    creds: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    acts = [
        {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "3"},
        {"action_type": "omni_purchase", "value": "4"},
        {"action_type": "purchase", "value": "4"},
    ]
    vals = [{"action_type": "omni_purchase", "value": "120"}]
    first = _meta_row("a1", "2026-10-01", actions=acts, action_values=vals)
    other = _meta_row("a2", "2026-10-01")  # pixel only: omni absent on this row reads 0
    _mock(monkeypatch, _meta_simple([first, other]))
    p = pull("meta", CONFIG, WINDOW)
    by_ad = {r.entity_ids["ad"]: r for r in p.rows}
    assert by_ad["a1"].conversions_reported == 4.0
    assert by_ad["a1"].revenue_reported.amount == 120
    assert by_ad["a2"].conversions_reported == 0.0
    assert "meta: conversions and revenue from action_type omni_purchase" in p.notes


def test_fix4_meta_no_purchase_type_noted(creds: None, monkeypatch: pytest.MonkeyPatch) -> None:
    row = _meta_row("a1", "2026-10-01", actions=[{"action_type": "link_click", "value": "4"}])
    row["action_values"] = None
    _mock(monkeypatch, _meta_simple([row]))
    p = pull("meta", CONFIG, WINDOW)
    assert p.rows[0].conversions_reported == 0.0
    assert any("are 0 because no purchase action" in n for n in p.notes)


def test_fix5_meta_missing_attribution_setting_noted(
    creds: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _meta_row("a1", "2026-10-01")
    del row["attribution_setting"]
    _mock(monkeypatch, _meta_simple([row]))
    p = pull("meta", CONFIG, WINDOW)
    assert p.rows[0].attribution_window == "7d_click_1d_view"  # registry default
    assert any("not confirmed by the API" in n for n in p.notes)
    _mock(monkeypatch, _meta_simple([_meta_row("a1", "2026-10-01")]))
    assert not any("not confirmed" in n for n in pull("meta", CONFIG, WINDOW).notes)


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_fix6_meta_bare_http_errors_retried(
    creds: None, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    state = {"n": 0}
    ok = _meta_simple([_meta_row("a1", "2026-10-01")])

    def handle(req: httpx.Request) -> httpx.Response:
        if "time_range" in str(req.url) and state["n"] == 0:
            state["n"] += 1
            return httpx.Response(status, text="upstream error")
        return ok(req)

    _mock(monkeypatch, handle)
    assert len(pull("meta", CONFIG, WINDOW).rows) == 1


def test_fix6_meta_retry_cap_fails_loudly(creds: None, monkeypatch: pytest.MonkeyPatch) -> None:
    def handle(req: httpx.Request) -> httpx.Response:
        if "time_range" in str(req.url):
            return httpx.Response(503, text="unavailable")
        return _json({"timezone_name": "UTC", "currency": "USD"})

    seen = _mock(monkeypatch, handle)
    with pytest.raises(H.ConnectorError, match="503"):
        pull("meta", CONFIG, WINDOW)
    assert len(seen) == 1 + H.MAX_ATTEMPTS


@pytest.mark.parametrize("status", [500, 503])
def test_fix7_google_ads_server_errors_retried(
    creds: None, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    state = {"n": 0}

    def handle(req: httpx.Request) -> httpx.Response:
        if "googleAds:search" in str(req.url) and state["n"] == 0:
            state["n"] += 1
            return _json({"error": {"code": status, "message": "backend"}}, status)
        return gads_handler(req)

    _mock(monkeypatch, handle)
    assert len(pull("google_ads", CONFIG, WINDOW).rows) == 2


def test_fix7_google_ads_401_refreshes_token_once(
    creds: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = {"tokens": 0, "n401": 0}

    def handle(req: httpx.Request) -> httpx.Response:
        tok = google_token(req)
        if tok is not None:
            state["tokens"] += 1
            return tok
        if "FROM ad_group_ad" in req.content.decode() and state["n401"] == 0:
            state["n401"] += 1
            return _json({"error": {"code": 401, "status": "UNAUTHENTICATED"}}, 401)
        return gads_handler(req)

    _mock(monkeypatch, handle)
    assert len(pull("google_ads", CONFIG, WINDOW).rows) == 2
    assert state["tokens"] == 2


def test_fix7_google_ads_second_401_fails(creds: None, monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"tokens": 0}

    def handle(req: httpx.Request) -> httpx.Response:
        tok = google_token(req)
        if tok is not None:
            state["tokens"] += 1
            return tok
        return _json({"error": {"code": 401, "status": "UNAUTHENTICATED"}}, 401)

    _mock(monkeypatch, handle)
    with pytest.raises(H.ConnectorError, match="401"):
        pull("google_ads", CONFIG, WINDOW)
    assert state["tokens"] == 2


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/v26.0/act_111/insights?after=X",
        "http://graph.facebook.com/v26.0/act_111/insights?after=X",
        "https://graph.facebook.com.evil.example/v26.0/x",
    ],
)
def test_fix8_meta_paging_next_off_host_raises(
    creds: None, monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    seen = _mock(monkeypatch, _meta_simple([_meta_row("a1", "2026-10-01")], next_url=url))
    with pytest.raises(H.ConnectorError, match=r"paging\.next"):
        pull("meta", CONFIG, WINDOW)
    assert all(r.url.host == "graph.facebook.com" for r in seen)


def test_fix10_linkedin_utc_note(creds: None, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock(monkeypatch, linkedin_handler)
    p = pull("linkedin", CONFIG, WINDOW)
    assert any("UTC" in n and "Campaign Manager" in n for n in p.notes)


def test_fix11_failed_record_keeps_existing_recording(
    creds: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "meta"
    _record(monkeypatch, target, "meta", meta_handler(META_ROWS))
    before = {f.name: f.read_text() for f in target.iterdir()}

    def broken(req: httpx.Request) -> httpx.Response:
        return _json({"error": {"code": 190, "message": "expired"}}, 400)

    _mock(monkeypatch, broken)
    monkeypatch.setenv(H.RECORD_ENV, str(target))
    with pytest.raises(H.ConnectorError):
        pull("meta", CONFIG, WINDOW)
    assert {f.name: f.read_text() for f in target.iterdir()} == before
    assert [p.name for p in tmp_path.iterdir()] == ["meta"]  # no staging left behind


def test_fix11_successful_record_replaces_target(
    creds: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "meta"
    target.mkdir()
    (target / "exchange_0099.json").write_text("{}")
    _record(monkeypatch, target, "meta", meta_handler(META_ROWS))
    names = sorted(f.name for f in target.iterdir())
    assert "exchange_0099.json" not in names and "request.json" in names
    assert [p.name for p in tmp_path.iterdir()] == ["meta"]
    assert len(_replay(monkeypatch, target, "meta").rows) == 3
