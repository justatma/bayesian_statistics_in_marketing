"""Shared fixtures for the J8 acceptance set (Brain join spec v0.4, J8 items 10 to 13, S40).

No NUTS fit runs here. ``model_spec.compile.compile_model`` and ``NumpyroSampler.fit`` are
replaced the way ``tests/acceptance/test_P6.py`` replaces them, through their modules:

* ``StepCompiler`` compiles a spec into a ``CompiledModel`` whose ``spec_version`` names the
  §7.5 step the spec belongs to (``j8:nuts_full``, ``j8:nuts_static``, ``j8:nuts_unpooled``),
  found by comparing it with the chain written from §7.5's text (``chain_steps``).
* ``ScriptedSampler`` reads the step from the model and counts the calls per step, so call k of
  a step is its try k. A script maps (step, k) to the report it returns: by default a clean
  report (G3 passes); ``div(n)`` fails G3 on divergences alone. The state and report ids are a
  hash of (step, seed), so a different seed gives a different state, and every failed try has a
  state of its own to quarantine. With ``derivable=True`` the state carries joint draws from
  the exact conjugate fit of the data at the call's seed (relabelled as a NUTS state), so the
  whole pipeline can derive quantities from it, and those quantities move with the seed.

``PipelineEnv`` runs ``pipeline.execute`` on the north_pier_day14 scenario (generated into
``tmp_path``), with ``min_ads_for_coupling`` lowered to 2 in the isolated registry copy so the
run takes the NUTS route, and the clock pinned (a run id hashes ``started_at``, S40 (5)).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from bayesian_marketing import core as C
from bayesian_marketing import pipeline
from bayesian_marketing.cli import _window as scenario_window
from bayesian_marketing.core import inputs_hash
from bayesian_marketing.inference import conjugate, sampler_numpyro
from bayesian_marketing.model_spec import compile as compile_mod
from bayesian_marketing.simulate.generate import MANIFEST_NAME, generate
from tests.fakes import builders as B

REPO = Path(__file__).resolve().parents[2]
SCEN = REPO / "data" / "scenarios"
T_RUN = dt.datetime(2026, 11, 27, 15, 0, 0, 250000, tzinfo=dt.UTC)
NUTS_STEPS = ("nuts_full", "nuts_static", "nuts_unpooled")
TRIES = 3  # J8 (10): the first try and up to two retries

Report = dict[str, Any]
Script = Callable[[str, int], Report]


def clean() -> Report:
    """A report that passes G3."""
    return {}


def div(n: int) -> Report:
    """G3 fails on divergences alone (every other check passes)."""
    return {"divergences": n}


def chain_steps(spec: C.FunnelSpec) -> list[tuple[str, C.FunnelSpec]]:
    """§7.5 from its text: full, static, unpooled above the ad; a step equal to the one before is
    not refit."""
    static = spec.model_copy(update={"dynamics": "static"})
    unpooled = static.model_copy(update={"hierarchy": ["ad"]})
    out: list[tuple[str, C.FunnelSpec]] = []
    for name, s in (("nuts_full", spec), ("nuts_static", static), ("nuts_unpooled", unpooled)):
        if out and out[-1][1] == s:
            continue
        out.append((name, s))
    return out


def retry_seed_formula(seed: int, step: str, n: int) -> int:
    """S40 (2), unsalted."""
    return int(inputs_hash({"seed": seed, "step": step, "try": n})[:8], 16)


class StepCompiler:
    """Stands in for ``compile_model``. ``base`` is the spec the chain starts from; None takes
    ``pipeline.funnel_spec(data)``, the spec ``pipeline.fit`` gives the chain."""

    def __init__(self, base: C.FunnelSpec | None = None) -> None:
        self.base = base
        self.priors: C.PriorSet | None = None
        self.steps: list[str] = []

    def __call__(self, spec: C.FunnelSpec, priors: C.PriorSet, data: C.FunnelData):
        base = self.base if self.base is not None else pipeline.funnel_spec(data)
        step = next((name for name, s in chain_steps(base) if s == spec), None)
        assert step is not None, f"the chain compiled a spec that is no §7.5 step: {spec}"
        self.priors = priors
        self.steps.append(step)
        return C.CompiledModel(
            spec_version=f"j8:{step}",
            model_fn_ref="tests.fakes:model",
            data_shape={"ads": len(data.entities), "days": len(data.dates)},
        )


@dataclass
class Call:
    step: str
    k: int
    seed: int
    state_id: str
    report_id: str
    divergences: int | None


@dataclass
class ScriptedSampler:
    script: Script = lambda step, k: clean()
    derivable: bool = False
    compiler: StepCompiler | None = None
    calls: list[Call] = field(default_factory=list)

    def fit(self, model: C.CompiledModel, data: C.FunnelData, config: C.FitConfig):
        step = model.spec_version.removeprefix("j8:")
        k = 1 + sum(1 for c in self.calls if c.step == step)
        seed = int(config.seed)
        tag = inputs_hash({"j8_step": step, "seed": seed})[:8]
        kw = {"rhat": 1.001, "ess_bulk": 1500.0, "ess_tail": 1200.0, "divergences": 0}
        kw.update(self.script(step, k))
        report = B.diagnostics_report(**kw, report_id=f"dg_{tag}")
        state_id = f"fs_{tag}"
        if self.derivable:
            priors = self.compiler.priors if self.compiler else None
            base = conjugate.fit_conjugate(data, priors or B.default_prior_set(), seed)
            params = {k2: v for k2, v in (base.posterior.params or {}).items()}
            params.pop("route.too_few_ads", None)
            state = base.model_copy(
                update={
                    "state_id": state_id,
                    "route": "nuts",
                    "spec_version": model.spec_version,
                    "diagnostics_id": report.report_id,
                    "posterior": base.posterior.model_copy(update={"params": params}),
                }
            )
        else:
            state = B.funnel_state(route="nuts", state_id=state_id, diagnostics_id=report.report_id)
        self.calls.append(Call(step, k, seed, state_id, report.report_id, kw["divergences"]))
        return state, report


def patch_chain(
    monkeypatch: pytest.MonkeyPatch,
    script: Script | dict[tuple[str, int], Report] | None = None,
    *,
    base: C.FunnelSpec | None = None,
    derivable: bool = False,
) -> ScriptedSampler:
    """Replace the compiler and the sampler. A dict script names (step, try) cells; any other
    cell is clean."""
    if isinstance(script, dict):
        cells = dict(script)
        fn: Script = lambda step, k: cells.get((step, k), clean())  # noqa: E731
    else:
        fn = script or (lambda step, k: clean())
    compiler = StepCompiler(base)
    sampler = ScriptedSampler(fn, derivable=derivable, compiler=compiler)
    monkeypatch.setattr(compile_mod, "compile_model", compiler)
    monkeypatch.setattr(
        sampler_numpyro.NumpyroSampler, "fit", lambda self, m, d, c: sampler.fit(m, d, c)
    )
    return sampler


def always(report: Report) -> Script:
    return lambda step, k: report


def eight_ads(n_ads: int = 8, n_days: int = 21) -> C.FunnelData:
    """test_P6's data: eight ads, so ``pipeline.fit`` routes to NUTS with the default bounds."""
    dates = [B.D_END - dt.timedelta(days=n_days - 1 - i) for i in range(n_days)]
    return B.funnel_data(
        {
            f"ad_{i}": {
                "impressions": [800] * n_days,
                "clicks": [16 + i] * n_days,
                "spend": [20.0] * n_days,
                "conv_obs": [1] * n_days,
                "conv_rep": [1.0] * n_days,
                "mature": [1.0] * n_days,
            }
            for i in range(n_ads)
        },
        dates=dates,
    )


