"""§9.1 generate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from bayesian_marketing.core import ClientEconomics, GroundTruth
from bayesian_marketing.simulate.draw import World, draw_world
from bayesian_marketing.simulate.scenario import Scenario, load_scenario
from bayesian_marketing.simulate.write import (
    economics,
    manifest,
    write_economics,
    write_exports,
    write_orders,
)

MANIFEST_NAME = "manifest.json"
GROUND_TRUTH_NAME = "ground_truth.json"


def _json_native(obj: Any) -> Any:
    """Round-trip through JSON so the in-memory GroundTruth equals the one read back."""
    return json.loads(json.dumps(obj, default=str))


def true_quantities(world: World, econ: ClientEconomics) -> dict[str, float]:
    """Per variant: ctr, cvr, cpc, cpm, order value mean, roas and contribution per click."""
    out: dict[str, float] = {}
    cost = float(econ.variable_cost_per_order.amount)
    for a in world.ads:
        aov = a.order_value_mean
        price = float(econ.fixed_price.amount) if econ.fixed_price is not None else aov
        q = {
            "ctr": a.ctr,
            "cvr": a.cvr,
            "cpc": a.cpc,
            "cpm": a.cpm,
            "order_value_mean": aov,
            "roas": a.cvr * aov / a.cpc,
            "contribution_per_click": a.cvr * (price - cost) - a.cpc,
        }
        out.update({f"{a.variant}.{k}": float(v) for k, v in q.items()})
    return out


def true_best(world: World, tq: dict[str, float]) -> dict[str, str]:
    """Objective -> variant with the highest true value (first in scenario order on a tie)."""
    objectives = {
        "ctr": "ctr",
        "cvr": "cvr",
        "roas": "roas",
        "contribution": "contribution_per_click",
    }
    best: dict[str, str] = {}
    for objective, q in objectives.items():
        best[objective] = max(world.ads, key=lambda a, q=q: tq[f"{a.variant}.{q}"]).variant
    return best


def _params(sc: Scenario, raw: dict[str, Any], world: World, seed: int) -> dict[str, Any]:
    return _json_native({"seed": seed, "scenario": raw, "drawn": world.params, **sc.notes})


def generate(scenario_path: Path, seed: int, out_dir: Path) -> GroundTruth:
    """Write platform-shaped CSVs (column names from ChannelModel export maps), an orders CSV, a
    synthetic DatasetManifest and ground_truth.json."""
    sc, raw = load_scenario(Path(scenario_path))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    world = draw_world(sc, rng)
    files, windows = write_exports(sc, world, out_dir, rng)
    files.append(write_orders(sc, world, out_dir))
    econ = economics(sc)
    write_economics(econ, out_dir)
    m = manifest(sc, world, files, windows, econ, seed)
    (out_dir / MANIFEST_NAME).write_text(m.model_dump_json(indent=2) + "\n")
    tq = true_quantities(world, econ)
    gt = GroundTruth(
        scenario=sc.scenario,
        seed=seed,
        params=_params(sc, raw, world, seed),
        true_quantities=tq,
        true_best=true_best(world, tq),
    )
    (out_dir / GROUND_TRUTH_NAME).write_text(gt.model_dump_json(indent=2) + "\n")
    return gt
