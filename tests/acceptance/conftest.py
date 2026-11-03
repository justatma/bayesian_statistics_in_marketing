"""Isolation for acceptance tests.

CONTRACT ASSUMPTION (all pieces): every persistent engine store (run record SQLite, funnel states,
status registry, prior proposals and approvals) lives under the directory named by the environment
variable ``BAYES_DATA_DIR``, and every registry read goes through ``core.registries`` (so
``BAYES_REGISTRY_DIR`` redirects it). Each test runs with both pointed into its own tmp dir, with
the working directory also set there.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from bayesian_marketing.core import registries

REPO = Path(__file__).resolve().parents[2]


@dataclass
class Iso:
    root: Path
    registry: Path
    store: Path

    def edit_yaml(self, name: str, fn: Callable[[dict[str, Any]], None]) -> None:
        """Edit a registry file in the isolated copy (e.g. ``"channels"``) and drop the cache."""
        path = self.registry / f"{name}.yaml"
        data = yaml.safe_load(path.read_text())
        fn(data)
        path.write_text(yaml.safe_dump(data, sort_keys=False))
        registries.clear_cache()


@pytest.fixture(autouse=True)
def iso(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iso:
    reg = tmp_path / "registries"
    shutil.copytree(REPO / "registries", reg)
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("BAYES_REGISTRY_DIR", str(reg))
    monkeypatch.setenv("BAYES_DATA_DIR", str(store))
    monkeypatch.delenv("RECORD", raising=False)
    monkeypatch.chdir(tmp_path)
    registries.clear_cache()
    yield Iso(tmp_path, reg, store)
    registries.clear_cache()
