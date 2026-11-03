"""P1 unit tests beyond the frozen set: encodings, Excel id cells, G1 file checks, C1 edge cases."""

from __future__ import annotations

import datetime as dt
import hashlib
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from tests.fakes import builders as B

from bayesian_marketing import core as C
from bayesian_marketing.channels.model import channel_model, load_channel_model
from bayesian_marketing.data_contract.readers.read import read_export
from bayesian_marketing.data_contract.readers.table import decode

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "exports"


def _manifest(path: Path, platform: str, **kw) -> C.DatasetManifest:
    f = C.ManifestFile(
        path=path.name,
        platform=platform,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        export_kind="export",
    )
    return B.manifest([f], **kw)


def _read(platform: str, path: Path) -> C.PlatformPull:
    return read_export(platform, path, _manifest(path, platform))


def test_google_ads_utf16_tab_excel_ids(tmp_path: Path) -> None:
    text = (FIX / "google_ads_canonical.csv").read_text()
    lines = text.splitlines()
    out = []
    for ln in lines:
        if ln.startswith("2026-"):
            cells = ln.split(",")
            cells[1] = '="1234567890"'
            ln = ",".join(cells)
        out.append(ln.replace(",", "\t") if not ln.startswith('"') else ln)
    path = tmp_path / "gads.csv"
    path.write_bytes("\n".join(out).encode("utf-16"))
    pull = _read("google_ads", path)
    assert pull.quarantined == []
    assert len(pull.rows) == 4
    assert {r.entity_ids["account"] for r in pull.rows} == {"1234567890"}
    assert pull.account_id == "1234567890"
    canon = _read("google_ads", FIX / "google_ads_canonical.csv")
    assert sorted(r.model_dump_json() for r in pull.rows) == sorted(
        r.model_dump_json() for r in canon.rows
    )


def test_decode_utf8_bom_and_bomless_utf16() -> None:
    assert decode("﻿a,b".encode()) == "a,b"
    assert decode("a,b".encode("utf-16-le")) == "a,b"


def test_file_not_in_manifest_fails_g1(tmp_path: Path) -> None:
    path = FIX / "meta_canonical.csv"
    other = tmp_path / "x.csv"
    other.write_text("x\n")
    with pytest.raises(C.GateFailure) as ei:
        read_export("meta", path, _manifest(other, "meta"))
    assert ei.value.result.gate == "G1"


def test_missing_required_column_fails_g1(tmp_path: Path) -> None:
    lines = (FIX / "meta_canonical.csv").read_text().splitlines()
    cut = [",".join(ln.split(",")[:9] + ln.split(",")[10:]) for ln in lines]  # drop Impressions
    path = tmp_path / "meta.csv"
    path.write_text("\n".join(cut) + "\n")
    with pytest.raises(C.GateFailure) as ei:
        _read("meta", path)
    assert "impressions" in ei.value.result.reasons[0]


def test_orders_naive_timestamp_and_identical_duplicate(tmp_path: Path) -> None:
    src = (FIX / "orders_canonical.csv").read_text().splitlines()
    naive = src[2].replace("2026-11-02T12:30:00-05:00", "2026-11-02T12:30:00")
    path = tmp_path / "orders.csv"
    path.write_text("\n".join([src[0], src[1], naive, src[3], src[3]]) + "\n")
    pull = _read("orders", path)
    ids = [r.order_id for r in pull.rows]
    assert ids == ["o1", "o3"]
    reasons = [r for q in pull.quarantined for r in q.reasons]
    assert any("no UTC offset" in r for r in reasons)
    assert any("identical repeat" in r for r in reasons)


def test_currency_header_conflict_quarantined(tmp_path: Path) -> None:
    lines = (FIX / "meta_canonical.csv").read_text().splitlines()
    lines[0] += ",Currency"  # not in Meta's map: ignored, so no conflict
    lines[1:] = [ln + ",EUR" for ln in lines[1:]]
    path = tmp_path / "meta.csv"
    path.write_text("\n".join(lines) + "\n")
    pull = _read("meta", path)
    assert pull.quarantined == [] and all(r.spend.currency == "USD" for r in pull.rows)

    lines = (FIX / "google_ads_canonical.csv").read_text().splitlines()
    lines[3] = lines[3].replace(",USD,", ",usd,")
    path = tmp_path / "gads.csv"
    path.write_text("\n".join(lines) + "\n")
    pull = _read("google_ads", path)
    assert pull.quarantined == [] and len(pull.rows) == 4  # F8: upper-cased before validation


