"""P11 unit checks beyond the frozen set: assembly, D30/D28 refusals on client data, socket edges,
the demo CLI."""

from __future__ import annotations

import datetime as dt
import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from bayesian_marketing import core as C
from bayesian_marketing import pipeline
from bayesian_marketing.atmaos import socket as sock
from bayesian_marketing.cli import main as cli_main
from bayesian_marketing.core import registries
from bayesian_marketing.decision import run_record
from bayesian_marketing.simulate.generate import MANIFEST_NAME, generate

REPO = Path(__file__).resolve().parents[3]
SCEN = REPO / "data" / "scenarios"
UTC = dt.UTC


@pytest.fixture(autouse=True)
def _iso(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    reg = tmp_path / "registries"
    shutil.copytree(REPO / "registries", reg)
    monkeypatch.setenv("BAYES_REGISTRY_DIR", str(reg))
    monkeypatch.setenv("BAYES_DATA_DIR", str(tmp_path / "store"))
    monkeypatch.delenv("BAYES_CONFIG_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    registries.clear_cache()
    yield
    registries.clear_cache()


def _perf(ad: str, day: int, clicks: int, conv: float | None = None) -> C.PerformanceRow:
    return C.PerformanceRow(
        entity_ids={"account": "acc", "campaign": "c1", "ad": ad},
        date=dt.date(2026, 10, day),
        impressions=clicks * 50,
        clicks=clicks,
        spend=C.Money(amount=Decimal("10.00"), currency="USD"),
        conversions_reported=conv,
        attribution_window="7d_click_1d_view",
    )


def _pull(platform: str, rows: list, sha: str = "00000001") -> C.PlatformPull:
    return C.PlatformPull(
        pull_id=f"pull_{platform}_{sha}",
        platform=platform,
        channel_ref=f"channels/{platform}@v1",
        rows=rows,
        quarantined=[],
        partial_truth=False,
        measurement_changes=[],
        pulled_at=dt.datetime(2026, 11, 1, tzinfo=UTC),
        synthetic=True,
    )


def _order(oid: str, campaign: str, clicked: int, ordered: int) -> C.OrderRow:
    return C.OrderRow(
        order_id=oid,
        ordered_at=dt.datetime(2026, 10, ordered, 15, tzinfo=UTC),
        value=C.Money(amount=Decimal("50.00"), currency="USD"),
        refunded=C.Money(amount=Decimal("0"), currency="USD"),
        utm={"campaign": campaign},
        first_click_at=dt.datetime(2026, 10, clicked, 12, tzinfo=UTC),
    )


def test_assemble_sums_rows_and_joins_orders_on_click_date() -> None:
    perf = _pull(
        "meta",
        [_perf("a", 1, 10), _perf("a", 1, 5), _perf("a", 2, 20), _perf("b", 1, 8, 1.0)],
    )
    orders = _pull(
        "orders",
        [_order("o1", "ca", 1, 2), _order("o2", "ca", 2, 2), _order("o3", "ca", 2, 9)],
    )
    utm = {"ca": {"meta": "a"}}
    data = pipeline.assemble_funnel_data([perf, orders], None, dt.date(2026, 10, 2), utm_map=utm)
    assert data.entities == ["a", "b"]
    assert data.clicks[0] == [15, 20]
    # o3 was ordered after as_of: not yet observed
    assert data.conversions_observed[0] == [1, 1]
    assert data.conversions_observed[1] == [None, None]
    assert data.conversions_reported[1] == [1.0, None]
    assert data.order_values == {"a": [50.0, 50.0]}
    assert data.mature_fraction == [[1.0, 1.0], [1.0, 1.0]]
    assert data.pull_ids == ["pull_meta_00000001", "pull_orders_00000001"]


def test_assemble_without_joined_orders_leaves_out_the_orders_pull() -> None:
    perf = _pull("meta", [_perf("a", 1, 10, 0.0), _perf("b", 1, 8, 1.0)])
    orders = _pull("orders", [_order("o1", "elsewhere", 1, 1)])
    data = pipeline.assemble_funnel_data([perf, orders], None, dt.date(2026, 10, 1), utm_map={})
    assert data.pull_ids == ["pull_meta_00000001"]
    assert data.order_values == {}


def test_observed_as_of_runs_past_the_window_end_for_late_orders() -> None:
    perf = _pull("meta", [_perf("a", 1, 10)])
    orders = [_order("o1", "ca", 1, 5)]
    assert pipeline.observed_as_of([perf], orders, dt.date(2026, 10, 3)) == dt.date(2026, 10, 5)
    assert pipeline.observed_as_of([perf], [], dt.date(2026, 10, 3)) == dt.date(2026, 10, 3)


def _dataset(tmp_path: Path, name: str = "north_pier_day14") -> tuple[Path, C.DatasetManifest]:
    out = tmp_path / "ds"
    generate(SCEN / f"{name}.yaml", 1, out)
    return out, C.DatasetManifest.load(out / MANIFEST_NAME)


def _as_client(out: Path, m: C.DatasetManifest, econ_update: dict) -> C.DatasetManifest:
    m = m.model_copy(update={"synthetic": False})
    (out / MANIFEST_NAME).write_text(m.model_dump_json())
    path = out / "economics" / f"{m.economics_id}.json"
    econ = json.loads(path.read_text()) | econ_update
    path.write_text(json.dumps(econ))
    return m


def _request(m: C.DatasetManifest, **kw) -> C.CompareRequest:
    base = {
        "metric": "contribution",
        "variants": sorted(m.entity_map),
        "priors": {},
        "window": (dt.date(2026, 10, 1), dt.date(2026, 10, 14)),
        "horizon": C.Horizon(unit="clicks", amount=Decimal(1000)),
    }
    return C.CompareRequest(**(base | kw))


@pytest.mark.parametrize(
    "update",
    [{"approved_by": None, "approved_at": None}, {"loss_tolerance": None}],
    ids=["unapproved", "no_tolerance"],
)
def test_client_run_refused_without_approved_economics_D30(tmp_path: Path, update: dict) -> None:
    out, m = _dataset(tmp_path)
    m = _as_client(out, m, update)
    with pytest.raises(C.GateFailure) as ei:
        pipeline.run(m, _request(m), manifest_dir=out)
    assert ei.value.result.gate == "G9"
    assert run_record.read("RunRecord") == []
    assert not (tmp_path / "store" / "states").exists()


def test_synthetic_run_without_tolerance_gives_not_knowable(tmp_path: Path) -> None:
    out, m = _dataset(tmp_path)
    path = out / "economics" / f"{m.economics_id}.json"
    path.write_text(json.dumps(json.loads(path.read_text()) | {"loss_tolerance": None}))
    res = pipeline.run(m, _request(m), manifest_dir=out)
    assert res.comparison is None
    assert [r.action for r in res.recommendations] == ["not_knowable"]
    assert "no loss tolerance set" in res.recommendations[0].guarantee.slots["reason"]


def test_client_run_with_unknown_prior_fails_G8(tmp_path: Path) -> None:
    out, m = _dataset(tmp_path)
    m = _as_client(out, m, {})
    with pytest.raises(C.GateFailure) as ei:
        pipeline.run(m, _request(m, priors={"ctr": "pr_00000000"}), manifest_dir=out)
    assert ei.value.result.gate == "G8"


def test_client_run_with_approved_economics_runs(tmp_path: Path) -> None:
    out, m = _dataset(tmp_path)
    m = _as_client(out, m, {})
    res = pipeline.run(m, _request(m), manifest_dir=out)
    assert res.comparison is not None
    assert all(not q.provenance.synthetic for q in res.quantities)
    assert res.recommendations[0].action == "allocate"
    # allocate found the economics (no "not found" notice)
    assert not any("not found" in n for n in res.recommendations[0].params["notices"])


def test_metric_ctr_needs_an_impressions_horizon(tmp_path: Path) -> None:
    out, m = _dataset(tmp_path)
    with pytest.raises(ValueError, match="impressions"):
        pipeline.run(m, _request(m, metric="ctr"), manifest_dir=out)
    req = _request(m, metric="ctr", horizon=C.Horizon(unit="impressions", amount=Decimal(10000)))
    res = pipeline.run(m, req, manifest_dir=out)
    assert res.comparison is not None and res.comparison.objective.target == "clicks"


def test_variants_must_share_one_platform(tmp_path: Path) -> None:
    _, m = _dataset(tmp_path)
    with pytest.raises(ValueError, match="at least two"):
        pipeline.comparison_platform(m, ["A"])
    with pytest.raises(ValueError, match="entity_map"):
        pipeline.comparison_platform(m, ["A", "Z"])


def test_socket_edges(tmp_path: Path) -> None:
    out, _ = _dataset(tmp_path)
    res = sock.compare(
        f"file://{out / MANIFEST_NAME}",
        metric="cvr",
        variants=["A", "B"],
        priors={},
        window={"start": "2026-10-01", "end": "2026-10-14"},
        segments={},
    )
    assert res["uncertainty"]["horizon"]["unit"] == "clicks"  # registry default horizon
    run_id = res["uncertainty"]["run_id"]
    with pytest.raises(KeyError):
        sock.record_outcome("rec_nothere", {"revenue": 1})
    rid = sock.recommendations(run_id)[0]["recommendation_id"]
    sock.record_outcome(rid, {"regret": 0.0})
    assert len(run_record.read("OutcomeRecord", recommendation_id=rid)) == 1
    with pytest.raises(C.GateFailure) as ei:
        sock.render_report(run_id, "client", [])
    assert ei.value.result.gate == "G10"
    path = sock.render_report(run_id, "internal", [])
    assert Path(path).exists() and "INTERNAL" in Path(path).read_text()
    g5 = sock.check_narrative({"text": "Ad ad_b caused more orders."}, run_id)
    assert g5["gate"] == "G5" and g5["passed"] is False
    ev = sock.observation_evidence(res, "tr_9")
    assert ev["configuration"]["metric"] == "cvr"


def test_inventory_class_mapping() -> None:
    f = sock.inventory_class
    assert f("platform_attributed", "observational", True) == "simulation"
    assert f("deterministic", "none", False) == "deterministic derived quantity"
    assert f("platform_attributed", "observational", False) == "model inference / prediction"
    between = "experimental estimate (between"
    assert f("platform_attributed", "randomized", False).startswith(between)
    assert f("causally_incremental", "holdout", False) == "experimental estimate (incremental)"
    assert f("commercially_realized", "observational", False).endswith("commercially realized data")


def test_demo_cli_prints_plain_stages_and_writes_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli_main(["demo", "--scenario", "north_pier_day14", "--out", str(tmp_path / "demo")])
    text = capsys.readouterr().out
    assert code == 0
    labels = [line.split(":", 1)[0] for line in text.splitlines()[1:]]
    assert labels[:4] == ["Simulated", "Pulled", "Quarantined", "Fitted"]
    assert "Report" in labels and "Recommendation" in labels and "Diagnostics" in labels
    assert "exact per-ad model" in text and "—" not in text
    report = next((tmp_path / "demo").glob("report_*_demo.html"))
    assert "DEMO" in report.read_text()
