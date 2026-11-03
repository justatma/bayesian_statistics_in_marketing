"""Command-line entry. Piece P11.

``python -m bayesian_marketing.cli demo --scenario north_pier_day14 --out <dir>`` simulates the
scenario, runs the pipeline end to end and renders the watermarked demo report into ``<dir>``,
printing each stage in plain words. No network, no model calls. When ``BAYES_DATA_DIR`` is unset
the run's stores go under ``<dir>/store`` so a demo never touches another run's record.

D38.4: a stage line is never stronger than the report. Lines use the report's option names (ad
ids), name the compared and requested quantities that are not knowable, show negative expected
values, give the recommended action's own expected loss (the split's loss for an allocation, the
report's "Expected loss") with the tolerance verdict for that same amount, and name the actual
fitting step, including the degraded NUTS steps.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SCENARIOS = REPO / "data" / "scenarios"
PLATFORM_NAMES = {
    "meta": "Meta",
    "google_ads": "Google Ads",
    "linkedin": "LinkedIn",
    "ga4": "GA4",
    "orders": "orders file",
}
SHOWN_SHARES = 3
"""Allocation shares and expected values named on one line; the rest are summed or counted."""
ACTIONS = {
    "allocate": "split the budget",
    "reallocate": "move budget",
    "hold": "hold",
    "stop_test": "stop the test",
    "continue_test": "keep the test running",
    "collect_more_data": "collect more data",
    "repair_measurement": "repair measurement",
    "not_knowable": "not knowable yet",
}
FIT_STEPS = {
    "conjugate": "exact per-ad model, {size} (too few ads for the joint model)",
    "nuts_full": "joint funnel model with the NUTS sampler, {size}",
    "nuts_static": (
        "joint funnel model with the NUTS sampler, static step, {size} "
        "(the full model failed its checks)"
    ),
    "nuts_unpooled": (
        "joint funnel model with the NUTS sampler, unpooled above the ad, {size} "
        "(the pooled steps failed their checks)"
    ),
    "fallback_conjugate": (
        "joint funnel model failed its checks; used the exact per-ad model, {size}"
    ),
}
LAG_SOURCES = {
    "orders_history": "estimated from {n} orders' click dates in the orders file",
    "platform_lag_report": "taken from the platform's lag report",
    "registry_default": "conversion lag assumed (default curve, {days}-day click window)",
}
LOSS_FOR = {
    "allocate": "for this split",
    "stop_test": "if we stop on {best}",
    "continue_test": "if we stopped now on {best}",
}


WHY_BOTH = "which ad is ahead is clear enough to act on; what each earns is not yet"


def _say(label: str, text: str) -> None:
    print(f"{label + ':':<16}{text}", flush=True)


def _count(n: int, word: str) -> str:
    return f"{n:,} {word}" + ("" if n == 1 else "s")


def _amount(m: Any, target: str) -> str:
    """A comparison amount in its objective's unit: money for contribution, else a count of
    clicks or orders (compare carries those as Money too, §8.1)."""
    from bayesian_marketing.decision.reallocation import fmt_money

    if target == "contribution":
        return fmt_money(m)
    return f"{float(m.amount):,.1f} {target}"


def _verdict(loss: Any, tolerance: Any, target: str) -> str:
    """The tolerance verdict for one expected loss, with the registry's marginal band (D9)."""
    from bayesian_marketing.core import registries
    from bayesian_marketing.decision.reallocation import fmt_money
    from bayesian_marketing.floors.estimability import DECISION_KEY

    if target != "contribution":
        return f"no money tolerance applies to a loss in {target}"
    if tolerance is None:
        return "no loss tolerance set"
    if tolerance.currency != loss.currency:
        return f"tolerance in {tolerance.currency}, loss in {loss.currency}: not compared"
    version = registries.load("bounds")["version"]
    mult = float(registries.resolve(f"{DECISION_KEY}@{version}")["marginal_multiplier"])
    amount, tol = float(loss.amount), float(tolerance.amount)
    if amount <= tol:
        return f"within the {fmt_money(tolerance)} tolerance"
    if amount <= mult * tol:
        return f"above the {fmt_money(tolerance)} tolerance (within {mult:g} times it)"
    return f"above the {fmt_money(tolerance)} tolerance"