def test_ga4_currency_from_manifest_else_xxx(tmp_path: Path) -> None:
    path = FIX / "ga4_canonical.csv"
    pull = read_export("ga4", path, _manifest(path, "ga4").model_copy(update={"currency": "EUR"}))
    assert {r.revenue.currency for r in pull.rows} == {"EUR"}
    assert {r.revenue.currency for r in _read("ga4", path).rows} == {"XXX"}
    assert pull.partial_truth is False


def test_pull_id_is_deterministic_per_file() -> None:
    a = _read("meta", FIX / "meta_canonical.csv")
    b = _read("meta", FIX / "meta_canonical.csv")
    assert a.pull_id == b.pull_id
    assert a.window == (dt.date(2026, 11, 1), dt.date(2026, 11, 2))
    assert a.channel_ref == "channels/channels/meta@v1"
    C.registries.resolve(a.channel_ref)


@pytest.fixture
def reg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = tmp_path / "registries"
    shutil.copytree(Path(__file__).resolve().parents[3] / "registries", root)
    monkeypatch.setenv("BAYES_REGISTRY_DIR", str(root))
    C.registries.clear_cache()
    yield root
    C.registries.clear_cache()


def test_channel_model_switching_cost_and_stale(reg: Path) -> None:
    path = reg / "channels.yaml"
    data = yaml.safe_load(path.read_text())
    data["channels"]["meta"]["learning_phase_switching_cost"] = {"amount": "250", "currency": "USD"}
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    C.registries.clear_cache()
    cm = load_channel_model("meta")
    assert cm.learning_phase_switching_cost == C.Money(amount=Decimal("250"), currency="USD")
    late = cm.freshness_date + dt.timedelta(days=cm.max_age_days + 1)
    with pytest.raises(C.GateFailure) as ei:
        channel_model("meta", late)
    assert ei.value.result.gate == "G1" and ei.value.result.blocking
    channel_model("meta", late - dt.timedelta(days=1))


# --- review fixes ---------------------------------------------------------------------------------


def _write(tmp_path: Path, name: str, lines: list[str]) -> Path:
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n")
    return path


def _gads(tmp_path: Path, edit=None) -> Path:
    lines = (FIX / "google_ads_canonical.csv").read_text().splitlines()
    if edit:
        lines = edit(lines)
    return _write(tmp_path, "gads.csv", lines)


def test_F1_empty_file_and_header_only(tmp_path: Path) -> None:
    zero = tmp_path / "meta.csv"
    zero.write_bytes(b"")
    pull = _read("meta", zero)
    assert pull.empty_account and pull.rows == [] and pull.measurement_changes
    head = _gads(tmp_path, lambda ls: ls[:3])
    pull = _read("google_ads", head)
    assert pull.empty_account and pull.rows == [] and pull.quarantined == []
    assert _read("google_ads", FIX / "google_ads_canonical.csv").empty_account is False


def test_F2_truncated_utf16_fails_g1(tmp_path: Path) -> None:
    path = tmp_path / "gads.csv"
    path.write_bytes((FIX / "google_ads_canonical.csv").read_text().encode("utf-16")[:-1])
    with pytest.raises(C.GateFailure) as ei:
        _read("google_ads", path)
    assert ei.value.result.gate == "G1"


def test_F3_minority_currency_quarantined_tie_fails(tmp_path: Path) -> None:
    pull = _read(
        "google_ads", _gads(tmp_path, lambda ls: [*ls[:3], ls[3].replace("USD", "EUR"), *ls[4:]])
    )
    assert len(pull.rows) == 3 and {r.spend.currency for r in pull.rows} == {"USD"}
    assert len(pull.quarantined) == 1 and "EUR" in pull.quarantined[0].reasons[0]

    def tie(ls: list[str]) -> list[str]:
        return [*ls[:3], ls[3].replace("USD", "EUR"), ls[4].replace("USD", "EUR"), *ls[5:]]

    with pytest.raises(C.GateFailure):
        _read("google_ads", _gads(tmp_path, tie))


