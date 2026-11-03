"""P11 review fixes (D38): not-knowable wording, metric/horizon validation, Google lag, the demo
lines, replay scoring and window, the socket's D33, G5 and G6 checks, the comparison label."""

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
from bayesian_marketing.cli import Narrator
from bayesian_marketing.cli import _window as scenario_window
from bayesian_marketing.cli import main as cli_main
from bayesian_marketing.core import registries
from bayesian_marketing.decision import run_record
from bayesian_marketing.decision.reallocation import fmt_money
from bayesian_marketing.lag.model import lag_model, lag_notices, longest_default_window
from bayesian_marketing.simulate import replay as replay_mod
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


def _dataset(tmp_path: Path, name: str) -> tuple[Path, C.DatasetManifest, tuple[dt.date, dt.date]]:
    out = tmp_path / name
    generate(SCEN / f"{name}.yaml", 1, out)
    m = C.DatasetManifest.load(out / MANIFEST_NAME)
    platform = pipeline.comparison_platform(m, sorted(m.entity_map))
    return out, m, scenario_window(m, out, platform)


def _request(m: C.DatasetManifest, window, **kw) -> C.CompareRequest:
    base = {
        "metric": "contribution",
        "variants": sorted(m.entity_map),
        "priors": {},
        "window": window,
        "horizon": C.Horizon(unit="clicks", amount=Decimal(1000)),
    }
    return C.CompareRequest(**(base | kw))


def _nothing_written(tmp_path: Path) -> None:
    assert run_record.read("RunRecord") == []
    assert not (tmp_path / "store" / "states").exists()
    assert not (tmp_path / "store" / "runs").exists()


# ------------------------------------------------------------------ F1 (D38.1)


def test_not_estimable_states_its_own_reason_once(tmp_path: Path) -> None:
    out, m, window = _dataset(tmp_path, "tiny_campaign")
    res = pipeline.run(m, _request(m, window), manifest_dir=out)
    [rec] = res.recommendations
    assert rec.action == "not_knowable"
    slots = rec.guarantee.slots
    assert slots["requirement"] != pipeline.G9_REQUIREMENT
    reason = slots["reason"]
    assert "contribution per click not estimable for" in reason
    first = reason.split(": ", 1)[1]
    assert reason.count(first) == 1, "a reason shared by every ad is said once"


def test_g9_requirement_only_when_g9_is_the_reason(tmp_path: Path) -> None:
    out, m, window = _dataset(tmp_path, "north_pier_day14")
    path = out / "economics" / f"{m.economics_id}.json"
    path.write_text(json.dumps(json.loads(path.read_text()) | {"loss_tolerance": None}))
    res = pipeline.run(m, _request(m, window), manifest_dir=out)
    [rec] = res.recommendations
    assert rec.guarantee.slots["requirement"] == pipeline.G9_REQUIREMENT


# ------------------------------------------------------------------ F2 (D38.2)


@pytest.mark.parametrize(
    "metric,horizon",
    [("ctr", ("clicks", 1000)), ("contribution", ("days", 7)), ("cvr", ("impressions", 10))],
)
def test_metric_horizon_mismatch_refused_before_any_work(
    tmp_path: Path, metric: str, horizon: tuple
) -> None:
    out, m, window = _dataset(tmp_path, "north_pier_day14")
    h = C.Horizon(unit=horizon[0], amount=Decimal(horizon[1]))
    with pytest.raises(ValueError, match="needs a horizon in"):
        pipeline.run(m, _request(m, window, metric=metric, horizon=h), manifest_dir=out)
    with pytest.raises(ValueError, match="needs a horizon in"):
        sock.compare(
            f"file://{out / MANIFEST_NAME}",
            metric=metric,
            variants=sorted(m.entity_map),
            priors={},
            window={"start": "2026-10-01", "end": "2026-10-14", "horizon": dict(
                unit=horizon[0], amount=horizon[1])},
            segments={},
        )  # fmt: skip
    _nothing_written(tmp_path)


def test_socket_ctr_default_horizon_is_impressions(tmp_path: Path) -> None:
    out, m, _ = _dataset(tmp_path, "north_pier_day14")
    res = sock.compare(
        f"file://{out / MANIFEST_NAME}",
        metric="ctr",
        variants=sorted(m.entity_map),
        priors={},
        window={"start": "2026-10-01", "end": "2026-10-14"},
        segments={},
    )
    assert res["uncertainty"]["horizon"]["unit"] == "impressions"
    assert res["uncertainty"]["objective"]["target"] == "clicks"


def test_demo_ctr_runs_and_a_bad_pair_stops_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli_main(["demo", "--metric", "ctr", "--out", str(tmp_path / "demo")])
    text = capsys.readouterr().out
    assert code == 0, text
    assert "1,000 impressions" in text and "Traceback" not in text
    assert "USD tolerance" not in text  # a loss in clicks is not held against money


