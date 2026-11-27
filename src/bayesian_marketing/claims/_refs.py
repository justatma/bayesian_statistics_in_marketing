"""Reading the engine items a slot names (J4R): runs, notebook releases, names, newest.

Lifted from the unmerged free-text J4 branch (piece/J4 at 3ebcd01, ``claims/figures.py``): the
default loaders (P4), newest by S21 and S23 (2) and (3), client resolution from a snapshot head
and from a release id, the conversion kind (S6) and the names layers (S16). Nothing here reads a
figure out of prose.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

#: ``nb_<client>_<day>_<n>``; client ids hold underscores, so the client is the greedy prefix.
RELEASE_ID_RE = re.compile(r"nb_(?P<client>[\w-]+)_(?P<day>\d{8})_(?P<n>\d+)")
_CLIENT_IN_FILE_RE = re.compile(r'"client_id"\s*:\s*"((?:[^"\\]|\\.)*)"')
_MIN_TIME = datetime.min.replace(tzinfo=UTC)
NAMED_LEVELS = ("campaign", "ad_set", "ad")
_DASHES = "\\-\u2010\u2011\u2012\u2013\u2014\u2015"


def norm_name(s: str) -> str:
    """Lower case, with hyphens, dashes and underscores read as spaces (J4 point 2)."""
    return re.sub(r"\s+", " ", re.sub(rf"[{_DASHES}_]", " ", s.lower())).strip()


# --- clients ---------------------------------------------------------------------------------


def client_of_release_id(release_id: str) -> str | None:
    m = RELEASE_ID_RE.fullmatch(release_id)
    return m["client"] if m else None


def client_of_run_file(path: Path) -> str | None:
    """S25 (10): the client id read from the whole saved snapshot. A file whose head names a
    different client from its body is unreadable, and gives None."""
    try:
        return _client_of_text(path.read_text())
    except (OSError, ValueError):
        return None


def _client_of_text(text: str) -> str:
    body = json.loads(text)
    if not isinstance(body, dict) or not isinstance(body.get("client_id"), str):
        raise ValueError("the snapshot names no client")
    names = [json.loads(f'"{m}"') for m in _CLIENT_IN_FILE_RE.findall(text)]
    if any(n != body["client_id"] for n in names):
        raise ValueError("the snapshot's head and body name different clients")
    return body["client_id"]


def config_kind(client_id: str) -> str | None:
    """``live.refresh._conversion_kind`` on the client config (S6); None when it can't be read."""
    from bayesian_marketing.live import config as live_config
    from bayesian_marketing.live import refresh as live_refresh

    try:
        return live_refresh._conversion_kind(live_config.load_client(client_id))
    except Exception:
        return None


def kind_from_runs(client_id: str) -> str | None:
    """S25 (8), last resort: "lead" if any of the client's saved runs says lead, "purchase" if
    some say purchase and none lead, None if none can be read."""
    from bayesian_marketing import pipeline

    kinds: set[str] = set()
    runs_dir = pipeline.data_dir() / pipeline.RUNS_DIR
    for p in sorted(runs_dir.glob("run_*.json")) if runs_dir.is_dir() else []:
        try:
            text = p.read_text()
            if _client_of_text(text) != client_id:
                continue
            kind = json.loads(text).get("conversion_kind")
        except (OSError, ValueError):
            continue
        if kind in ("lead", "purchase"):
            kinds.add(kind)
    if "lead" in kinds:
        return "lead"
    return "purchase" if kinds else None


def run_kind(snap: Any) -> str:
    from bayesian_marketing.atmaos import socket as sock

    return sock.conversion_kind_of(snap)


# --- default loaders (P4, S16) ---------------------------------------------------------------


def default_load_run(run_id: str) -> Any:
    """``pipeline.load_snapshot``, after S25 (10)'s check that the file names one client."""
    from bayesian_marketing import pipeline

    _client_of_text(pipeline.snapshot_path(run_id).read_text())
    return pipeline.load_snapshot(run_id)


def release_folder(release_id: str) -> Path:
    from bayesian_marketing import notebook

    m = RELEASE_ID_RE.fullmatch(release_id)
    if m is None:
        raise ValueError(f"bad release id {release_id!r}")
    root = notebook.root()
    folder = root / m["client"] / "releases" / release_id
    if folder.is_dir():
        return folder
    for d in sorted(root.glob(f"*/releases/{release_id}")):  # a client id the id splits wrongly
        if d.is_dir():
            return d
    raise KeyError(f"no release {release_id!r} under {root}")


def default_load_release(
    release_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """The release's catalog, entries and sources, after ``notebook.verify`` passes on it."""
    from bayesian_marketing import notebook

    folder = release_folder(release_id)
    notebook.verify(folder)
    catalog = json.loads((folder / "catalog.json").read_text())
    entries = [json.loads(x) for x in (folder / "entries.jsonl").read_text().splitlines() if x]
    sources = [json.loads(x) for x in (folder / "sources.jsonl").read_text().splitlines() if x]
    return catalog, entries, sources


def _live_store_path() -> Path | None:
    from bayesian_marketing import pipeline

    parent = pipeline.data_dir().parent
    candidates = []
    if os.environ.get("BAYES_LIVE_DIR"):
        candidates.append(Path(os.environ["BAYES_LIVE_DIR"]) / "live.sqlite")
    candidates += [parent / "live.sqlite", parent / "live" / "live.sqlite"]
    return next((p for p in candidates if p.is_file()), None)


def default_load_names(client_id: str) -> dict[str, str]:
    """The live store, opened read only: the newest name per ad, ad set and campaign id. No
    store on this machine means no names, not a failure."""
    path = _live_store_path()
    if path is None:
        return {}
    con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT r.entity_ids_json, r.entity_names_json FROM rows r "
            "JOIN polls p ON p.poll_id = r.poll_id WHERE r.client_id = ? "
            "ORDER BY p.started_at, r.date",
            (client_id,),
        ).fetchall()
    finally:
        con.close()
    names: dict[str, str] = {}
    for ids_json, names_json in rows:
        ids, got = json.loads(ids_json), json.loads(names_json)
        for level in NAMED_LEVELS:
            if ids.get(level) and got.get(level):
                names[str(ids[level])] = str(got[level])
    return names


