"""L1 connector widening (live view spec v0.2 §3.1 to §3.3, §5 L1; build log B2, B4, B7).

Every pull below goes through ``pull("meta", ...)`` against ``meta_handler`` on an httpx mock
transport, or replays a recording with sockets blocked. No network.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from bayesian_marketing import core as C
from bayesian_marketing.data_contract.connectors import http as H
from bayesian_marketing.data_contract.connectors import meta
from bayesian_marketing.data_contract.connectors.pull import pull
from tests.fakes.meta_api import ACCOUNT, META_TOKEN, _meta_row, meta_handler

pytestmark = pytest.mark.piece("L1")

REPO = Path(__file__).resolve().parents[2]
REC = REPO / "data" / "recordings"
WINDOW = (dt.date(2026, 10, 1), dt.date(2026, 10, 2))
DAY = "2026-10-01"
REAL_CLIENT = httpx.Client
ACCOUNT_KEYS = ("timezone_name", "currency", "name", "account_status", "spend_cap", "amount_spent")


def _config(**kw: Any) -> C.ClientConfig:
    base: dict[str, Any] = {
        "client_id": "unit_client",
        "timezone": "America/Los_Angeles",
        "currency": "USD",
        "accounts": {"meta": "act_111"},
    }
    base.update(kw)
    return C.ClientConfig(**base)


@pytest.fixture
def creds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(H.REPLAY_ENV, raising=False)
    monkeypatch.delenv(H.RECORD_ENV, raising=False)
    monkeypatch.setenv("META_ACCESS_TOKEN", META_TOKEN)
    monkeypatch.setattr(H, "BACKOFF_BASE_S", 0.0)


def _mock(monkeypatch: pytest.MonkeyPatch, handler: Any) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(
        H.httpx, "Client", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(wrapped), **kw)
    )
    return seen


def _pull(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict[str, Any]],
    config: C.ClientConfig | None = None,
    **handler_kw: Any,
) -> C.PlatformPull:
    _mock(monkeypatch, meta_handler(rows, **handler_kw))
    return pull("meta", config or _config(), WINDOW)


def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access during replay")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)


def _replay(monkeypatch: pytest.MonkeyPatch, name: str) -> C.PlatformPull:
    _block_network(monkeypatch)
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)
    d = REC / name
    req = json.loads((d / "request.json").read_text())
    config = C.ClientConfig.model_validate(req["config"])
    window = tuple(dt.date.fromisoformat(x) for x in req["window"])
    monkeypatch.setenv("BAYES_REPLAY_DIR", str(d))
    return pull("meta", config, window)  # type: ignore[arg-type]


def _el(kind: str, value: str) -> dict[str, str]:
    return {"action_type": kind, "value": value}


# ------------------------------------------------------------------ names and objective


def test_L1_entity_names_fill_four_keys(creds: None, monkeypatch: pytest.MonkeyPatch) -> None:
    row = _meta_row(
        "a1",
        DAY,
        account_name="Acct Name",
        campaign_name="Camp Name",
        adset_name="Set Name",
        ad_name="Ad Name",
    )
    p = _pull(monkeypatch, [row])
    assert len(p.rows) == 1
    # L1 check 1, B4: keys are the entity_ids keys, suffix stripped
    assert p.rows[0].entity_names == {
        "account": "Acct Name",
        "campaign": "Camp Name",
        "ad_set": "Set Name",
        "ad": "Ad Name",
    }
    assert set(p.rows[0].entity_names) == set(p.rows[0].entity_ids)


def test_L1_objective_filled_when_requested(creds: None, monkeypatch: pytest.MonkeyPatch) -> None:
    row = _meta_row("a1", DAY, objective="OUTCOME_LEADS")
    p = _pull(monkeypatch, [row])
    if meta.OBJECTIVE_REQUESTED:
        assert p.rows[0].objective == "OUTCOME_LEADS"  # L1 check 2, §3.1
    else:
        pytest.skip("OBJECTIVE_REQUESTED is False: no acceptance test depends on objective (§3.1)")


# ------------------------------------------------------------------ conversion event


def test_L1_lead_event_counts_lead_and_never_values_it(
    creds: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _meta_row(
        "a1",
        DAY,
        actions=[_el("link_click", "40"), _el("lead", "5"), _el("omni_purchase", "2")],
        action_values=[_el("omni_purchase", "90"), _el("lead", "50")],
    )
    p = _pull(monkeypatch, [row], _config(conversion_event={"meta": "lead"}))
    [r] = p.rows
    assert r.conversions_reported == 5.0  # L1 check 3, §3.2: count from the wanted type
    assert r.revenue_reported is None  # L1 check 3, D33: a lead is never valued
    assert any("conversion event lead used" in n for n in p.notes)  # L1 check 3
    # L1 check 5: the same elements with no conversion_event give omni_purchase and its value
    p2 = _pull(monkeypatch, [row], _config())
    [r2] = p2.rows
    assert r2.conversions_reported == 2.0
    assert r2.revenue_reported == C.Money(amount="90.00", currency="USD")


def test_L1_lead_string_containing_lead_is_a_lead_event(
    creds: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    ev = "offsite_conversion.fb_pixel_lead"
    row = _meta_row(
        "a1",
        DAY,
        actions=[_el("link_click", "40"), _el(ev, "3")],
        action_values=[_el(ev, "30")],
    )
    p = _pull(monkeypatch, [row], _config(conversion_event={"meta": ev}))
    [r] = p.rows
    assert r.conversions_reported == 3.0  # L1 §3.2
    assert r.revenue_reported is None  # L1 §3.2: a config event containing "lead" is a lead event
    assert any(f"conversion event {ev} used" in n for n in p.notes)


def test_L1_lead_event_absent_gives_zero_rows_and_note(
    creds: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        _meta_row(
            ad,
            DAY,
            actions=[_el("link_click", "40"), _el("omni_purchase", "2")],
            action_values=[_el("omni_purchase", "90")],
        )
        for ad in ("a1", "a2")
    ]
    p = _pull(monkeypatch, rows, _config(conversion_event={"meta": "lead"}))
    assert len(p.rows) == 2  # L1 check 4: rows are still stored
    assert all(r.conversions_reported == 0.0 for r in p.rows)  # L1 check 4
    assert all(r.revenue_reported is None for r in p.rows)  # L1 §3.2 lead event
    assert any("conversion event lead not seen in this pull" in n for n in p.notes)  # L1 check 4
    assert not any("conversion event lead used" in n for n in p.notes)  # L1 check 4


def test_L1_non_lead_event_takes_count_and_value_from_its_type(
    creds: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _meta_row(
        "a1",
        DAY,
        actions=[_el("link_click", "40"), _el("omni_purchase", "4"), _el("lead", "9")],
        action_values=[_el("omni_purchase", "120.00")],
    )
    p = _pull(monkeypatch, [row], _config(conversion_event={"meta": "omni_purchase"}))
    [r] = p.rows
    assert r.conversions_reported == 4.0  # L1 §3.2 [2.5]
    assert r.revenue_reported == C.Money(amount="120.00", currency="USD")  # L1 §3.2 [2.5]
    assert any("conversion event omni_purchase used" in n for n in p.notes)


# ------------------------------------------------------------------ account fields


def test_L1_account_fields_land_as_text(creds: None, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _pull(monkeypatch, [_meta_row("a1", DAY)])
    for key in ACCOUNT_KEYS:  # L1 check 6, §3.3
        assert key in p.account, key
        assert isinstance(p.account[key], str), key
    assert p.account["account_status"] == "1"  # L1 check 6: an int in the API body, text here
    assert p.account["spend_cap"] == ACCOUNT["spend_cap"]
    assert p.account["amount_spent"] == ACCOUNT["amount_spent"]
    assert p.account["name"] == ACCOUNT["name"]
    assert p.account["currency"] == "USD"
    assert p.account["timezone_name"] == ACCOUNT["timezone_name"]


def test_L1_missing_account_key_is_absent_not_blank(
    creds: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = {k: v for k, v in ACCOUNT.items() if k != "spend_cap"}
    p = _pull(monkeypatch, [_meta_row("a1", DAY)], account=account)
    assert "spend_cap" not in p.account  # L1 §3.3: missing keys absent
    assert p.account["amount_spent"] == ACCOUNT["amount_spent"]  # L1 §3.3: the rest still land


# ------------------------------------------------------------------ recordings


def test_L1_meta_empty_replays_empty_with_account_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    p = _replay(monkeypatch, "meta_empty")
    assert p.empty_account is True  # L1 check 7
    assert p.rows == []
    for key in ACCOUNT_KEYS:  # L1 §3.3 on the re-recorded account response
        assert key in p.account, key


def test_L1_p8_meta_tests_unchanged_and_new_recording_carries_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # L1 check 8: the P8 meta replay tests pass unchanged on the new recordings. The three other
    # P8 failures at the time of writing (google_ads and linkedin recordings, secrets scan) are
    # not L1's, so only the meta tests are run. They run in a child process with the piece gate.
    env = {**os.environ, "BAYES_PIECES": "P8"}
    env.pop("BAYES_REPLAY_DIR", None)
    out = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests/acceptance/test_P8.py",
            "-k",
            "meta_replay or empty_account",
        ],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stdout[-2000:]  # L1 check 8
    # and the 7-day recording, made with the widened field lists, parses into names (B7)
    p = _replay(monkeypatch, "meta_jovannah_7d")
    assert p.rows
    assert all(set(r.entity_names) == {"account", "campaign", "ad_set", "ad"} for r in p.rows)
    assert all(r.entity_names["ad"] for r in p.rows)  # L1 §3.1 on a real response
    assert p.account["name"] == "Jovannah"  # L1 §3.3 on a real response
