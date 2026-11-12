"""L10 unit checks beyond the frozen tests: the one-level cap holds for every mismatch count,
and ``horizon_basis`` never reaches the request key whatever its text (D52, S6)."""

from __future__ import annotations

import datetime as dt

import pytest
from tests.fakes import builders as B

from bayesian_marketing import core as C
from bayesian_marketing import pipeline
from bayesian_marketing.core import registries
from bayesian_marketing.core.base import canonical_json
from bayesian_marketing.floors.estimability import quantity_feasibility, registry_target

KEYS = ("lag_approx", "too_few_ads", "platform_modeled", "joint_failed")


def _notice(key: str) -> str:
    return registries.resolve(f"phrasing/notices/{key}@v1")


def _feasibility(width: tuple[int, int], keys: tuple[str, ...]) -> C.Feasibility:
    q = B.quantity("ctr", estimate=B.beta_spec(*width), notices=[_notice(k) for k in keys])
    return quantity_feasibility(q, registry_target())


@pytest.mark.parametrize("n", [1, 2, 3, 4])
def test_cap_is_one_level_for_any_count(n: int) -> None:
    f = _feasibility((400, 19600), KEYS[:n])
    assert f.status == "marginal"
    regime = [f"regime mismatch: {_notice(k)}" for k in KEYS]
    assert [r for r in f.reasons if r in regime] == regime[:n]


def test_repeated_notice_still_one_level() -> None:
    f = _feasibility((400, 19600), ("lag_approx", "lag_approx"))
    assert f.status == "marginal"
    assert f.reasons.count(f"regime mismatch: {_notice('lag_approx')}") == 2  # all kept


def test_below_floor_stays_below_floor() -> None:
    assert _feasibility((3, 97), ()).status == "below_floor"
    assert _feasibility((3, 97), KEYS).status == "below_floor"


def _req(kind: str, basis: str | None) -> C.CompareRequest:
    return C.CompareRequest(
        metric="ctr",
        variants=["a", "b"],
        priors={},
        window=(dt.date(2026, 11, 1), dt.date(2026, 11, 7)),
        horizon=C.Horizon(unit="impressions", amount="1000"),
        conversion_kind=kind,  # type: ignore[arg-type]
        horizon_basis=basis,
    )


@pytest.mark.parametrize("kind", ["purchase", "lead"])
def test_any_basis_text_keys_the_same(kind: str) -> None:
    keys = {canonical_json(pipeline._request_key(_req(kind, b))) for b in (None, "a", "b")}
    assert len(keys) == 1
    assert "horizon_basis" not in next(iter(keys))