# --- newest (S21, S23) -----------------------------------------------------------------------


def _client_run_ids(client_id: str) -> set[str]:
    from bayesian_marketing import pipeline

    ids: set[str] = set()
    runs_dir = pipeline.data_dir() / pipeline.RUNS_DIR
    if runs_dir.is_dir():
        for p in runs_dir.glob("run_*.json"):
            if client_of_run_file(p) == client_id:
                ids.add(p.stem)
    return ids


def _started() -> dict[str, datetime]:
    from bayesian_marketing.decision import run_record

    try:
        return {r.run_id: r.started_at for r in run_record.read("RunRecord")}
    except Exception:
        return {}


def newest_run_id(client_id: str, also: str | None = None) -> str | None:
    """S21, S23 (2): the latest run record ``started_at`` among the client's saved runs, ties to
    the greater run id."""
    ids = _client_run_ids(client_id)
    if also is not None:
        ids.add(also)
    if not ids:
        return None
    started = _started()
    return max(ids, key=lambda rid: (started.get(rid) or _MIN_TIME, rid))


def run_is_newest(snap: Any) -> bool:
    return newest_run_id(str(snap.client_id), also=str(snap.run_id)) == snap.run_id


def release_key(release_id: str) -> tuple[int, int]:
    m = RELEASE_ID_RE.fullmatch(release_id)
    return (int(m["day"]), int(m["n"])) if m else (0, 0)


def _release_standing(client_id: str, extra: tuple[str, dict[str, Any]] | None) -> list[str]:
    from bayesian_marketing import notebook

    ids, parents = set(), set()
    if extra is not None:
        ids.add(extra[0])
        if extra[1].get("parent_release_id"):
            parents.add(str(extra[1]["parent_release_id"]))
    folder = notebook.root() / client_id / "releases"
    if folder.is_dir():
        for d in folder.iterdir():
            if not d.is_dir() or RELEASE_ID_RE.fullmatch(d.name) is None:
                continue
            ids.add(d.name)
            try:
                parent = json.loads((d / "catalog.json").read_text()).get("parent_release_id")
            except (OSError, ValueError):
                continue
            if parent:
                parents.add(str(parent))
    return [i for i in ids if i not in parents]


def newest_release_id(client_id: str) -> str | None:
    """S21, S23 (3): the greatest (day, n) among the client's releases no release names as its
    parent."""
    standing = _release_standing(client_id, None)
    return max(standing, key=release_key) if standing else None


def release_is_newest(release_id: str, catalog: dict[str, Any]) -> bool:
    client = str(catalog.get("client_id") or client_of_release_id(release_id))
    standing = _release_standing(client, (release_id, catalog))
    return bool(standing) and max(standing, key=release_key) == release_id


# --- names (S16) -----------------------------------------------------------------------------


def cited_names(entry: dict[str, Any], sources: list[Any]) -> dict[str, str]:
    """S16: names from the meta_object sources the entry cites."""
    basis = entry.get("basis") or []
    if not isinstance(basis, list) or not all(isinstance(b, dict) for b in basis):
        raise TypeError("basis is not a list of objects")
    cited = {b.get("source_id") for b in basis}
    names: dict[str, str] = {}
    for s in sources:
        if not isinstance(s, dict):
            raise TypeError(f"source {s!r} is not an object")
        sref, content = s.get("ref") or {}, s.get("content") or {}
        if s.get("source_id") not in cited or s.get("kind") != "meta_object":
            continue
        oid = sref.get("object_id") or content.get("id")
        if oid and content.get("name") and sref.get("object_type") != "account":
            names.setdefault(str(oid), str(content["name"]))
    return names


def source_names(sources: list[Any]) -> dict[str, str]:
    """Names from every meta_object source of a release (not only an entry's cited ones)."""
    names: dict[str, str] = {}
    for s in sources:
        if not isinstance(s, dict) or s.get("kind") != "meta_object":
            continue
        sref, content = s.get("ref") or {}, s.get("content") or {}
        oid = sref.get("object_id") or content.get("id")
        if oid and content.get("name") and sref.get("object_type") != "account":
            names.setdefault(str(oid), str(content["name"]))
    return names


def merge_names(layers: list[dict[str, str]]) -> dict[str, str]:
    """S16: the snapshot's names, then the notebook sources', then the store's, first wins; a
    name that maps to two ids is treated as unnamed."""
    merged: dict[str, str] = {}
    for layer in layers:
        for eid, name in layer.items():
            merged.setdefault(str(eid), str(name))
    by_name: dict[str, set[str]] = {}
    for eid, name in merged.items():
        by_name.setdefault(norm_name(name), set()).add(eid)
    return {eid: n for eid, n in merged.items() if len(by_name[norm_name(n)]) == 1}


def day_of(value: Any) -> date | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None
