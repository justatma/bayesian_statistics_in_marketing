"""P10 claims and reporting (spec v0.3 §10, §12, G5, G7, I11, I13).

# CONTRACT ASSUMPTION: G5 matches a quoted percent against every bundle quantity's summary values
#   formatted with phrasing.yaml rounding (percent_decimals: 1, e.g. 0.0213 -> "2.1%").
# CONTRACT ASSUMPTION: narrative names options by the exact strings in Comparison.options (here
#   the ad ids), and "X is better than Y" is a comparative; the decision basis it needs is the
#   decision_feasibility of the bundle's recommendation(s).
# CONTRACT ASSUMPTION: a rejecting GateResult names the injected claim: one of its reasons
#   contains the offending token (the number as written, the causal verb, or the option name).
# CONTRACT ASSUMPTION: the 120 property bundles are built by tests/fakes from the shapes of the
#   simulator scenarios (40 shaped as tiny_campaign or fractional_conversions) rather than by
#   running P2 + P11, so P10 can be tested in wave 3.
# CONTRACT ASSUMPTION: render writes HTML to RenderedReport.html_path; tests read it as text.
#   render raises core.GateFailure with gate "G7" when provenance is missing, listing the
#   quantity ids; a client bundle with a synthetic quantity (built without validation) is
#   refused with an exception other than NotImplementedError.
# CONTRACT ASSUMPTION: the not-knowable block shows Feasibility.available and .required as
#   integers and does not show the quantity's estimate.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

import pytest

from bayesian_marketing import core as C
from bayesian_marketing.claims.check import check_narrative
from bayesian_marketing.core import registries
from bayesian_marketing.reporting.render import render
from tests.fakes import builders as B

pytestmark = pytest.mark.piece("P10")


def _phr() -> dict:
    return registries.load("phrasing")


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _rate_q(name: str, ad: str, mean: float, status: str, *, notices=None, design="observational",
            synthetic=True, n=None):  # fmt: skip
    n = n or {"estimable": 20000, "marginal": 2000, "below_floor": 100}[status]
    return B.quantity(
        name,
        ad,
        estimate=B.beta_spec(mean * n, (1 - mean) * n),
        status=status,
        design=design,
        synthetic=synthetic,
        notices=notices,
        pulls=[B.META_PULL, B.ORDERS_PULL],
        evidence="delivery" if name == "ctr" else "commercially_realized",
        quantity_id=f"q_{name}_{ad}_{int(mean * 1e6)}",
    )


@dataclass
class Case:
    bundle: C.ReportBundle
    clean: str
    corrupted: dict[str, tuple[str, str]]  # kind -> (text, token)


def _displays(q: C.Quantity) -> set[str]:
    return {pct(v) for v in q.estimate.summary.values()}


def _make_case(i: int) -> Case:
    rng = random.Random(1000 + i)
    shape = "tiny" if i < 20 else "fractional" if i < 40 else "regular"
    phr = _phr()
    caveat = phr["caveat_marginal"]
    while True:
        ks = rng.sample(range(5, 95), 3)
        m1, m2, m3 = ((k + 0.3) / 1000 for k in ks)
        s1 = "marginal" if shape == "fractional" else "estimable"
        notes = [phr["notices"]["platform_modeled"]] if shape == "fractional" else None
        q1 = _rate_q("ctr", "ad_a", m1, s1, notices=notes)
        q2 = _rate_q("cvr", "ad_b", m2, "marginal", notices=notes)
        q3 = _rate_q("cvr", "ad_c", m3, "below_floor", notices=notes)
        others = _displays(q1) | _displays(q2)
        if pct(m3) not in others and pct(m1) != pct(m2):
            break
    if shape == "tiny":
        rec = B.recommendation("not_knowable", status="below_floor", economics_id=None)
    else:
        rec = B.recommendation("allocate", status=rng.choice(["estimable", "marginal"]))
    comp = B.comparison(("ad_a", "ad_b"), p_best={"ad_a": 0.1, "ad_b": 0.9})
    bundle = B.bundle(
        "internal",
        [q1, q2, q3],
        recommendations=[rec],
        comparisons=[comp],
        know=B.knowability(not_knowable=[q3.quantity_id]),
    )

    def rate_sentence(label: str, ad: str, q: C.Quantity, mean: float) -> str:
        if q.feasibility.status == "below_floor":
            return f"The {label} for {ad} is {phr['not_knowable']}."
        if q.feasibility.status == "marginal":
            return f"The {label} for {ad} is {pct(mean)}, but {caveat}."
        return f"The {label} for {ad} is {pct(mean)}."

    s1_txt = rate_sentence("click-through rate", "ad_a", q1, m1)
    s2_txt = rate_sentence("conversion rate", "ad_b", q2, m2)
    s3_txt = rate_sentence("conversion rate", "ad_c", q3, m3)
    parts = [s1_txt, s2_txt, s3_txt]
    if shape != "tiny":
        parts.append("ad_b is better than ad_a.")
    clean = " ".join(parts)

    corrupted = {
        "wrong_number": (clean.replace(pct(m1), "97.7%", 1), "97.7%"),
        "below_floor_as_finding": (
            clean.replace(s3_txt, f"The conversion rate for ad_c is {pct(m3)}."),
            pct(m3),
        ),
        "causal_without_randomization": (clean + " ad_b caused more orders than ad_a.", "caused"),
        "missing_marginal_caveat": (clean.replace(f"{pct(m2)}, but {caveat}", pct(m2)), pct(m2)),
        "comparative_without_comparison": (clean + " ad_c is better than ad_a.", "ad_c"),
    }
    for kind, (text, _) in corrupted.items():
        assert text != clean, kind
    return Case(bundle, clean, corrupted)


def _block(text: str, i: int) -> C.NarrativeBlock:
    return C.NarrativeBlock(block_id=f"nb_{i}", text=text, author="atmaos")


def test_P10_A_ai_property() -> None:
    cases = [_make_case(i) for i in range(120)]
    misses: list[str] = []
    for i, case in enumerate(cases):
        ok = check_narrative(_block(case.clean, i), case.bundle)
        assert ok.gate == "G5"
        if not ok.passed:
            misses.append(f"bundle {i}: clean draft rejected: {ok.reasons}")
        for kind, (text, token) in case.corrupted.items():
            res = check_narrative(_block(text, i), case.bundle)
            if res.passed:
                misses.append(f"bundle {i}: {kind} accepted")
            elif not any(token in r for r in res.reasons):
                misses.append(f"bundle {i}: {kind} rejected without naming {token!r}")
    assert not misses, "\n".join(misses[:20])


def test_P10_extra_incremental_needs_holdout() -> None:
    comp = B.comparison(("ad_a", "ad_b"), p_best={"ad_a": 0.05, "ad_b": 0.95})
    rec = B.recommendation("allocate")
    text = "ad_b drove more orders than ad_a."
    for design, verb_ok in (("randomized", True), ("observational", False)):
        qs = [
            _rate_q("cvr", "ad_a", 0.0213, "estimable", design=design),
            _rate_q("cvr", "ad_b", 0.0413, "estimable", design=design),
        ]
        b = B.bundle("internal", qs, recommendations=[rec], comparisons=[comp])
        assert check_narrative(_block(text, 0), b).passed is verb_ok, design
    inc = "ad_b generated incremental orders over ad_a."
    randomized = B.bundle(
        "internal",
        [_rate_q("cvr", "ad_b", 0.0413, "estimable", design="randomized")],
        recommendations=[rec],
        comparisons=[comp],
    )
    res = check_narrative(_block(inc, 0), randomized)
    assert res.passed is False and any("incremental" in r for r in res.reasons)
    holdout_q = B.quantity(
        "lift",
        "ad_b",
        estimate=B.beta_spec(30, 970),
        evidence="causally_incremental",
        design="holdout",
        quantity_id="q_lift_ad_b",
    )
    holdout = B.bundle("internal", [holdout_q], recommendations=[rec], comparisons=[comp])
    assert check_narrative(_block(inc, 0), holdout).passed is True


def _html(r: C.RenderedReport) -> str:
    return Path(r.html_path).read_text()


def test_P10_tiny_campaign_not_knowable_block(tmp_path: Path) -> None:
    q = B.quantity(
        "cvr",
        "ad_c",
        estimate=B.beta_spec(4.3, 95.7),
        feas=B.feasibility("below_floor", available=12, required=68),
        synthetic=True,
        quantity_id="q_tiny_cvr",
    )
    b = B.bundle(
        "demo",
        [q],
        recommendations=[B.recommendation("not_knowable", status="below_floor", economics_id=None)],
        know=B.knowability(not_knowable=[q.quantity_id]),
    )
    html = _html(render(b, tmp_path))
    assert _phr()["not_knowable"] in html.lower()
    assert "68" in html and "12" in html
    assert pct(q.estimate.summary["mean"]) not in html, "a below-floor rate must not be quoted"


def _nuts_bundle(diag: list[C.DiagnosticsReport], kind: str = "internal") -> C.ReportBundle:
    q = B.quantity("ctr", "ad_a", route="nuts", diagnostics_ref="dg_00000001", quantity_id="q_n1")
    return B.bundle(kind, [q], diagnostics=diag)


def test_P10_G7_blocks_untraced(tmp_path: Path) -> None:
    for diag in ([], [B.diagnostics_report(passed=False, rhat=1.2)]):
        with pytest.raises(C.GateFailure) as ei:
            render(_nuts_bundle(diag), tmp_path)
        assert ei.value.result.gate == "G7"
        assert any("q_n1" in r for r in ei.value.result.reasons)
    ok = render(_nuts_bundle([B.diagnostics_report(passed=True)]), tmp_path)
    assert Path(ok.html_path).exists()


def test_P10_client_report_refuses_synthetic(tmp_path: Path) -> None:
    good = B.bundle("client", [B.quantity()])
    bad = C.ReportBundle.model_construct(
        **{**dict(good), "quantities": [B.quantity(synthetic=True)]}
    )
    with pytest.raises(Exception) as ei:
        render(bad, tmp_path / "bad")
    assert not isinstance(ei.value, NotImplementedError)

    client = render(good, tmp_path / "client")
    assert client.watermark is None
    wm = _phr()["watermark"]
    demo = render(B.bundle("demo", [B.quantity(synthetic=True)]), tmp_path / "demo")
    assert demo.watermark == wm["demo"]
    assert wm["demo"] in _html(demo)
    internal = render(B.bundle("internal", [B.quantity()]), tmp_path / "internal")
    assert internal.watermark == wm["internal"]
    assert wm["demo"] not in _html(client) and wm["internal"] not in _html(client)


def test_P10_diagnostics_appendix_real(tmp_path: Path) -> None:
    rep = B.diagnostics_report(
        rhat=1.0042,
        ess_bulk=812.3,
        ess_tail=655.1,
        divergences=0,
        ppc={"delivery": 0.37, "ctr": 0.43, "cvr": 0.61, "value": 0.52},
        passed=True,
    )
    html = _html(render(_nuts_bundle([rep]), tmp_path / "nuts"))
    assert "1.0042" in html or "1.004" in html
    assert "812" in html and "655" in html
    for v in ("0.37", "0.43", "0.61", "0.52"):
        assert v in html
    conj = _html(render(B.bundle("internal", [B.quantity()]), tmp_path / "conj"))
    assert "exact conjugate model; no sampler ran" in conj


def test_P10_extra_narrative_needs_passing_G5(tmp_path: Path) -> None:
    passing = C.NarrativeBlock(
        block_id="nb_ok", text="Narrative that passed.", author="atmaos",
        gate=B.gate_result("G5", True),
    )  # fmt: skip
    failing = C.NarrativeBlock(
        block_id="nb_bad", text="Narrative that failed.", author="atmaos",
        gate=B.gate_result("G5", False),
    )  # fmt: skip
    unchecked = C.NarrativeBlock(block_id="nb_none", text="Never checked.", author="atmaos")
    html = _html(render(B.bundle("internal", narrative=[passing, failing, unchecked]), tmp_path))
    assert "Narrative that passed." in html
    assert "Narrative that failed." not in html
    assert "Never checked." not in html