# ------------------------------------------------------------------ D33 (D38.6)


@pytest.mark.parametrize("metric", ["leads", "subscription_contribution"])
def test_socket_refuses_d33_objectives_naming_the_value_model(tmp_path: Path, metric: str) -> None:
    out, m, _ = _dataset(tmp_path, "north_pier_day14")
    with pytest.raises(C.NotInScope, match="value model"):
        sock.compare(
            f"file://{out / MANIFEST_NAME}",
            metric=metric,
            variants=sorted(m.entity_map),
            priors={},
            window={"start": "2026-10-01", "end": "2026-10-14"},
            segments={},
        )
    _nothing_written(tmp_path)


# ------------------------------------------------------------------ F3, F8 (D38.3)


def _orders(n: int, lag_days: int) -> list[C.OrderRow]:
    out = []
    for i in range(n):
        clicked = dt.datetime(2026, 9, 1, 12, tzinfo=UTC) + dt.timedelta(days=i % 10)
        out.append(
            C.OrderRow(
                order_id=f"o{i}",
                ordered_at=clicked + dt.timedelta(days=lag_days),
                value=C.Money(amount=Decimal("50.00"), currency="USD"),
                refunded=C.Money(amount=Decimal("0"), currency="USD"),
                utm={"campaign": "c"},
                first_click_at=clicked,
            )
        )
    return out


def test_per_conversion_action_lag_from_orders_when_enough() -> None:
    days = longest_default_window()
    lag = lag_model(
        "google_ads", "per_conversion_action", _orders(60, 2), None, click_window_days=days
    )
    assert lag.source == "orders_history" and lag.n_lagged_conversions == 60
    assert any("orders' click dates" in n for n in lag_notices(lag))


def test_per_conversion_action_default_curve_when_too_few() -> None:
    days = longest_default_window()
    lag = lag_model(
        "google_ads", "per_conversion_action", _orders(5, 2), None, click_window_days=days
    )
    assert lag.source == "registry_default" and len(lag.cdf) == days + 1
    notes = lag_notices(lag)
    assert registries.resolve("phrasing/notices/lag_assumed@v1") in notes
    assert any(f"{days}-day default lag curve" in n for n in notes)
    with pytest.raises(ValueError):  # the code alone still names no window (P7 rule kept)
        lag_model("google_ads", "per_conversion_action", None, None)


def test_lag_heavy_is_lag_adjusted_and_refuses_a_premature_stop(tmp_path: Path) -> None:
    out, m, window = _dataset(tmp_path, "lag_heavy")
    ctx = pipeline.execute(m, _request(m, window), manifest_dir=out)
    s = ctx.snapshot
    assert s.configuration["lag"]["source"] == "registry_default"
    assert not any("not adjusted" in n for n in s.notices)
    assert any("per_conversion_action names no click window" in n for n in s.notices)
    actions = [r.action for r in s.recommendations]
    assert "stop_test" not in actions
    assert {"continue_test", "not_knowable"} & set(actions)


def test_narrator_lag_labels_name_the_source(capsys: pytest.CaptureFixture[str]) -> None:
    base = {"n_ads": 2, "n_days": 3, "step": "conjugate", "reports": [], "lag_window": 7}
    for source, n, want in (
        ("orders_history", 60, "estimated from 60 orders' click dates in the orders file"),
        ("platform_lag_report", 0, "taken from the platform's lag report"),
        ("registry_default", 0, "conversion lag assumed (default curve, 7-day click window)"),
    ):
        Narrator()("fitted", base | {"lag_source": source, "lag_n": n, "lag_notices": []})
        assert want in capsys.readouterr().out


# ------------------------------------------------------------------ F4 (D38.4)


@pytest.mark.parametrize(
    "step,want",
    [
        ("nuts_static", "static step"),
        ("nuts_unpooled", "unpooled above the ad"),
        ("fallback_conjugate", "joint funnel model failed its checks"),
    ],
)
def test_narrator_names_the_actual_fit_step(
    step: str, want: str, capsys: pytest.CaptureFixture[str]
) -> None:
    info = {"n_ads": 5, "n_days": 3, "step": step, "reports": [], "lag_source": None,
            "lag_n": None, "lag_window": None, "lag_notices": []}  # fmt: skip
    Narrator()("fitted", info)
    assert want in capsys.readouterr().out


