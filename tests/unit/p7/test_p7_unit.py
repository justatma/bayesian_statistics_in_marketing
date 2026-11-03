"""P7 unit tests beyond the frozen acceptance set."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from tests.fakes import builders as B
from tests.fakes import synth

from bayesian_marketing import core as C
from bayesian_marketing.core import registries
from bayesian_marketing.lag.model import lag_model, lag_notices, mature_fraction
from bayesian_marketing.prior_registry import registry as priors

AS_OF = dt.datetime(2026, 11, 2, tzinfo=dt.UTC)


@pytest.fixture(autouse=True)
def _iso(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BAYES_DATA_DIR", str(tmp_path / "store"))
    registries.clear_cache()


def test_propose_drops_incoming_approval() -> None:
    pid = priors.propose(B.prior_record("cvr", approved=True, client_id="c1"))
    with pytest.raises(C.GateFailure):
        priors.resolve("cvr", "c1", AS_OF)
    assert priors.approve(pid, "owner").approved


def test_propose_needs_client_hop() -> None:
    with pytest.raises(ValueError):
        priors.propose(B.prior_record("cvr", client_id=None))


def test_refused_prior_blocks_until_superseded() -> None:
    bad = priors.propose(B.prior_record("cvr", params={"a": 50.0, "b": 10.0}, client_id="c2"))
    with pytest.raises(priors.PriorRefused):
        priors.approve(bad, "owner")
    with pytest.raises(C.GateFailure):
        priors.resolve("cvr", "c2", AS_OF)
    good = priors.propose(B.prior_record("cvr", params={"a": 3.0, "b": 97.0}, client_id="c2"))
    priors.approve(good, "owner")
    got = priors.resolve("cvr", "c2", AS_OF)
    assert got.prior_id == good and got.params == {"a": 3.0, "b": 97.0}


def test_client_prior_is_per_client_and_per_path() -> None:
    pid = priors.propose(B.prior_record("cvr", client_id="c3"))
    assert priors.resolve("ctr", "c3", AS_OF).params == {"a": 2.0, "b": 98.0}
    assert priors.resolve("cvr", "c4", AS_OF).params == {"a": 1.0, "b": 49.0}
    check = priors.approve(pid, "owner").predictive_check
    assert check is not None and check["ceiling_applies"] == 1.0


def test_default_resolution_records_every_hop() -> None:
    got = priors.resolve("cvr", "c5", AS_OF)
    assert got.resolution_path[0].startswith("client:c5")
    assert got.resolution_path[1].startswith("vertical:")
    assert got.resolution_path[-1].startswith("default:")
    assert got.approved and got.elicitation.source == "human"


def test_structural_default_is_approved_after_d32() -> None:
    got = priors.resolve("cpm_impressions_per_dollar", "c6", AS_OF)
    assert got.approved
    assert "records/cpm_impressions_per_dollar" in got.resolution_path[-1]


def test_unknown_path_raises() -> None:
    with pytest.raises(LookupError):
        priors.resolve("no_such_path", "c7", AS_OF)


def test_non_beta_rate_prior_refused() -> None:
    rec = B.prior_record("ctr", family="gamma", params={"shape": 1.0, "rate": 1.0}, client_id="c8")
    with pytest.raises(priors.PriorRefused):
        priors.approve(priors.propose(rec), "owner")


def test_import_promoted_rejects_mismatched_id() -> None:
    rec = B.prior_record(
        "cvr", approved=True, client_id=None, source="promoted", promotion_id="promo_1"
    )
    with pytest.raises(ValueError):
        priors.import_promoted(rec.model_dump(mode="json"), "promo_2")


def test_cohorts_reject_degenerate_input() -> None:
    with pytest.raises(ValueError):
        priors.prior_from_cohorts([0.02], 1.0)
    with pytest.raises(ValueError):
        priors.prior_from_cohorts([0.02, 0.02], 1.0)
    with pytest.raises(ValueError):
        priors.prior_from_cohorts([0.01, 0.03], 0.0)


@pytest.mark.parametrize(
    "window,length", [("1d_click", 2), ("7d_click_1d_view", 8), ("28d_click_1d_view", 29)]
)
def test_default_curve_shape(window: str, length: int) -> None:
    lag = lag_model("meta", window, None, None)
    assert lag.source == "registry_default"
    assert len(lag.cdf) == length and lag.cdf[-1] == 1.0
    assert lag_notices(lag) == [registries.resolve("phrasing/notices/lag_assumed@v1")]


def test_estimated_curve_has_no_notice() -> None:
    lag = lag_model("meta", "7d_click_1d_view", synth.lag_heavy().history, None)
    assert lag.source == "orders_history" and lag_notices(lag) == []
    assert lag.cdf[-1] == 1.0


U = dt.UTC


def _orders(n: int, click: dt.datetime, order: dt.datetime, tag: str = "o") -> list[C.OrderRow]:
    return [
        B.order_row(order_id=f"{tag}{i}", first_click_at=click, ordered_at=order) for i in range(n)
    ]


def test_lag_is_calendar_date_difference_d27_1() -> None:
    h = _orders(
        50, dt.datetime(2026, 10, 1, 23, 30, tzinfo=U), dt.datetime(2026, 10, 2, 0, 30, tzinfo=U)
    )
    assert lag_model("meta", "7d_click", h, None).cdf == [0.0, 1.0]
    h = _orders(
        50, dt.datetime(2026, 10, 1, 0, 30, tzinfo=U), dt.datetime(2026, 10, 2, 23, 30, tzinfo=U)
    )
    assert lag_model("meta", "7d_click", h, None).cdf == [0.0, 1.0]  # 47 hours, 1 date


def test_lag_uses_account_timezone() -> None:
    # 01:30Z and 23:30Z the same UTC day are different dates in Los Angeles (UTC-7 in October)
    h = _orders(
        50, dt.datetime(2026, 10, 2, 1, 30, tzinfo=U), dt.datetime(2026, 10, 2, 23, 30, tzinfo=U)
    )
    assert lag_model("meta", "7d_click", h, None).cdf == [1.0]
    la = lag_model("meta", "7d_click", h, None, timezone="America/Los_Angeles")
    assert la.cdf == [0.0, 1.0]


def test_naive_datetime_refused_with_value_error() -> None:
    h = _orders(50, dt.datetime(2026, 10, 1), dt.datetime(2026, 10, 2, tzinfo=U))
    with pytest.raises(ValueError, match="naive"):
        lag_model("meta", "7d_click", h, None)


@pytest.mark.parametrize(
    "window",
    [
        "none",
        "property_setting",
        "per_conversion_action",
        "14d_click",
        "90d_click",
        "0d_click",
        "1d_view",
    ],
)
def test_unknown_window_code_raises(window: str) -> None:
    with pytest.raises(ValueError):
        lag_model("meta", window, None, None)


def test_default_curve_matches_d27_2() -> None:
    medians = registries.resolve("bounds/lag/default_median_days@v1")
    assert {int(k): v for k, v in medians.items()} == {1: 1, 7: 2, 28: 4}
    for window, median in ((1, 1), (7, 2), (28, 4)):
        q = 0.5 ** (1 / (median + 1))
        top = 1 - q ** (window + 1)
        cdf = lag_model("meta", f"{window}d_click", None, None).cdf
        assert len(cdf) == window + 1
        for a, v in enumerate(cdf):
            assert v == pytest.approx((1 - q ** (a + 1)) / top)
    one = lag_model("meta", "1d_click", None, None).cdf
    assert one[0] > 0.5  # attributed median on day 0 (D27.2)


def test_future_click_has_zero_maturity_d27_4() -> None:
    lag = lag_model("meta", "7d_click_1d_view", None, None)
    d = dt.date(2026, 11, 1)
    assert mature_fraction(d + dt.timedelta(days=1), d, lag) == 0.0


def test_lag_report_with_enough_history_is_kept(tmp_path: Path) -> None:
    report = [{"days": 0, "conversions": 1}]
    lag = lag_model("meta", "7d_click_1d_view", synth.lag_heavy().history, report)
    assert lag.source == "orders_history"
    assert list((tmp_path / "store" / "lag_reports").glob("*.json"))
    with pytest.raises(ValueError):
        lag_model("meta", "7d_click_1d_view", None, report)


def test_right_censored_orders_dropped() -> None:
    old = _orders(
        50, dt.datetime(2026, 10, 1, 9, tzinfo=U), dt.datetime(2026, 10, 3, 9, tzinfo=U), "a"
    )
    recent = _orders(
        30, dt.datetime(2026, 10, 28, 9, tzinfo=U), dt.datetime(2026, 10, 28, 10, tzinfo=U), "b"
    )
    lag = lag_model("meta", "7d_click", old + recent, None, as_of=dt.date(2026, 11, 1))
    assert lag.n_lagged_conversions == 50 and lag.cdf == [0.0, 0.0, 1.0]
    assert lag_model("meta", "7d_click", old + recent, None).n_lagged_conversions == 80


def test_import_promoted_is_checked_and_unapproved() -> None:
    ok = B.prior_record(
        "cvr",
        params={"a": 3.0, "b": 97.0},
        approved=True,
        client_id=None,
        source="promoted",
        promotion_id="p1",
    )
    with pytest.raises(ValueError):
        priors.import_promoted(ok.model_dump(mode="json"), "   ")
    pid = priors.import_promoted(ok.model_dump(mode="json"), "p1")
    stored = priors._read_record(pid)
    assert not stored.approved and stored.elicitation.promotion_id == "p1"
    assert priors.approve(pid, "owner").approved
    bad = B.prior_record("cvr", params={"a": 30.0, "b": 3.0}, approved=True, client_id=None)
    with pytest.raises(priors.PriorRefused):
        priors.import_promoted(bad.model_dump(mode="json"), "p9")


def test_resolve_ignores_proposals_created_after_as_of() -> None:
    priors.approve(priors.propose(B.prior_record("cvr", client_id="c9")), "owner")
    early = B.T0 - dt.timedelta(days=1)
    assert priors.resolve("cvr", "c9", early).params == {"a": 1.0, "b": 49.0}
    assert priors.resolve("cvr", "c9", AS_OF).params == {"a": 2.0, "b": 60.0}
