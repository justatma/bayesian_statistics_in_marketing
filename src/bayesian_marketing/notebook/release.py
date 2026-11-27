"""Write and verify an account notebook release (spec/notebook_format.md, bayes-notebook-1.0.0).

    from bayesian_marketing.notebook.release import verify

`write_release` is called by an authoring script with the entries and the copied sources; it
refuses an entry whose basis is missing, a source with person fields left in, and a folder that
already exists. A written release is never changed: a correction is a new release naming its parent.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "bayes-notebook-1.0.0"
KINDS = ("event", "finding", "figure", "constraint", "open")
METHODS = ("observed", "estimated")
SOURCE_KINDS = ("engine_run", "meta_change", "meta_object", "meta_insights", "live_rows")
PERSON_FIELDS = ("actor_name", "actor_id", "email", "user_id", "first_name", "last_name")
FILES = ("catalog.json", "entries.jsonl", "sources.jsonl")


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def release_hash(files: dict[str, str]) -> str:
    """Boswell's rule: sha256 over "<name> <digest>\\n" per file, sorted by name."""
    return sha("".join(f"{n} {files[n]}\n" for n in sorted(files)).encode())


def _person_fields(obj: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in PERSON_FIELDS:
                found.append(f"{path}{k}")
            found += _person_fields(v, f"{path}{k}.")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found += _person_fields(v, f"{path}{i}.")
    return found


def source(kind: str, ref: dict[str, Any], content: Any, redacted: list[str] | None = None) -> dict:
    if kind not in SOURCE_KINDS:
        raise ValueError(f"unknown source kind {kind!r}")
    left = _person_fields(content)
    if left:
        raise ValueError(f"person fields left in a {kind} source: {left}")
    digest = sha(canonical(content))
    return {
        "source_id": f"src_{digest[:16]}",
        "kind": kind,
        "ref": ref,
        "content": content,
        "redacted": sorted(redacted or []),
        "content_sha256": digest,
    }


def _check_entry(e: dict, ids: set[str]) -> None:
    need = ("entry_id", "kind", "statement", "method", "date", "as_of", "basis")
    missing = [k for k in need if not e.get(k)]
    if missing:
        raise ValueError(f"{e.get('entry_id')}: missing {missing}")
    if e["kind"] not in KINDS or e["method"] not in METHODS:
        raise ValueError(f"{e['entry_id']}: kind or method not allowed")
    for b in e["basis"]:
        if b.get("source_id") not in ids or b.get("role") not in ("primary", "context"):
            raise ValueError(f"{e['entry_id']}: basis {b} not in sources or role not allowed")
    if not any(b["role"] == "primary" for b in e["basis"]):
        raise ValueError(f"{e['entry_id']}: no primary basis")
    for q in e.get("quantities", []):
        interval = all(k in q for k in ("p05", "p95", "level"))
        if e["method"] == "estimated" and "p50" in q and not interval:
            raise ValueError(f"{e['entry_id']}: estimated quantity without its interval")


def write_release(
    root: Path,
    client_id: str,
    entries: list[dict],
    sources: list[dict],
    *,
    parent_release_id: str | None,
    engine_version: str,
    day: str,
) -> Path:
    by_id = {s["source_id"]: s for s in sources}
    for e in entries:
        e.setdefault("date_end", None)
        e.setdefault("quantities", [])
        e.setdefault("supersedes", None)
        e.setdefault("tags", [])
        _check_entry(e, set(by_id))
    if len({e["entry_id"] for e in entries}) != len(entries):
        raise ValueError("duplicate entry_id")
    releases = root / client_id / "releases"
    n = 1
    while (releases / f"nb_{client_id}_{day}_{n}").exists():
        n += 1
    rid = f"nb_{client_id}_{day}_{n}"
    folder = releases / rid
    folder.mkdir(parents=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=root, check=True
    ).stdout.strip()
    catalog = {
        "schema": SCHEMA,
        "release_id": rid,
        "parent_release_id": parent_release_id,
        "client_id": client_id,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "engine_version": engine_version,
        "engine_commit": commit,
        "n_entries": len(entries),
        "n_sources": len(sources),
    }
    (folder / "catalog.json").write_bytes(canonical(catalog) + b"\n")
    (folder / "entries.jsonl").write_bytes(b"".join(canonical(e) + b"\n" for e in entries))
    (folder / "sources.jsonl").write_bytes(
        b"".join(canonical(s) + b"\n" for s in sorted(sources, key=lambda s: s["source_id"]))
    )
    files = {name: sha((folder / name).read_bytes()) for name in FILES}
    integrity = {"algorithm": "sha256", "files": files, "release_hash": release_hash(files)}
    (folder / "integrity.json").write_bytes(canonical(integrity) + b"\n")
    verify(folder)
    return folder


def verify(folder: Path) -> str:
    """The importer's checks, run here first. Returns the release hash."""
    folder = Path(folder)
    integrity = json.loads((folder / "integrity.json").read_text())
    present = {p.name for p in folder.iterdir() if p.name != "integrity.json"}
    if present != set(integrity["files"]):
        raise ValueError(f"files present {sorted(present)} differ from integrity.json")
    for name, digest in integrity["files"].items():
        if sha((folder / name).read_bytes()) != digest:
            raise ValueError(f"{name} does not match its hash")
    if release_hash(integrity["files"]) != integrity["release_hash"]:
        raise ValueError("release hash does not recompute")
    catalog = json.loads((folder / "catalog.json").read_text())
    sources = [json.loads(x) for x in (folder / "sources.jsonl").read_text().splitlines()]
    entries = [json.loads(x) for x in (folder / "entries.jsonl").read_text().splitlines()]
    for s in sources:
        d = sha(canonical(s["content"]))
        if d != s["content_sha256"] or s["source_id"] != f"src_{d[:16]}":
            raise ValueError(f"{s['source_id']} does not match its content")
        if _person_fields(s["content"]):
            raise ValueError(f"{s['source_id']} holds person fields")
    ids = {s["source_id"] for s in sources}
    for e in entries:
        _check_entry(e, ids)
    if catalog["n_entries"] != len(entries) or catalog["n_sources"] != len(sources):
        raise ValueError("catalog counts differ")
    if catalog["schema"] != SCHEMA or catalog["release_id"] != folder.name:
        raise ValueError("catalog schema or release id differs")
    return integrity["release_hash"]


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "verify":
        sys.exit(__doc__)
    print(verify(Path(sys.argv[2])))
