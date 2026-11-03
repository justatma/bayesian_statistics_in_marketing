"""P9 decisions and audit (spec v0.3 §8.2 to §8.4, §8.7, D9, D16).

# CONTRACT ASSUMPTION: in reallocate, Comparison.options[0] is the incumbent (keep) and the others
#   are switch candidates; the switching cost is ChannelModel.learning_phase_switching_cost. The
#   hold test swaps the registry so every ad platform has a $250 cost written as
#   {amount: "250", currency: USD}, so it does not matter which platform reallocate consults.
# CONTRACT ASSUMPTION: notices and stated caveats on a Recommendation (which has no notices field)
#   appear somewhere in its JSON (params, guarantee slots or assumptions); tests search the dump.
# CONTRACT ASSUMPTION: stop_or_continue treats every (entity, day) cell of FunnelData with clicks
#   > 0 for the compared options as a cited cohort; Comparison options are FunnelData entity ids.
# CONTRACT ASSUMPTION: Feasibility.required on a below-floor decision is the additional volume in
#   the objective's horizon unit; stop_or_continue prices it with test_design and compares with
#   ClientEconomics.test_budget.
# CONTRACT ASSUMPTION: allocate puts the split in params["allocation"] as {option: share}.
# CONTRACT ASSUMPTION: guarantee_report reads run_record (under BAYES_DATA_DIR) and keys by_source
#   with OutcomeRecord.source values; OutcomeRecord.realized carries "benefit" in account currency.
"""

from __future__ import annotations

import datetime as dt

import pytest

from bayesian_marketing import core as C
from bayesian_marketing.audit.report import guarantee_report
from bayesian_marketing.core import registries
from bayesian_marketing.decision import run_record
from bayesian_marketing.decision.allocation import allocate
from bayesian_marketing.decision.guarantees import render_guarantee
from bayesian_marketing.decision.reallocation import reallocate
from bayesian_marketing.decision.stopping import stop_or_continue
from tests.fakes import builders as B
from tests.oracle import north_pier as NP

pytestmark = pytest.mark.piece("P9")

RUN = "run_p9000001"


def _hold_comparison() -> C.Comparison:
    return B.comparison(
        ("keep", "switch"),
        p_best={"keep": 0.3, "switch": 0.7},
        expected_value={"keep": NP.HOLD_KEEP, "switch": NP.HOLD_SWITCH_EV},
        expected_loss={"keep": 350, "switch": 180},
    )


def _set_switching_cost(iso, amount: str | None) -> None:
    cost = None if amount is None else {"amount": amount, "currency": "USD"}

    def edit(d: dict) -> None:
        for p in ("meta", "google_ads", "linkedin"):
            d["channels"][p]["learning_phase_switching_cost"] = cost

    iso.edit_yaml("channels", edit)
    iso.edit_yaml(
        "decision_defaults",
        lambda d: d.update(
            learning_phase_switching_cost=dict.fromkeys(("meta", "google_ads", "linkedin"), cost)
        ),
    )


def _estimable() -> C.Feasibility:
    return B.feasibility("estimable", "decision_loss", target=1000.0)


def test_P9_hold_oracle(iso) -> None:
    assert NP.HOLD_SWITCH_EV - NP.HOLD_SWITCH_COST == NP.HOLD_NET < NP.HOLD_KEEP
    _set_switching_cost(iso, str(NP.HOLD_SWITCH_COST))
    rec = reallocate(_hold_comparison(), _estimable(), B.economics(), RUN)
    assert rec.action == "hold"
    assert rec.run_id == RUN
    assert rec.requires_human_approval is True


def test_P9_extra_unknown_switching_cost_is_costly(iso) -> None:
    _set_switching_cost(iso, None)
    rec = reallocate(_hold_comparison(), _estimable(), B.economics(), RUN)
    # benefit 1170 - 1000 = 170 > 0 with the cost taken as zero, which is stated (C1)
    assert rec.action == "reallocate"
    assert rec.reversibility == "costly"
    assert "switching cost" in rec.model_dump_json().lower()