class Narrator:
    """Turns pipeline stage events into short, plain lines."""

    def __call__(self, stage: str, info: dict[str, Any]) -> None:
        getattr(self, f"_{stage}")(info)

    def _pulled(self, info: dict[str, Any]) -> None:
        parts = [f"{PLATFORM_NAMES.get(p, p)} {_count(n, 'row')}" for p, n in info["rows"].items()]
        tag = " (simulated)" if info["synthetic"] else ""
        _say("Pulled", ", ".join(parts) + tag)
        q = {p: n for p, n in info["quarantined"].items() if n}
        if q:
            detail = ", ".join(f"{PLATFORM_NAMES.get(p, p)} {n}" for p, n in q.items())
            _say("Quarantined", f"{_count(sum(q.values()), 'row')} ({detail})")
        else:
            _say("Quarantined", "none, every row passed the checks")
        for change in info["changes"]:
            _say("Note", change)

    def _fitted(self, info: dict[str, Any]) -> None:
        from bayesian_marketing.core import registries

        size = f"{_count(info['n_ads'], 'ad')}, {_count(info['n_days'], 'day')}"
        _say("Fitted", FIT_STEPS[info["step"]].format(size=size))
        source = info["lag_source"]
        if source is None:
            _say("Lag", "not adjusted: no lag curve for this attribution window")
        else:
            _say("Lag", LAG_SOURCES[source].format(n=info["lag_n"], days=info["lag_window"]))
        assumed = registries.resolve("phrasing/notices/lag_assumed@v1")
        for note in info["lag_notices"]:
            if note != assumed and source is not None:
                _say("Note", note)
        self._diagnostics(info["reports"])

    def _diagnostics(self, reports: list[Any]) -> None:
        from bayesian_marketing.core import registries

        lo, hi = registries.resolve("diagnostics/thresholds/ppc_band@v1")
        sampled = [r for r in reports if r.sampler == "numpyro_nuts"]
        if sampled:
            r = sampled[-1]
            verdict = "passed" if r.passed else "failed"
            _say(
                "Diagnostics",
                f"R-hat {r.rhat_max:.3f}, ESS {r.ess_bulk_min:,.0f}, "
                f"{_count(int(r.n_divergences or 0), 'divergence')}; {verdict}",
            )
            if any(x.sampler != "numpyro_nuts" for x in reports):
                _say("Diagnostics", "the exact model's predictive checks ran after the fallback")
            return
        ppc = reports[-1].ppc if reports else {}
        inside = sum(1 for p in ppc.values() if lo <= p <= hi)
        _say(
            "Diagnostics",
            f"exact model, no sampler ran; predictive checks in band for {inside} of "
            f"{len(ppc)} stages",
        )

    def _not_knowable(self, info: dict[str, Any]) -> None:
        """The compared and requested quantities that are not knowable, by ad (D38.4)."""
        from bayesian_marketing.claims.vocab import METRIC_LABELS

        names = list(dict.fromkeys([info["compare_quantity"], info["metric_quantity"]]))
        by_name: dict[str, list[str]] = {}
        shown: set[tuple[str, str]] = set()
        for ad in info["variants"].values():
            for name in names:
                q = next(
                    (x for x in info["quantities"] if x.name == name and x.scope.ids["ad"] == ad),
                    None,
                )
                if q is None or q.feasibility.status == "below_floor":
                    by_name.setdefault(name, []).append(ad)
                    shown.add((ad, name))
        others = sum(1 for q in info["quantities"] if q.feasibility.status == "below_floor")
        others += sum(len(m) for m in info["not_estimable"].values())
        others -= len(shown)
        parts = [f"{METRIC_LABELS[n]} for {', '.join(ads)}" for n, ads in by_name.items()]
        if others > 0:
            more = "1 more quantity" if others == 1 else f"{others:,} more quantities"
            parts.append(f"{more} in the report")
        if parts:
            _say("Not knowable", "; ".join(parts))

    def _decided(self, info: dict[str, Any]) -> None:
        from bayesian_marketing.decision.reallocation import fmt_prob, horizon_text

        c = info["comparison"]
        if c is not None:
            target = c.objective.target
            best = max(c.p_best, key=c.p_best.get)
            _say("Decision", f"{best} is best with probability {fmt_prob(c.p_best[best])}")
            values = sorted(c.expected_value.items(), key=lambda kv: -float(kv[1].amount))
            some = next(iter(c.expected_value.values()))
            h = horizon_text(c.objective.horizon, some.currency)
            line = ", ".join(f"{o} {_amount(m, target)}" for o, m in values[:SHOWN_SHARES])
            negative = [o for o, m in values if m.amount < 0]
            if negative:
                line += f"; {len(negative)} of {_count(len(values), 'option')} negative"
            _say("Expected value", f"over the next {h}: {line}")
        self._not_knowable(info)
        if c is not None and self._compared_not_knowable(info):
            # D39: a decision rests on expected loss (D9), not on each value's precision.
            _say(
                "Why both",
                "which ad is ahead is clear enough to act on; what each earns is not yet",
            )
        recs = info["recommendations"]
        testing = any(r.action == "continue_test" for r in recs)
        for r in recs:
            self._recommendation(r, info, c, testing)

    @staticmethod
    def _compared_not_knowable(info: dict[str, Any]) -> bool:
        name = info["compare_quantity"]
        for ad in info["variants"].values():
            q = next(
                (x for x in info["quantities"] if x.name == name and x.scope.ids["ad"] == ad),
                None,
            )
            if q is None or q.feasibility.status == "below_floor":
                return True
        return False

    def _recommendation(self, r: Any, info: dict[str, Any], c: Any, testing: bool = False) -> None:
        from bayesian_marketing.decision.reallocation import horizon_text

        action = ACTIONS.get(r.action, r.action)
        slots = r.guarantee.slots
        shares = (r.params or {}).get("allocation") or {}
        if r.action == "allocate" and shares:
            ranked = sorted(shares.items(), key=lambda kv: -float(kv[1]))
            split = ", ".join(f"{ad} {100 * float(s):.0f}%" for ad, s in ranked[:SHOWN_SHARES])
            rest = ranked[SHOWN_SHARES:]
            if rest:
                left = 100 * sum(float(s) for _, s in rest)
                split += f", {_count(len(rest), 'other ad')} {left:.0f}% between them"
            label = "While testing" if testing else "Recommendation"
            _say(label, f"{action}: {split}; needs human approval")
        elif r.action in ("not_knowable", "continue_test"):
            why = "; ".join(x for x in (slots.get("reason"), slots.get("requirement")) if x)
            tail = "; needs human approval" if r.action != "not_knowable" else ""
            label = "Test" if r.action == "continue_test" else "Recommendation"
            _say(label, f"{action}: {why}{tail}")
        else:
            _say("Recommendation", f"{action}; needs human approval")
        if r.expected_loss is not None and r.action in LOSS_FOR:
            h = horizon_text(r.horizon, r.expected_loss.currency)
            best = (r.params or {}).get("best", "")
            what = LOSS_FOR[r.action].format(best=best)
            target = c.objective.target if c is not None else "contribution"
            verdict = _verdict(r.expected_loss, info["tolerance"], target)
            _say(
                "Expected loss",
                f"{_amount(r.expected_loss, target)} over the next {h} {what}, {verdict}",
            )


