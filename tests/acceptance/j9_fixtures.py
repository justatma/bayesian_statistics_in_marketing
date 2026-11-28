"""Fixtures for the J9 acceptance set (Brain join spec v0.4, J9 and S45).

Runs are J7's series runs (``j7_fixtures.J7Env.put_run``: copies of one template lead run of
three ads, written as run files plus run-record entries in the test's data dir), edited after
they are written by ``J9Env.edit``. The template holds, per ad, ctr, cvr and cpa, with aov, roas
and contribution_per_click in ``not_estimable`` (a lead is never valued, D33), plus one ad-set
quantity (``cvr`` of ad set ``s1``) that has no ad in its scope.

``J9Env.run9`` is ``put_run`` plus the J9 edits: the variants relabelled so that no variant label
equals its ad id (S45 (2)), the ad-set quantity taken out unless a case asks for it (so a plain
run has nothing unkeyed, J9 (8)), the attribution window set, and quantities added by name.

``expected_entry`` is J9 (3) and S45 (3), (4) and (7) written from the text, in the shape the
pre-J9 ``socket._posterior_entry`` writes for the run's metric. A test holds it equal to that code
on the metric name, so it is the same shape. ``pre_j9_socket`` loads ``socket.py`` as it stood
at the commit before J9, so ``result_of`` can be compared with the code as it was.

All data is synthetic. Nothing here reads ``data/live``.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import subprocess
import types
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from bayesian_marketing import core as C
from bayesian_marketing import pipeline
from bayesian_marketing.atmaos import socket as sock
from bayesian_marketing.claims import held as H
from tests.acceptance.j4_fixtures import IMG2_ID, IMG3_ID, IMG4_ID
from tests.acceptance.j7_fixtures import J7Env, at

REPO = Path(__file__).resolve().parents[2]
SOCKET_PATH = "src/bayesian_marketing/atmaos/socket.py"
PRE_J9_COMMIT = "fa857ee"
"""The commit before J9's build (the S45 settlements). ``socket.py`` there is the code J9 (4)
says must give the same ``posterior`` and the same rest of ``result_of``."""

BASE = at("2026-11-10T12:00")
H1 = dt.timedelta(hours=1)

LABELS = {IMG3_ID: "img3", IMG2_ID: "img2", IMG4_ID: "img4"}
"""S45 (2): variant labels that differ from the ad ids."""

JO_WINDOW = "1d_view_7d_click_1d_ev"
"""J9 (10): the attribution window code on a Meta account (a Meta setting, not client data)."""

CONVERSION_NAMES = frozenset({"cvr", "cpa", "aov", "roas", "contribution_per_click"})
"""S45 (5): exactly the names that carry an attribution window."""

VALUED = ("aov", "roas", "contribution_per_click")
J9_KEYS = frozenset({"unit", "label", "attribution_window"})
"""J9 (4): what a ``quantities`` entry adds to the posterior entry of the same name."""

FUTURE_NAME = "a_future_measure"
"""A name no table lists (J9 (6), (9)). Only ``not_estimable`` can hold a free name."""


def unit_table(kind: str, currency: str) -> dict[str, dict[str, Any] | None]:
    """S45 (6), literally: K the kind, C the currency."""
    return {
        "ctr": {"numerator": "link_click", "denominator": "impression", "currency": None},
        "cvr": {"numerator": kind, "denominator": "link_click", "currency": None},
        "cpa": {"numerator": "money", "denominator": kind, "currency": currency},
        "aov": {"numerator": "money", "denominator": kind, "currency": currency},
        "roas": {"numerator": "money", "denominator": "money", "currency": currency},
        "contribution_per_click": {
            "numerator": "money",
            "denominator": "link_click",
            "currency": currency,
        },
    }


def expected_unit(name: str, kind: str, currency: str) -> dict[str, Any] | None:
    return unit_table(kind, currency).get(name)


# ------------------------------------------------------------------ the pre-J9 code

_PRE: dict[str, types.ModuleType] = {}


def pre_j9_socket() -> types.ModuleType | None:
    """``socket.py`` as it stood at ``PRE_J9_COMMIT``, loaded as a module of its own. None when
    git or the commit isn't there (a shallow copy)."""
    if "m" not in _PRE:
        try:
            src = subprocess.run(
                ["git", "-C", str(REPO), "show", f"{PRE_J9_COMMIT}:{SOCKET_PATH}"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError):
            return None
        mod = types.ModuleType("socket_pre_j9")
        mod.__file__ = str(REPO / SOCKET_PATH)
        exec(compile(src, f"{PRE_J9_COMMIT}:{SOCKET_PATH}", "exec"), mod.__dict__)
        _PRE["m"] = mod
    return _PRE["m"]


# ------------------------------------------------------------------ snapshot edits


def _qid(rid: str, *parts: str) -> str:
    return "q_" + hashlib.sha256("|".join((rid, "j9", *parts)).encode()).hexdigest()[:8]


def relabel(d: dict[str, Any], labels: Mapping[str, str] = LABELS) -> None:
    """Variant labels from ``labels`` (ad id -> label), ``not_estimable`` moved with them."""
    old = dict(d["variants"])
    d["variants"] = {labels[ad]: ad for ad in old.values()}
    d["not_estimable"] = {labels[old[v]]: m for v, m in d["not_estimable"].items()}


def variant_of(d: Mapping[str, Any], ad: str) -> str:
    (v,) = [v for v, a in d["variants"].items() if a == ad]
    return v


def find_q(d: Mapping[str, Any], ad: str, name: str) -> dict[str, Any]:
    (q,) = [q for q in d["quantities"] if q["name"] == name and q["scope"]["ids"].get("ad") == ad]
    return q


def add_quantity(
    d: dict[str, Any],
    ad: str | None,
    name: str,
    *,
    like: str | None = None,
    status: str | None = None,
    synthetic: bool | None = None,
    level: str = "ad",
    keep_not_estimable: bool = False,
    index: int | None = None,
) -> str:
    """Add a quantity ``name`` for ``ad``, copied from that ad's ``like`` quantity (ctr for a
    delivery name, else cpa), with a unique id and a summary of its own. Unless
    ``keep_not_estimable``, the name leaves the variant's ``not_estimable``. ``ad`` may be one not
    among ``variants`` (copied from IMG3's), and with ``level`` other than "ad" the scope has no
    ad. Returns the quantity id."""
    like = like or ("ctr" if name in ("ctr", "cpm", "cpc") else "cpa")
    src_ad = ad if ad in d["variants"].values() else IMG3_ID
    q = copy.deepcopy(find_q(d, src_ad, like))
    q["name"] = name
    qid = _qid(d["run_id"], str(ad), name, level)
    q["quantity_id"] = qid
    if level == "ad":
        q["scope"]["ids"] = {"ad": ad}
    else:
        q["scope"]["level"] = level
        q["scope"]["ids"] = {level: "s_j9"}
    h = int(hashlib.sha256(qid.encode()).hexdigest()[:6], 16) / 0xFFFFFF
    q["estimate"]["summary"].update(mean=1 + h, q50=1 + h, q05=0.5 + h, q95=1.5 + h)
    q["notices"] = [f"{name} added for the case"]
    if status is not None:
        _set_feasibility(q["feasibility"], status)
    if synthetic is not None:
        q["provenance"]["synthetic"] = synthetic
    if index is None:
        d["quantities"].append(q)
    else:
        d["quantities"].insert(index, q)
    d["published"][qid] = True
    if not keep_not_estimable and ad in d["variants"].values():
        d["not_estimable"].get(variant_of(d, ad), {}).pop(name, None)
    return qid


def _set_feasibility(f: dict[str, Any], status: str) -> None:
    f["status"] = status
    if status == "estimable":
        f["reasons"] = []
    elif not f["reasons"]:
        f["reasons"] = [f"set {status} for the case"]
    if status == "below_floor":
        f["required"] = 4000.0


def drop_adset(d: dict[str, Any]) -> None:
    """Take out every quantity with no ad in its scope."""
    gone = {q["quantity_id"] for q in d["quantities"] if "ad" not in q["scope"]["ids"]}
    d["quantities"] = [q for q in d["quantities"] if q["quantity_id"] not in gone]
    for g in gone:
        d["published"].pop(g, None)


def set_window(d: dict[str, Any], code: str | None, platform: str | None = None) -> None:
    """``knowability.attribution_windows``: ``{platform: code}``, or no entries for None."""
    p = platform or d["platform"]
    d["knowability"]["attribution_windows"] = {} if code is None else {p: code}


class J9Env(J7Env):
    """J7Env with the J9 edits."""

    def edit(self, rid: str, fn: Callable[[dict[str, Any]], Any]) -> None:
        path = self.data_dir / "runs" / f"{rid}.json"
        d = json.loads(path.read_text())
        fn(d)
        pipeline.RunSnapshot.model_validate(d)
        path.write_text(json.dumps(d))

    def run9(
        self,
        when: dt.datetime = BASE,
        ctr: Any = "marginal",
        *,
        labels: Mapping[str, str] | None = LABELS,
        adset: bool = False,
        window: str | None = JO_WINDOW,
        currency: str | None = None,
        add: Iterable[Mapping[str, Any]] = (),
        also: Callable[[dict[str, Any]], Any] | None = None,
        **kw: Any,
    ) -> str:
        """``put_run(when, ctr, **kw)`` and then: variants relabelled by ``labels`` (None keeps
        the ad ids), the ad-set quantity dropped unless ``adset``, the window code for the run's
        platform (None leaves no entry), ``currency``, each of ``add`` passed to
        ``add_quantity`` (``ad`` and ``name`` required), then ``also``."""
        rid = self.put_run(when, ctr, **kw)

        def fn(d: dict[str, Any]) -> None:
            if labels is not None:
                relabel(d, labels)
            if not adset:
                drop_adset(d)
            set_window(d, window)
            if currency is not None:
                d["currency"] = currency
            for a in add:
                a = dict(a)
                add_quantity(d, a.pop("ad"), a.pop("name"), **a)
            if also is not None:
                also(d)

        self.edit(rid, fn)
        return rid

    def snapshot9(self, rid: str) -> pipeline.RunSnapshot:
        return self.in_data(lambda: pipeline.load_snapshot(rid))

    def held_or_none(self, rid: str) -> dict[Any, str] | None:
        try:
            return self.held(rid)
        except Exception:
            return None

    def pre_result(self, snap: pipeline.RunSnapshot) -> dict[str, Any] | None:
        mod = pre_j9_socket()
        return None if mod is None else self.in_data(lambda: mod.result_of(snap))


# ------------------------------------------------------------------ J9 (3) from the text


def _plain(x: Any) -> Any:
    return json.loads(C.canonical_json(x))


def kind_of(s: pipeline.RunSnapshot) -> str:
    """S45 (1): the one reader for the kind."""
    return H.run_kind(s.conversion_kind, s.synthetic, s.client_id)


def names_of(s: pipeline.RunSnapshot, variant: str) -> list[str]:
    """J9 (2), S45 (2), (3): the ad's quantity names, its variant's ``not_estimable`` names and
    the run's metric name, sorted."""
    ad = s.variants[variant]
    names = {q.name for q in s.quantities if q.scope.ids.get("ad") == ad}
    names |= set(s.not_estimable.get(variant, {}))
    names.add(pipeline.metric_quantity(s.metric))
    return sorted(names)


def expected_entry(
    s: pipeline.RunSnapshot,
    variant: str,
    name: str,
    held: Mapping[Any, str] | None,
    held_reason: str | None = None,
) -> dict[str, Any]:
    """J9 (3) for one variant and name, without ``unit``, ``label`` and ``attribution_window``:
    the fields ``_posterior_entry`` writes for the metric, written for ``name``. ``held`` is the
    run's ``held_status`` answer, or None with ``held_reason`` when it raised."""
    ad = s.variants[variant]
    q = next((x for x in s.quantities if x.name == name and x.scope.ids.get("ad") == ad), None)
    pre = "bayes-rows-c1:"
    hexes = [h.removeprefix(pre) for h in s.dataset_hashes if h.startswith(pre)]
    accepted = pipeline.accepted_attempt(s.fit_attempts)
    fit_route = {
        "kind": s.route.kind,
        "step": s.configuration.get("fit_step"),
        "try": None if accepted is None else accepted["try"],
    }
    entry: dict[str, Any] = {
        "entity": {s.platform: ad},
        "metric": name,  # S45 (4): the entry's own name
        "synthetic": s.synthetic,
        "rows_form": s.rows_form,
        "rows_sha256": hexes[0] if hexes else None,
        "row_keys": list(s.row_keys),
    }
    value: str | None = None
    why = held_reason
    if held is not None:
        value = H.lookup(dict(held), H.quantity_key("ad", ad, name, kind_of(s), s.metric))
        if value is None:
            why = f"held status not available: no held status for {name} of ad {ad}"  # S45 (10)
    ne = s.not_estimable.get(variant, {})

    def held_fields(raw: str, reasons: list[str]) -> dict[str, Any]:
        out: dict[str, Any] = {"held_status": value, "fit_route": fit_route}
        if value is None:
            out["held_status_reason"] = why
        elif H.rank(value) < H.rank(raw):
            reasons = [*reasons, H.HELD_REASON.format(held=value, raw=raw)]
        out["status_reasons"] = reasons
        return out

    if q is None:
        reason = ne.get(name, "not estimable")
        return _plain(
            entry
            | {
                "quantity_id": None,
                "status": "below_floor",
                "summary": None,
                "evidence_class": None,
                "inventory_class": None,
                "design": None,
                "notices": [reason],
                "published": False,
                **held_fields("below_floor", [reason]),
            }
        )
    notices = list(q.notices)
    if name in ne:  # S45 (3): the quantity wins, its reason follows the quantity's own notices
        notices.append(ne[name])
    return _plain(
        entry
        | {
            "quantity_id": q.quantity_id,
            "summary": dict(q.estimate.summary),
            "status": q.feasibility.status,
            "status_basis": q.feasibility.basis,
            **held_fields(q.feasibility.status, list(q.feasibility.reasons)),
            "evidence_class": q.evidence_class,
            "inventory_class": sock.inventory_class(
                q.evidence_class, q.design, q.provenance.synthetic
            ),
            "design": q.design,
            "route": q.provenance.route,
            "funnel_state_id": q.provenance.funnel_state_id,
            "notices": notices,
            "published": s.published.get(q.quantity_id, False),
            "synthetic": q.provenance.synthetic,  # S45 (7)
        }
    )


def without_j9(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in entry.items() if k not in J9_KEYS}
