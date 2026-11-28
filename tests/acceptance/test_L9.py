"""L9: a Meta window code's click window is read wherever it sits, by one parser (D51 (5)).

Spec: ``spec/Units_and_Window_Fix_v0.2.md`` §3 C9 and §5 U8 (U8 holds where they differ).

``click_window_days`` is called directly. The callers U8 names (``_click_window_days`` through
``lag_model``, ``lag_notices``, ``simulate/write.py``) are checked by what they return for Meta's
real code ``1d_view_7d_click_1d_ev``. ``lag_notices`` is also checked with the shared parser
replaced, which shows it consults that function rather than a regex of its own. The pipeline check
runs ``refresh`` against ``FakeStore`` with real economics, as in test_L5, on rows that carry Meta's
code.

Revised by the test writer under ``spec/Mismatch_Lead_Lag_Horizon_Fix_v0.2.md`` S7 (build log
B25): a lead takes no lag curve (D53 (2)), so the 7-day curve and the Meta code checks run on
purchase runs with the same rows, and the lead runs assert no lag (C2, S4).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
from pathlib import Path
from typing import Any

import pytest

from bayesian_marketing import core as C
from bayesian_marketing import pipeline
from bayesian_marketing.core import registries
from bayesian_marketing.lag import model as lag
from bayesian_marketing.live.contracts import LiveRow, PollRecord
from bayesian_marketing.live.refresh import refresh
from bayesian_marketing.simulate import write
from bayesian_marketing.simulate.scenario import PlatformSpec
from tests.fakes import builders as B
from tests.fakes.live import FakeStore, FixedClock

pytestmark = pytest.mark.piece("L9")

UTC = dt.UTC
CLIENT = "window_client"
ECON_ID = "window_econ"
START = dt.datetime(2026, 11, 7, 17, 30, 0, 123456, tzinfo=UTC)
WINDOW = (dt.date(2026, 11, 1), dt.date(2026, 11, 7))
LEAD_EVENT = "offsite_conversion.fb_pixel_lead"
META_CODE = "1d_view_7d_click_1d_ev"
NOT_ADJUSTED = "conversion lag not adjusted"
NAMES_NO_WINDOW = "names no click window"


# ------------------------------------------------------------------ C9, U8: the parser


@pytest.mark.parametrize(
    ("code", "days"),
    [
        (META_CODE, 7),  # C9: view, click, engaged view
        ("7d_click_1d_view", 7),
        ("28d_click", 28),
        ("28d_click_1d_view", 28),
        ("1d_click", 1),
        ("7d_click", 7),
        ("1d_view_28d_click", 28),
        ("1d_view", None),  # C9: names none
        ("per_conversion_action", None),
        ("none", None),
        ("17d_click", 17),  # U8: whole components, so not 7
        ("7d_clicks", None),  # U8: "clicks" is not the component "click"
        ("14d_click", 14),  # parsed; the registry lookup refuses it later
        ("90d_click", 90),
        ("90d_click_90d_view", 90),  # LinkedIn: parsed; no registry row (not in scope)
    ],
)
def test_L9_click_window_days(code: str, days: int | None) -> None:
    assert lag.click_window_days(code) == days  # C9, U8


@pytest.mark.parametrize("code", ["0d_click", "7d_click_28d_click", "1d_view_1d_click_7d_click"])
def test_L9_click_window_days_refuses(code: str) -> None:
    with pytest.raises(ValueError):  # U8: 0 days, or two click windows
        lag.click_window_days(code)


def test_L9_old_regex_is_gone() -> None:
    assert not hasattr(lag, "_CLICK_WINDOW")  # U8: one parser, the second source deleted
    assert not hasattr(write, "CLICK_WINDOW")  # U8: the generator's own regex deleted


# ------------------------------------------------------------------ U8: lag_model


def test_L9_meta_code_takes_the_seven_day_default_curve() -> None:
    got = lag.lag_model("meta", META_CODE, None, None)
    want = lag.lag_model("meta", "7d_click", None, None)
    assert got.source == "registry_default"
    assert got.attribution_window == META_CODE
    assert got.cdf == want.cdf  # C9: the 7-day default curve
    assert len(got.cdf) == 8


@pytest.mark.parametrize("code", ["14d_click", "90d_click", "0d_click", "1d_view", "7d_clicks"])
def test_L9_off_table_and_windowless_codes_still_raise(code: str) -> None:
    """Guard (U8, A14): passes before the build and must keep passing."""
    with pytest.raises(ValueError):
        lag.lag_model("meta", code, None, None)


def test_L9_per_conversion_action_keeps_the_d38_path() -> None:
    """Guard (D38.3): passes before the build."""
    got = lag.lag_model("google_ads", "per_conversion_action", None, None, click_window_days=28)
    assert got.cdf == lag.lag_model("meta", "28d_click", None, None).cdf
    notices = lag.lag_notices(got)
    assert any(NAMES_NO_WINDOW in n for n in notices)


# ------------------------------------------------------------------ U8: lag_notices


def default_lag(code: str) -> C.LagModel:
    return lag.lag_model("meta", "7d_click", None, None).model_copy(
        update={"attribution_window": code}
    )


def test_L9_lag_notices_on_the_meta_code() -> None:
    notices = lag.lag_notices(default_lag(META_CODE))
    assert registries.resolve("phrasing/notices/lag_assumed@v1") in notices
    assert not any(NAMES_NO_WINDOW in n for n in notices)  # U8, A13: no false notice


def test_L9_lag_notices_consults_the_shared_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def none_for_all(code: str) -> int | None:
        seen.append(code)
        return None

    usual = default_lag("7d_click_1d_view")  # built before the parser is replaced
    monkeypatch.setattr(lag, "click_window_days", none_for_all)
    notices = lag.lag_notices(usual)
    assert "7d_click_1d_view" in seen  # U8: lag_notices uses the one parser
    assert any(NAMES_NO_WINDOW in n for n in notices)  # and acts on its answer


# ------------------------------------------------------------------ U8: simulate/write


def spec(code: str, days: int | None = None) -> PlatformSpec:
    return PlatformSpec(
        attribution_window=code, click_window_days=days, utm_source="fb", utm_medium="paid"
    )


def test_L9_generator_reads_the_meta_code() -> None:
    assert write._windows(spec(META_CODE), "meta", 3) == [(META_CODE, 7)] * 3  # U8, B6


@pytest.mark.parametrize(
    ("code", "days"), [("17d_click", 17), ("1d_click", 1), ("7d_click_1d_view", 7)]
)
def test_L9_generator_keeps_the_codes_it_read(code: str, days: int) -> None:
    """Guard (U8): codes the generator read before read the same; passes before the build."""
    assert write._windows(spec(code), "meta", 3) == [(code, days)] * 3


def test_L9_generator_refuses_a_code_with_no_click_window() -> None:
    with pytest.raises(ValueError):  # "7d_clicks" names no click window under U8
        write._windows(spec("7d_clicks"), "meta", 2)
    assert write._windows(spec("7d_clicks", 7), "meta", 2) == [("7d_clicks", 7)] * 2


# ------------------------------------------------------------------ pipeline: a lead run


def write_economics(config_root: Path) -> None:
    econ = B.economics(
        economics_id=ECON_ID,
        client_id=CLIENT,
        loss_tolerance=150,
        fixed_price=795,
        variable_cost=235,
        approved=True,
    )
    path = config_root / "economics" / f"{ECON_ID}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(econ.model_dump_json())


def seed_poll(store: FakeStore, code: str) -> PollRecord:
    ads = {"ad_a": (1000, 40), "ad_b": (1000, 60)}
    pid = "poll_" + hashlib.sha256(f"{CLIENT}|meta|{START.isoformat()}".encode()).hexdigest()[:8]
    rows = [
        LiveRow(
            poll_id=pid,
            client_id=CLIENT,
            platform="meta",
            entity_ids={"account": "555", "campaign": "c1", "ad_set": "s1", "ad": ad},
            entity_names={},
            objective="OUTCOME_LEADS",
            date=WINDOW[0] + dt.timedelta(days=i),
            impressions=imp,
            clicks=clk,
            spend=C.Money(amount="10.00", currency="USD"),
            conversions_reported=float(clk // 4),
            conversions_observed=None,
            revenue_reported=None,
            attribution_window=code,
        )
        for ad, (imp, clk) in ads.items()
        for i in range(7)
    ]
    rec = PollRecord(
        poll_id=pid,
        client_id=CLIENT,
        platform="meta",
        account_id="act_555",
        started_at=START,
        finished_at=START + dt.timedelta(seconds=5),
        window=WINDOW,
        status="ok",
        error=None,
        pull_id="pull_meta_00000009",
        n_rows=len(rows),
        n_quarantined=0,
        empty_account=False,
        timezone="America/New_York",
        currency="USD",
        account={"currency": "USD"},
        recording_dir=None,
    )
    store.begin_poll(rec)
    store.finish_poll(rec, rows)
    return rec


def pipeline_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: str, *, lead: bool) -> Any:
    config_root = tmp_path / "configs"
    data_dir = tmp_path / "engine_data"
    data_dir.mkdir()
    write_economics(config_root)
    contexts: list[Any] = []
    real = pipeline.execute

    def capture(manifest: Any, request: Any, **kw: Any) -> Any:
        ctx = real(manifest, request, **kw)
        contexts.append(ctx)
        return ctx

    monkeypatch.setattr(pipeline, "execute", capture)
    cfg = C.ClientConfig(
        client_id=CLIENT,
        timezone="America/New_York",
        currency="USD",
        accounts={"meta": "act_555"},
        economics_path=f"economics/{ECON_ID}.json",
        conversion_event={"meta": LEAD_EVENT} if lead else {},
    )
    store = FakeStore()
    clock = FixedClock(dt.datetime(2026, 11, 7, 18, 0, 0, 654321, tzinfo=UTC))
    before = os.environ["BAYES_DATA_DIR"]
    rec = refresh(
        cfg, seed_poll(store, code), store, clock, data_dir=data_dir, config_root=config_root
    )
    assert os.environ["BAYES_DATA_DIR"] == before
    assert rec.status == "ran", rec.reason
    assert len(contexts) == 1
    return contexts[0]


def test_L9_purchase_run_with_the_meta_code_adjusts_for_lag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guard (S7): L9's lag check on a purchase run with the same rows; passes before the build."""
    ctx = pipeline_run(tmp_path, monkeypatch, META_CODE, lead=False)
    snap = ctx.snapshot
    assert not any(NOT_ADJUSTED in n for n in snap.notices), snap.notices  # §4 L9
    assert not any(NAMES_NO_WINDOW in n for n in snap.notices), snap.notices  # U8, A13
    assert registries.resolve("phrasing/notices/lag_assumed@v1") in snap.notices
    assert snap.configuration["lag"] == {"source": "registry_default", "window": META_CODE}
    seven = lag.lag_model("meta", "7d_click", None, None)  # §4 L9: the 7-day default curve
    want = [lag.mature_fraction(d, snap.as_of, seven) for d in ctx.data.dates]
    assert all(row == want for row in ctx.data.mature_fraction)
    assert min(want) < 1.0  # the curve was applied, not the "no lag" fallback of 1.0


