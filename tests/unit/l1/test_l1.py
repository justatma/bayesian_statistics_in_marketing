"""L1 unit checks beyond the frozen tests: conversion_type, lead detection, account text."""

from __future__ import annotations

from typing import Any

from bayesian_marketing.data_contract.connectors import meta


def _el(actions: list[str], values: list[str] | None = None) -> dict[str, Any]:
    return {
        "actions": [{"action_type": a, "value": "1"} for a in actions],
        "action_values": [{"action_type": a, "value": "10"} for a in values or []],
    }


def test_conversion_type_wanted_found_in_actions_only() -> None:
    assert meta.conversion_type([_el(["link_click"]), _el(["lead"])], "lead") == "lead"


def test_conversion_type_wanted_found_in_action_values_only() -> None:
    assert meta.conversion_type([_el([], ["omni_purchase"])], "omni_purchase") == "omni_purchase"


def test_conversion_type_wanted_absent_is_none_even_with_purchases() -> None:
    assert meta.conversion_type([_el(["omni_purchase"], ["omni_purchase"])], "lead") is None


def test_conversion_type_no_wanted_keeps_purchase_order() -> None:
    els = [_el(["offsite_conversion.fb_pixel_purchase", "purchase"])]
    assert meta.conversion_type(els, None) == "purchase"
    assert meta.conversion_type([_el(["lead"])], None) is None
    assert meta.conversion_type([], None) is None


def test_is_lead_event() -> None:
    assert meta.is_lead_event("lead")
    assert meta.is_lead_event("onsite_web_lead")
    assert meta.is_lead_event("offsite_conversion.fb_pixel_lead")
    assert not meta.is_lead_event("omni_purchase")
    assert not meta.is_lead_event(None)


def test_account_fields_text_and_absent() -> None:
    info = {"name": "X", "account_status": 1, "spend_cap": "", "currency": "USD", "other": "y"}
    assert meta._account(info) == {"name": "X", "account_status": "1", "currency": "USD"}
