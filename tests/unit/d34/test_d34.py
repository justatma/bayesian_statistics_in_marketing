"""D34: names and objective, conversion semantics, GA4 quality notes."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from tests.fakes import builders as B
from tests.unit.p8.test_p8_connectors import (
    CONFIG,
    _json,
    _mock,
    gads_handler,
    google_token,
)

from bayesian_marketing import core as C
from bayesian_marketing.channels.model import load_channel_model
from bayesian_marketing.core import registries
from bayesian_marketing.data_contract.connectors import ga4, google_ads, linkedin
from bayesian_marketing.data_contract.connectors.base import PERF_TARGETS, Record
from bayesian_marketing.data_contract.connectors.pull import _table, pull
from bayesian_marketing.data_contract.readers.read import (
    _performance,
    may_exceed_clicks,
    read_export,
)
from bayesian_marketing.data_contract.readers.rows import Context
from bayesian_marketing.derived_metrics import derive as derive_mod
from bayesian_marketing.derived_metrics.derive import derive
from bayesian_marketing.inference.conjugate import fit_conjugate

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "exports"
WINDOW = (dt.date(2026, 10, 1), dt.date(2026, 10, 7))


@pytest.fixture(autouse=True)
def _iso(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BAYES_DATA_DIR", str(tmp_path / "store"))
    registries.clear_cache()


def _read(platform: str, path: Path) -> C.PlatformPull:
    f = C.ManifestFile(
        path=path.name,
        platform=platform,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        export_kind="export",
    )
    return read_export(platform, path, B.manifest([f]))


def _write(tmp_path: Path, name: str, lines: list[str]) -> Path:
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n")
    return path


# --- 1 names and objective ---------------------------------------------------------------------
def test_reader_fills_names_and_objective(tmp_path: Path) -> None:
    lines = (FIX / "meta_canonical.csv").read_text().splitlines()
    out = [lines[0] + ",Result indicator", *[ln + ",actions:purchase" for ln in lines[1:]]]
    pull = _read("meta", _write(tmp_path, "meta.csv", out))
    a = next(r for r in pull.rows if r.entity_ids["ad"] == "ad_a")
    assert a.entity_names == {
        "account": "North Pier",
        "campaign": "Launch",
        "ad_set": "Broad",
        "ad": "Ad A",
    }
    assert a.objective == "actions:purchase"
    assert "ad_name" not in a.entity_ids and set(a.entity_ids) == set(a.entity_names)


def test_reader_without_objective_column_leaves_none() -> None:
    pull = _read("meta", FIX / "meta_canonical.csv")
    assert pull.rows and all(r.objective is None for r in pull.rows)


def test_google_ads_record_names() -> None:
    r = {
        "customer": {"id": "1", "descriptiveName": "Shop"},
        "campaign": {"id": "2", "name": "Brand"},
        "adGroup": {"id": "3", "name": "Exact"},
        "adGroupAd": {"ad": {"id": "4", "name": " "}},
        "segments": {"date": "2026-10-01"},
        "metrics": {"impressions": "10", "clicks": "1", "costMicros": "1000000"},
    }
    rec = google_ads._record(r, WINDOW, r)
    assert rec.values["entity_ids.account_name"] == "Shop"
    assert rec.values["entity_ids.campaign_name"] == "Brand"
    assert rec.values["entity_ids.ad_set_name"] == "Exact"
    assert rec.values["entity_ids.ad_name"] is None  # blank name is no name
    assert google_ads._record(r, WINDOW).values["entity_ids.campaign_name"] is None


def test_google_ads_main_query_has_only_verified_name_field() -> None:
    assert "ad_group_ad.ad.name" in google_ads.AD_FIELDS
    assert not set(google_ads.NAME_FIELDS) & set(google_ads.AD_FIELDS)


def _names_handler(fail: bool):
    def handle(req: httpx.Request) -> httpx.Response:
        if google_token(req) is None:
            q = json.loads(req.content)["query"]
            if "campaign.name" in q:
                if fail:
                    return _json({"error": {"code": 400, "message": "unrecognized field"}}, 400)
                assert "segments.date BETWEEN '2026-10-01' AND '2026-10-02'" in q
                row = {"customer": {"descriptiveName": "Shop"}, "campaign": {"name": "Brand"},
                       "adGroup": {"name": "Exact"}, "adGroupAd": {"ad": {"id": "71"}}}  # fmt: skip
                return _json({"results": [row]})
        return gads_handler(req)

    return handle


def test_google_ads_names_query_fills_names(creds: None, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock(monkeypatch, _names_handler(fail=False))
    p = pull("google_ads", CONFIG, (dt.date(2026, 10, 1), dt.date(2026, 10, 2)))
    assert len(p.rows) == 2
    assert all(
        r.entity_names == {"account": "Shop", "campaign": "Brand", "ad_set": "Exact"}
        for r in p.rows
    )


def test_google_ads_names_query_failure_keeps_pull(
    creds: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock(monkeypatch, _names_handler(fail=True))
    p = pull("google_ads", CONFIG, (dt.date(2026, 10, 1), dt.date(2026, 10, 2)))
    assert len(p.rows) == 2 and all(r.entity_names == {} for r in p.rows)
    assert any("names not read" in n for n in p.notes)


def test_linkedin_record_account_name() -> None:
    el = {
        "dateRange": {"start": {"year": 2026, "month": 10, "day": 1},
                      "end": {"year": 2026, "month": 10, "day": 1}},
        "pivotValues": ["urn:li:sponsoredCampaignGroup:1", "urn:li:sponsoredCampaign:2",
                        "urn:li:sponsoredCreative:3"],
        "impressions": 10, "clicks": 1, "costInLocalCurrency": "1.00",
    }  # fmt: skip
    rec = linkedin._record(el, "9", WINDOW, "Acme")
    assert rec.values["entity_ids.account_name"] == "Acme"
    assert rec.values.get("entity_ids.ad_name") is None


def _api_rows(platform: str, values: list[dict[str, str | None]], *, modeled: bool = True):
    cm = load_channel_model(platform)
    if not modeled:
        cm = cm.model_copy(update={"conversion_field_may_be_modeled": False})
    recs = [Record(values=v, source=dict(v)) for v in values]
    table = _table(PERF_TARGETS, recs)
    ctx = Context(
        table=table,
        fallback_currency="USD",
        attribution_window="7d_click_1d_view",
        conversions_may_exceed_clicks=may_exceed_clicks(platform),
    )
    notes: list[str] = []
    rows, q = _performance(platform, table, ctx, cm, notes)
    return rows, q, notes


def _row(ad: str, clicks: str, conv: str, **kw: str | None) -> dict[str, str | None]:
    return {
        "date": "2026-10-01",
        "entity_ids.ad": ad,
        "impressions": "1000",
        "clicks": clicks,
        "spend": "10.00",
        "conversions_reported": conv,
        **kw,
    }


def test_connector_table_carries_names_and_objective() -> None:
    rows, q, _ = _api_rows(
        "meta", [_row("a1", "5", "1", **{"entity_ids.ad_name": "Hero", "objective": "SALES"})]
    )
    assert q == [] and rows[0].entity_names == {"ad": "Hero"} and rows[0].objective == "SALES"


# --- 2 conversion semantics --------------------------------------------------------------------
@pytest.mark.parametrize("platform", ["meta", "linkedin"])
def test_reported_above_clicks_kept_with_note_under_any_window(platform: str) -> None:
    rows, q, notes = _api_rows(
        platform, [_row("a1", "2", "5", attribution_window="7d_click"), _row("a2", "5", "1")]
    )
    assert q == [] and len(rows) == 2
    assert any("reported conversions above clicks on 1 row;" in n for n in notes)
    rows, q, notes = _api_rows(platform, [_row("a1", "2", "5"), _row("a2", "1", "3")])
    assert any("on 2 rows;" in n for n in notes)


def test_reported_above_clicks_quarantined_on_google_ads() -> None:
    rows, q, notes = _api_rows("google_ads", [_row("a1", "2", "5.5"), _row("a2", "5", "1")])
    assert [r.entity_ids["ad"] for r in rows] == ["a2"]
    assert q[0].reasons == ["conversions above clicks (5.5 > 2)"]
    assert not any("above clicks" in n for n in notes)


def test_registry_flag_per_platform() -> None:
    assert may_exceed_clicks("meta") and may_exceed_clicks("linkedin")
    assert not may_exceed_clicks("google_ads")


def test_observed_above_clicks_quarantined() -> None:
    rows, q, _ = _api_rows("meta", [_row("a1", "2", "5"), _row("a2", "5", "1")], modeled=False)
    assert [r.entity_ids["ad"] for r in rows] == ["a2"]
    assert rows[0].conversions_observed == 1
    assert q[0].reasons == ["observed conversions above clicks (5 > 2)"]


def test_conjugate_reported_above_clicks_left_out_of_binomial() -> None:
    days = [dt.date(2026, 10, 1), dt.date(2026, 10, 2)]
    data = B.funnel_data(
        {"a": {"impressions": [1000, 1000], "clicks": [10, 2], "spend": [5.0, 5.0],
               "conv_rep": [3.0, 6.0]}},
        dates=days,
    )  # fmt: skip
    st = fit_conjugate(data, B.default_prior_set(), seed=1)
    p = st.posterior.params
    prior = B.default_prior_set().records["cvr"].params
    assert p["a.cvr.a"] == prior["a"] + 3.0  # day 2 (6 > 2 clicks) not in the binomial
    assert p["a.cvr.b"] == prior["b"] + 10.0 - 3.0
    assert p["a.n.conversions"] == 9.0  # both days count for CPA
    assert p["a.flag.reported_above_clicks"] == 1.0
    notices = derive_mod.NOTICE_REPORTED_ABOVE_CLICKS
    assert notices["cvr"] in derive("cvr", st, B.scope("a"), None).notices
    cpa = derive("cpa", st, B.scope("a"), None).notices
    assert notices["cpa"] in cpa and "counted in this cost per acquisition" in notices["cpa"]
    assert not any(n in derive("ctr", st, B.scope("a"), None).notices for n in notices.values())
    assert set(notices) == derive_mod.CONVERSION_BASED


def test_conjugate_only_above_days_gives_no_cvr_but_cpa() -> None:
    data = B.funnel_data({"a": {"impressions": 1000, "clicks": 2, "spend": 5.0, "conv_rep": 4.0}})
    st = fit_conjugate(data, B.default_prior_set(), seed=1)
    p = st.posterior.params
    assert "a.cvr.a" not in p and "a.cpa.a" in p


def test_conjugate_observed_above_clicks_still_raises() -> None:
    data = B.funnel_data({"a": {"impressions": 1000, "clicks": 2, "spend": 5.0, "conv_obs": 3}})
    with pytest.raises(ValueError, match="observed conversions 3 exceed clicks 2"):
        fit_conjugate(data, B.default_prior_set(), seed=1)


# --- 3 GA4 quality -----------------------------------------------------------------------------
def test_ga4_quality_notes() -> None:
    meta = {
        "samplingMetadatas": [{"samplesReadCount": "1000", "samplingSpaceSize": "50000"}],
        "subjectToThresholding": True,
        "dataLossFromOtherRow": True,
        "schemaRestrictionResponse": {
            "activeMetricRestrictions": [
                {"metricName": "purchaseRevenue", "restrictedMetricTypes": ["REVENUE_DATA"]}
            ]
        },
        "dataTruncationReasons": [
            {"dataTruncationDate": "2023-11-03", "dataTruncationType": "T"},
            {"dataTruncationDate": "2023-11-03", "dataTruncationType": "T"},
        ],
    }
    notes = ga4.quality_notes(meta)
    tagged = [n for n in notes if n.startswith(ga4.QUALITY_PREFIX)]
    assert len(tagged) == 2
    assert "1000 of 50000" in tagged[0] and "thresholded" in tagged[1]
    assert any('"(other)"' in n for n in notes)
    assert any("purchaseRevenue (REVENUE_DATA)" in n for n in notes)
    assert [n for n in notes if "truncated" in n] == ["ga4: data truncated: T before 2023-11-03"]


def test_ga4_clean_metadata_has_no_quality_notes() -> None:
    meta = {"subjectToThresholding": False, "dataLossFromOtherRow": False, "timeZone": "UTC"}
    assert ga4.quality_notes(meta) == []


def test_ga4_replay_reports_truncation(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = Path(__file__).resolve().parents[3] / "data" / "recordings" / "ga4"
    req = json.loads((rec / "request.json").read_text())
    config = C.ClientConfig.model_validate(req["config"])
    window = (dt.date.fromisoformat(req["window"][0]), dt.date.fromisoformat(req["window"][1]))
    monkeypatch.setenv("BAYES_REPLAY_DIR", str(rec))
    p = pull("ga4", config, window)
    assert any("data truncated" in n for n in p.notes)
    assert not any(n.startswith(ga4.QUALITY_PREFIX) for n in p.notes)


def test_ga4_quality_notes_from_every_page(creds: None, monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [
        {"timeZone": "UTC", "currencyCode": "USD"},
        {"subjectToThresholding": True},
        {"subjectToThresholding": True},
    ]
    state = {"n": 0}

    def handle(req: httpx.Request) -> httpx.Response:
        tok = google_token(req)
        if tok is not None:
            return tok
        i = state["n"]
        state["n"] += 1
        row = {"dimensionValues": [{"value": v} for v in ("20261001", "g", "cpc", f"c{i}")],
               "metricValues": [{"value": v} for v in ("10", "1", "5")]}  # fmt: skip
        return _json({"metadata": pages[i], "rows": [row], "rowCount": 3})

    monkeypatch.setattr(ga4, "PAGE_LIMIT", 1)
    _mock(monkeypatch, handle)
    p = pull("ga4", CONFIG, (dt.date(2026, 10, 1), dt.date(2026, 10, 2)))
    assert len(p.rows) == 3
    assert [n for n in p.notes if n.startswith(ga4.QUALITY_PREFIX)] == [
        "ga4_quality: thresholded; rows with small user counts may be withheld"
    ]
