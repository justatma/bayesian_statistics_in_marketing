"""P8 connectors (spec v0.3 §5.1 C4, C6; §16).

# CONTRACT ASSUMPTION: recordings live under data/recordings/<platform>/ for meta, google_ads,
#   linkedin and ga4, plus data/recordings/meta_empty/ for an empty account. Each directory holds
#   request.json = {"config": <ClientConfig JSON>, "window": ["YYYY-MM-DD", "YYYY-MM-DD"]} naming
#   the pull the recording answers.
# CONTRACT ASSUMPTION: with the environment variable BAYES_REPLAY_DIR set to such a directory,
#   pull() serves every exchange from it and opens no socket. The tests block sockets to prove it.
# CONTRACT ASSUMPTION: each connector module data_contract/connectors/<platform>.py defines
#   ENDPOINTS and FIELDS (tuples of str) listing every endpoint and field it names; each must
#   appear verbatim in its facts pack: meta F2_meta.md, google_ads F3_*.md, linkedin F4_*.md,
#   ga4 F5_*.md under spec/facts/.
"""

from __future__ import annotations

import datetime as dt
import importlib
import json
import re
import socket
from pathlib import Path

import pytest

from bayesian_marketing import core as C
from bayesian_marketing.data_contract.connectors.pull import pull

pytestmark = pytest.mark.piece("P8")

REPO = Path(__file__).resolve().parents[2]
REC = REPO / "data" / "recordings"
FACTS = REPO / "spec" / "facts"
PACKS = {"meta": "F2_", "google_ads": "F3_", "linkedin": "F4_", "ga4": "F5_"}
CONNECTOR_PLATFORMS = ["meta", "google_ads", "linkedin", "ga4"]


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access during a replay test")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def _replay(platform: str, dirname: str, monkeypatch: pytest.MonkeyPatch) -> C.PlatformPull:
    d = REC / dirname
    req = json.loads((d / "request.json").read_text())
    config = C.ClientConfig.model_validate(req["config"])
    window = (dt.date.fromisoformat(req["window"][0]), dt.date.fromisoformat(req["window"][1]))
    monkeypatch.setenv("BAYES_REPLAY_DIR", str(d))
    p = pull(platform, config, window)
    assert p.platform == platform
    assert p.pull_id.startswith(f"pull_{platform}_")
    assert p.window == window
    assert p.account_id == config.accounts[platform]
    assert p.timezone, "the account timezone the dates were normalized from (C2)"
    return p


def _replay_parses(platform: str, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _replay(platform, platform, monkeypatch)
    assert p.rows, "a recording for a live account returns rows"
    assert p.empty_account is False
    kind = C.SiteRow if platform == "ga4" else C.PerformanceRow
    assert all(isinstance(r, kind) for r in p.rows)
    if kind is C.PerformanceRow:
        assert all(r.attribution_window for r in p.rows)
        assert all(p.window[0] <= r.date <= p.window[1] for r in p.rows)
    # C4: a re-pull gets a new pull_id
    again = _replay(platform, platform, monkeypatch)
    assert again.pull_id != p.pull_id
    assert [r.model_dump() for r in again.rows] == [r.model_dump() for r in p.rows]


def test_P8_meta_replay_parses(no_network: None, monkeypatch: pytest.MonkeyPatch) -> None:
    _replay_parses("meta", monkeypatch)


def test_P8_google_ads_replay_parses(no_network: None, monkeypatch: pytest.MonkeyPatch) -> None:
    _replay_parses("google_ads", monkeypatch)


def test_P8_linkedin_replay_parses(no_network: None, monkeypatch: pytest.MonkeyPatch) -> None:
    _replay_parses("linkedin", monkeypatch)


def test_P8_ga4_replay_parses(no_network: None, monkeypatch: pytest.MonkeyPatch) -> None:
    _replay_parses("ga4", monkeypatch)


def test_P8_empty_account_flagged(no_network: None, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _replay("meta", "meta_empty", monkeypatch)
    assert p.rows == []
    assert p.empty_account is True
    assert p.quarantined == []


SECRET_PATTERNS = [
    re.compile(r"EAA[A-Za-z0-9]{20,}"),  # Meta access token
    re.compile(r"ya29\.[A-Za-z0-9_\-]{20,}"),  # Google OAuth access token
    re.compile(r"1//[A-Za-z0-9_\-]{20,}"),  # Google refresh token
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),  # Google API key
    re.compile(r"AQ[A-Za-z0-9_\-]{60,}"),  # LinkedIn access token
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)bearer\s+(?!redacted)[A-Za-z0-9._\-]{16,}"),
]
SECRET_KEYS = re.compile(
    r"(?i)\"?(access_token|refresh_token|client_secret|developer[-_]token|authorization|"
    r"api[-_]?key|private_key|password)\"?\s*[:=]\s*\"?([^\"\s,&}]+)"
)


def test_P8_recordings_contain_no_secrets() -> None:
    files = [p for p in REC.rglob("*") if p.is_file()]
    for platform in CONNECTOR_PLATFORMS:
        assert any(platform in p.parts for p in files), f"no recordings for {platform}"
    leaks = []
    for p in files:
        text = p.read_text(errors="ignore")
        for pat in SECRET_PATTERNS:
            if pat.search(text):
                leaks.append(f"{p.relative_to(REPO)}: {pat.pattern}")
        for m in SECRET_KEYS.finditer(text):
            if m.group(2).strip().upper() not in ("REDACTED", "<REDACTED>", "***", "NULL", ""):
                leaks.append(f"{p.relative_to(REPO)}: {m.group(1)} not redacted")
    assert not leaks, leaks


@pytest.mark.parametrize("platform", CONNECTOR_PLATFORMS)
def test_P8_fields_in_facts_pack(platform: str) -> None:
    mod = importlib.import_module(f"bayesian_marketing.data_contract.connectors.{platform}")
    packs = sorted(FACTS.glob(f"{PACKS[platform]}*.md"))
    assert packs, f"facts pack {PACKS[platform]}* missing for {platform}"
    text = "\n".join(p.read_text() for p in packs)
    names = list(mod.ENDPOINTS) + list(mod.FIELDS)
    assert mod.ENDPOINTS and mod.FIELDS
    missing = [n for n in names if n not in text]
    assert not missing, f"{platform}: not in its facts pack: {missing}"
