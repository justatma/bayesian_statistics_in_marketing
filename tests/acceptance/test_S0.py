"""S0 skeleton: core schemas, registries, G10, no model client (spec v0.3 §4, §10 C2, §14, §15)."""

from __future__ import annotations

import ast
import importlib.metadata
import importlib.util
import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel, ValidationError

from bayesian_marketing import core as C
from bayesian_marketing.core import registries
from tests.fakes import builders as B

# S0 has merged (it is the skeleton these tests check), so this module carries no piece gate.

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src" / "bayesian_marketing"

MODEL_CLIENTS = (
    "anthropic",
    "openai",
    "google.generativeai",
    "google.genai",
    "mistralai",
    "cohere",
    "litellm",
    "langchain",
    "llama_index",
)
MODEL_CLIENT_DISTS = (
    "anthropic",
    "openai",
    "google-generativeai",
    "google-genai",
    "mistralai",
    "cohere",
    "litellm",
    "langchain",
    "langchain-core",
    "langchain-community",
    "llama-index",
    "llama-index-core",
)


def _core_models() -> set[type]:
    out = set()
    for name in C.__all__:
        obj = getattr(C, name)
        if isinstance(obj, type) and issubclass(obj, BaseModel) and obj is not C.Frozen:
            out.add(obj)
    return out


def test_S0_schema_examples_validate(tmp_path: Path) -> None:
    examples = B.all_examples(tmp_path)
    missing = {m.__name__ for m in _core_models()} - {t.__name__ for t in examples}
    assert not missing, f"no example for {sorted(missing)}"
    for cls, obj in examples.items():
        again = cls.model_validate_json(obj.model_dump_json())
        assert again == obj, cls.__name__
        if cls.model_config.get("frozen"):
            field = next(iter(cls.model_fields))
            with pytest.raises(ValidationError):
                setattr(obj, field, getattr(obj, field))


def test_S0_registry_swap_needs_no_code(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ref = "bounds/coupling/min_ads_for_coupling@v1"
    assert registries.resolve(ref, root=REPO / "registries") == 8
    swapped = tmp_path / "swapped"
    shutil.copytree(REPO / "registries", swapped)
    path = swapped / "bounds.yaml"
    data = yaml.safe_load(path.read_text())
    data["coupling"]["min_ads_for_coupling"] = 5
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    monkeypatch.setenv("BAYES_REGISTRY_DIR", str(swapped))
    registries.clear_cache()
    assert registries.resolve(ref) == 5
    assert registries.versions()["bounds"] == "v1"
    registries.clear_cache()
    assert registries.resolve(ref, root=REPO / "registries") == 8


def _bad_quantities() -> list[tuple[str, dict]]:
    meta, orders, ga4 = B.META_PULL, B.ORDERS_PULL, "pull_ga4_00000001"
    realized = "commercially_realized"
    return [
        ("incremental_without_holdout",
         {"name": "cvr", "evidence": "causally_incremental", "design": "randomized"}),
        ("realized_without_orders_pull", {"name": "cvr", "evidence": realized, "pulls": [meta]}),
        ("deterministic_class_on_conjugate_route",
         {"name": "cpc", "evidence": "deterministic", "route": "conjugate"}),
        ("deterministic_route_with_posterior_class",
         {"name": "cpc", "evidence": "delivery", "route": "deterministic"}),
        ("platform_conversions_not_platform_attributed",
         {"name": "cvr", "evidence": "delivery", "pulls": [meta]}),
        ("sampled_without_diagnostics", {"name": "ctr", "_force_no_diag": True}),
        ("realized_with_ga4_but_no_orders",
         {"name": "roas", "evidence": realized, "pulls": [meta, ga4]}),
        ("ok_control", {"name": "cvr", "evidence": realized, "pulls": [meta, orders]}),
    ]  # fmt: skip


@pytest.mark.parametrize("case,kw", _bad_quantities(), ids=[c for c, _ in _bad_quantities()])
def test_S0_G10_rejects_bad_evidence_combos(case: str, kw: dict) -> None:
    kw = dict(kw)
    if kw.pop("_force_no_diag", False):
        q = B.quantity(name=kw["name"])
        data = q.model_dump()
        data["provenance"]["route"] = "nuts"
        data["diagnostics_ref"] = None
        with pytest.raises(ValidationError, match="G10"):
            C.Quantity.model_validate(data)
        return
    if case == "ok_control":
        q = B.quantity(**kw)
        assert C.g10_reasons(q) == []
        return
    with pytest.raises(ValidationError, match="G10"):
        B.quantity(**kw)


def test_S0_extra_G10_rejects_synthetic_in_client_bundle() -> None:
    q = B.quantity(synthetic=True)
    assert B.bundle("demo", [q]).kind == "demo"
    assert B.bundle("internal", [q]).kind == "internal"
    with pytest.raises(ValidationError, match="G10"):
        B.bundle("client", [q])
    assert B.bundle("client", [B.quantity()]).kind == "client"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
        elif (
            isinstance(node, ast.Call)
            and (
                getattr(node.func, "attr", None) == "import_module"
                or getattr(node.func, "id", None) == "__import__"
            )
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            names.add(str(node.args[0].value))
    return names


def _is_client(mod: str) -> bool:
    return any(mod == c or mod.startswith(c + ".") for c in MODEL_CLIENTS)


def test_S0_no_model_client_importable() -> None:
    files = sorted(SRC.rglob("*.py"))
    assert files, "no source files found"
    offenders = {
        str(f.relative_to(REPO)): sorted(m for m in _imported_modules(f) if _is_client(m))
        for f in files
    }
    offenders = {k: v for k, v in offenders.items() if v}
    assert not offenders, f"model client imported: {offenders}"

    installed = []
    for mod in MODEL_CLIENTS:
        try:
            if importlib.util.find_spec(mod) is not None:
                installed.append(mod)
        except ModuleNotFoundError:
            pass
    assert not installed, f"model client importable in this environment: {installed}"

    dists = {(d.metadata["Name"] or "").lower().replace("_", "-") for d in
             importlib.metadata.distributions()}  # fmt: skip
    present = sorted(d for d in MODEL_CLIENT_DISTS if d in dists)
    assert not present, f"model client distributions installed: {present}"
