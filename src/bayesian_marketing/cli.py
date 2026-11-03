"""Command-line entry. Piece P11.

``python -m bayesian_marketing.cli demo --scenario north_pier_day14 --out <dir>`` simulates the
scenario, runs the pipeline end to end and renders the watermarked demo report into ``<dir>``,
printing each stage in plain words. No network, no model calls. When ``BAYES_DATA_DIR`` is unset
the run's stores go under ``<dir>/store`` so a demo never touches another run's record.
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


def _say(label: str, text: str) -> None:
    print(f"{label + ':':<16}{text}", flush=True)


def _count(n: int, word: str) -> str:
    return f"{n:,} {word}" + ("" if n == 1 else "s")


class Narrator:
    """Turns pipeline stage events into short, plain lines."""

    def __init__(self) -> None:
        self.variants: dict[str, str] = {}

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
        n_ads, n_days = info["n_ads"], info["n_days"]
        size = f"{_count(n_ads, 'ad')}, {_count(n_days, 'day')}"
        if info["route"] == "conjugate":
            _say("Fitted", f"exact per-ad model, {size} (too few ads for the joint model)")
        elif info["fell_back"]:
            _say("Fitted", f"joint funnel model failed its checks; used the exact model, {size}")
        else:
            _say("Fitted", f"joint funnel model with the NUTS sampler, {size}")
        if info["lag_source"] == "registry_default":
            _say("Lag", "conversion lag assumed (default curve)")
        elif info["lag_source"] is None:
            _say("Lag", "not adjusted: no lag curve for this attribution window")
        else:
            _say("Lag", "estimated from the orders file")
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
            return
        ppc = reports[-1].ppc if reports else {}
        inside = sum(1 for p in ppc.values() if lo <= p <= hi)
        _say(
            "Diagnostics",
            f"exact model, no sampler ran; predictive checks in band for {inside} of "
            f"{len(ppc)} stages",
        )

    def _decided(self, info: dict[str, Any]) -> None:
        from bayesian_marketing.decision.reallocation import fmt_money, fmt_prob, horizon_text

        self.variants = {ad: v for v, ad in info["variants"].items()}
        c = info["comparison"]
        name = self.variants.get
        if c is not None:
            best = max(c.p_best, key=c.p_best.get)
            loss = c.expected_loss[best]
            h = horizon_text(c.objective.horizon, loss.currency)
            _say(
                "Decision",
                f"{name(best, best)} is best with probability {fmt_prob(c.p_best[best])}",
            )
            decision = info["decision"]
            tol = ""
            if decision is not None and decision.status == "estimable":
                tol = ", within tolerance"
            elif decision is not None:
                tol = ", above tolerance"
            _say("Expected loss", f"{fmt_money(loss)} over the next {h} if we pick it{tol}")
        for r in info["recommendations"]:
            action = ACTIONS.get(r.action, r.action)
            shares = (r.params or {}).get("allocation") or {}
            if r.action == "allocate" and shares:
                split = ", ".join(
                    f"{name(ad, ad)} {100 * float(s):.0f}%"
                    for ad, s in sorted(shares.items(), key=lambda kv: -float(kv[1]))
                )
                _say("Recommendation", f"{action}: {split}; needs human approval")
            elif r.action == "not_knowable":
                reason = (r.params or {}).get("reason") or "; ".join(r.decision_feasibility.reasons)
                _say("Recommendation", f"{action}: {reason}")
            else:
                _say("Recommendation", f"{action}; needs human approval")


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
        Horizon,
        registries,
    )
    from bayesian_marketing.reporting.render import render
    from bayesian_marketing.simulate.generate import generate

    path = SCENARIOS / f"{scenario}.yaml"
    if not path.exists():
        names = sorted(p.stem for p in SCENARIOS.glob("*.yaml"))
        print(f"No scenario {scenario!r}. Choose one of: {', '.join(names)}", file=sys.stderr)
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
    h = registries.resolve("decision_defaults/horizon_default@v1")
    request = CompareRequest(
        metric=metric,  # type: ignore[arg-type]
        variants=variants,
        priors={},
        window=(start, end),
        horizon=Horizon(unit=h["unit"], amount=Decimal(str(h["amount"]))),
    )
    try:
        ctx = pipeline.execute(manifest, request, manifest_dir=data_dir, on_stage=Narrator())
        bundle = bundle_of(ctx.snapshot, "demo", [])
        report = render(bundle, out)
    except GateFailure as e:
        _say("Stopped", f"gate {e.result.gate} failed: {'; '.join(e.result.reasons)}")
        return 1
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