def assert_no_lag(ctx: Any) -> None:
    snap = ctx.snapshot
    assert not any(NOT_ADJUSTED in n for n in snap.notices), snap.notices
    assert not any(NAMES_NO_WINDOW in n for n in snap.notices), snap.notices
    assert registries.resolve("phrasing/notices/lag_assumed@v1") not in snap.notices  # C2
    assert snap.notices.count(pipeline.LEAD_NO_LAG) == 1  # C2, S4: a run notice
    assert snap.configuration["lag"] is None  # C2
    assert all(f == 1.0 for row in ctx.data.mature_fraction for f in row)  # C2
    approx = registries.resolve("phrasing/notices/lag_approx@v1")
    for q in snap.quantities:
        assert approx not in q.notices and pipeline.LEAD_NO_LAG not in q.notices  # S4


def test_L9_lead_run_with_the_meta_code_takes_no_lag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S7: the lead run with Meta's code asserts no lag (C2, S4)."""
    assert_no_lag(pipeline_run(tmp_path, monkeypatch, META_CODE, lead=True))


def test_L9_purchase_run_with_the_usual_code_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guard: ``7d_click_1d_view`` runs as before on a purchase run (S7); passes before the
    build."""
    ctx = pipeline_run(tmp_path, monkeypatch, "7d_click_1d_view", lead=False)
    snap = ctx.snapshot
    assert not any(NOT_ADJUSTED in n for n in snap.notices)
    assert not any(NAMES_NO_WINDOW in n for n in snap.notices)
    assert snap.configuration["lag"] == {
        "source": "registry_default",
        "window": "7d_click_1d_view",
    }


def test_L9_lead_run_with_the_usual_code_takes_no_lag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S7: the lead run with the usual code asserts no lag (C2, S4)."""
    assert_no_lag(pipeline_run(tmp_path, monkeypatch, "7d_click_1d_view", lead=True))
