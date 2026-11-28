"""P2 unit checks beyond the frozen set: totals across seeds, lag median, window split, joins."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from bayesian_marketing.simulate.draw import lag_p
from bayesian_marketing.simulate.generate import generate
from bayesian_marketing.simulate.scenario import Phase, Scenario

REPO = Path(__file__).resolve().parents[3]
SCEN = REPO / "data" / "scenarios"


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open() as fh:
        return list(csv.DictReader(fh))


@pytest.mark.parametrize("seed", [0, 5, 123, 99_999])
def test_north_pier_totals_any_seed(seed: int, tmp_path: Path) -> None:
    generate(SCEN / "north_pier_day14.yaml", seed, tmp_path)
    rows = _rows(tmp_path / "meta_np_acc1.csv")
    tot: dict[str, list[float]] = {}
    for r in rows:
        t = tot.setdefault(r["Ad ID"], [0, 0, 0, 0.0])
        t[0] += int(r["Link clicks"])
        t[1] += int(r["Purchases"])
        t[2] += int(r["Impressions"])
        t[3] += float(r["Amount spent (USD)"])
        assert int(r["Link clicks"]) <= int(r["Impressions"])
        assert int(r["Purchases"]) <= int(r["Link clicks"])
    assert tot["ad_a"][:2] == [400, 8] and tot["ad_b"][:2] == [340, 18]
    assert tot["ad_a"][3] == pytest.approx(500.0) and tot["ad_b"][3] == pytest.approx(500.0)
    assert len(_rows(tmp_path / "orders.csv")) == 26


@pytest.mark.parametrize("median", [0, 1, 2, 4, 10])
def test_lag_p_has_stated_median(median: int) -> None:
    q = 1 - lag_p(median)
    cdf = lambda k: 1 - q ** (k + 1)  # noqa: E731
    assert cdf(median) >= 0.5
    assert median == 0 or cdf(median - 1) < 0.5


def test_lag_heavy_draws_have_median_four(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    lags = rng.geometric(lag_p(4), size=200_000) - 1
    assert np.median(lags) == 4


def test_window_change_rows_and_manifest(tmp_path: Path) -> None:
    generate(SCEN / "attribution_window_change.yaml", 3, tmp_path)
    rows = _rows(tmp_path / "meta_win_acc1.csv")
    windows = [r["Attribution setting"] for r in rows]
    assert set(windows) == {"7d_click_1d_view", "1d_click"}
    first_new = min(r["Day"] for r in rows if r["Attribution setting"] == "1d_click")
    assert first_new == "2026-10-11"
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert m["attribution_window"]["meta"] == "7d_click_1d_view"
    reported = sum(int(r["Purchases"]) for r in rows)
    assert reported < len(_rows(tmp_path / "orders.csv"))  # shorter window drops some orders


def test_fractional_orders_do_not_join(tmp_path: Path) -> None:
    generate(SCEN / "fractional_conversions.yaml", 2, tmp_path)
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert m["utm_map"] is None
    assert all(r["utm_campaign"] == "" for r in _rows(tmp_path / "orders.csv"))
    conv = [r["Conversions"] for r in _rows(tmp_path / "google_ads_123-456-7002.csv")]
    assert any(float(c) != int(float(c)) for c in conv)


def test_orders_join_through_utm_map(tmp_path: Path) -> None:
    generate(SCEN / "many_accounts.yaml", 4, tmp_path)
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert len(m["entity_map"]) == 120
    ids = {r["utm_campaign"] for r in _rows(tmp_path / "orders.csv")}
    assert ids <= set(m["utm_map"])
    assert len([p for p in m["files"] if p["platform"] == "meta"]) == 3


def test_economics_written_beside_manifest(tmp_path: Path) -> None:
    from bayesian_marketing.core import load_economics

    generate(SCEN / "north_pier_day14.yaml", 1, tmp_path)
    m = json.loads((tmp_path / "manifest.json").read_text())
    econ = load_economics(m["economics_id"], tmp_path)
    assert econ.approved and econ.loss_tolerance is not None
    assert econ.variable_cost_per_order.amount == 48


def test_scenario_rejects_inconsistent_phase() -> None:
    with pytest.raises(ValueError):
        Phase(days=2, spend="10", clicks=5, conversions=6)
    with pytest.raises(ValueError):
        Phase(days=2, spend="10", spend_per_day="5")
    raw = yaml.safe_load((SCEN / "north_pier_day2.yaml").read_text())
    raw["n_days"] = 3
    with pytest.raises(ValueError):
        Scenario.model_validate(raw)
