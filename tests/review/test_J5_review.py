"""Blind review of J5 at 8b4fd4c. Every test here is a finding or a recorded pass."""

from __future__ import annotations

import re

import pytest
import yaml
from tests.acceptance.test_J5 import J5Env, LEAD, config, lead_run, purchase_run
from tests.acceptance.conftest import iso  # noqa: F401
from tests.fakes import builders as B

from bayesian_marketing import core as C
from bayesian_marketing.atmaos import socket as sock
from bayesian_marketing.claims import vocab as V
from bayesian_marketing.claims.check import check_narrative, display_value
from bayesian_marketing.core import NarrativeBlock

pytestmark = pytest.mark.piece("J5")


@pytest.fixture
def env(iso, tmp_path, monkeypatch) -> J5Env:
    return J5Env(tmp_path, monkeypatch)


def _q(name: str, value: float, ad: str = "ad_a") -> C.Quantity:
    q = B.quantity(name, ad, route="deterministic")
    s = dict.fromkeys(("mean", "q05", "q50", "q95", "q025", "q975"), value)
    return q.model_copy(update={"estimate": q.estimate.model_copy(update={"summary": s})})


def _g5(text: str, kind: str, name: str = "cpa", value: float = 3.35):
    b = B.bundle(quantities=[_q(name, value)]).model_copy(update={"conversion_kind": kind})
    return check_narrative(NarrativeBlock(block_id="b1", text=text, author="atmaos"), b)


def _old_snapshot(env: J5Env, client: str = "demo"):
    s = env.snapshot(purchase_run(env))
    return s.model_copy(update={"conversion_kind": None, "client_id": client})


# ---- findings -------------------------------------------------------------------------------


def test_F1_malformed_yaml_config_does_not_crash_conversion_kind_of(env: J5Env) -> None:
    """A malformed client yaml raises yaml.YAMLError out of conversion_kind_of (not caught)."""
    old = _old_snapshot(env)
    (env.config_root / f"{old.client_id}.yaml").write_text("client_id: [unclosed\n  x: : :")
    assert sock.conversion_kind_of(old) == "purchase"


def test_F2_unreadable_config_path_does_not_crash_conversion_kind_of(env: J5Env) -> None:
    """A config path that is a directory raises IsADirectoryError (OSError, not caught)."""
    old = _old_snapshot(env)
    (env.config_root / f"{old.client_id}.yaml").mkdir()
    assert sock.conversion_kind_of(old) == "purchase"


def test_F3_hyphenated_purchase_word_refused_on_lead() -> None:
    """'pre-order' and 're-order' contain the word order but the (?<![\\w-]) guard skips them."""
    for w in ("pre-order", "re-order", "per-order"):
        g = _g5(f"Ad ad_a had a cost per sign-up of $3.35 for each {w}.", "lead")
        assert g.passed is False, (w, g.reasons)


def test_F4_lead_label_tables_name_no_purchase_word() -> None:
    """labels('lead') still has 'average order value' (aov); the lead aliases keep 'order value'."""
    labs, aliases = V.labels("lead")
    pat = re.compile(r"\b(order|orders|purchase|purchases)\b", re.I)
    bad = {k: v for k, v in labs.items() if pat.search(v)}
    bad |= {k: a for k, v in aliases.items() for a in v if pat.search(a)}
    assert not bad, bad


# ---- passes (no finding), kept as regression probes ------------------------------------------


@pytest.mark.parametrize("word", ["border", "reordered", "purchased", "disordered"])
def test_P_purchase_word_inside_other_word_not_refused(word: str) -> None:
    g = _g5(f"Ad ad_a had a cost per sign-up of $3.35 and was {word}.", "lead")
    assert g.passed is True, g.reasons


@pytest.mark.parametrize("val", [3.345, 3.355, 0.005])
def test_P_lead_boundaries_agree_between_check_and_display(val: float) -> None:
    q = _q("cpa", val)
    shown = display_value(q, val, "lead")
    assert shown == f"{val:,.2f}"
    g = _g5(f"Ad ad_a had a cost per sign-up of ${shown}.", "lead", value=val)
    assert g.passed is True, g.reasons


def test_P_lead_cpc_cents_and_cpm_whole() -> None:
    assert _g5("Ad ad_a had a cost per click of $0.42.", "lead", "cpc", 0.42).passed
    assert _g5("Ad ad_a had a cost per thousand impressions of $13.", "lead", "cpm", 12.6).passed


def test_P_purchase_cpa_unchanged() -> None:
    g = _g5("Ad ad_a had a cost per order of $3.", "purchase")
    assert g.passed is True, g.reasons


def test_P_purchase_word_in_other_sentence_not_refused() -> None:
    g = _g5("Orders are not tracked here. Ad ad_a had a cost per sign-up of $3.35.", "lead")
    assert g.passed is True, g.reasons


def test_P_old_snapshot_key_absent_through_every_socket_call(env: J5Env) -> None:
    run_id = lead_run(env)
    env.rewrite(run_id, lambda d: d.pop("conversion_kind"))
    s = env.snapshot(run_id)
    assert s.conversion_kind is None
    assert sock.conversion_kind_of(s) == "lead"
    result = env.in_data(sock.result_of, s)
    env.in_data(sock.recommendations, run_id)
    env.in_data(sock.observation_evidence, result, "t1")
    assert env.check(run_id, "Ad ad_a is rough.")["gate"] == "G5"
    html = env.report(run_id)
    body = re.sub(r"<[^>]*>", " ", html.split("<body", 1)[1]).lower()
    assert "cost per sign-up" in body


def test_P_config_oddities_fall_back_to_purchase(env: J5Env) -> None:
    old = _old_snapshot(env)
    p = env.config_root / f"{old.client_id}.yaml"
    for body in ("", "- a\n- b\n", "client_id: other\n", "conversion_event: {zzz: foo}\n"):
        p.write_text(body)
        assert sock.conversion_kind_of(old) == "purchase", body
    cfg = config(**LEAD).model_dump(mode="json")
    cfg["client_id"] = old.client_id
    cfg["conversion_event"] = {"tiktok": "lead"}
    p.write_text(yaml.safe_dump(cfg))
    assert sock.conversion_kind_of(old) == "purchase"
    cfg["conversion_event"] = {"meta": "offsite_conversion.fb_pixel_lead"}
    p.write_text(yaml.safe_dump(cfg))
    assert sock.conversion_kind_of(old.model_copy(update={"synthetic": True})) == "purchase"
    assert sock.conversion_kind_of(old) == "lead"