def test_demo_lines_match_the_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = cli_main(["demo", "--scenario", "north_pier_day14", "--out", str(tmp_path / "demo")])
    text = capsys.readouterr().out
    assert code == 0, text
    [snap] = (tmp_path / "store" / "runs").glob("*.json")
    s = pipeline.RunSnapshot.model_validate_json(snap.read_text())
    alloc = next(r for r in s.recommendations if r.action == "allocate")
    loss_line = next(x for x in text.splitlines() if x.startswith("Expected loss"))
    assert fmt_money(alloc.expected_loss) in loss_line and "for this split" in loss_line
    assert "tolerance" in loss_line
    assert all(ad in text for ad in s.variants.values())
    assert " B is best" not in text and " A is best" not in text
    negatives = [o for o, v in s.comparison.expected_value.items() if v.amount < 0]
    if negatives:
        assert "negative" in text and "-" in next(
            x for x in text.splitlines() if x.startswith("Expected value")
        )
    nk = [q for q in s.quantities if q.name == s.compare_quantity]
    if any(q.feasibility.status == "below_floor" for q in nk):
        assert "Not knowable:   contribution per click for" in text
    report = " ".join(next((tmp_path / "demo").glob("report_*_demo.html")).read_text().split())
    assert "Evidence: what the ad platform credited to the ads" in report  # D38.7


# ------------------------------------------------------------------ F5, F6 (D38.5)


def _q(mean: float) -> C.Quantity:
    from types import SimpleNamespace

    return SimpleNamespace(estimate=SimpleNamespace(summary={"mean": mean}))  # type: ignore[return-value]


def test_not_knowable_scored_against_truth_at_the_tolerance() -> None:
    f = replay_mod.not_knowable_correct
    truth = {"A": 0.10, "B": 0.30}
    # the data favour A, which in truth costs (0.30 - 0.10) * 1000 = 200 > 50: correct verdict
    assert f({"A": _q(0.5), "B": _q(0.2)}, truth, 1000.0, 50.0) is True
    # the data favour B, the true best: acting would have been fine, the verdict was wrong
    assert f({"A": _q(0.1), "B": _q(0.4)}, truth, 1000.0, 50.0) is False
    # a gap inside the tolerance: any pick is fine, so not knowable was wrong
    assert f({"A": None, "B": None}, truth, 100.0, 50.0) is False
    # no estimate for some option: any pick may be made, and the worst costs 200 > 50
    assert f({"A": None, "B": _q(0.4)}, truth, 1000.0, 50.0) is True


def test_replay_window_is_its_own_run_time(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fixed = dt.datetime(2026, 1, 2, 9, tzinfo=UTC)
    monkeypatch.setattr(pipeline, "utcnow", lambda: fixed)
    seen: list[dt.date] = []
    monkeypatch.setattr(replay_mod, "guarantee_report", lambda since: seen.append(since))
    _, _, (start, _) = _dataset(tmp_path, "north_pier_day14")
    replay_mod.replay(SCEN / "north_pier_day14.yaml", 1, start, start + dt.timedelta(days=1))
    assert seen == [fixed.date()]


# ------------------------------------------------------------------ F7 (D38.6)


def _run(tmp_path: Path) -> tuple[str, str]:
    out, m, _ = _dataset(tmp_path, "north_pier_day14")
    res = sock.compare(
        f"file://{out / MANIFEST_NAME}",
        metric="cvr",
        variants=sorted(m.entity_map),
        priors={},
        window={"start": "2026-10-01", "end": "2026-10-14"},
        segments={},
    )
    run_id = res["uncertainty"]["run_id"]
    return run_id, res["uncertainty"]["recommendation_ids"][0]


def test_check_narrative_uses_the_runs_bundle(tmp_path: Path) -> None:
    run_id, _ = _run(tmp_path)
    for text in (
        "ad_b converts at 99% and caused sales.",
        "Ad B converts at 99% and it caused sales.",
    ):
        g5 = sock.check_narrative({"text": text}, run_id)
        assert g5["passed"] is False
        assert any("99%" in r for r in g5["reasons"])
        assert any("caused" in r for r in g5["reasons"])
    assert sock.check_narrative({"text": "Hello."}, run_id)["passed"] is True


def test_record_approval_one_decision_and_a_person(tmp_path: Path) -> None:
    _, rid = _run(tmp_path)
    when = "2026-11-03T10:00:00+00:00"
    for who in ("system", "System", " engine "):
        with pytest.raises(C.GateFailure) as ei:
            sock.record_approval(rid, "apr_0", "approved", who, when)
        assert ei.value.result.gate == "G6"
    sock.record_approval(rid, "apr_1", "approved", "Atma", when)
    for decision in ("approved", "rejected"):
        with pytest.raises(C.GateFailure) as ei:
            sock.record_approval(rid, "apr_2", decision, "Atma", when)
        assert ei.value.result.gate == "G6"
        assert any("already has a decision" in r for r in ei.value.result.reasons)
    assert len(run_record.read("ApprovalRecord", recommendation_id=rid)) == 1