def test_P9_extra_below_floor_decision_holds(iso) -> None:
    _set_switching_cost(iso, "0")
    below = B.feasibility("below_floor", "decision_loss", required=5000.0)
    rec = reallocate(_hold_comparison(), below, B.economics(), RUN)
    assert rec.action == "hold"


def _stop_data(last_day_mature: float) -> C.FunnelData:
    dates = [B.D_END - dt.timedelta(days=2 - i) for i in range(3)]
    mature = [1.0, 1.0, last_day_mature]
    return B.funnel_data(
        {
            ad: {
                "impressions": [5000] * 3,
                "clicks": [100] * 3,
                "spend": [120.0] * 3,
                "conv_obs": [3, 3, 1],
                "conv_rep": [3.0, 3.0, 1.0],
                "mature": mature,
            }
            for ad in ("ad_a", "ad_b")
        },
        dates=dates,
    )


def _stop_comparison() -> C.Comparison:
    return B.comparison(
        p_best={"ad_a": 0.02, "ad_b": 0.98},
        expected_value={"ad_a": -600, "ad_b": 90},
        expected_loss={"ad_a": 700, "ad_b": 5},
    )


def test_P9_premature_stop_refused() -> None:
    waiting = registries.resolve("phrasing/notices/waiting_late@v1")
    min_maturity = registries.resolve("bounds/lag/min_maturity@v1")
    econ = B.economics(test_budget=1_000_000)
    early = stop_or_continue(
        _stop_comparison(), _estimable(), _stop_data(min_maturity - 0.4), econ, RUN
    )
    assert early.action == "continue_test"
    assert waiting in early.model_dump_json()
    late = stop_or_continue(_stop_comparison(), _estimable(), _stop_data(1.0), econ, RUN)
    assert late.action == "stop_test"


def test_P9_below_floor_continues_or_not_knowable() -> None:
    below = B.feasibility("below_floor", "decision_loss", required=5000.0)
    data = _stop_data(1.0)
    rich = stop_or_continue(_stop_comparison(), below, data, B.economics(test_budget=10**9), RUN)
    assert rich.action == "continue_test"
    poor = stop_or_continue(_stop_comparison(), below, data, B.economics(test_budget=1), RUN)
    assert poor.action == "not_knowable"


def test_P9_extra_allocation_floor_and_cap() -> None:
    floor = registries.resolve("bounds/allocation/min_arm_share@v1")
    cap = registries.resolve("bounds/allocation/max_arm_share@v1")
    rec = allocate(B.comparison(p_best={"ad_a": 0.97, "ad_b": 0.03}), RUN)
    alloc = rec.params["allocation"]
    assert set(alloc) == {"ad_a", "ad_b"}
    assert sum(alloc.values()) == pytest.approx(1.0)
    assert alloc["ad_b"] >= floor - 1e-12
    assert alloc["ad_a"] <= cap + 1e-12
    assert rec.guarantee.kind == "posterior_probability"
    even = allocate(B.comparison(p_best={"ad_a": 0.6, "ad_b": 0.4}), RUN).params["allocation"]
    assert even["ad_a"] == pytest.approx(0.6) and even["ad_b"] == pytest.approx(0.4)


def _all_recs(iso) -> list[C.Recommendation]:
    _set_switching_cost(iso, str(NP.HOLD_SWITCH_COST))
    econ = B.economics(test_budget=10**9)
    below = B.feasibility("below_floor", "decision_loss", required=5000.0)
    return [
        reallocate(_hold_comparison(), _estimable(), econ, RUN),
        reallocate(
            B.comparison(
                ("keep", "switch"),
                p_best={"keep": 0.01, "switch": 0.99},
                expected_value={"keep": 100, "switch": 2000},
                expected_loss={"keep": 1900, "switch": 1},
            ),
            _estimable(),
            econ,
            RUN,
        ),
        stop_or_continue(_stop_comparison(), _estimable(), _stop_data(0.3), econ, RUN),
        stop_or_continue(_stop_comparison(), _estimable(), _stop_data(1.0), econ, RUN),
        stop_or_continue(_stop_comparison(), below, _stop_data(1.0), econ, RUN),
        stop_or_continue(
            _stop_comparison(), below, _stop_data(1.0), B.economics(test_budget=1), RUN
        ),
        allocate(B.comparison(p_best={"ad_a": 0.8, "ad_b": 0.2}), RUN),
    ]