def test_F4_results_flags(tmp_path: Path) -> None:
    lines = (FIX / "meta_canonical.csv").read_text().splitlines()
    both = [lines[0] + ",Results,Result indicator"]
    both += [ln + f",9,{'purchase' if i % 2 else 'link_click'}" for i, ln in enumerate(lines[1:])]
    pull = _read("meta", _write(tmp_path, "meta.csv", both))
    assert sorted(r.conversions_reported for r in pull.rows) == [4.0, 4.0, 6.0, 12.0]
    notes = " ".join(pull.measurement_changes)
    assert "not used on 4 rows" in notes and "mixed objectives" in notes


def test_F5_non_daily_meta_rows_quarantined(tmp_path: Path) -> None:
    lines = (FIX / "meta_canonical.csv").read_text().splitlines()
    out = [lines[0].replace("Day,", "Reporting starts,", 1) + ",Reporting ends"]
    for i, ln in enumerate(lines[1:]):
        d = ln.split(",")[0]
        out.append(ln + ("," + d if i else ",2026-11-30"))
    pull = _read("meta", _write(tmp_path, "meta.csv", out))
    assert len(pull.rows) == 3
    assert "non-daily aggregate" in pull.quarantined[0].reasons[0]


def test_F6_total_named_campaign_kept(tmp_path: Path) -> None:
    def edit(ls: list[str]) -> list[str]:
        row = ls[3].split(",")
        row[0] = "Total Eclipse"  # first cell; a data row whose date is bad, not a summary
        return [*ls[:3], ",".join(row), *ls[4:]]

    pull = _read("google_ads", _gads(tmp_path, edit))
    assert len(pull.rows) == 3 and len(pull.quarantined) == 1  # quarantined, not silently dropped


def test_F7_dashes_optional_none(tmp_path: Path) -> None:
    pull = _read(
        "google_ads",
        _gads(tmp_path, lambda ls: [*ls[:3], ls[3].replace(",280.00", ",--"), *ls[4:]]),
    )
    assert pull.quarantined == []
    assert sum(r.revenue_reported is None for r in pull.rows) == 1


def test_F9_duplicates_and_cross_field_checks(tmp_path: Path) -> None:
    pull = _read(
        "google_ads", _gads(tmp_path, lambda ls: [*ls[:4], ls[3].replace("3.50", "3.00"), *ls[4:]])
    )
    assert len(pull.rows) == 3 and len(pull.quarantined) == 2
    assert all("duplicate" in q.reasons[0] for q in pull.quarantined)
    pull = _read("google_ads", _gads(tmp_path, lambda ls: [*ls[:4], ls[3], *ls[4:]]))
    assert len(pull.rows) == 4 and len(pull.quarantined) == 1

    src = (FIX / "orders_canonical.csv").read_text().splitlines()
    pull = _read("orders", _write(tmp_path, "o.csv", [src[0], src[1].replace(",0.00,", ",90.00,")]))
    assert pull.rows == [] and "refunded above value" in pull.quarantined[0].reasons[0]

    g = (FIX / "ga4_canonical.csv").read_text().splitlines()
    pull = _read("ga4", _write(tmp_path, "g.csv", [g[5], g[6].replace(",120,3,", ",2,3,")]))
    assert pull.rows == [] and "purchases above sessions" in pull.quarantined[0].reasons[0]


def test_F10_as_of_and_timezone() -> None:
    with pytest.raises(C.GateFailure):
        read_export(
            "meta",
            FIX / "meta_canonical.csv",
            _manifest(FIX / "meta_canonical.csv", "meta"),
            as_of=dt.date(2030, 1, 1),
        )
    assert _read("orders", FIX / "orders_canonical.csv").timezone == "UTC"
    assert _read("linkedin", FIX / "linkedin_canonical.csv").timezone == "UTC"
    assert _read("meta", FIX / "meta_canonical.csv").timezone is None


def test_F11_quoted_multiline_cell(tmp_path: Path) -> None:
    def edit(ls: list[str]) -> list[str]:
        return [*ls[:3], ls[3].replace(",Ad A,", ',"Ad\nA, two lines",'), *ls[4:]]

    pull = _read("google_ads", _gads(tmp_path, edit))
    assert pull.quarantined == [] and len(pull.rows) == 4
