"""Blind review of L1 (a90969f). Helpers come from the frozen acceptance module."""

from __future__ import annotations

import pytest
from tests.acceptance.test_L1 import DAY, _config, _el, _pull, creds  # noqa: F401
from tests.fakes.meta_api import ACCOUNT, _meta_row

pytestmark = pytest.mark.piece("L1")


@pytest.mark.parametrize("name", ["001", "1e3", "10.50", "1_000"])
def test_entity_names_are_not_numerically_rewritten(creds, monkeypatch, name):  # noqa: F811
    """§3.1: names land as the API states them. A campaign called '001' must stay '001'."""
    row = _meta_row("a1", DAY, campaign_name=name, ad_name=name, adset_name=name, account_name=name)
    [r] = _pull(monkeypatch, [row]).rows
    assert r.entity_names == {"account": name, "campaign": name, "ad_set": name, "ad": name}


@pytest.mark.parametrize("name", ["007", "1E5"])
def test_account_name_is_raw_text(creds, monkeypatch, name):  # noqa: F811
    """§3.3: Fetched.account holds the API's raw values as text."""
    account = {**ACCOUNT, "name": name}
    p = _pull(monkeypatch, [_meta_row("a1", DAY)], account=account)
    assert p.account["name"] == name


def test_wanted_not_seen_note_on_empty_pull(creds, monkeypatch):  # noqa: F811
    """§3.2: when wanted appears in neither actions nor action_values, the note reads
    'conversion event {wanted} not seen in this pull'. An empty pull has it in neither."""
    p = _pull(monkeypatch, [], _config(conversion_event={"meta": "lead"}))
    assert any("conversion event lead not seen in this pull" in n for n in p.notes)
