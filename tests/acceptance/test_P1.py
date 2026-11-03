"""P1 data contract readers and channels (spec v0.3 §5.1, §5.7, G1).

# CONTRACT ASSUMPTION: G1's staleness check in read_export uses today's date (no as-of argument
#   exists); a stale channel makes read_export raise core.GateFailure whose result.gate == "G1"
#   for that platform only. channel_model(platform, as_of) for a stale as_of either returns a
#   model with is_stale(as_of) True or raises GateFailure("G1").
# CONTRACT ASSUMPTION: when an export has no attribution column, rows take the window from
#   manifest.attribution_window[platform] (the fixtures set it equal to the channel default).
# CONTRACT ASSUMPTION: a row-level currency that is not an ISO 4217 code (e.g. "QQQ") is an
#   "unknown currency" and is quarantined.
# CONTRACT ASSUMPTION: "Attribution setting" values in a Meta export are passed through as the
#   row's attribution_window string unchanged (fixtures use the registry's codes).
# CONTRACT ASSUMPTION: export dates are ISO YYYY-MM-DD in the fixtures; account-local dates are
#   kept as-is; order timestamps with an offset are normalized to UTC (C2).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bayesian_marketing import core as C
from bayesian_marketing.channels.model import channel_model
from bayesian_marketing.core import registries
from bayesian_marketing.data_contract.readers.read import read_export
from tests.fakes import builders as B
from tests.fakes.exports import canonical_headers, write_export

pytestmark = pytest.mark.piece("P1")

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "exports"
D1, D2 = dt.date(2026, 11, 1), dt.date(2026, 11, 2)


def _manifest(path: Path, platform: str) -> C.DatasetManifest:
    f = C.ManifestFile(
        path=path.name,
        platform=platform,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        export_kind="export",
    )
    return B.manifest([f])


def _read(platform: str, path: Path) -> C.PlatformPull:
    return read_export(platform, path, _manifest(path, platform))


# (date, ad, impressions, clicks, spend, conversions_reported, revenue_reported)
PERF_EXPECTED = {
    "meta": [
        (D1, "ad_a", 1000, 20, "25.00", 4.0, "320.00"),
        (D1, "ad_b", 1000, 17, "21.25", 6.0, "480.00"),
        (D2, "ad_a", 1000, 20, "25.00", 4.0, "320.00"),
        (D2, "ad_b", 1000, 17, "21.25", 12.0, "960.00"),
    ],
    "google_ads": [
        (D1, "ad_a", 1000, 20, "25.00", 3.5, "280.00"),
        (D1, "ad_b", 1000, 17, "21.25", 6.0, "480.00"),
        (D2, "ad_a", 1000, 20, "25.00", 4.0, "320.00"),
        (D2, "ad_b", 1000, 17, "21.25", 12.0, "960.00"),
    ],
}
PERF_EXPECTED["linkedin"] = PERF_EXPECTED["meta"]
WINDOWS = {
    "meta": "7d_click_1d_view",
    "google_ads": "per_conversion_action",
    "linkedin": "90d_click_90d_view",
}
ACCOUNTS = {"meta": "acc1", "google_ads": "1234567890", "linkedin": "acc1"}


def _check_performance(platform: str, pull: C.PlatformPull) -> None:
    rows = sorted(pull.rows, key=lambda r: (r.date, r.entity_ids["ad"]))
    assert len(rows) == len(PERF_EXPECTED[platform]), "Total/preamble rows must not become data"
    for r, (d, ad, imp, clk, spend, conv, rev) in zip(rows, PERF_EXPECTED[platform], strict=True):
        assert isinstance(r, C.PerformanceRow)
        assert r.date == d
        assert r.entity_ids["ad"] == ad
        assert r.entity_ids["campaign"] == "c1"
        assert r.entity_ids["account"] == ACCOUNTS[platform]
        assert (r.impressions, r.clicks) == (imp, clk)
        assert r.spend == C.Money(amount=Decimal(spend), currency="USD")
        assert r.conversions_reported == pytest.approx(conv)
        assert r.revenue_reported is not None
        assert r.revenue_reported.amount == Decimal(rev)
        assert r.attribution_window == WINDOWS[platform]


def _check_ga4(pull: C.PlatformPull) -> None:
    rows = sorted(pull.rows, key=lambda r: (r.date, r.utm["campaign"]))
    want = [
        (D1, "np_a", 120, 3, "240.00"),
        (D1, "np_b", 100, 5, "400.00"),
        (D2, "np_a", 110, 2, "160.00"),
        (D2, "np_b", 95, 9, "720.00"),
    ]
    assert len(rows) == 4
    for r, (d, camp, sess, purch, rev) in zip(rows, want, strict=True):
        assert isinstance(r, C.SiteRow)
        assert (r.date, r.utm["campaign"], r.sessions, r.purchases) == (d, camp, sess, purch)
        assert r.utm["source"] == "facebook" and r.utm["medium"] == "paid"
        assert r.revenue.amount == Decimal(rev)


def _check_orders(pull: C.PlatformPull) -> None:
    rows = {r.order_id: r for r in pull.rows}
    assert set(rows) == {"o1", "o2", "o3"}
    o1, o2, o3 = rows["o1"], rows["o2"], rows["o3"]
    assert all(isinstance(r, C.OrderRow) for r in rows.values())
    utc = dt.UTC
    assert o1.ordered_at == dt.datetime(2026, 11, 1, 15, 0, tzinfo=utc)
    assert o1.ordered_at.utcoffset() == dt.timedelta(0)
    assert o3.ordered_at == dt.datetime(2026, 11, 3, 4, 30, tzinfo=utc)
    assert o1.first_click_at == dt.datetime(2026, 10, 30, 14, 0, tzinfo=utc)
    assert o2.first_click_at is None
    assert o1.value == C.Money(amount=Decimal("80.00"), currency="USD")
    assert o2.refunded.amount == Decimal("10.00")
    assert o1.utm is not None and o1.utm["campaign"] == "np_a" and o1.utm["content"] == "ad_a"
    assert o2.click_id == "fbclid123"
    assert o3.click_id == "gclid456"


PLATFORMS = ["meta", "google_ads", "linkedin", "ga4", "orders"]


@pytest.mark.parametrize("variant", ["canonical", "aliases"])
@pytest.mark.parametrize("platform", PLATFORMS)
def test_P1_reads_each_platform_export(platform: str, variant: str) -> None:
    path = FIX / f"{platform}_{variant}.csv"
    pull = _read(platform, path)
    assert pull.platform == platform
    assert pull.pull_id.startswith(f"pull_{platform}_")
    assert pull.quarantined == []
    assert pull.synthetic is False
    assert pull.measurement_changes == []
    if platform == "ga4":
        _check_ga4(pull)
    elif platform == "orders":
        _check_orders(pull)
    else:
        _check_performance(platform, pull)
    if variant == "aliases":
        canon = _read(platform, FIX / f"{platform}_canonical.csv")
        key = (lambda r: r.model_dump_json()) if platform != "orders" else (lambda r: r.order_id)
        assert sorted(map(key, pull.rows)) == sorted(map(key, canon.rows))


# --- C1 quarantine fuzz ---------------------------------------------------------------------------

BAD_KINDS = [
    "clicks_gt_impressions",
    "negative_impressions",
    "negative_clicks",
    "negative_spend",
    "conversions_gt_clicks",
    "negative_conversions",
    "unknown_currency",
]


@st.composite
def _row(draw: st.DrawFn, i: int) -> dict:
    kind = draw(st.sampled_from(["valid", "valid", *BAD_KINDS]))
    imp = draw(st.integers(1, 1_000_000))
    clk = draw(st.integers(0, imp))
    conv = draw(st.integers(0, clk * 100)) / 100
    cents = draw(st.integers(0, 10_000_000))
    row = {
        "date": "2026-11-01",
        "entity_ids.account": "1234567890",
        "entity_ids.campaign": "c1",
        "entity_ids.ad_set": "ag1",
        "entity_ids.ad": f"ad_{i:03d}",
        "impressions": imp,
        "clicks": clk,
        "spend": f"{cents / 100:.2f}",
        "currency": "USD",
        "conversions_reported": f"{conv:.2f}",
        "revenue_reported": "0.00",
    }
    if kind == "clicks_gt_impressions":
        row["clicks"] = imp + draw(st.integers(1, 1000))
        row["conversions_reported"] = "0.00"
    elif kind == "negative_impressions":
        row["impressions"] = -draw(st.integers(1, 1000))
        row["clicks"] = 0
        row["conversions_reported"] = "0.00"
    elif kind == "negative_clicks":
        row["clicks"] = -draw(st.integers(1, 1000))
        row["conversions_reported"] = "0.00"
    elif kind == "negative_spend":
        row["spend"] = f"-{draw(st.integers(1, 100000)) / 100:.2f}"
    elif kind == "conversions_gt_clicks":
        row["conversions_reported"] = f"{clk + draw(st.integers(1, 50)) + 0.5:.2f}"
    elif kind == "negative_conversions":
        row["conversions_reported"] = f"-{draw(st.integers(1, 50))}.00"
    elif kind == "unknown_currency":
        row["currency"] = "QQQ"
    return {"kind": kind, "row": row}


@st.composite
def _rows(draw: st.DrawFn) -> list[dict]:
    n = draw(st.integers(1, 8))
    return [draw(_row(i)) for i in range(n)]


@settings(
    max_examples=500,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(cases=_rows())
def test_P1_quarantine_fuzz(cases: list[dict]) -> None:
    with tempfile.TemporaryDirectory() as d:
        path = write_export(Path(d) / "google_ads.csv", "google_ads", [c["row"] for c in cases])
        pull = _read("google_ads", path)
    valid = {c["row"]["entity_ids.ad"]: c["row"] for c in cases if c["kind"] == "valid"}
    invalid = {c["row"]["entity_ids.ad"]: c["kind"] for c in cases if c["kind"] != "valid"}
    assert len(pull.quarantined) == len(invalid), (invalid, pull.quarantined)
    for ad in invalid:
        hits = [q for q in pull.quarantined if any(str(v) == ad for v in q.raw.values())]
        assert len(hits) == 1, f"{invalid[ad]} row {ad} not quarantined exactly once"
        assert hits[0].reasons and all(isinstance(r, str) and r for r in hits[0].reasons)
    got = {r.entity_ids["ad"]: r for r in pull.rows}
    assert set(got) == set(valid)
    for ad, raw in valid.items():
        r = got[ad]
        assert r.impressions == raw["impressions"]
        assert r.clicks == raw["clicks"]
        assert r.spend == C.Money(amount=Decimal(raw["spend"]), currency="USD")
        assert r.conversions_reported == pytest.approx(float(raw["conversions_reported"]))
        assert r.date == dt.date(2026, 11, 1)


def test_P1_extra_duplicate_order_id_quarantined(tmp_path: Path) -> None:
    src = (FIX / "orders_canonical.csv").read_text().splitlines()
    dup = src[1].replace("80.00", "81.00")
    path = tmp_path / "orders.csv"
    path.write_text("\n".join([*src, dup]) + "\n")
    pull = _read("orders", path)
    assert [r.order_id for r in pull.rows].count("o1") <= 1
    hits = [q for q in pull.quarantined if "o1" in map(str, q.raw.values())]
    assert hits and all(q.reasons for q in hits)
    assert {r.order_id for r in pull.rows} >= {"o2", "o3"}


# --- C5 attribution change ------------------------------------------------------------------------


def test_P1_attribution_change_splits(tmp_path: Path) -> None:
    rows = []
    for i in range(6):
        rows.append(
            {
                "date": (D1 + dt.timedelta(days=i)).isoformat(),
                "entity_ids.account": "acc1",
                "entity_ids.campaign": "c1",
                "entity_ids.ad_set": "as1",
                "entity_ids.ad": "ad_a",
                "impressions": 1000,
                "clicks": 20,
                "spend": "25.00",
                "conversions_reported": 2,
                "revenue_reported": "160.00",
                "attribution_window": "7d_click_1d_view" if i < 3 else "1d_click",
            }
        )
    path = write_export(tmp_path / "meta.csv", "meta", rows)
    pull = _read("meta", path)
    assert pull.quarantined == []
    assert len(pull.rows) == 6
    by_date = {r.date: r.attribution_window for r in pull.rows}
    assert [by_date[D1 + dt.timedelta(days=i)] for i in range(6)] == ["7d_click_1d_view"] * 3 + [
        "1d_click"
    ] * 3
    assert len(pull.measurement_changes) == 1
    assert pull.measurement_changes[0]


def test_P1_extra_no_change_no_split() -> None:
    pull = _read("meta", FIX / "meta_canonical.csv")
    assert pull.measurement_changes == []


# --- C8 conversion typing -------------------------------------------------------------------------


def _linkedin_file(tmp_path: Path, conversions: list[str]) -> Path:
    lines = (FIX / "linkedin_canonical.csv").read_text().splitlines()
    out = [lines[0]]
    for line, conv in zip(lines[1:], conversions, strict=True):
        cells = line.split(",")
        cells[13] = conv
        out.append(",".join(cells))
    path = tmp_path / "linkedin.csv"
    path.write_text("\n".join(out) + "\n")
    return path


def test_P1_conversion_typing_C8(tmp_path: Path, iso) -> None:
    # A platform whose conversions may be modeled: reported only, never observed.
    meta = _read("meta", FIX / "meta_canonical.csv")
    assert all(r.conversions_observed is None for r in meta.rows)
    assert all(r.conversions_reported is not None for r in meta.rows)
    assert meta.partial_truth is (all(r.conversions_modeled_share is None for r in meta.rows))
    assert meta.partial_truth is True

    # Same platform with the field marked not modeled: integers are copied to observed.
    iso.edit_yaml(
        "channels",
        lambda d: d["channels"]["linkedin"].update(conversion_field_may_be_modeled=False),
    )
    whole = _read("linkedin", _linkedin_file(tmp_path, ["4", "6", "4", "12"]))
    assert sorted(r.conversions_observed for r in whole.rows) == [4, 4, 6, 12]
    assert all(r.conversions_reported == r.conversions_observed for r in whole.rows)
    assert whole.partial_truth is False

    # One fractional value anywhere in the pull: nothing is copied.
    frac = _read("linkedin", _linkedin_file(tmp_path, ["4", "6", "4.5", "12"]))
    assert all(r.conversions_observed is None for r in frac.rows)
    assert sorted(r.conversions_reported for r in frac.rows) == [4.0, 4.5, 6.0, 12.0]
    assert frac.partial_truth is True


# --- G1 stale channel -----------------------------------------------------------------------------


def test_P1_stale_channel_blocks(iso) -> None:
    iso.edit_yaml(
        "channels",
        lambda d: d["channels"]["meta"].update(freshness_date=dt.date(2020, 1, 1)),
    )
    with pytest.raises(C.GateFailure) as ei:
        _read("meta", FIX / "meta_canonical.csv")
    assert ei.value.result.gate == "G1"
    assert ei.value.result.passed is False
    assert ei.value.result.blocking is True
    assert ei.value.result.reasons
    # Only its own platform is blocked.
    ok = _read("google_ads", FIX / "google_ads_canonical.csv")
    assert len(ok.rows) == 4

    stale_day = dt.date(2020, 1, 1) + dt.timedelta(days=200)
    try:
        cm = channel_model("meta", stale_day)
    except C.GateFailure as e:
        assert e.result.gate == "G1"
    else:
        assert cm.is_stale(stale_day)


def test_P1_extra_channel_model_from_registry() -> None:
    raw = registries.load("channels")["channels"]
    for platform in PLATFORMS:
        as_of = dt.date(2026, 11, 10)
        cm = channel_model(platform, as_of)
        entry = raw[platform]
        assert cm.platform == platform
        assert cm.export_map == entry["export_map"]
        assert cm.conversion_field_may_be_modeled is entry["conversion_field_may_be_modeled"]
        assert cm.default_attribution_window == entry["default_attribution_window"]
        assert cm.learning_phase_switching_cost is None
        assert cm.freshness_date == entry["freshness_date"]
        assert cm.max_age_days == entry["max_age_days"]
        assert not cm.is_stale(as_of)
        assert canonical_headers(platform)  # every platform has a map
