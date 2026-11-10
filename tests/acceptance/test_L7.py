"""L7: prior scoring (prior learning spec v0.2 §5, as amended by §8 R4 to R18).

``score_priors`` runs against ``FakeStore`` and ``FixedClock`` with the prior registry under a temp
``data_dir`` (R10). Expected numbers are computed here with ``scipy.stats.betabinom`` and
``scipy.stats.beta`` from the params in ``registries/priors/default.yaml`` read at test time; the
lead record (``lead_records.cvr``) is never hard-coded, and a test that needs it fails cleanly when
it is absent.

Candidates named ``framework_lead`` resolve through L6, so the candidate and scoring tests need L6
merged (or present in the L7 worktree). ``write_score``, ``load_latest_score`` and the page tests
build a ``PriorScore`` by hand and do not depend on ``score_priors`` or on L6.

The CLI tests drive ``cli.main`` with ``BAYES_LIVE_DIR``, ``BAYES_CONFIG_DIR`` and
``BAYES_DATA_DIR`` in temp directories and a ``SqliteStore`` seeded by the test. ``live poll`` is
driven without network by replacing ``live.poll.poll`` with a fake that writes one ok poll.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import math
import os
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from scipy import stats
from scipy.special import betaln, gammaln

from bayesian_marketing import cli
from bayesian_marketing import core as C
from bayesian_marketing.core import registries
from bayesian_marketing.live import prior_score as ps
from bayesian_marketing.live import view
from bayesian_marketing.live.contracts import LiveRow, PollRecord
from bayesian_marketing.live.prior_score import (
    CLICKS_ABOVE_IMPRESSIONS,
    CONVERSIONS_ABOVE_CLICKS,
    NO_ADS_WITH_DATA,
    NO_CONVERSION_ROWS,
    NO_TRIALS,
    AdScore,
    CandidateScore,
    PriorScore,
    load_latest_score,
    score_priors,
    write_score,
)
from bayesian_marketing.live.registry import load_live_registry
from bayesian_marketing.live.store import SqliteStore
from bayesian_marketing.prior_registry import registry as prior_registry
from tests.fakes import builders as B
from tests.fakes.live import FakeStore, FixedClock

pytestmark = pytest.mark.piece("L7")

UTC = dt.UTC
CLIENT = "score_client"
NOW = dt.datetime(2026, 11, 10, 18, 0, 0, 250000, tzinfo=UTC)
T1 = dt.datetime(2026, 11, 8, 9, 0, tzinfo=UTC)
D1, D2, D3 = dt.date(2026, 11, 5), dt.date(2026, 11, 6), dt.date(2026, 11, 7)
LEAD_EVENT = "offsite_conversion.fb_pixel_lead"
TOL = 1e-9


# ------------------------------------------------- registry facts (read at test time)


def default_file() -> dict[str, Any]:
    return registries.load("priors/default")


def purchase_params(path: str) -> dict[str, float]:
    entry = default_file()["records"][path]
    assert entry["family"] == "beta"
    return {k: float(v) for k, v in entry["params"].items()}


def lead_params() -> dict[str, float]:
    entry = (default_file().get("lead_records") or {}).get("cvr")
    if entry is None:
        pytest.fail("registries/priors/default.yaml has no lead_records.cvr (skeleton step 1, D48)")
    assert entry["family"] == "beta"
    return {k: float(v) for k, v in entry["params"].items()}


def purchase_id(path: str) -> str:
    return C.make_id("pr_", {"default": path, "params": purchase_params(path)})


def lead_id() -> str:
    return C.make_id("pr_", {"default": "cvr", "params": lead_params(), "table": "lead_records"})


def surprise_tail() -> float:
    return float(registries.load("bounds")["prior_scoring"]["surprise_tail"])  # R17


def default_resolution(client: str, path: str, table: str = "records") -> str:
    return " > ".join(
        [f"client:{client}:none", "vertical:unmapped", f"default:priors/default/{table}/{path}@v1"]
    )


# ------------------------------------------------------------------ expected numbers


def expect(params: dict[str, float], n: int, k: int) -> dict[str, Any]:
    """Every AdScore number by hand: §5 table, R7 tail, R17 threshold."""
    a, b = params["a"], params["b"]
    bb = stats.betabinom(n, a, b)
    tail = (float(bb.cdf(k - 1)) if k > 0 else 0.0) + 0.5 * float(bb.pmf(k))  # R7
    log_score = float(bb.logpmf(k))
    closed = (  # the BetaBinomial pmf in closed form, as a check on scipy
        gammaln(n + 1)
        - gammaln(k + 1)
        - gammaln(n - k + 1)
        + betaln(k + a, n - k + b)
        - betaln(a, b)
    )
    assert abs(log_score - closed) < 1e-10
    thr = surprise_tail()
    beta = stats.beta(a, b)
    return {
        "n": n,
        "k": k,
        "raw_rate": k / n,
        "prior_q05": float(beta.ppf(0.05)),
        "prior_q50": float(beta.ppf(0.50)),
        "prior_q95": float(beta.ppf(0.95)),
        "tail": tail,
        "surprised": tail < thr or tail > 1 - thr,
        "log_score": log_score,
        "prior_weight": (a + b) / (a + b + n),
        "posterior_mean": (a + k) / (a + b + n),
        "shrinkage": (a + k) / (a + b + n) - k / n,
    }


def check_ad(got: AdScore, want: dict[str, Any]) -> None:
    for name, value in want.items():
        g = getattr(got, name)
        if isinstance(value, float):
            assert abs(g - value) <= TOL, (got.ad_id, name, g, value)
        else:
            assert g == value, (got.ad_id, name, g, value)


# ------------------------------------------------------------------ store builders


def poll_id(client: str, started: dt.datetime) -> str:
    return "poll_" + hashlib.sha256(f"{client}|meta|{started.isoformat()}".encode()).hexdigest()[:8]


def row(
    pid: str,
    ad: str | None,
    day: dt.date,
    impressions: int,
    clicks: int,
    reported: float | None,
    *,
    observed: int | None = None,
    name: str | None = None,
    client: str = CLIENT,
) -> LiveRow:
    ids = {"account": "555", "campaign": "c1", "ad_set": "s1"}
    if ad is not None:
        ids["ad"] = ad
    return LiveRow(
        poll_id=pid,
        client_id=client,
        platform="meta",
        entity_ids=ids,
        entity_names={"ad": name} if name else {},
        objective=None,
        date=day,
        impressions=impressions,
        clicks=clicks,
        spend=C.Money(amount="5.00", currency="USD"),
        conversions_reported=reported,
        conversions_observed=observed,
        revenue_reported=None,
        attribution_window="7d_click_1d_view",
    )


Spec = list[tuple[str | None, dt.date, int, int, float | None, int | None, str | None]]


def poll_rec(client: str, started: dt.datetime, status: str = "ok", n_rows: int = 0) -> PollRecord:
    ok = status == "ok"
    return PollRecord(
        poll_id=poll_id(client, started),
        client_id=client,
        platform="meta",
        account_id="act_555",
        started_at=started,
        finished_at=started + dt.timedelta(seconds=5),
        window=(D1, D3),
        status=status,  # type: ignore[arg-type]
        error=None if ok else "boom",
        pull_id="pull_meta_00000007" if ok else None,
        n_rows=n_rows,
        n_quarantined=0,
        empty_account=False,
        timezone="America/New_York",
        currency="USD",
        account={"currency": "USD"},
        recording_dir=None,
    )


def add_poll(
    store: Any,
    started: dt.datetime,
    spec: Spec,
    *,
    status: str = "ok",
    client: str = CLIENT,
    finish: bool = True,
) -> PollRecord:
    pid = poll_id(client, started)
    rows = [
        row(pid, ad, day, imp, clk, rep, observed=obs, name=name, client=client)
        for ad, day, imp, clk, rep, obs, name in spec
    ]
    rec = poll_rec(client, started, status, len(rows))
    store.begin_poll(rec)
    if finish:
        store.finish_poll(rec, rows)
    return rec


TWO_ADS: Spec = [
    ("ad_a", D1, 1000, 20, 1.0, None, "Hero"),
    ("ad_a", D2, 800, 15, 2.0, None, "Hero"),
    ("ad_b", D1, 500, 30, 6.0, None, "Static"),
]
# per ad: ctr (impressions, clicks), cvr (clicks, conversions)
TWO_ADS_COUNTS = {
    "ad_a": {"ctr": (1800, 35), "cvr": (35, 3)},
    "ad_b": {"ctr": (500, 30), "cvr": (30, 6)},
}


def config(**kw: Any) -> C.ClientConfig:
    base: dict[str, Any] = {
        "client_id": CLIENT,
        "timezone": "America/New_York",
        "currency": "USD",
        "accounts": {"meta": "act_555"},
    }
    base.update(kw)
    return C.ClientConfig(**base)


def lead_config(**kw: Any) -> C.ClientConfig:
    return config(conversion_event={"meta": LEAD_EVENT}, **kw)


class Env:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tmp = tmp_path
        self.data_dir = tmp_path / "engine_data"
        self.data_dir.mkdir()
        self.store = FakeStore()
        self.clock = FixedClock(NOW)
        self.mp = monkeypatch
        self.iso = os.environ["BAYES_DATA_DIR"]

    def score(self, cfg: C.ClientConfig) -> PriorScore:
        return score_priors(cfg, self.store, self.clock, data_dir=self.data_dir)

    def client_prior(self, path: str, params: dict[str, float], **approve_kw: Any) -> str:
        """An approved client prior in the registry under ``data_dir`` only."""
        self.mp.setenv("BAYES_DATA_DIR", str(self.data_dir))
        try:
            rec = B.prior_record(path, "beta", params, approved=False, client_id=CLIENT)
            pid = prior_registry.propose(rec)
            prior_registry.approve(pid, "owner", **approve_kw)
        finally:
            self.mp.setenv("BAYES_DATA_DIR", self.iso)
        return pid

    def files(self) -> dict[str, bytes]:
        return {
            str(p.relative_to(self.tmp)): p.read_bytes()
            for p in sorted(self.tmp.rglob("*"))
            if p.is_file()
        }


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    return Env(tmp_path, monkeypatch)


def roles(score: PriorScore, path: str) -> list[str]:
    return [c.role for c in score.paths[path]]


def ids(score: PriorScore, path: str) -> list[str]:
    return [c.prior_id for c in score.paths[path]]


def by_role(score: PriorScore, path: str, role: str) -> CandidateScore:
    (c,) = [c for c in score.paths[path] if c.role == role]
    return c


def ads_of(c: CandidateScore) -> dict[str, AdScore]:
    return {a.ad_id: a for a in c.ads}


# ------------------------------------------------- hand-computed numbers (§5, R7, R17)


def test_L7_two_ads_match_hand_computed_betabinomial_values(env: Env) -> None:
    lead = lead_params()
    add_poll(env.store, T1, TWO_ADS)
    score = env.score(config())
    assert score.client_id == CLIENT
    assert score.scored_at == NOW
    assert score.conversion_kind == "purchase"
    assert score.days == (D1, D2)  # R12
    assert set(score.paths) == {"ctr", "cvr"}

    priors = {
        ("ctr", "in_force"): purchase_params("ctr"),
        ("cvr", "in_force"): purchase_params("cvr"),
        ("cvr", "framework_lead"): lead,  # R9: framework_lead for cvr always
    }
    totals: dict[tuple[str, str], float] = {}
    for (path, role), params in priors.items():
        cand = by_role(score, path, role)
        assert cand.family == "beta"
        assert cand.params == params
        assert cand.skipped == {}
        got = ads_of(cand)
        assert set(got) == {"ad_a", "ad_b"}
        assert got["ad_a"].ad_name == "Hero" and got["ad_b"].ad_name == "Static"
        wants = {ad: expect(params, *TWO_ADS_COUNTS[ad][path]) for ad in got}
        for ad, want in wants.items():
            check_ad(got[ad], want)
        total = sum(w["log_score"] for w in wants.values())
        assert abs(cand.log_score - total) <= TOL  # §5: summed over scored ads
        assert cand.n_ads == 2
        assert cand.n_surprised == sum(w["surprised"] for w in wants.values())
        totals[(path, role)] = total

    assert by_role(score, "ctr", "in_force").log_bf_vs_in_force == 0.0  # §5: 0 for in_force
    assert by_role(score, "cvr", "in_force").log_bf_vs_in_force == 0.0
    bf = by_role(score, "cvr", "framework_lead").log_bf_vs_in_force
    want_bf = totals[("cvr", "framework_lead")] - totals[("cvr", "in_force")]
    assert abs(bf - want_bf) <= TOL  # §5, R8: relative to the prior in force


def test_L7_tail_at_k_zero_is_half_the_pmf(env: Env) -> None:
    add_poll(env.store, T1, [("ad_z", D1, 400, 0, 0.0, None, None)])
    score = env.score(config())
    ad = ads_of(by_role(score, "ctr", "in_force"))["ad_z"]
    p = purchase_params("ctr")
    want = expect(p, 400, 0)
    half_pmf = 0.5 * float(stats.betabinom(400, p["a"], p["b"]).pmf(0))
    assert abs(want["tail"] - half_pmf) < 1e-15
    check_ad(ad, want)  # R7: cdf(k - 1) is 0 when k = 0
    assert ad.surprised == (want["tail"] < surprise_tail())
    assert ad.ad_name is None
    # n = 0 for cvr: no scored ad on the path (R12); whether the path is then absent from
    # ``paths`` or present with empty candidates is not fixed by the spec, so either is accepted
    assert score.not_scored.get("cvr") == NO_ADS_WITH_DATA
    for cand in score.paths.get("cvr", []):
        assert cand.ads == [] and cand.skipped == {"ad_z": NO_TRIALS}  # R6


# ------------------------------------------------------------------ R4: merge across polls


def test_L7_rows_merge_per_ad_and_date_with_the_later_ok_poll_winning(env: Env) -> None:
    t2 = T1 + dt.timedelta(hours=1)
    t3 = T1 + dt.timedelta(hours=2)
    t4 = T1 + dt.timedelta(hours=3)
    # inserted out of order: the later poll first, so the scorer must order by started_at
    add_poll(
        env.store,
        t2,
        [
            ("ad_a", D2, 200, 20, 5.0, None, "Hero"),
            ("ad_a", D3, 300, 30, 3.0, None, "Hero"),
            (None, dt.date(2026, 10, 1), 9000, 900, 90.0, None, None),  # no ad id: ignored (R4)
        ],
    )
    add_poll(
        env.store,
        T1,
        [("ad_a", D1, 100, 10, 1.0, None, "Hero"), ("ad_a", D2, 100, 10, 1.0, None, "Hero")],
    )
    # an error poll carrying rows (the fake allows it): never read (R4, ok only)
    add_poll(
        env.store,
        t3,
        [
            ("ad_a", D3, 9999, 999, 99.0, None, "Hero"),
            ("ad_err", dt.date(2026, 12, 1), 50, 5, 1.0, None, None),
        ],
        status="error",
    )
    add_poll(env.store, t4, [("ad_int", D3, 50, 5, 1.0, None, None)], finish=False)  # interrupted
    score = env.score(config())
    ctr = by_role(score, "ctr", "in_force")
    cvr = by_role(score, "cvr", "in_force")
    assert set(ads_of(ctr)) == {"ad_a"} and set(ads_of(cvr)) == {"ad_a"}
    # D1 from the first poll, D2 and D3 from the later one
    check_ad(ads_of(ctr)["ad_a"], expect(purchase_params("ctr"), 600, 60))
    check_ad(ads_of(cvr)["ad_a"], expect(purchase_params("cvr"), 60, 9))
    assert score.days == (D1, D3)  # R12: rows used, not the ignored ones


# ------------------------------------------------------------------ R5: conversions, rounding


def test_L7_cvr_prefers_observed_drops_none_rows_and_rounds_half_up(env: Env) -> None:
    add_poll(
        env.store,
        T1,
        [
            # sum 1.25 + 1.25 = 2.5, rounded half-up once to 3 (Python round would give 2)
            ("ad_r", D1, 500, 10, 1.25, None, None),
            ("ad_r", D2, 500, 10, 1.25, None, None),
            # observed 4 wins over reported 7.0; a row with both None is left out with its 6
            # clicks; 0.4 reported; sum 4.4 rounds to 4 over 10 + 5 clicks
            ("ad_o", D1, 300, 10, 7.0, 4, None),
            ("ad_o", D2, 300, 6, None, None, None),
            ("ad_o", D3, 300, 5, 0.4, None, None),
            # every row None: skipped for cvr, still scored for ctr
            ("ad_n", D1, 400, 8, None, None, None),
        ],
    )
    score = env.score(config())
    cvr = by_role(score, "cvr", "in_force")
    got = ads_of(cvr)
    p = purchase_params("cvr")
    check_ad(got["ad_r"], expect(p, 20, 3))  # R5: floor(2.5 + 0.5) = 3
    check_ad(got["ad_o"], expect(p, 15, 4))  # R5: observed preferred, None row and clicks dropped
    assert "ad_n" not in got
    assert cvr.skipped == {"ad_n": NO_CONVERSION_ROWS}  # R5
    ctr = ads_of(by_role(score, "ctr", "in_force"))
    q = purchase_params("ctr")
    check_ad(ctr["ad_o"], expect(q, 900, 21))  # ctr counts every row
    check_ad(ctr["ad_n"], expect(q, 400, 8))


def test_L7_skip_reasons_for_ctr_and_cvr(env: Env) -> None:
    add_poll(
        env.store,
        T1,
        [
            ("ad_ok", D1, 1000, 20, 2.0, None, None),
            ("ad_ok2", D1, 1000, 25, 1.0, None, None),
            ("ad_zero", D1, 0, 0, 0.0, None, None),  # n = 0 on both paths
            ("ad_vt", D1, 100, 5, 7.0, None, None),  # k > n on cvr (view-through, D34)
            ("ad_ci", D1, 3, 7, 0.0, None, None),  # clicks above impressions
        ],
    )
    score = env.score(config())
    assert NO_TRIALS == "no trials"  # R6 strings, as the skeleton set them
    assert CLICKS_ABOVE_IMPRESSIONS == "clicks above impressions"
    assert CONVERSIONS_ABOVE_CLICKS == "reported conversions above clicks (D34)"
    assert NO_CONVERSION_ROWS == "no rows with conversions"
    for cand in score.paths["ctr"]:
        assert cand.skipped == {"ad_zero": NO_TRIALS, "ad_ci": CLICKS_ABOVE_IMPRESSIONS}  # R6
        assert set(ads_of(cand)) == {"ad_ok", "ad_ok2", "ad_vt"}
    for cand in score.paths["cvr"]:  # R8: every candidate scores the same set of ads
        assert cand.skipped == {"ad_zero": NO_TRIALS, "ad_vt": CONVERSIONS_ABOVE_CLICKS}  # R6
        assert set(ads_of(cand)) == {"ad_ok", "ad_ok2", "ad_ci"}
        assert cand.n_ads == 3
    check_ad(
        ads_of(by_role(score, "cvr", "in_force"))["ad_ci"], expect(purchase_params("cvr"), 7, 0)
    )


# ------------------------------------------------------------------ R9: candidates


def test_L7_purchase_client_candidates_ordered_and_deduplicated(env: Env) -> None:
    add_poll(env.store, T1, TWO_ADS)
    score = env.score(config())
    assert roles(score, "cvr") == ["in_force", "framework_lead"]  # R9: purchase dup dropped
    assert ids(score, "cvr") == [purchase_id("cvr"), lead_id()]
    assert roles(score, "ctr") == ["in_force"]  # every framework role resolves to the same id
    assert ids(score, "ctr") == [purchase_id("ctr")]
    assert by_role(score, "cvr", "in_force").resolution == default_resolution(CLIENT, "cvr")
    assert by_role(score, "cvr", "framework_lead").resolution == default_resolution(
        ps.FRAMEWORK_CLIENT, "cvr", "lead_records"
    )  # R9: carried verbatim


def test_L7_lead_client_candidates_ordered_and_deduplicated(env: Env) -> None:
    add_poll(env.store, T1, TWO_ADS)
    score = env.score(lead_config())
    assert score.conversion_kind == "lead"  # meta.is_lead_event, as in refresh
    assert roles(score, "cvr") == ["in_force", "framework_purchase"]  # R9: first role wins
    assert ids(score, "cvr") == [lead_id(), purchase_id("cvr")]
    assert by_role(score, "cvr", "in_force").resolution == default_resolution(
        CLIENT, "cvr", "lead_records"
    )
    assert by_role(score, "cvr", "framework_purchase").resolution == default_resolution(
        ps.FRAMEWORK_CLIENT, "cvr"
    )
    assert ids(score, "ctr") == [purchase_id("ctr")]
    assert roles(score, "ctr") == ["in_force"]


def test_L7_client_priors_give_every_role_and_bayes_factors_against_in_force(env: Env) -> None:
    cvr_pid = env.client_prior("cvr", {"a": 6.0, "b": 24.0})
    ctr_pid = env.client_prior("ctr", {"a": 3.0, "b": 97.0})
    add_poll(env.store, T1, TWO_ADS)
    score = env.score(lead_config())
    assert roles(score, "cvr") == ["in_force", "framework_lead", "framework_purchase"]  # R9
    assert ids(score, "cvr") == [cvr_pid, lead_id(), purchase_id("cvr")]
    assert by_role(score, "cvr", "in_force").resolution == f"client:{CLIENT}:{cvr_pid}"
    # ctr: the client prior, then the purchase default once (its role is the first that
    # reaches it; the spec does not say which name a ctr framework row carries)
    assert ids(score, "ctr") == [ctr_pid, purchase_id("ctr")]
    assert roles(score, "ctr")[0] == "in_force"
    assert roles(score, "ctr")[1] in ("framework_lead", "framework_purchase")
    for path in ("ctr", "cvr"):
        cands = score.paths[path]
        base = cands[0].log_score
        assert cands[0].log_bf_vs_in_force == 0.0
        for c in cands[1:]:
            assert abs(c.log_bf_vs_in_force - (c.log_score - base)) <= TOL  # R8
    inf = by_role(score, "cvr", "in_force")
    check_ad(ads_of(inf)["ad_b"], expect({"a": 6.0, "b": 24.0}, 30, 6))


def test_L7_equal_params_with_different_ids_are_both_shown(env: Env) -> None:
    params = lead_params()
    pid = env.client_prior("cvr", params, conversion_kind="lead")
    assert pid != lead_id()
    add_poll(env.store, T1, TWO_ADS)
    score = env.score(lead_config())
    assert ids(score, "cvr") == [pid, lead_id(), purchase_id("cvr")]  # R9
    a, b = score.paths["cvr"][:2]
    assert a.params == b.params
    assert abs(b.log_bf_vs_in_force) <= TOL


# ------------------------------------------------- R10: reads under data_dir, never writes


def test_L7_score_reads_the_registry_under_data_dir_and_writes_nothing(env: Env) -> None:
    pid = env.client_prior("cvr", {"a": 6.0, "b": 24.0})  # only under data_dir
    add_poll(env.store, T1, TWO_ADS)
    before = env.files()
    score = env.score(config())
    assert ids(score, "cvr")[0] == pid  # R10: the registry swap to data_dir
    assert os.environ["BAYES_DATA_DIR"] == env.iso  # R10: put back
    assert env.files() == before  # §5: score_priors never writes


# ------------------------------------------------------------------ R12, R18: not_scored and empty


def test_L7_non_beta_prior_is_listed_as_not_scored(env: Env, iso: Any) -> None:
    def make_ctr_normal(data: dict[str, Any]) -> None:
        data["records"]["ctr"] = {"family": "normal", "params": {"loc": 0.02, "scale": 0.01}}

    iso.edit_yaml("priors/default", make_ctr_normal)
    add_poll(env.store, T1, TWO_ADS)
    score = env.score(config())
    pid = C.make_id("pr_", {"default": "ctr", "params": {"loc": 0.02, "scale": 0.01}})
    assert f"ctr:{pid}" in score.not_scored  # R12: "<path>:<prior_id>" for a non-Beta prior
    assert all(c.family == "beta" for c in score.paths.get("ctr", []))  # §5: only Beta scored
    assert by_role(score, "cvr", "in_force").n_ads == 2


def test_L7_path_with_no_scored_ads_is_in_not_scored(env: Env) -> None:
    add_poll(env.store, T1, [("ad_a", D1, 1000, 20, None, None, None)])
    score = env.score(config())
    assert score.not_scored.get("cvr") == NO_ADS_WITH_DATA  # R12
    assert all(c.n_ads == 0 for c in score.paths.get("cvr", []))
    assert by_role(score, "ctr", "in_force").n_ads == 1
    assert score.days == (D1, D1)


def test_L7_no_rows_gives_empty_paths_and_reasons(env: Env) -> None:
    score = env.score(config())
    assert score.paths == {}  # R18
    assert score.days is None
    assert score.not_scored.get("ctr") == NO_ADS_WITH_DATA  # R12, R18
    assert score.not_scored.get("cvr") == NO_ADS_WITH_DATA


# ------------------------------------------------- R11: write_score, load_latest_score


def sample_score(scored_at: dt.datetime, *, client: str = CLIENT) -> PriorScore:
    """A hand-built score: two ads under ctr, two candidates under cvr, one ad low and one high."""

    def ad(ad_id: str, name: str | None, tail: float, n: int, k: int) -> AdScore:
        return AdScore(
            ad_id=ad_id, ad_name=name, n=n, k=k, raw_rate=k / n,
            prior_q05=0.004, prior_q50=0.017, prior_q95=0.05,
            tail=tail, surprised=tail < 0.05 or tail > 0.95, log_score=-3.25,
            prior_weight=0.5, posterior_mean=0.03, shrinkage=-0.01,
        )  # fmt: skip

    def cand(role: str, pid: str, ads: list[AdScore], bf: float) -> CandidateScore:
        return CandidateScore(
            role=role, prior_id=pid, family="beta", params={"a": 1.0, "b": 49.0},
            resolution=f"client:{client}:none > vertical:unmapped > default:x@v1",
            ads=ads, skipped={"ad_skip": NO_TRIALS}, log_score=-6.5,
            n_ads=len(ads), n_surprised=sum(a.surprised for a in ads), log_bf_vs_in_force=bf,
        )  # fmt: skip

    low = ad("ad_low", "Hero Video", 0.01, 400, 1)
    high = ad("ad_high", "Static Image", 0.99, 300, 40)
    return PriorScore(
        client_id=client,
        scored_at=scored_at,
        conversion_kind="lead",
        days=(D1, D3),
        paths={
            "ctr": [cand("in_force", "pr_0000c7a1", [low, high], 0.0)],
            "cvr": [
                cand("in_force", "pr_0000c7a2", [low, high], 0.0),
                cand("framework_lead", "pr_0000c7a3", [low, high], 1.75),
            ],
        },
        not_scored={"ctr:pr_0000c7a4": "family normal"},
    )


def test_L7_write_score_names_the_file_from_scored_at(tmp_path: Path) -> None:
    score = sample_score(NOW)
    path = write_score(score, tmp_path)
    assert path == tmp_path / "prior_scores" / CLIENT / "20261110T180000Z.json"  # §5, R11
    data = json.loads(path.read_text())
    assert data["client_id"] == CLIENT
    assert data["scored_at"] == NOW.isoformat()  # R11: datetimes as ISO strings
    assert data["days"] == [D1.isoformat(), D3.isoformat()]  # R11: dates as ISO strings
    assert data["conversion_kind"] == "lead"
    cand = data["paths"]["cvr"][1]
    assert cand["log_bf_vs_in_force"] == 1.75  # R8: the JSON key stays
    assert cand["role"] == "framework_lead"
    assert cand["ads"][0]["ad_id"] == "ad_low"
    assert data["not_scored"] == {"ctr:pr_0000c7a4": "family normal"}


def test_L7_write_score_never_overwrites_and_suffixes_collisions(tmp_path: Path) -> None:
    score = sample_score(NOW)
    first = write_score(score, tmp_path)
    content = first.read_bytes()
    second = write_score(score, tmp_path)
    third = write_score(score, tmp_path)
    folder = tmp_path / "prior_scores" / CLIENT
    assert first.name == "20261110T180000Z.json"
    assert second == folder / "20261110T180000Z-2.json"  # R11
    assert third == folder / "20261110T180000Z-3.json"
    assert first.read_bytes() == content  # §5: never overwrites
    assert sorted(p.name for p in folder.iterdir()) == sorted([first.name, second.name, third.name])


def test_L7_write_score_leaves_a_foreign_file_in_place(tmp_path: Path) -> None:
    folder = tmp_path / "prior_scores" / CLIENT
    folder.mkdir(parents=True)
    taken = folder / "20261110T180000Z.json"
    taken.write_text("not mine")
    path = write_score(sample_score(NOW), tmp_path)
    assert path.name == "20261110T180000Z-2.json"  # R11
    assert taken.read_text() == "not mine"


def test_L7_load_latest_score_round_trips(tmp_path: Path) -> None:
    assert load_latest_score(CLIENT, tmp_path) is None  # R11: none yet
    older = sample_score(NOW - dt.timedelta(days=1))
    newer = sample_score(NOW)
    write_score(newer, tmp_path)
    write_score(older, tmp_path)
    got = load_latest_score(CLIENT, tmp_path)
    assert got == newer  # R11: lexicographically last file, dataclasses rebuilt
    assert isinstance(got, PriorScore)
    assert isinstance(got.paths["cvr"][0], CandidateScore)
    assert isinstance(got.paths["cvr"][0].ads[0], AdScore)
    assert isinstance(got.scored_at, dt.datetime) and got.scored_at.tzinfo is not None
    assert got.days == (D1, D3) and isinstance(got.days, tuple)
    assert load_latest_score("another_client", tmp_path) is None


def test_L7_empty_score_round_trips(tmp_path: Path) -> None:
    empty = PriorScore(
        client_id=CLIENT,
        scored_at=NOW,
        conversion_kind="purchase",
        days=None,
        paths={},
        not_scored={"ctr": NO_ADS_WITH_DATA, "cvr": NO_ADS_WITH_DATA},
    )
    write_score(empty, tmp_path)  # R18: written even with no scored ad
    assert load_latest_score(CLIENT, tmp_path) == empty


# ------------------------------------------------------------------ CLI


class Cli:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.live = tmp_path / "live"
        self.live.mkdir()
        self.configs = tmp_path / "configs"
        self.configs.mkdir()
        self.data_dir = tmp_path / "engine_data"
        self.data_dir.mkdir()
        monkeypatch.setenv("BAYES_LIVE_DIR", str(self.live))
        monkeypatch.setenv("BAYES_CONFIG_DIR", str(self.configs))
        monkeypatch.setenv("BAYES_DATA_DIR", str(self.data_dir))
        self.mp = monkeypatch

    def write_config(self, cfg: C.ClientConfig) -> None:
        path = self.configs / f"{cfg.client_id}.yaml"
        path.write_text(yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False))

    def seed(self, spec: Spec, started: dt.datetime = T1) -> None:
        store = SqliteStore.open(self.live / "live.sqlite")
        try:
            add_poll(store, started, spec)
        finally:
            store.close()

    def score_files(self, client: str = CLIENT) -> list[Path]:
        folder = self.data_dir / "prior_scores" / client
        return sorted(folder.glob("*.json")) if folder.exists() else []


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Cli:
    return Cli(tmp_path, monkeypatch)


def role_names(role: str) -> set[str]:
    return {role, registries.load("phrasing")["live_columns"][role]}


def test_L7_cli_score_priors_writes_a_file_and_prints_a_line_per_candidate(
    cli_env: Cli, capsys: pytest.CaptureFixture[str]
) -> None:
    cli_env.write_config(config())
    cli_env.seed(TWO_ADS)
    assert cli.main(["live", "score-priors", "--client", CLIENT]) == 0
    files = cli_env.score_files()
    assert len(files) == 1  # §5 CLI: scores and writes
    score = load_latest_score(CLIENT, cli_env.data_dir)
    assert score is not None and set(score.paths) == {"ctr", "cvr"}
    lines = capsys.readouterr().out.splitlines()
    matched: set[int] = set()
    for path, cands in score.paths.items():
        for c in cands:
            hits = [
                i
                for i, line in enumerate(lines)
                if path in line
                and any(r in line for r in role_names(c.role))
                and c.family in line
                and str(c.n_ads) in line
                and str(c.n_surprised) in line
            ]
            assert hits, (path, c.role, lines)  # §5 CLI: one line per (path, candidate)
            matched.add(hits[0])
    n_cands = sum(len(v) for v in score.paths.values())
    assert len(matched) == n_cands  # a distinct line for each


def test_L7_cli_score_priors_with_no_data_writes_and_exits_zero(
    cli_env: Cli, capsys: pytest.CaptureFixture[str]
) -> None:
    cli_env.write_config(config())
    assert cli.main(["live", "score-priors", "--client", CLIENT]) == 0  # R18
    assert len(cli_env.score_files()) == 1  # R18: the file is still written
    score = load_latest_score(CLIENT, cli_env.data_dir)
    assert score is not None and score.paths == {} and score.not_scored
    out = [x for x in capsys.readouterr().out.splitlines() if x.strip()]
    assert len(out) == 1, out  # R18: one line


def fake_poll(spec: Spec) -> Any:
    def poll(cfg: C.ClientConfig, store: Any, clock: Any, **kw: Any) -> PollRecord:
        return add_poll(store, clock.now(), spec, client=cfg.client_id)

    return poll


def test_L7_live_poll_runs_the_scoring_after_refresh(
    cli_env: Cli, capsys: pytest.CaptureFixture[str]
) -> None:
    from bayesian_marketing.live import poll as poll_mod

    cli_env.write_config(config())  # no economics: the refresh is skipped (R18 still scores)
    cli_env.mp.setattr(poll_mod, "poll", fake_poll(TWO_ADS))
    assert cli.main(["live", "poll", "--client", CLIENT]) == 0
    files = cli_env.score_files()
    assert len(files) == 1  # §5 CLI, R18: scored after a refresh that ran or was skipped
    score = load_latest_score(CLIENT, cli_env.data_dir)
    assert score is not None and by_role(score, "cvr", "in_force").n_ads == 2


def test_L7_a_failing_scorer_never_fails_live_poll(
    cli_env: Cli, capsys: pytest.CaptureFixture[str]
) -> None:
    from bayesian_marketing.live import poll as poll_mod

    calls: list[str] = []

    def boom(cfg: C.ClientConfig, *args: Any, **kw: Any) -> Any:
        calls.append(cfg.client_id)
        raise RuntimeError("scorer boom")

    cli_env.write_config(config())
    cli_env.mp.setattr(poll_mod, "poll", fake_poll(TWO_ADS))
    cli_env.mp.setattr(ps, "score_priors", boom)  # where cli imports it from
    if hasattr(cli, "score_priors"):
        cli_env.mp.setattr(cli, "score_priors", boom)
    assert cli.main(["live", "poll", "--client", CLIENT]) == 0  # §5 CLI, R18: never fails the poll
    assert calls == [CLIENT]  # the poll did call the scorer
    out = capsys.readouterr()
    assert "scorer boom" in out.out + out.err  # one line says what failed
    assert cli_env.score_files() == []


# ------------------------------------------------------------------ page (§5 Page, R8, R16)

PAGE_NOW = dt.datetime(2026, 11, 10, 18, 0, tzinfo=UTC)
PAGE_POLL = PAGE_NOW - dt.timedelta(minutes=30)
HEAD = re.compile(r"<(h[1-6])[^>]*>(.*?)</\1>", re.S | re.I)
H2 = re.compile(r"<h2[^>]*>(.*?)</h2>", re.S | re.I)


def text_of(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def phrasing() -> dict[str, Any]:
    return registries.load("phrasing")


def priors_section(page: str) -> str:
    """The HTML after the heading whose text is live.priors_title, to the next h2 or the end.
    The heading must come after the engine heading (§5 Page)."""
    live = phrasing()["live"]
    heads = [(m.start(), m.end(), text_of(m.group(2))) for m in HEAD.finditer(page)]
    engine = [s for s, _, t in heads if t == live["h_engine"]]
    mine = [(s, e) for s, e, t in heads if t == live["priors_title"]]
    assert engine and mine, [t for *_, t in heads]
    start, end = mine[0]
    assert start > engine[0]  # after the engine section
    nxt = [m.start() for m in H2.finditer(page) if m.start() > start]
    return page[end : nxt[0] if nxt else len(page)]


def rows_of(fragment: str) -> list[str]:
    return [text_of(m.group(1)) for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", fragment, re.S | re.I)]


def page_store() -> FakeStore:
    store = FakeStore()
    spec: Spec = [
        ("ad_low", D3, 400, 1, 0.0, None, "Hero Video"),
        ("ad_high", D3, 300, 40, 2.0, None, "Static Image"),
    ]
    add_poll(store, PAGE_POLL, spec)
    return store


def render(store: FakeStore, data_dir: Path) -> str:
    return view.render(
        store,
        CLIENT,
        FixedClock(PAGE_NOW),
        registry=load_live_registry(),
        phrasing=phrasing(),
        data_dir=data_dir,
        config=lead_config(),
    )


def test_L7_page_without_a_score_file_says_so(tmp_path: Path) -> None:
    page = render(page_store(), tmp_path)
    sec = priors_section(page)  # §5 Page: a section after the engine section
    live = phrasing()["live"]
    assert live["no_prior_score"] == "No prior score yet."  # R16
    assert live["no_prior_score"] in text_of(sec)
    assert "<table" not in sec.lower()


def test_L7_page_with_a_score_file_shows_candidates_and_in_force_ads(tmp_path: Path) -> None:
    scored = PAGE_NOW - dt.timedelta(minutes=10)  # after the latest ok poll: not stale
    write_score(sample_score(scored), tmp_path)
    page = render(page_store(), tmp_path)
    sec = priors_section(page)
    text = text_of(sec)
    live = phrasing()["live"]
    cols = phrasing()["live_columns"]
    assert live["no_prior_score"] not in text
    assert live["prior_score_stale"] not in text  # R16
    assert live["prior_score_note"] in text  # R8: the note on the log score
    for key in ("role", "prior", "ads_surprised", "log_score_vs_in_force"):  # candidate table
        assert cols[key] in text, key
    for key in (
        "trials",
        "successes",
        "raw_rate",
        "prior_range",
        "tail",
        "prior_weight",
        "shrinkage",
    ):
        assert cols[key] in text, key  # per-ad table for the in-force prior
    assert cols["scored_at"] in text  # R16: the score's own scored_at
    shown = {scored.isoformat(), view.fmt_utc(scored), scored.strftime("%Y-%m-%d %H:%M")}
    assert any(s in text for s in shown), text
    assert cols["in_force"] in text and cols["framework_lead"] in text  # role labels
    ad_rows = [r for r in rows_of(sec) if "Hero Video" in r or "Static Image" in r]
    assert any("Hero Video" in r for r in ad_rows) and any("Static Image" in r for r in ad_rows)
    low = [r for r in ad_rows if "Hero Video" in r]
    high = [r for r in ad_rows if "Static Image" in r]
    assert any(live["tail_low"] in r for r in low)  # R7: the page says which tail
    assert any(live["tail_high"] in r for r in high)


def test_L7_page_marks_a_score_older_than_the_latest_ok_poll_stale(tmp_path: Path) -> None:
    write_score(sample_score(PAGE_POLL - dt.timedelta(hours=1)), tmp_path)
    page = render(page_store(), tmp_path)
    text = text_of(priors_section(page))
    assert phrasing()["live"]["prior_score_stale"] in text  # R16
    assert phrasing()["live"]["no_prior_score"] not in text


def test_L7_constants_match_the_spec() -> None:
    """Guard: the skeleton's names and strings as R5, R6, R9 and R12 give them."""
    assert ps.PATHS == ("ctr", "cvr")
    assert ps.ROLES == ("in_force", "framework_lead", "framework_purchase")
    assert ps.SCORES_DIR == "prior_scores"
    assert NO_ADS_WITH_DATA == "no ads with data"
    assert math.isclose(surprise_tail(), 0.05)
