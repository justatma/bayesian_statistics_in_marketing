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
    assert len(pull.quarantined) == 1 and "unknown currency" in pull.quarantined[0].reasons[0]


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
