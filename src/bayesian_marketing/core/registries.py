"""Registry loader (I6). Every bound, threshold, template and phrase comes from here.

A registry is a YAML file under the registry root with a top-level ``version`` key. A
``RegistryRef`` is ``"<file path without .yaml>/<key>/<key>...@<version>"``, for example
``"bounds/estimability/posterior_width@v1"`` or ``"priors/default/cvr@v1"``. The root is
``registries/`` at the repo root unless ``BAYES_REGISTRY_DIR`` names another, so swapping a
registry needs no code change (S0 acceptance).
"""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from bayesian_marketing.core.base import RegistryRef

DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "registries"


class RegistryError(LookupError):
    """A ref that does not resolve, or a version that does not match."""


def registry_root() -> Path:
    return Path(os.environ.get("BAYES_REGISTRY_DIR", DEFAULT_ROOT))


@cache
def _load_file(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict) or "version" not in data:
        raise RegistryError(f"{path} has no top-level 'version'")
    return data


def load(name: str, root: Path | None = None) -> dict[str, Any]:
    """Load a whole registry file by name, e.g. ``"bounds"`` or ``"priors/default"``."""
    path = (root or registry_root()) / f"{name}.yaml"
    if not path.exists():
        raise RegistryError(f"no registry {name!r} at {path}")
    return _load_file(path)


def resolve(ref: RegistryRef, root: Path | None = None) -> Any:
    """The value a ref points to. Raises RegistryError on a missing key or wrong version."""
    if "@" not in ref:
        raise RegistryError(f"ref {ref!r} has no @version")
    path_part, version = ref.rsplit("@", 1)
    parts = path_part.split("/")
    base = root or registry_root()
    for i in range(len(parts), 0, -1):
        candidate = base.joinpath(*parts[:i]).with_suffix(".yaml")
        if candidate.exists():
            data = _load_file(candidate)
            keys = parts[i:]
            break
    else:
        raise RegistryError(f"no registry file for {ref!r} under {base}")
    if str(data["version"]) != version:
        raise RegistryError(f"{ref!r}: registry is at version {data['version']}")
    node: Any = data
    for k in keys:
        if not isinstance(node, dict) or k not in node:
            raise RegistryError(f"{ref!r}: key {k!r} not found")
        node = node[k]
    return node


def versions(root: Path | None = None) -> dict[str, str]:
    """Every registry file's version, keyed by name, for the run record."""
    base = root or registry_root()
    out: dict[str, str] = {}
    for p in sorted(base.rglob("*.yaml")):
        name = p.relative_to(base).with_suffix("").as_posix()
        out[name] = str(_load_file(p)["version"])
    return out


def clear_cache() -> None:
    """Forget loaded files (tests that swap the root call this)."""
    _load_file.cache_clear()
