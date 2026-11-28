"""Client configs (``configs/<client_id>.yaml``) as ``ClientConfig`` (spec v0.2 §4, [2.7])."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from bayesian_marketing.core.records import ClientConfig

CONFIG_ENV = "BAYES_CONFIG_DIR"
DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "configs"


def config_root(root: Path | None = None) -> Path:
    if root is not None:
        return Path(root)
    return Path(os.environ.get(CONFIG_ENV, DEFAULT_ROOT))


def load_client(client_id: str, root: Path | None = None) -> ClientConfig:
    if not client_id or "/" in client_id or "\\" in client_id or client_id.startswith("."):
        raise ValueError(f"bad client id {client_id!r}")
    path = config_root(root) / f"{client_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no client config {path}")
    cfg = ClientConfig.model_validate(yaml.safe_load(path.read_text()))
    if cfg.client_id != client_id:
        raise ValueError(f"{path} names client {cfg.client_id!r}, not {client_id!r}")
    return cfg


def all_clients(root: Path | None = None) -> list[ClientConfig]:
    """Every ``configs/*.yaml``, sorted by client id. Subdirectories (economics/) are not read."""
    base = config_root(root)
    return [load_client(p.stem, base) for p in sorted(base.glob("*.yaml"))]