def _manifest_path(out: Path) -> Path:
    from bayesian_marketing.simulate.generate import MANIFEST_NAME

    return out / MANIFEST_NAME


def _window(manifest: Any, data_dir: Path, platform: str) -> tuple[date, date]:
    from bayesian_marketing.data_contract.readers.read import read_export

    dates: list[date] = []
    for f in manifest.files:
        if f.platform == platform:
            pull = read_export(f.platform, data_dir / f.path, manifest)
            dates += [r.date for r in pull.rows]
    if not dates:
        raise ValueError(f"the scenario wrote no {platform} rows")
    return min(dates), max(dates)


def demo_horizon(metric: str) -> Any:
    """The registry's default horizon amount in the unit the metric's comparison needs (D38.2:
    CTR is valued per impression)."""
    from bayesian_marketing import pipeline
    from bayesian_marketing.core import Horizon, registries

    h = registries.resolve("decision_defaults/horizon_default@v1")
    unit = pipeline.horizon_unit(metric)
    horizon = Horizon(unit=unit, amount=Decimal(str(h["amount"])))  # type: ignore[arg-type]
    pipeline.objective_for(metric, horizon)  # refuses an incompatible pair before any work
    return horizon


def demo(scenario: str, out: Path, seed: int, metric: str) -> int:
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("BAYES_DATA_DIR", str(out / "store"))

    from bayesian_marketing import pipeline
    from bayesian_marketing.atmaos.socket import bundle_of
    from bayesian_marketing.core import (
        CompareRequest,
        DatasetManifest,
        GateFailure,
        NotInScope,
    )
    from bayesian_marketing.reporting.render import render
    from bayesian_marketing.simulate.generate import generate

    path = SCENARIOS / f"{scenario}.yaml"
    if not path.exists():
        names = sorted(p.stem for p in SCENARIOS.glob("*.yaml"))
        print(f"No scenario {scenario!r}. Choose one of: {', '.join(names)}", file=sys.stderr)
        return 2
    try:
        horizon = demo_horizon(metric)
    except (ValueError, NotInScope) as e:
        _say("Stopped", str(e))
        return 2
    data_dir = out / "data"
    print(f"ENG-BAYES demo: {scenario}. Simulated data, not a client result.", flush=True)
    generate(path, seed, data_dir)
    manifest = DatasetManifest.load(_manifest_path(data_dir))
    variants = sorted(manifest.entity_map)
    platform = pipeline.comparison_platform(manifest, variants)
    start, end = _window(manifest, data_dir, platform)
    _say("Simulated", f"{_count(len(variants), 'ad')} on {PLATFORM_NAMES[platform]}, "
                      f"{start.isoformat()} to {end.isoformat()}, seed {seed}")  # fmt: skip
    request = CompareRequest(
        metric=metric,  # type: ignore[arg-type]
        variants=variants,
        priors={},
        window=(start, end),
        horizon=horizon,
    )
    try:
        ctx = pipeline.execute(manifest, request, manifest_dir=data_dir, on_stage=Narrator())
        bundle = bundle_of(ctx.snapshot, "demo", [])
        report = render(bundle, out)
    except GateFailure as e:
        _say("Stopped", f"gate {e.result.gate} failed: {'; '.join(e.result.reasons)}")
        return 1
    except (ValueError, NotInScope) as e:
        _say("Stopped", str(e))
        return 2
    _say("Report", report.html_path)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bayesian_marketing.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("demo", help="simulate a scenario, run the engine, render the demo report")
    d.add_argument("--scenario", default="north_pier_day14")
    d.add_argument("--out", type=Path, required=True)
    d.add_argument("--seed", type=int, default=1)
    d.add_argument(
        "--metric",
        default="contribution",
        choices=["ctr", "cvr", "cpa", "roas", "contribution_per_click", "contribution"],
    )
    args = parser.parse_args(argv)
    if args.command == "demo":
        return demo(args.scenario, args.out, args.seed, args.metric)
    return 2  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
