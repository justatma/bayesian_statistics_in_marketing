"""L5 unit checks beyond the frozen tests (D46): a lead run prices nothing anywhere, cpa (the
cost per lead) stays, and a purchase request hashes exactly as before ``conversion_kind``."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.acceptance.test_L5 import LEAD_EVENT, LEAD_TEXT, VALUED, WINDOW, Env, config

from bayesian_marketing import core as C
from bayesian_marketing import pipeline
from bayesian_marketing.core.base import canonical_json
from bayesian_marketing.live.refresh import _conversion_kind


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    return Env(tmp_path, monkeypatch)


def _request(**kw: object) -> C.CompareRequest:
    return C.CompareRequest(
        metric="ctr",
        variants=["a", "b"],
        priors={},
        window=WINDOW,
        horizon=C.Horizon(unit="impressions", amount="1000"),
        **kw,  # type: ignore[arg-type]
    )


def test_lead_run_recommendations_name_no_price(env: Env) -> None:
    rec = env.run(config(conversion_event={"meta": LEAD_EVENT}))
    assert rec.status == "ran", rec.reason
    snap = env.snapshot(rec.run_id)
    assert snap.recommendations
    for r in snap.recommendations:
        text = r.model_dump_json()
        assert "contribution_per_click" not in text
        assert "contribution per click" not in text


def test_lead_run_keeps_cost_per_lead(env: Env) -> None:
    rec = env.run(config(conversion_event={"meta": LEAD_EVENT}))
    snap = env.snapshot(rec.run_id)
    for ad in ("ad_a", "ad_b"):
        got = {q.name for q in snap.quantities if q.scope.ids.get("ad") == ad}
        assert "cpa" in got, got
        assert not set(VALUED) & got
        assert "cpa" not in snap.not_estimable.get(ad, {})


def test_purchase_request_hashes_as_before_the_field() -> None:
    req = _request()
    old = req.model_dump(mode="json")
    del old["conversion_kind"]
    assert canonical_json(pipeline._request_key(req)) == canonical_json(old)
    lead = _request(conversion_kind="lead")
    assert canonical_json(pipeline._request_key(lead)) != canonical_json(old)


@pytest.mark.parametrize(
    ("events", "kind"),
    [
        ({"meta": LEAD_EVENT}, "lead"),
        ({"meta": "offsite_conversion.fb_pixel_purchase"}, "purchase"),
        ({}, "purchase"),
    ],
)
def test_conversion_kind_from_config(events: dict[str, str], kind: str) -> None:
    assert _conversion_kind(config(conversion_event=events)) == kind


def test_lead_text_is_the_constant() -> None:
    assert pipeline.LEAD_NOT_VALUED == LEAD_TEXT
