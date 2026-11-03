"""P7 unit tests beyond the frozen acceptance set."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from tests.fakes import builders as B
from tests.fakes import synth

from bayesian_marketing import core as C
from bayesian_marketing.core import registries
from bayesian_marketing.lag.model import lag_model, mature_fraction, notices
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


def test_pending_default_comes_back_unapproved() -> None:
    got = priors.resolve("cpm_impressions_per_dollar", "c6", AS_OF)
    assert not got.approved
    assert "pending_records" in got.resolution_path[-1]


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


@pytest.mark.parametrize("window,length", [("1d_click", 2), ("7d_click_1d_view", 8), ("none", 29)])
def test_default_curve_shape(window: str, length: int) -> None:
    lag = lag_model("meta", window, None, None)
    assert lag.source == "registry_default"
    assert len(lag.cdf) == length and lag.cdf[-1] == 1.0
    assert notices(lag) == [registries.resolve("phrasing/notices/lag_assumed@v1")]


def test_estimated_curve_has_no_notice() -> None:
    lag = lag_model("meta", "7d_click_1d_view", synth.lag_heavy().history, None)
    assert lag.source == "orders_history" and notices(lag) == []
    assert lag.cdf[-1] == 1.0


def test_lag_report_refused_and_future_click_refused() -> None:
    with pytest.raises(ValueError):
        lag_model("meta", "7d_click_1d_view", None, [{"days": 0, "conversions": 1}])
    lag = lag_model("meta", "7d_click_1d_view", None, None)
    d = dt.date(2026, 11, 1)
    with pytest.raises(ValueError):
        mature_fraction(d, d - dt.timedelta(days=1), lag)
