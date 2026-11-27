"""J5 unit checks for the live view: a lead run's engine lines say sign-ups with cost-per money in
cents, through ``finding_lines``, ``not_knowable_lines`` and ``view._engine``; purchase lines are
the defaults, unchanged."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.fakes import builders as B

from bayesian_marketing import core as C
from bayesian_marketing import pipeline
from bayesian_marketing.claims import vocab as V
from bayesian_marketing.core import registries
from bayesian_marketing.live import view
from bayesian_marketing.reporting.render import finding_lines, not_knowable_lines

PHR = registries.load("phrasing")


def _q(name: str, value: float, status: str = "estimable") -> C.Quantity:
    q = B.quantity(name, "ad_a", route="deterministic", status=status)
    summary = dict.fromkeys(("mean", "q05", "q50", "q95", "q025", "q975"), value)
    return q.model_copy(update={"estimate": q.estimate.model_copy(update={"summary": summary})})


def test_finding_lines_lead_cpa_and_cpc_in_cents() -> None:
    cpa = finding_lines(_q("cpa", 3.35), PHR, "lead")
    assert cpa["label"] == "cost per sign-up"
    assert (cpa["estimate"], cpa["low"], cpa["high"]) == ("3.35", "3.35", "3.35")
    cpc = finding_lines(_q("cpc", 0.42), PHR, "lead")
    assert cpc["label"] == "cost per click" and cpc["estimate"] == "0.42"


def test_finding_lines_lead_cpm_and_rates_unchanged() -> None:
    cpm = _q("cpm", 12.6)
    assert finding_lines(cpm, PHR, "lead")["estimate"] == V.fmt_value(cpm, 12.6) == "13"
    cvr = finding_lines(_q("cvr", 0.05), PHR, "lead")
    assert cvr["label"] == "sign-up rate" and cvr["estimate"] == V.fmt_percent(0.05)


@pytest.mark.parametrize("name", ["cpa", "cpc", "cpm", "cvr", "ctr"])
def test_finding_lines_purchase_default_unchanged(name: str) -> None:
    q = _q(name, 3.35)
    default = finding_lines(q, PHR)
    assert default == finding_lines(q, PHR, "purchase")
    assert default["label"] == V.METRIC_LABELS[name]
    assert default["estimate"] == V.fmt_value(q, 3.35)


def test_not_knowable_lines_lead_says_sign_up() -> None:
    q = _q("cpa", 3.35, status="below_floor")
    lead = not_knowable_lines(q, PHR, "lead")
    assert "cost per sign-up for ad_a" in lead["text"] and "order" not in lead["text"]
    purchase = not_knowable_lines(q, PHR)
    assert purchase == not_knowable_lines(q, PHR, "purchase")
    assert "cost per order for ad_a" in purchase["text"]


def _engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str | None) -> dict:
    snap = SimpleNamespace(
        conversion_kind=kind,
        synthetic=False,
        client_id="no_such_client",
        quantities=[_q("cpa", 3.35), _q("cpc", 0.42), _q("cvr", 0.05, status="below_floor")],
        diagnostics=[],
    )
    monkeypatch.setattr(pipeline, "load_snapshot", lambda run_id: snap)
    monkeypatch.setenv("BAYES_CONFIG_DIR", str(tmp_path))  # no config: a None kind is purchase
    rec = SimpleNamespace(status="ran", run_id="run_00000001", reason=None)
    store = SimpleNamespace(latest_refresh=lambda client_id: rec)
    live = {"no_diagnostics": "none"}
    return view._engine(store, "no_such_client", PHR, tmp_path, live)  # type: ignore[arg-type]


def test_engine_lead_run_says_sign_ups_in_cents(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    e = _engine(monkeypatch, tmp_path, "lead")
    cpa, cpc = (f["cells"] for f in e["findings"])
    assert cpa[1:3] == ["cost per sign-up", "3.35"]
    assert cpc[1:3] == ["cost per click", "0.42"]
    (nk,) = e["not_knowable"]
    assert "sign-up rate for ad_a" in nk["text"]
    words = " ".join([*cpa, *cpc, nk["text"]])
    assert not any(w in words.split() for w in V.PURCHASE_WORDS), words


@pytest.mark.parametrize("kind", ["purchase", None])
def test_engine_purchase_run_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str | None
) -> None:
    e = _engine(monkeypatch, tmp_path, kind)
    cpa, cpc = (f["cells"] for f in e["findings"])
    assert cpa[1:3] == ["cost per order", "3"]
    assert cpc[1:3] == ["cost per click", "0"]
    for f, q in zip(e["findings"], (_q("cpa", 3.35), _q("cpc", 0.42)), strict=True):
        lines = finding_lines(q, PHR)
        assert f["cells"] == [str(lines[k]) for k in view._FINDING_KEYS]
    (nk,) = e["not_knowable"]
    assert "conversion rate for ad_a" in nk["text"]
