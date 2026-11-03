"""D34: names and objective, conversion semantics, GA4 quality notes."""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

import pytest
from tests.fakes import builders as B

from bayesian_marketing import core as C
from bayesian_marketing.channels.model import load_channel_model
from bayesian_marketing.core import registries
from bayesian_marketing.data_contract.connectors import ga4, google_ads, linkedin
from bayesian_marketing.data_contract.connectors.base import PERF_TARGETS, Record
from bayesian_marketing.data_contract.connectors.pull import _table
from bayesian_marketing.data_contract.readers.read import _performance, read_export
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
    rec = google_ads._record(r, WINDOW)
    assert rec.values["entity_ids.account_name"] == "Shop"
    assert rec.values["entity_ids.campaign_name"] == "Brand"
    assert rec.values["entity_ids.ad_set_name"] == "Exact"
    assert rec.values["entity_ids.ad_name"] is None  # blank name is no name
    assert set(google_ads.FIELDS) >= {"campaign.name", "ad_group.name", "ad_group_ad.ad.name"}


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
    ctx = Context(table=table, fallback_currency="USD", attribution_window="7d_click_1d_view")
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
def test_reported_above_clicks_kept_with_note() -> None:
    rows, q, notes = _api_rows("meta", [_row("a1", "2", "5"), _row("a2", "5", "1")])
    assert q == [] and len(rows) == 2
    assert any("reported conversions above clicks on 1 rows" in n for n in notes)


def test_reported_above_clicks_quarantined_under_click_only_window() -> None:
    rows, q, notes = _api_rows(
        "meta", [_row("a1", "2", "5", attribution_window="7d_click"), _row("a2", "5", "1")]
    )
    assert [r.entity_ids["ad"] for r in rows] == ["a2"]
    assert "conversions above clicks" in q[0].reasons[0]
    assert not any("above clicks" in n for n in notes)


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
    q = derive("cvr", st, B.scope("a"), None)
    assert derive_mod.NOTICE_REPORTED_ABOVE_CLICKS in q.notices
    assert (
        derive_mod.NOTICE_REPORTED_ABOVE_CLICKS not in derive("ctr", st, B.scope("a"), None).notices
    )


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
    import json

    from bayesian_marketing.data_contract.connectors.pull import pull

    rec = Path(__file__).resolve().parents[3] / "data" / "recordings" / "ga4"
    req = json.loads((rec / "request.json").read_text())
    config = C.ClientConfig.model_validate(req["config"])
    window = (dt.date.fromisoformat(req["window"][0]), dt.date.fromisoformat(req["window"][1]))
    monkeypatch.setenv("BAYES_REPLAY_DIR", str(rec))
    p = pull("ga4", config, window)
    assert any("data truncated" in n for n in p.notes)
    assert not any(n.startswith(ga4.QUALITY_PREFIX) for n in p.notes)