def test_P9_every_recommendation_templated_and_approval_required(iso) -> None:
    templates = registries.load("guarantee_templates")["templates"]
    recs = _all_recs(iso)
    assert {r.action for r in recs} >= {"hold", "reallocate", "continue_test", "stop_test",
                                        "not_knowable", "allocate"}  # fmt: skip
    for r in recs:
        assert r.requires_human_approval is True
        assert r.run_id == RUN
        assert r.decision_feasibility.basis == "decision_loss"
        assert r.guarantee.template_id in templates
        assert templates[r.guarantee.template_id]["kind"] == r.guarantee.kind
        text = render_guarantee(r.guarantee)
        assert text and "{" not in text
        assert "execute" not in r.params and "api_call" not in r.params  # I3: no execution path
        if r.action not in ("not_knowable", "repair_measurement"):
            assert r.economics_id is not None


def test_P9_extra_audit_separates_sources() -> None:
    rec = B.recommendation(run_id=RUN, recommendation_id="rec_p9audit1")
    run_record.append(rec)
    run_record.append(B.outcome_record(rec.recommendation_id, "atmaos"))
    run_record.append(B.outcome_record(rec.recommendation_id, "ground_truth"))
    report = guarantee_report(B.D_START)
    assert isinstance(report, C.AuditReport)
    assert report.n_recommendations >= 1
    assert {"atmaos", "ground_truth"} <= set(report.by_source)


# CONTRACT ASSUMPTION (survival floor, §8.2 C3): an option whose Comparison.value_q05 is below
#   ClientEconomics.survival_floor is never recommended. reallocate reads the floor from its
#   `econ` argument; allocate, which takes no economics, resolves c.economics_id through
#   core.load_economics (configs/economics/<id>.json under BAYES_CONFIG_DIR). A blocked option
#   gets share 0 or is absent from params["allocation"]; a blocked switch target means the action
#   is not "reallocate"; the Recommendation's JSON mentions "survival floor" (case-insensitive).
def _with_q05(c: C.Comparison, q05: dict[str, int]) -> C.Comparison:
    return c.model_copy(update={"value_q05": {k: B.money(v) for k, v in q05.items()}})


def test_P9_survival_floor_respected(iso, tmp_path, monkeypatch) -> None:
    floor = 100
    econ = B.economics(survival_floor=floor)

    # reallocate: "switch" has the higher expected value but its q05 is below the floor.
    _set_switching_cost(iso, "0")
    c = _with_q05(_hold_comparison(), {"keep": 300, "switch": -200})
    assert float(c.expected_value["switch"].amount) > float(c.expected_value["keep"].amount)
    rec = reallocate(c, _estimable(), econ, RUN)
    assert rec.action != "reallocate"
    assert "survival floor" in rec.model_dump_json().lower()

    # allocate: "ad_a" has the higher expected value and p_best but q05 below the floor.
    cfg = tmp_path / "configs"
    (cfg / "economics").mkdir(parents=True)
    (cfg / "economics" / f"{econ.economics_id}.json").write_text(econ.model_dump_json())
    monkeypatch.setenv("BAYES_CONFIG_DIR", str(cfg))
    a = _with_q05(
        B.comparison(
            p_best={"ad_a": 0.8, "ad_b": 0.2},
            expected_value={"ad_a": 900, "ad_b": 400},
            expected_loss={"ad_a": 50, "ad_b": 500},
        ),
        {"ad_a": -500, "ad_b": 400},
    )
    arec = allocate(a, RUN)
    assert arec.params["allocation"].get("ad_a", 0) == 0
    assert "survival floor" in arec.model_dump_json().lower()
