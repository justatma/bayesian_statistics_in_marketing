"""P2 simulator (spec v0.3 §9.1, D17, D20).

# CONTRACT ASSUMPTION: scenarios live at data/scenarios/<name>.yaml for the ten names of §9.1.
# CONTRACT ASSUMPTION: generate writes into out_dir exactly one JSON DatasetManifest (any file
#   name) besides ground_truth.json; ManifestFile.path is relative to out_dir.
# CONTRACT ASSUMPTION: north_pier_day2 / north_pier_day14 reproduce the Manuscript totals exactly
#   for any seed: per-ad impressions/clicks 2,000/40 and 2,000/34 (day 2); clicks 400 and 340 with
#   8 and 18 conversions (day 14), counted either as the platform conversion column per ad or as
#   orders-file rows (26 in all).
# CONTRACT ASSUMPTION: an export may carry headers listed under the platform's ignored_columns;
#   every other header is the canonical (first-listed) one for its field.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from bayesian_marketing import core as C
from bayesian_marketing.simulate.generate import generate
from tests.fakes.exports import (
    canonical_headers,
    channel_entry,
    header_matches,
    header_row,
    read_table,
)

pytestmark = pytest.mark.piece("P2")

REPO = Path(__file__).resolve().parents[2]
SCENARIOS_DIR = REPO / "data" / "scenarios"
SCENARIOS = [
    "north_pier_day2",
    "north_pier_day14",
    "tiny_campaign",
    "negative_dependence",
    "delivery_mix_shift",
    "attribution_window_change",
    "lag_heavy",
    "fractional_conversions",
    "switching_cost_hold",
    "many_accounts",
]


def _gen(name: str, seed: int, out: Path) -> tuple[C.GroundTruth, C.DatasetManifest]:
    gt = generate(SCENARIOS_DIR / f"{name}.yaml", seed, out)
    manifests = []
    for p in out.glob("*.json"):
        if p.name == "ground_truth.json":
            continue
        try:
            manifests.append(C.DatasetManifest.model_validate_json(p.read_text()))
        except ValueError:
            continue
    assert len(manifests) == 1, f"expected one DatasetManifest JSON in {out}"
    return gt, manifests[0]


def test_P2_extra_all_scenarios_present() -> None:
    missing = [s for s in SCENARIOS if not (SCENARIOS_DIR / f"{s}.yaml").exists()]
    assert not missing


@pytest.mark.parametrize("name", SCENARIOS)
def test_P2_manifest_marked_synthetic(name: str, tmp_path: Path) -> None:
    gt, m = _gen(name, 1, tmp_path)
    assert m.synthetic is True
    assert m.files, "manifest lists no files"
    platforms = {f.platform for f in m.files}
    assert "orders" in platforms, "an orders CSV is always written (§9.1)"
    assert platforms & {"meta", "google_ads", "linkedin"}
    for f in m.files:
        p = tmp_path / f.path
        assert p.exists(), f.path
        assert hashlib.sha256(p.read_bytes()).hexdigest() == f.sha256
    for platform in platforms:
        assert platform in m.attribution_window
    assert gt.scenario == name
    assert gt.seed == 1


@pytest.mark.parametrize("name", SCENARIOS)
def test_P2_exports_read_by_channel_maps(name: str, tmp_path: Path) -> None:
    _, m = _gen(name, 1, tmp_path)
    for f in m.files:
        entry = channel_entry(f.platform)
        canon = set(canonical_headers(f.platform).values())
        ignored = entry.get("ignored_columns", [])
        header = header_row(tmp_path / f.path, f.platform)
        for h in header:
            ok = any(header_matches(h, k) for k in canon) or any(
                header_matches(h, k) for k in ignored
            )
            assert ok, f"{f.platform} header {h!r} is not canonical in channels.yaml"
        fields = [
            next(fld for k, fld in entry["export_map"].items() if header_matches(h, k))
            for h in header
            if any(header_matches(h, k) for k in canon)
        ]
        assert len(fields) == len(set(fields)), f"{f.platform}: a field is written twice"


def _ad_totals(out: Path, m: C.DatasetManifest) -> list[tuple[int, int, float]]:
    totals: dict[str, list[float]] = {}
    for f in m.files:
        if f.platform not in ("meta", "google_ads", "linkedin"):
            continue
        for r in read_table(out / f.path, f.platform):
            t = totals.setdefault(r["entity_ids.ad"], [0, 0, 0.0])
            t[0] += int(float(r["impressions"]))
            t[1] += int(float(r["clicks"]))
            t[2] += float(r.get("conversions_reported") or 0)
    return [(int(a), int(b), c) for a, b, c in totals.values()]


def _orders_count(out: Path, m: C.DatasetManifest) -> int:
    return sum(len(read_table(out / f.path, "orders")) for f in m.files if f.platform == "orders")


def test_P2_ground_truth_matches_totals(tmp_path: Path) -> None:
    out2 = tmp_path / "d2"
    _, m2 = _gen("north_pier_day2", 1, out2)
    t2 = _ad_totals(out2, m2)
    assert sorted((i, c) for i, c, _ in t2) == [(2000, 34), (2000, 40)]

    out14 = tmp_path / "d14"
    _, m14 = _gen("north_pier_day14", 1, out14)
    t14 = _ad_totals(out14, m14)
    assert sorted(c for _, c, _ in t14) == [340, 400]
    by_clicks = {c: conv for _, c, conv in t14}
    platform_conv = sorted([round(by_clicks[400]), round(by_clicks[340])])
    assert platform_conv == [8, 18] or _orders_count(out14, m14) == 26

    for name in SCENARIOS:
        out = tmp_path / name
        gt, m = _gen(name, 1, out)
        on_disk = json.loads((out / "ground_truth.json").read_text())
        assert C.GroundTruth.model_validate(on_disk) == gt
        assert gt.true_quantities, name
        for key in gt.true_quantities:
            variant, _, qname = key.partition(".")
            assert variant in m.entity_map and qname, f"{name}: bad key {key!r}"
        for winner in gt.true_best.values():
            assert winner in m.entity_map, f"{name}: true_best names unknown variant {winner}"


def _all_bytes(out: Path) -> dict[str, bytes]:
    return {str(p.relative_to(out)): p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()}


def test_P2_seed_reproducible(tmp_path: Path) -> None:
    for name in ("negative_dependence", "tiny_campaign", "lag_heavy"):
        a, b, c = tmp_path / f"{name}_a", tmp_path / f"{name}_b", tmp_path / f"{name}_c"
        gta, _ = _gen(name, 42, a)
        gtb, _ = _gen(name, 42, b)
        assert gta == gtb
        assert _all_bytes(a) == _all_bytes(b), f"{name}: same seed, different files"
        _gen(name, 43, c)
        assert _all_bytes(a) != _all_bytes(c), f"{name}: different seed, identical files"
    counts = Counter()
    for f in _all_bytes(tmp_path / "negative_dependence_a"):
        counts[Path(f).suffix] += 1
    assert counts[".csv"] >= 2
