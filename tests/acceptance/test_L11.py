"""L11: the live view's horizon is the test budget left, priced at the observed cost (D53 (1)).

Spec: ``spec/Mismatch_Lead_Lag_Horizon_Fix_v0.2.md`` §3 C4 to C7 and §4 L11; §6 (S8 to S13)
holds where it differs from §1 to §5.

``live.horizon.spend_to_date`` runs against ``FakeStore`` seeded with polls by hand (ok, error,
interrupted, another platform, later than ``as_of``, a ``started_at`` tie). ``budget_horizon`` is
called directly on ``LiveRow`` lists. The refresh checks run ``refresh`` against ``FakeStore`` with
real economics in a temp config root, as in test_L4 and test_L8, wrapping ``pipeline.execute``
(never replacing it) to keep the request refresh built and the run it made. They need L10 merged:
the basis reaches the run's notices through ``pipeline.execute`` (C3, S10).

Money in the expected sentences is written with two decimals, as the S9 worked sentence is
(``money``); amounts with ``claims.vocab.fmt_count``. See the manifest for that choice.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from bayesian_marketing import core as C
from bayesian_marketing import pipeline
from bayesian_marketing.claims.vocab import fmt_count
from bayesian_marketing.core import registries
from bayesian_marketing.live import horizon as H
from bayesian_marketing.live.contracts import LiveRow, PollRecord
from bayesian_marketing.live.refresh import refresh
from tests.fakes import builders as B
from tests.fakes.live import FakeStore, FixedClock

pytestmark = pytest.mark.piece("L11")

UTC = dt.UTC
CLIENT = "budget_client"
ECON_ID = "budget_econ"
T0 = dt.datetime(2026, 11, 7, 17, 30, 0, 123456, tzinfo=UTC)
D = [dt.date(2026, 10, 31) + dt.timedelta(days=i) for i in range(8)]  # Oct 31 .. Nov 7
JOVANNAH_SINCE = dt.date(2026, 11, 7)

S9_SENTENCE = (
    "horizon: 42,238 impressions, the 1,256.24 USD left of the 1,500.00 USD test budget "
    "(spend counted since 2026-11-07) at 29.74 USD per 1,000 impressions"
)  # S9, verbatim


def usd(x: Any) -> C.Money:
    return C.Money(amount=Decimal(str(x)), currency="USD")


def money(x: Any) -> str:
    """Money as the S9 worked sentence writes it: thousands separated, two decimals."""
    return f"{Decimal(str(x)):,.2f} USD"


def default_amount() -> Decimal:
    return Decimal(str(registries.resolve("decision_defaults/horizon_default@v1")["amount"]))


def fallback(unit: str, why: str) -> tuple[C.Horizon, str]:
    """C6: the registry default in ``unit`` and its sentence (amount by ``fmt_count``)."""
    amount = default_amount()
    text = f"horizon: the default {fmt_count(amount)} {unit}, because {why}"
    return C.Horizon(unit=unit, amount=amount), text  # type: ignore[arg-type]


def row(
    ad: str,
    day: dt.date,
    spend: Any,
    *,
    impressions: int = 1000,
    clicks: int = 40,
    currency: str = "USD",
    poll_id: str = "poll_00000000",
    platform: str = "meta",
    client: str = CLIENT,
) -> LiveRow:
    return LiveRow(
        poll_id=poll_id,
        client_id=client,
        platform=platform,  # type: ignore[arg-type]
        entity_ids={"account": "555", "campaign": "c1", "ad_set": "s1", "ad": ad},
        entity_names={},
        objective="OUTCOME_LEADS",
        date=day,
        impressions=impressions,
        clicks=clicks,
        spend=C.Money(amount=Decimal(str(spend)), currency=currency),
        conversions_reported=float(clicks // 4),
        conversions_observed=None,
        revenue_reported=None,
        attribution_window="7d_click_1d_view",
    )


def add_poll(
    store: FakeStore,
    started: dt.datetime,
    rows: list[tuple[str, dt.date, Any]] | list[LiveRow],
    *,
    status: str = "ok",
    platform: str = "meta",
    client: str = CLIENT,
    poll_id: str | None = None,
    currency: str = "USD",
    finish: bool = True,
) -> PollRecord:
    """A poll in the store; ``rows`` as (ad, date, spend) triples or ready LiveRows."""
    pid = poll_id or (
        "poll_"
        + hashlib.sha256(f"{client}|{platform}|{started.isoformat()}".encode()).hexdigest()[:8]
    )
    live = [
        r.model_copy(update={"poll_id": pid}) if isinstance(r, LiveRow)
        else row(r[0], r[1], r[2], poll_id=pid, platform=platform, client=client,
                 currency=currency)
        for r in rows
    ]  # fmt: skip
    dates = sorted({r.date for r in live}) or [D[1], D[7]]
    rec = PollRecord(
        poll_id=pid,
        client_id=client,
        platform=platform,  # type: ignore[arg-type]
        account_id="act_555",
        started_at=started,
        finished_at=started + dt.timedelta(seconds=5),
        window=(dates[0], dates[-1]),
        status=status,  # type: ignore[arg-type]
        error=None if status == "ok" else "boom",
        pull_id="pull_meta_00000011" if status == "ok" else None,
        n_rows=len(live),
        n_quarantined=0,
        empty_account=False,
        timezone="America/New_York",
        currency=currency,
        account={"currency": currency},
        recording_dir=None,
    )
    store.begin_poll(rec)
    if finish:
        store.finish_poll(rec, live)
    return rec


def total(spent: Any) -> tuple[Decimal, str]:
    assert spent is not None
    return Decimal(spent.amount), spent.currency


# ------------------------------------------------------------------ guard: the final strings


def test_L11_final_strings() -> None:
    """Guard: the skeleton carries the final strings (C5, C6, S8, S11, S13); passes before the
    build."""
    assert H.HORIZON_FROM_BUDGET == (
        "horizon: {amount} {unit}, the {remaining} left of the {budget} test budget "
        "(spend counted since {since}) at {per_1000} per 1,000 {unit}"
    )  # C5
    assert H.HORIZON_FALLBACK == "horizon: the default {amount} {unit}, because {why}"  # C6
    assert H.WHY_NO_BUDGET == "no test budget is set in the economics file"  # C6
    assert H.WHY_NO_SPEND == (
        "no spend to date could be read from the store (none recorded, or in more than one "
        "currency)"
    )  # S13
    assert H.WHY_CURRENCY == "the budget and the spend are in different currencies"  # C6
    assert H.WHY_SPENT == "the test budget is spent"  # C6
    assert H.WHY_NO_UNITS == "no {unit} in the window to price the budget"  # C6
    assert H.WHY_UNDER_ONE == "less than one {singular} of budget is left"  # C6
    assert H.WHY_NO_ECONOMICS == "the economics file could not be read"  # S8
    assert H.SINGULAR == {"impressions": "impression", "clicks": "click"}  # S11


# ------------------------------------------------------------------ C4, S12, S13: spend to date


def two_polls(store: FakeStore) -> None:
    """P1 at T0 carries Oct 31 to Nov 2; P2 an hour later carries Nov 1 to Nov 3 at new amounts.
    Newest per (ad, date): Oct 31 from P1 (no longer in P2's window), Nov 1 to 3 from P2."""
    add_poll(store, T0, [(ad, D[i], s) for ad, s in (("ad_a", 10), ("ad_b", 5)) for i in (0, 1, 2)])
    add_poll(
        store,
        T0 + dt.timedelta(hours=1),
        [(ad, D[i], s) for ad, s in (("ad_a", 12), ("ad_b", 6)) for i in (1, 2, 3)],
    )


TWO_POLLS_TOTAL = Decimal(10 + 5 + 3 * 12 + 3 * 6)  # 69


def test_L11_spend_newest_ok_poll_per_ad_and_date(env_store: FakeStore) -> None:
    two_polls(env_store)
    spent, since = H.spend_to_date(env_store, CLIENT, "meta", T0 + dt.timedelta(hours=1))
    assert total(spent) == (TWO_POLLS_TOTAL, "USD")  # C4, S12: newest row per (ad, date)
    assert since == D[0]  # C4: the earliest date, one no longer in the latest window


def test_L11_spend_sums_dates_no_longer_in_the_latest_window(env_store: FakeStore) -> None:
    two_polls(env_store)
    later = [(ad, D[i], 1) for ad in ("ad_a", "ad_b") for i in (5, 6, 7)]
    add_poll(env_store, T0 + dt.timedelta(hours=2), later)  # window Nov 5 to Nov 7 only
    spent, since = H.spend_to_date(env_store, CLIENT, "meta", T0 + dt.timedelta(hours=2))
    assert total(spent) == (TWO_POLLS_TOTAL + 6, "USD")  # §4 L11: older dates still summed
    assert since == D[0]  # C4


def test_L11_spend_ignores_error_and_interrupted_polls(env_store: FakeStore) -> None:
    two_polls(env_store)
    big = [(ad, D[i], 1000) for ad in ("ad_a", "ad_b") for i in (0, 1, 2, 3)]
    add_poll(env_store, T0 + dt.timedelta(hours=2), big, status="error")
    add_poll(env_store, T0 + dt.timedelta(hours=3), big, finish=False)  # reads back interrupted
    spent, since = H.spend_to_date(env_store, CLIENT, "meta", T0 + dt.timedelta(hours=4))
    assert total(spent) == (TWO_POLLS_TOTAL, "USD")  # S12: status "ok" only
    assert since == D[0]


def test_L11_spend_ignores_another_platform(env_store: FakeStore) -> None:
    two_polls(env_store)
    other = [(ad, D[i], 1000) for ad in ("ad_a", "ad_b") for i in (0, 1, 2, 3, 4)]
    add_poll(env_store, T0 + dt.timedelta(hours=2), other, platform="google_ads")
    spent, since = H.spend_to_date(env_store, CLIENT, "meta", T0 + dt.timedelta(hours=4))
    assert total(spent) == (TWO_POLLS_TOTAL, "USD")  # S12: platform equal to the argument
    assert since == D[0]
    g_spent, g_since = H.spend_to_date(env_store, CLIENT, "google_ads", T0 + dt.timedelta(hours=4))
    assert total(g_spent) == (Decimal(10 * 1000), "USD")  # S12: the other platform on its own
    assert g_since == D[0]


def test_L11_spend_ignores_polls_after_as_of(env_store: FakeStore) -> None:
    two_polls(env_store)
    late = [(ad, D[i], 999) for ad in ("ad_a", "ad_b") for i in (2, 3, 4)]
    add_poll(env_store, T0 + dt.timedelta(hours=5), late)
    spent, _ = H.spend_to_date(env_store, CLIENT, "meta", T0 + dt.timedelta(hours=1))
    assert total(spent) == (TWO_POLLS_TOTAL, "USD")  # S12: started_at <= as_of, inclusive
    spent, _ = H.spend_to_date(env_store, CLIENT, "meta", T0 + dt.timedelta(minutes=30))
    assert total(spent) == (Decimal(3 * 10 + 3 * 5), "USD")  # S12: only P1 by then
    spent, _ = H.spend_to_date(env_store, CLIENT, "meta", T0 + dt.timedelta(hours=5))
    assert total(spent) == (Decimal(10 + 5 + 12 + 6 + 3 * 999 * 2), "USD")  # S12: inclusive


@pytest.mark.parametrize("first", ["poll_aaaaaaaa", "poll_bbbbbbbb"])
def test_L11_spend_tie_on_started_at_goes_to_the_greater_poll_id(
    env_store: FakeStore, first: str
) -> None:
    second = "poll_bbbbbbbb" if first == "poll_aaaaaaaa" else "poll_aaaaaaaa"
    amount = {"poll_aaaaaaaa": 7, "poll_bbbbbbbb": 9}
    for pid in (first, second):  # both insertion orders
        add_poll(env_store, T0, [("ad_a", D[1], amount[pid])], poll_id=pid)
    spent, since = H.spend_to_date(env_store, CLIENT, "meta", T0)
    assert total(spent) == (Decimal(9), "USD")  # S12: ties go to the greater poll_id
    assert since == D[1]


def test_L11_spend_none_when_nothing_recorded(env_store: FakeStore) -> None:
    assert H.spend_to_date(env_store, CLIENT, "meta", T0) == (None, None)  # C4, S13
    add_poll(env_store, T0, [("ad_a", D[1], 5)], client="someone_else")
    add_poll(env_store, T0 + dt.timedelta(hours=1), [("ad_a", D[1], 5)], status="error")
    assert H.spend_to_date(env_store, CLIENT, "meta", T0 + dt.timedelta(hours=2)) == (None, None)


def test_L11_spend_in_two_currencies_is_none(env_store: FakeStore) -> None:
    add_poll(env_store, T0, [("ad_a", D[1], 5), ("ad_b", D[1], 5)])
    add_poll(
        env_store, T0 + dt.timedelta(hours=1), [("ad_a", D[2], 5)], currency="EUR"
    )  # a counted row in EUR
    got = H.spend_to_date(env_store, CLIENT, "meta", T0 + dt.timedelta(hours=1))
    assert got == (None, None)  # C4, S13: both None


def test_L11_spend_counts_each_ad_and_date_once_across_many_polls(env_store: FakeStore) -> None:
    for h in range(5):  # hourly polls re-reading the same week at rising amounts
        rows = [(ad, D[i], h + 1) for ad in ("ad_a", "ad_b") for i in range(1, 8)]
        add_poll(env_store, T0 + dt.timedelta(hours=h), rows)
    spent, since = H.spend_to_date(env_store, CLIENT, "meta", T0 + dt.timedelta(hours=4))
    assert total(spent) == (Decimal(2 * 7 * 5), "USD")  # C4: summed once, newest wins
    assert since == D[1]


@pytest.fixture
def env_store() -> FakeStore:
    return FakeStore()


# ------------------------------------------------------------------ C5, S9: budget horizon


def jovannah_rows() -> list[LiveRow]:
    """$243.76 over 8,196 impressions and 80 clicks (§4 L11's shape)."""
    return [
        row(f"ad_{i}", JOVANNAH_SINCE, "60.94", impressions=2049, clicks=20) for i in range(1, 5)
    ]


def test_L11_budget_horizon_on_jovannah_shape() -> None:
    h, basis = H.budget_horizon(
        usd("1500"), usd("243.76"), JOVANNAH_SINCE, jovannah_rows(), "impressions"
    )
    assert h == C.Horizon(unit="impressions", amount=Decimal(42238))  # §4 L11, C5
    assert str(h.amount) == "42238"  # C5: an integer Decimal (B10)
    assert basis == S9_SENTENCE  # S9: the worked sentence, exactly


def test_L11_budget_horizon_in_clicks() -> None:
    h, basis = H.budget_horizon(
        usd("1500"), usd("243.76"), JOVANNAH_SINCE, jovannah_rows(), "clicks"
    )
    assert h == C.Horizon(unit="clicks", amount=Decimal(412))  # C5: 1,256.24 / (243.76 / 80)
    assert basis == (
        f"horizon: 412 clicks, the {money('1256.24')} left of the {money('1500')} test budget "
        f"(spend counted since 2026-11-07) at {money('3047')} per 1,000 clicks"
    )  # C5, S9


def test_L11_budget_horizon_prices_from_the_unrounded_cost() -> None:
    """S9: the amount is computed from the unrounded cost (29.7413... per 1,000), so rounding
    the rate to the cent first (42,240) is wrong."""
    h, _ = H.budget_horizon(
        usd("1500"), usd("243.76"), JOVANNAH_SINCE, jovannah_rows(), "impressions"
    )
    assert h.amount != Decimal(42240)  # S9
    assert h.amount == Decimal(42238)


def window(
    spend: Any = "100", impressions: int = 1000, clicks: int = 50, cur: str = "USD"
) -> list[LiveRow]:
    return [row("ad_a", D[7], spend, impressions=impressions, clicks=clicks, currency=cur)]


def eur(x: Any) -> C.Money:
    return C.Money(amount=Decimal(str(x)), currency="EUR")


FALLBACK_CASES = [
    # (id, test_budget, spent, since, window_rows, unit, why) in C6's order; each case also meets
    # a later row's condition where it can, so the first matching row is the one that must win.
    ("no_budget", None, None, None, window(), "impressions", H.WHY_NO_BUDGET),
    ("no_budget_spend_known", None, usd(10), D[7], window(), "clicks", H.WHY_NO_BUDGET),
    ("no_spend", usd(1500), None, None, window(cur="EUR"), "impressions", H.WHY_NO_SPEND),
    ("spent_in_eur", usd(1500), eur(2000), D[7], window(), "impressions", H.WHY_CURRENCY),
    ("row_in_eur", usd(1500), usd(1600), D[7], window(cur="EUR"), "impressions", H.WHY_CURRENCY),
    ("spent_exactly", usd(1500), usd(1500), D[7], [], "impressions", H.WHY_SPENT),
    ("overspent", usd(1500), usd("1500.01"), D[7], window(), "clicks", H.WHY_SPENT),
    ("no_impressions", usd(1500), usd(100), D[7], window(impressions=0), "impressions",
     H.WHY_NO_UNITS.format(unit="impressions")),
    ("no_spend_in_window", usd(1500), usd(100), D[7], window(spend=0), "impressions",
     H.WHY_NO_UNITS.format(unit="impressions")),
    ("empty_window", usd(1500), usd(100), D[7], [], "impressions",
     H.WHY_NO_UNITS.format(unit="impressions")),
    ("no_clicks", usd(1500), usd(100), D[7], window(clicks=0), "clicks",
     H.WHY_NO_UNITS.format(unit="clicks")),
    ("under_one_impression", usd(1500), usd("1499.99"), D[7], window(impressions=10),
     "impressions", H.WHY_UNDER_ONE.format(singular="impression")),
    ("under_one_click", usd(1500), usd("1499.99"), D[7], window(clicks=2), "clicks",
     H.WHY_UNDER_ONE.format(singular="click")),
]  # fmt: skip


@pytest.mark.parametrize(
    ("budget", "spent", "since", "rows", "unit", "why"),
    [c[1:] for c in FALLBACK_CASES],
    ids=[c[0] for c in FALLBACK_CASES],
)
def test_L11_budget_horizon_fallback_rows(
    budget: Any, spent: Any, since: Any, rows: list[LiveRow], unit: str, why: str
) -> None:
    got = H.budget_horizon(budget, spent, since, rows, unit)
    assert got == fallback(unit, why)  # C6: the default in the unit, and its sentence


def test_L11_fallback_sentences_spelled_out() -> None:
    """C6, S11, S13 as a reader sees them (the default amount is the registry's 1,000)."""
    assert default_amount() == 1000
    assert fallback("impressions", H.WHY_NO_BUDGET)[1] == (
        "horizon: the default 1,000 impressions, because no test budget is set in the economics "
        "file"
    )
    assert fallback("clicks", H.WHY_UNDER_ONE.format(singular="click"))[1] == (
        "horizon: the default 1,000 clicks, because less than one click of budget is left"
    )
    got = H.budget_horizon(usd(1500), usd("1499.99"), D[7], window(impressions=10), "impressions")
    assert got[1] == (
        "horizon: the default 1,000 impressions, because less than one impression of budget is left"
    )  # S11: the module's own singular


# ------------------------------------------------------------------ C7, S8: refresh


def write_economics(config_root: Path, *, raw: str | None = None, **kw: Any) -> None:
    path = config_root / "economics" / f"{ECON_ID}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        path.write_text(raw)
        return
    econ = B.economics(
        economics_id=ECON_ID,
        client_id=CLIENT,
        loss_tolerance=150,
        fixed_price=795,
        variable_cost=235,
        approved=True,
        **kw,
    )
    path.write_text(econ.model_dump_json())


def config(**kw: Any) -> C.ClientConfig:
    base: dict[str, Any] = {
        "client_id": CLIENT,
        "timezone": "America/New_York",
        "currency": "USD",
        "accounts": {"meta": "act_555"},
        "economics_path": f"economics/{ECON_ID}.json",
    }
    base.update(kw)
    return C.ClientConfig(**base)


def week(days: list[dt.date], spend: dict[str, str]) -> list[LiveRow]:
    return [
        row(ad, d, s, impressions=1000, clicks=40 if ad == "ad_a" else 60)
        for ad, s in spend.items()
        for d in days
    ]


class Env:
    """Two ok polls: P0 (a day earlier) reads Oct 31 to Nov 6 at 9.00 a day per ad; P1 reads
    Nov 1 to Nov 7 at 10.00 (ad_a) and 11.00 (ad_b). Spend to date as of P1: 165.00 since Oct 31
    (Oct 31 from P0, the rest from P1). P1's window: 147.00 over 14,000 impressions."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.config_root = tmp_path / "configs"
        self.config_root.mkdir()
        self.data_dir = tmp_path / "engine_data"
        self.data_dir.mkdir()
        self.store = FakeStore()
        self.clock = FixedClock(dt.datetime(2026, 11, 7, 18, 0, 0, 654321, tzinfo=UTC))
        self.mp = monkeypatch
        self.iso = os.environ["BAYES_DATA_DIR"]
        self.calls: list[dict[str, Any]] = []
        self.contexts: list[Any] = []
        real = pipeline.execute

        def capture(manifest: Any, request: Any, **kw: Any) -> Any:
            self.calls.append({"manifest": manifest, "request": request, **kw})
            ctx = real(manifest, request, **kw)
            self.contexts.append(ctx)
            return ctx

        monkeypatch.setattr(pipeline, "execute", capture)
        self.p0 = add_poll(
            self.store, T0 - dt.timedelta(days=1), week(D[0:7], {"ad_a": "9", "ad_b": "9"})
        )
        self.p1 = add_poll(self.store, T0, week(D[1:8], {"ad_a": "10", "ad_b": "11"}))

    def run(self, poll_rec: PollRecord | None = None, cfg: C.ClientConfig | None = None) -> Any:
        return refresh(
            cfg or config(),
            poll_rec or self.p1,
            self.store,
            self.clock,
            data_dir=self.data_dir,
            config_root=self.config_root,
        )


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    return Env(tmp_path, monkeypatch)


def test_L11_refresh_with_a_test_budget_runs_at_the_budget_horizon(env: Env) -> None:
    write_economics(env.config_root, test_budget=1500)
    rec = env.run()
    assert rec.status == "ran", rec.reason
    want = (
        f"horizon: 127,142 impressions, the {money('1335')} left of the {money('1500')} test "
        f"budget (spend counted since 2026-10-31) at {money('10.50')} per 1,000 impressions"
    )  # C5, S9: 1,335 / (147 / 14,000) = 127,142.86
    request = env.calls[0]["request"]
    assert request.horizon == C.Horizon(unit="impressions", amount=Decimal(127142))  # C7
    assert request.horizon_basis == want  # C7
    snap = env.contexts[0].snapshot
    assert snap.run_id == rec.run_id
    assert snap.horizon == C.Horizon(unit="impressions", amount=Decimal(127142))  # §4 L11
    assert snap.notices[-1] == want and snap.notices.count(want) == 1  # §4 L11, S10


def test_L11_refresh_of_an_older_poll_counts_spend_only_to_that_poll(env: Env) -> None:
    write_economics(env.config_root, test_budget=1500)
    rec = env.run(env.p0)  # P1 is in the store, but started after P0 (S12: as_of)
    assert rec.status == "ran", rec.reason
    want = (
        f"horizon: 152,666 impressions, the {money('1374')} left of the {money('1500')} test "
        f"budget (spend counted since 2026-10-31) at {money('9')} per 1,000 impressions"
    )  # C7, S12: 126.00 spent by P0; P0's window 126.00 over 14,000 impressions
    request = env.calls[0]["request"]
    assert request.horizon == C.Horizon(unit="impressions", amount=Decimal(152666))  # C7, S12
    assert request.horizon_basis == want
    assert env.contexts[0].snapshot.notices[-1] == want  # S10


def test_L11_refresh_without_a_test_budget_runs_at_the_default(env: Env) -> None:
    write_economics(env.config_root)
    rec = env.run()
    assert rec.status == "ran", rec.reason
    h, want = fallback("impressions", H.WHY_NO_BUDGET)
    request = env.calls[0]["request"]
    assert request.horizon == h  # C6, C7: the default 1,000 impressions for ctr
    assert request.horizon_basis == want  # C7
    snap = env.contexts[0].snapshot
    assert snap.horizon == h  # §4 L11
    assert snap.notices[-1] == want and snap.notices.count(want) == 1  # §4 L11, S10


def test_L11_refresh_with_the_budget_spent_runs_at_the_default(env: Env) -> None:
    write_economics(env.config_root, test_budget=100)  # 165.00 already spent
    rec = env.run()
    assert rec.status == "ran", rec.reason
    h, want = fallback("impressions", H.WHY_SPENT)
    assert env.calls[0]["request"].horizon == h  # C6, C7
    assert env.contexts[0].snapshot.notices[-1] == want  # C6, S10


def test_L11_refresh_missing_economics_falls_back_and_skips_as_today(env: Env) -> None:
    rec = env.run()  # economics_path is set; no file under config_root
    h, want = fallback("impressions", H.WHY_NO_ECONOMICS)
    assert len(env.calls) == 1
    request = env.calls[0]["request"]
    assert request.horizon == h  # S8: the fallback horizon
    assert request.horizon_basis == want  # S8
    assert rec.status == "skipped"  # S8: pipeline decides as today (G9)
    assert rec.reason == "; ".join(
        [pipeline.CLIENT_NEEDS_ECONOMICS, pipeline.NO_ECONOMICS.format(eid=ECON_ID)]
    )  # S8: today's G9 reason, unchanged
    assert rec.run_id is None


def test_L11_refresh_unreadable_economics_falls_back_and_fails_as_today(env: Env) -> None:
    write_economics(env.config_root, raw="{this is not json")
    rec = env.run()
    h, want = fallback("impressions", H.WHY_NO_ECONOMICS)
    assert len(env.calls) == 1
    request = env.calls[0]["request"]
    assert request.horizon == h  # S8: any exception gives the fallback
    assert request.horizon_basis == want  # S8
    assert rec.status == "failed"  # S8: pipeline decides as today
    assert rec.reason and rec.reason.startswith("ValidationError: "), rec.reason  # as today
    assert rec.run_id is None