def attempt_rows(attempts: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return [(a["step"], a["try"], a["seed"], a["divergences"], a["passed"]) for a in attempts]


@dataclass
class PipelineEnv:
    """One synthetic manifest and request, run through ``pipeline.execute`` on the NUTS route."""

    root: Path
    mp: pytest.MonkeyPatch
    manifest: C.DatasetManifest
    manifest_dir: Path
    window: tuple[dt.date, dt.date]

    def request(self) -> C.CompareRequest:
        return C.CompareRequest(
            metric="contribution",
            variants=sorted(self.manifest.entity_map),
            priors={},
            window=self.window,
            horizon=C.Horizon(unit="clicks", amount=Decimal(1000)),
        )

    def seed(self) -> int:
        """The run's seed as the engine derives it (``pipeline._seed``), unchanged by J8."""
        return pipeline._seed(self.manifest, self.request())

    def execute(self, at: dt.datetime = T_RUN) -> pipeline.RunContext:
        self.mp.setattr(pipeline, "utcnow", lambda: at)
        return pipeline.execute(self.manifest, self.request(), manifest_dir=self.manifest_dir)


def fresh_store(monkeypatch: pytest.MonkeyPatch, root: Path, name: str) -> Path:
    """Point ``BAYES_DATA_DIR`` at a new folder. States are immutable, so a second run of the same
    inputs, whose fake states have the same ids, needs a store of its own."""
    store = root / name
    store.mkdir()
    monkeypatch.setenv("BAYES_DATA_DIR", str(store))
    return store


def pipeline_env(iso: Any, monkeypatch: pytest.MonkeyPatch, *, nuts: bool = True) -> PipelineEnv:
    if nuts:
        iso.edit_yaml("bounds", lambda d: d["coupling"].update(min_ads_for_coupling=2))
    out = iso.root / "north_pier_day14"
    generate(SCEN / "north_pier_day14.yaml", 1, out)
    m = C.DatasetManifest.load(out / MANIFEST_NAME)
    platform = pipeline.comparison_platform(m, sorted(m.entity_map))
    return PipelineEnv(iso.root, monkeypatch, m, out, scenario_window(m, out, platform))


def quantities_digest(quantities: list[C.Quantity]) -> str:
    """The quantities as the run saved them, less what moves from one test to the next (the
    times they were checked and computed at, and the draws file's path under ``tmp_path``)."""
    rows = []
    for q in quantities:
        d = q.model_dump(mode="json")
        d["feasibility"].pop("checked_at", None)
        d["provenance"].pop("computed_at", None)
        d["estimate"].pop("samples_path", None)
        rows.append(d)
    return inputs_hash(sorted(rows, key=lambda d: (d["quantity_id"], d["name"])))
