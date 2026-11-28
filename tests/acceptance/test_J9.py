"""J9: every measure in result_of (Brain join spec v0.4, J9 checks (a) to (k), and S45, which
adds check (l) and governs where it differs from J9's text).

Runs are J7's series runs edited by ``j9_fixtures.J9Env.run9``: three ads of a lead client
(``lead_client``, marked lead by its config), each with ctr, cvr and cpa, and aov, roas and
contribution_per_click listed in ``not_estimable``. Unless a case says otherwise the variant
labels differ from the ad ids (S45 (2)), the attribution window for Meta is Jo's code, and the
ad-set quantity is taken out so nothing is unkeyed. All data is synthetic; no case reads
``data/live``. Check (i) runs over a synthetic multi-run series shaped like Jo's runs.

Check (a) is pinned two ways: a sha256 of ``posterior`` on two pinned runs, taken from the code at
``PRE_J9_COMMIT``, and a byte-for-byte comparison of everything ``result_of`` gave before J9
(``socket.py`` loaded from that commit) with what it gives now, on every fixture run of the
comparison case. Both pass before J9 is built.

Readings the spec leaves to the test writer, and how they are read here:

* An entry's fields are J9 (3)'s ``_posterior_entry`` fields for its name plus exactly ``unit``,
  ``label`` and ``attribution_window``. ``held_status_reason`` is there only when
  ``held_status`` is null, as ``_posterior_entry`` writes it now.
* S45 (3): when a name is both a quantity and in ``not_estimable``, the reason is appended to
  ``notices`` only. ``status_reasons`` stays the quantity's.
* J9 (10), S45 (5): a conversion-based name carries the window whether or not the quantity is
  present (a not-estimable-only aov on a lead run carries it too).
* J9 (8): a ``quantities_unkeyed`` element is the entry a keyed one would be, so it carries
  ``quantity_id``, ``metric`` (its own name), ``summary``, ``status``, ``unit``, ``label``,
  ``attribution_window`` and ``fit_route``. Nothing else about it is asserted: it has no variant
  and so no held lookup the spec defines.
* S45 (10): the "no held status" case is made by wrapping ``claims.held.held_status`` so its
  answer lacks one key. ``result_of`` reads it through the module attribute, as ``_held_of``
  does now.
* "Missing knowability" (S45 (5)) can't be stored, since ``RunSnapshot.knowability`` is required,
  so it is a snapshot copied in memory with ``knowability`` None.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from bayesian_marketing import core as C
from bayesian_marketing import pipeline
from bayesian_marketing.atmaos import socket as sock
from bayesian_marketing.claims import held as H
from bayesian_marketing.claims import vocab
from tests.acceptance.j4_fixtures import IMG2_ID, IMG3_ID, IMG4_ID, OTHER
from tests.acceptance.j7_fixtures import (
    BELOW_FLOOR_ENTRY_KEYS,
    QUANTITY_ENTRY_KEYS,
    B,
    E,
    M,
    hours,
)
from tests.acceptance.j9_fixtures import (
    BASE,
    CONVERSION_NAMES,
    FUTURE_NAME,
    H1,
    J9_KEYS,
    JO_WINDOW,
    LABELS,
    PRE_J9_COMMIT,
    VALUED,
    J9Env,
    expected_entry,
    expected_unit,
    find_q,
    kind_of,
    names_of,
    pre_j9_socket,
    variant_of,
    without_j9,
)
from tests.fakes.atmaos_base import BayesianResult

pytestmark = pytest.mark.piece("J9")

ADS = (IMG3_ID, IMG2_ID, IMG4_ID)
HELD_KEYS = frozenset({"held_status", "fit_route"})

#: sha256 of ``canonical_json(result_of(...)["posterior"])`` on the two pinned runs, from the
#: code at PRE_J9_COMMIT (27 Nov).
PIN_PLAIN_SHA = "26f8c2ff6671ae3f7cc4bec05024fd398fe9fc96081dff5dd72dba3089e49699"
PIN_SERIES_SHA = "03ba217f93bf8789e65d912074d17c846cd388d2ff8e5a3d26b7ecad6632aaee"


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[J9Env]:
    e = J9Env(tmp_path, monkeypatch)
    yield e
    e.close()


# ------------------------------------------------------------------ helpers


def marginal_day(env: J9Env, start: dt.datetime = BASE, **kw: Any) -> dt.datetime:
    """Marginal runs every six hours for 36 hours; returns the last run's time."""
    times = hours(start, 7, 6)
    kw.setdefault("decision", M)
    for t in times:
        env.run9(t, M, **kw)
    return times[-1]


def result(env: J9Env, rid: str) -> dict[str, Any]:
    return env.result(rid)


def qs(res: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    assert "quantities" in res["uncertainty"], "no uncertainty.quantities (J9 (1), S47)"
    return res["uncertainty"]["quantities"]


def mixed_run(env: J9Env) -> str:
    """The newest run of a marginal day: IMG3's cvr raw estimable (held marginal), IMG2's cpa
    below floor and its ctr not estimable, IMG4's cpa not estimable, IMG4 with a cpm quantity."""
    last = marginal_day(env)
    env.run9(last + H1, M)
    return env.run9(
        last + 2 * H1,
        {IMG3_ID: E},
        status={(IMG3_ID, "cvr"): E, (IMG2_ID, "cpa"): B},
        not_estimable=[(IMG2_ID, "ctr"), (IMG4_ID, "cpa")],
        add=[{"ad": IMG4_ID, "name": "cpm"}],
    )


def assert_entry_keys(entry: dict[str, Any], present: bool) -> None:
    base = QUANTITY_ENTRY_KEYS if present else BELOW_FLOOR_ENTRY_KEYS
    want = base | HELD_KEYS | J9_KEYS
    if entry.get("held_status") is None:
        want = want | {"held_status_reason"}
    assert set(entry) == want, sorted(set(entry) ^ want)


def is_json_plain(x: Any) -> bool:
    if x is None or isinstance(x, (str, bool, int, float)):
        return True
    if isinstance(x, list):
        return all(is_json_plain(v) for v in x)
    if isinstance(x, dict):
        return all(isinstance(k, str) and is_json_plain(v) for k, v in x.items())
    return False


def posterior_sha(res: dict[str, Any]) -> str:
    return hashlib.sha256(C.canonical_json(res["posterior"]).encode()).hexdigest()


# ------------------------------------------------------------------ (a) posterior unchanged


def _pin_plain(env: J9Env) -> str:
    return env.put_run(BASE, run_id="run_9a000001")


def _pin_series(env: J9Env) -> str:
    for i, t in enumerate(hours(BASE, 7, 6)):
        env.put_run(t, M, decision=M, run_id=f"run_9b00000{i}")
    return env.run9(
        BASE + dt.timedelta(hours=37),
        {IMG3_ID: E},
        not_estimable=[(IMG2_ID, "ctr"), (IMG4_ID, "cpa")],
        status={(IMG4_ID, "cvr"): B},
        run_id="run_9b0000ff",
    )


@pytest.mark.parametrize(
    ("build", "sha"), [(_pin_plain, PIN_PLAIN_SHA), (_pin_series, PIN_SERIES_SHA)]
)
def test_J9_a_posterior_is_pinned(env: J9Env, build: Any, sha: str) -> None:
    rid = build(env)
    assert posterior_sha(result(env, rid)) == sha


def _comparison_runs(env: J9Env) -> list[str]:
    """Fixture runs of every shape the cases use."""
    rids = [mixed_run(env)]
    t = BASE + dt.timedelta(days=3)
    rids.append(env.run9(t, M, labels=None, adset=True))
    rids.append(env.run9(t + H1, M, kind=None, gone=[(IMG2_ID, "ctr")]))
    rids.append(
        env.run9(
            t + 2 * H1,
            E,
            kind="purchase",
            currency="EUR",
            add=[{"ad": a, "name": n} for a in ADS for n in VALUED],
        )
    )
    rids.append(
        env.run9(t + 3 * H1, M, add=[{"ad": "999000111", "name": "cvr", "index": 0}], adset=True)
    )
    rids.append(env.run9(t + 4 * H1, M, route_kind="nuts", fit_step="nuts_full"))
    return rids


def test_J9_a_4_result_of_is_byte_for_byte_the_pre_J9_result_beside_quantities(
    env: J9Env,
) -> None:
    if pre_j9_socket() is None:
        pytest.skip(f"git or commit {PRE_J9_COMMIT} not available")
    for rid in _comparison_runs(env):
        snap = env.snapshot9(rid)
        before = env.pre_result(snap)
        now = env.result_of_snapshot(snap)
        assert before is not None
        rest = dict(now)
        rest["uncertainty"] = {
            k: v
            for k, v in now["uncertainty"].items()
            if k not in ("quantities", "quantities_unkeyed")
        }  # S47: the new keys live under uncertainty
        assert json.dumps(rest) == json.dumps(before), rid
        assert C.canonical_json(rest["posterior"]) == C.canonical_json(before["posterior"]), rid


def test_J9_a_the_oracle_is_the_pre_J9_posterior_entry_on_the_metric(env: J9Env) -> None:
    """``expected_entry`` for the metric name equals ``posterior[v]`` as the code gives it, so
    the oracle the other cases use has the posterior entry's shape (passes before J9)."""
    for rid in _comparison_runs(env):
        snap = env.snapshot9(rid)
        res = env.result_of_snapshot(snap)
        held = env.held_or_none(rid)
        metric = pipeline.metric_quantity(snap.metric)
        for v in snap.variants:
            why = res["posterior"][v].get("held_status_reason")
            assert expected_entry(snap, v, metric, held, why) == res["posterior"][v], (rid, v)


# ------------------------------------------------------------------ (1), (2) the keys


def test_J9_1_keys_are_exactly_the_variants_and_labels_differ_from_ad_ids(env: J9Env) -> None:
    rid = mixed_run(env)
    snap = env.snapshot9(rid)
    assert set(snap.variants) == set(LABELS.values())
    assert all(v != ad for v, ad in snap.variants.items())  # S45 (2)
    q = qs(result(env, rid))
    assert list(q) == sorted(snap.variants)
    assert not set(q) & set(ADS)


def test_J9_2_names_are_the_union_and_inner_keys_sorted(env: J9Env) -> None:
    rid = mixed_run(env)
    snap = env.snapshot9(rid)
    q = qs(result(env, rid))
    for v in snap.variants:
        assert list(q[v]) == names_of(snap, v), v
    img2, img4 = LABELS[IMG2_ID], LABELS[IMG4_ID]
    assert list(q[img2]) == sorted(["aov", "contribution_per_click", "cpa", "ctr", "cvr", "roas"])
    assert "cpm" in q[img4] and "cpm" not in q[img2]


def test_J9_2_the_metric_is_always_there(env: J9Env) -> None:
    """IMG2's ctr gone without a ``not_estimable`` line: still a key, with "not estimable"."""
    rid = env.run9(BASE, M, gone=[(IMG2_ID, "ctr")])
    snap = env.snapshot9(rid)
    entry = qs(result(env, rid))[LABELS[IMG2_ID]]["ctr"]
    assert entry["quantity_id"] is None and entry["status"] == B
    assert entry["notices"] == ["not estimable"]
    assert entry["summary"] is None
    assert entry["metric"] == "ctr" == pipeline.metric_quantity(snap.metric)


# ------------------------------------------------------------------ (b), (3) the entries


def test_J9_b_the_metric_entry_is_the_posterior_entry_with_three_more_keys(env: J9Env) -> None:
    for rid in _comparison_runs(env):
        res = result(env, rid)
        snap = env.snapshot9(rid)
        metric = pipeline.metric_quantity(snap.metric)
        for v in snap.variants:
            entry = qs(res)[v][metric]
            assert set(entry) >= J9_KEYS, (rid, v)
            assert without_j9(entry) == res["posterior"][v], (rid, v)


def test_J9_3_every_entry_is_the_posterior_entry_for_its_name(env: J9Env) -> None:
    for rid in _comparison_runs(env):
        res = result(env, rid)
        snap = env.snapshot9(rid)
        held = env.held_or_none(rid)
        for v in snap.variants:
            why = res["posterior"][v].get("held_status_reason")
            for name, entry in qs(res)[v].items():
                want = expected_entry(snap, v, name, held, why)
                assert without_j9(entry) == want, (rid, v, name)
                assert_entry_keys(entry, want["quantity_id"] is not None)


def test_J9_S45_4_an_entry_s_metric_is_its_own_name(env: J9Env) -> None:
    rid = mixed_run(env)
    q = qs(result(env, rid))
    assert q[LABELS[IMG3_ID]]["cvr"]["metric"] == "cvr"
    for v, by_name in q.items():
        for name, entry in by_name.items():
            assert entry["metric"] == name, (v, name)


def test_J9_c_every_ad_quantity_appears_once_under_its_variant_and_name(env: J9Env) -> None:
    for rid in _comparison_runs(env):
        res = result(env, rid)
        d = env.snap_json(rid)
        seen: list[tuple[str, str, str]] = [
            (v, name, e["quantity_id"])
            for v, by_name in qs(res).items()
            for name, e in by_name.items()
            if e["quantity_id"] is not None
        ]
        unkeyed = res["uncertainty"].get("quantities_unkeyed", [])
        seen += [("", e["metric"], e["quantity_id"]) for e in unkeyed]
        ids = [x[2] for x in seen]
        assert len(ids) == len(set(ids)), rid
        present = set(d["variants"].values())
        for q in d["quantities"]:
            ad = q["scope"]["ids"].get("ad")
            if q["scope"]["level"] != "ad" or ad not in present:
                continue
            assert ids.count(q["quantity_id"]) == 1, (rid, q["quantity_id"])
            assert (variant_of(d, ad), q["name"], q["quantity_id"]) in seen, (rid, q["name"])


def test_J9_d_every_not_estimable_name_has_its_reason_and_no_quantity_id(env: J9Env) -> None:
    rid = mixed_run(env)
    d = env.snap_json(rid)
    q = qs(result(env, rid))
    assert d["not_estimable"], "the fixture lists not-estimable names"
    for v, reasons in d["not_estimable"].items():
        assert v in LABELS.values()  # S45 (2): keyed by variant, not ad id
        for name, reason in reasons.items():
            entry = q[v][name]
            assert entry["quantity_id"] is None, (v, name)
            assert entry["status"] == B
            assert entry["notices"] == [reason]
            assert entry["status_reasons"] == [reason]
            assert entry["summary"] is None
            assert entry["published"] is False
    assert q[LABELS[IMG4_ID]]["cpa"]["notices"] == ["not estimable for the case"]
    assert q[LABELS[IMG2_ID]]["aov"]["notices"] == ["a lead is counted, never valued (D33)"]


def test_J9_S45_3_a_quantity_wins_over_its_not_estimable_line(env: J9Env) -> None:
    def both(d: dict[str, Any]) -> None:
        d["not_estimable"].setdefault(variant_of(d, IMG3_ID), {})["cvr"] = "listed as well"

    rid = env.run9(BASE, M, also=both)
    d = env.snap_json(rid)
    q = find_q(d, IMG3_ID, "cvr")
    entry = qs(result(env, rid))[LABELS[IMG3_ID]]["cvr"]
    assert entry["quantity_id"] == q["quantity_id"]
    assert entry["summary"] == q["estimate"]["summary"]
    assert entry["status"] == q["feasibility"]["status"]
    assert entry["notices"] == [*q["notices"], "listed as well"]


def test_J9_S45_7_synthetic_is_the_quantity_s_provenance_else_the_snapshot_s(
    env: J9Env,
) -> None:
    def mark(d: dict[str, Any]) -> None:
        find_q(d, IMG3_ID, "cvr")["provenance"]["synthetic"] = True

    rid = env.run9(BASE, M, also=mark)
    q = qs(result(env, rid))[LABELS[IMG3_ID]]
    assert q["cvr"]["synthetic"] is True
    assert q["cpa"]["synthetic"] is False
    assert q["aov"]["synthetic"] is False  # not estimable: the snapshot's


# ------------------------------------------------------------------ (e) held status


def test_J9_e_cvr_and_cpa_carry_the_held_status_lookup_gives(env: J9Env) -> None:
    rid = mixed_run(env)
    snap = env.snapshot9(rid)
    held = env.held(rid)
    q = qs(result(env, rid))
    kind = kind_of(snap)
    for v, ad in snap.variants.items():
        for name in ("cvr", "cpa"):
            want = H.lookup(held, H.quantity_key("ad", ad, name, kind, snap.metric))
            assert want is not None, (ad, name)
            assert q[v][name]["held_status"] == want, (ad, name)
            assert "held_status_reason" not in q[v][name]
    img3 = q[LABELS[IMG3_ID]]["cvr"]
    assert (img3["status"], img3["held_status"]) == (E, M)
    assert H.HELD_REASON.format(held=M, raw=E) in img3["status_reasons"]
    img2 = q[LABELS[IMG2_ID]]["cpa"]
    assert (img2["status"], img2["held_status"]) == (B, B)
    assert q[LABELS[IMG4_ID]]["cpa"]["held_status"] == B  # not estimable


def test_J9_e_S45_10_no_held_status_for_a_name_gives_the_reason(
    env: J9Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    rid = mixed_run(env)
    real = H.held_status

    def lacking(run_id: str, **kw: Any) -> dict[Any, str]:
        return {k: v for k, v in real(run_id, **kw).items() if (k[1], k[2]) != (IMG4_ID, "cvr")}

    monkeypatch.setattr(H, "held_status", lacking)
    res = result(env, rid)
    entry = qs(res)[LABELS[IMG4_ID]]["cvr"]
    assert entry["held_status"] is None
    assert entry["held_status_reason"] == (
        f"held status not available: no held status for cvr of ad {IMG4_ID}"
    )
    assert qs(res)[LABELS[IMG4_ID]]["cpa"]["held_status"] == B
    assert "held_status_reason" not in qs(res)[LABELS[IMG4_ID]]["ctr"]


def test_J9_e_an_unsaved_snapshot_gives_null_held_on_every_entry(env: J9Env) -> None:
    rid = mixed_run(env)
    d = env.snap_json(rid)
    d["run_id"] = "run_0badf00d"
    res = env.result_of_snapshot(pipeline.RunSnapshot.model_validate(d))
    for v, by_name in qs(res).items():
        why = res["posterior"][v]["held_status_reason"]
        assert why
        for name, entry in by_name.items():
            assert entry["held_status"] is None, (v, name)
            assert entry["held_status_reason"] == why, (v, name)


# ------------------------------------------------------------------ (f) units, S45 (1), (6)


def _assert_units(q: dict[str, Any], kind: str, currency: str) -> None:
    for v, by_name in q.items():
        for name, entry in by_name.items():
            assert entry["unit"] == expected_unit(name, kind, currency), (v, name, entry["unit"])


def test_J9_f_the_unit_table_on_a_lead_run(env: J9Env) -> None:
    rid = env.run9(BASE, M, add=[{"ad": IMG4_ID, "name": "cpm"}])
    snap = env.snapshot9(rid)
    assert snap.conversion_kind == "lead" and snap.currency == "USD"
    q = qs(result(env, rid))
    _assert_units(q, "lead", "USD")
    img3 = q[LABELS[IMG3_ID]]
    assert img3["ctr"]["unit"] == {
        "numerator": "link_click",
        "denominator": "impression",
        "currency": None,
    }
    assert img3["cvr"]["unit"] == {
        "numerator": "lead",
        "denominator": "link_click",
        "currency": None,
    }
    assert img3["cpa"]["unit"] == {"numerator": "money", "denominator": "lead", "currency": "USD"}
    assert img3["aov"]["unit"] == {"numerator": "money", "denominator": "lead", "currency": "USD"}
    assert img3["roas"]["unit"] == {"numerator": "money", "denominator": "money", "currency": "USD"}
    assert img3["contribution_per_click"]["unit"] == {
        "numerator": "money",
        "denominator": "link_click",
        "currency": "USD",
    }
    assert q[LABELS[IMG4_ID]]["cpm"]["unit"] is None  # a name the table doesn't list


def test_J9_f_the_unit_table_on_a_purchase_run_in_another_currency(env: J9Env) -> None:
    rid = env.run9(
        BASE,
        E,
        kind="purchase",
        currency="EUR",
        add=[{"ad": a, "name": n} for a in ADS for n in VALUED],
    )
    q = qs(result(env, rid))
    _assert_units(q, "purchase", "EUR")
    img2 = q[LABELS[IMG2_ID]]
    assert img2["cvr"]["unit"] == {
        "numerator": "purchase",
        "denominator": "link_click",
        "currency": None,
    }
    assert img2["cpa"]["unit"] == {
        "numerator": "money",
        "denominator": "purchase",
        "currency": "EUR",
    }
    assert img2["aov"]["unit"]["denominator"] == "purchase"
    assert img2["aov"]["quantity_id"] is not None  # present on a purchase run


def test_J9_f_a_name_no_table_lists_gets_null_unit_and_label(env: J9Env) -> None:
    def future(d: dict[str, Any]) -> None:
        d["not_estimable"].setdefault(variant_of(d, IMG2_ID), {})[FUTURE_NAME] = "not yet built"

    rid = env.run9(BASE, M, also=future)
    entry = qs(result(env, rid))[LABELS[IMG2_ID]][FUTURE_NAME]
    assert entry["unit"] is None
    assert entry["label"] is None
    assert entry["attribution_window"] is None
    assert entry["notices"] == ["not yet built"]


def test_J9_S45_1_a_none_kind_lead_run_takes_lead_from_the_client_config(env: J9Env) -> None:
    rid = env.run9(BASE, M, kind=None)
    snap = env.snapshot9(rid)
    assert snap.conversion_kind is None and not snap.synthetic
    assert H.run_kind(None, False, snap.client_id) == "lead"
    q = qs(result(env, rid))
    _assert_units(q, "lead", "USD")
    img3 = q[LABELS[IMG3_ID]]
    assert img3["cvr"]["label"] == "sign-up rate"
    assert img3["cpa"]["label"] == "cost per sign-up"


def test_J9_S45_1_the_kind_is_held_run_kind_s_reading(env: J9Env) -> None:
    """A client with no config: an earlier run states lead, a later one states nothing.
    ``held.run_kind`` gives lead (any of the client's runs says lead); ``conversion_kind_of``
    would give purchase. Labels and units follow ``run_kind``."""
    env.run9(BASE, M, client=OTHER, kind="lead")
    rid = env.run9(BASE + H1, M, client=OTHER, kind=None)
    snap = env.snapshot9(rid)
    want = env.in_data(lambda: H.run_kind(snap.conversion_kind, snap.synthetic, snap.client_id))
    assert want == "lead"
    assert env.in_data(lambda: sock.conversion_kind_of(snap)) == "purchase"
    q = qs(result(env, rid))
    _assert_units(q, "lead", snap.currency)
    assert q[LABELS[IMG3_ID]]["cvr"]["label"] == vocab.METRIC_LABELS_LEAD["cvr"]


def test_J9_S45_1_a_synthetic_none_kind_run_is_purchase(env: J9Env) -> None:
    rid = env.run9(BASE, M, kind=None, synthetic=True)
    q = qs(result(env, rid))
    _assert_units(q, "purchase", "USD")
    assert q[LABELS[IMG3_ID]]["cpa"]["label"] == "cost per order"


# ------------------------------------------------------------------ (j) labels and windows


def test_J9_j_labels_on_a_lead_run(env: J9Env) -> None:
    rid = env.run9(BASE, M, add=[{"ad": IMG4_ID, "name": "cpm"}])
    q = qs(result(env, rid))
    for v, by_name in q.items():
        for name, entry in by_name.items():
            assert entry["label"] == vocab.METRIC_LABELS_LEAD.get(name), (v, name)
    img3 = q[LABELS[IMG3_ID]]
    assert img3["ctr"]["label"] == "click-through rate"
    assert img3["cvr"]["label"] == "sign-up rate"
    assert img3["cpa"]["label"] == "cost per sign-up"
    assert img3["aov"]["label"] == "average value per sign-up"
    assert q[LABELS[IMG4_ID]]["cpm"]["label"] == "cost per thousand impressions"


def test_J9_j_labels_on_a_purchase_run(env: J9Env) -> None:
    rid = env.run9(
        BASE, M, kind="purchase", add=[{"ad": a, "name": n} for a in ADS for n in VALUED]
    )
    q = qs(result(env, rid))
    for v, by_name in q.items():
        for name, entry in by_name.items():
            assert entry["label"] == vocab.METRIC_LABELS.get(name), (v, name)
    img3 = q[LABELS[IMG3_ID]]
    assert img3["cvr"]["label"] == "conversion rate"
    assert img3["cpa"]["label"] == "cost per order"
    assert img3["aov"]["label"] == "average order value"


def _windows(q: dict[str, Any]) -> dict[tuple[str, str], Any]:
    return {(v, n): e["attribution_window"] for v, by in q.items() for n, e in by.items()}


def test_J9_j_the_attribution_window_on_conversion_names_only(env: J9Env) -> None:
    rid = env.run9(BASE, M, add=[{"ad": IMG4_ID, "name": "cpm"}])
    for (v, name), w in _windows(qs(result(env, rid))).items():
        assert w == (JO_WINDOW if name in CONVERSION_NAMES else None), (v, name, w)
    q = qs(result(env, rid))
    assert q[LABELS[IMG3_ID]]["ctr"]["attribution_window"] is None
    assert q[LABELS[IMG3_ID]]["cvr"]["attribution_window"] == JO_WINDOW
    assert q[LABELS[IMG3_ID]]["aov"]["attribution_window"] == JO_WINDOW  # not estimable too
    assert q[LABELS[IMG4_ID]]["cpm"]["attribution_window"] is None


def test_J9_j_a_purchase_run_carries_the_window_on_every_conversion_name(env: J9Env) -> None:
    rid = env.run9(
        BASE,
        M,
        kind="purchase",
        window="7d_click_1d_view",
        add=[{"ad": a, "name": n} for a in ADS for n in VALUED],
    )
    for (v, name), w in _windows(qs(result(env, rid))).items():
        assert w == ("7d_click_1d_view" if name in CONVERSION_NAMES else None), (v, name)


def test_J9_S45_5_a_two_code_string_gives_the_last_code(env: J9Env) -> None:
    rid = env.run9(BASE, M, window=f"7d_click_1d_view then {JO_WINDOW}")
    q = qs(result(env, rid))
    assert q[LABELS[IMG3_ID]]["cvr"]["attribution_window"] == JO_WINDOW
    assert q[LABELS[IMG3_ID]]["cpa"]["attribution_window"] == JO_WINDOW
    rid3 = env.run9(BASE + H1, M, window="1d_click then 7d_click then 28d_click")
    assert qs(result(env, rid3))[LABELS[IMG2_ID]]["cpa"]["attribution_window"] == "28d_click"


@pytest.mark.parametrize("case", ["empty", "other_platform", "no_entries"])
def test_J9_S45_5_no_window_code_gives_null(env: J9Env, case: str) -> None:
    def fn(d: dict[str, Any]) -> None:
        aw = d["knowability"]["attribution_windows"]
        if case == "empty":
            aw[d["platform"]] = ""
        elif case == "other_platform":
            d["knowability"]["attribution_windows"] = {"google": JO_WINDOW}
        else:
            d["knowability"]["attribution_windows"] = {}

    rid = env.run9(BASE, M, also=fn)
    for key, w in _windows(qs(result(env, rid))).items():
        assert w is None, (case, key)


def test_J9_S45_5_missing_knowability_gives_null(env: J9Env) -> None:
    rid = env.run9(BASE, M)
    snap = env.snapshot9(rid).model_copy(update={"knowability": None})
    res = env.result_of_snapshot(snap)
    for key, w in _windows(qs(res)).items():
        assert w is None, key


# ------------------------------------------------------------------ (k) below floor


def test_J9_k_a_below_floor_quantity_keeps_its_summary(env: J9Env) -> None:
    rid = env.run9(BASE, M, status={(IMG3_ID, "cvr"): B}, not_estimable=[(IMG3_ID, "cpa")])
    d = env.snap_json(rid)
    q = qs(result(env, rid))[LABELS[IMG3_ID]]
    cvr = find_q(d, IMG3_ID, "cvr")
    assert cvr["feasibility"]["status"] == B
    assert q["cvr"]["status"] == B
    assert q["cvr"]["quantity_id"] == cvr["quantity_id"]
    assert q["cvr"]["summary"] == cvr["estimate"]["summary"]  # J9 (11): never left out
    assert q["cvr"]["held_status"] == B
    assert q["cpa"]["quantity_id"] is None
    assert q["cpa"]["summary"] is None  # only a name with no quantity
    assert q["cpa"]["status"] == B


# ------------------------------------------------------------------ (h) unkeyed quantities


def test_J9_h_unkeyed_quantities_in_quantity_order(env: J9Env) -> None:
    """S45 (8): one quantity whose ad isn't among ``variants`` (put first) and one with no ad in
    its scope (the template's ad-set cvr, last)."""
    foreign = "999000111"
    rid = env.run9(BASE, M, adset=True, add=[{"ad": foreign, "name": "cpa", "index": 0}])
    d = env.snap_json(rid)
    unkeyed = [
        q
        for q in d["quantities"]
        if "ad" not in q["scope"]["ids"] or q["scope"]["ids"]["ad"] not in d["variants"].values()
    ]
    assert [q["scope"]["ids"] for q in unkeyed] == [{"ad": foreign}, {"ad_set": "s1"}]
    res = result(env, rid)
    assert "quantities_unkeyed" in res["uncertainty"]
    got = res["uncertainty"]["quantities_unkeyed"]
    assert [e["quantity_id"] for e in got] == [q["quantity_id"] for q in unkeyed]
    for e, q in zip(got, unkeyed, strict=True):
        assert e["metric"] == q["name"]
        assert e["summary"] == q["estimate"]["summary"]
        assert e["status"] == q["feasibility"]["status"]
        assert e["unit"] == expected_unit(q["name"], "lead", d["currency"])
        assert e["label"] == vocab.METRIC_LABELS_LEAD[q["name"]]
        assert e["attribution_window"] == JO_WINDOW
        assert e["fit_route"] == res["posterior"][LABELS[IMG3_ID]]["fit_route"]
    keyed = {e["quantity_id"] for by in qs(res).values() for e in by.values()}
    assert not keyed & {e["quantity_id"] for e in got}
    assert set(qs(res)) == set(d["variants"])


def test_J9_h_no_unkeyed_quantity_means_no_key(env: J9Env) -> None:
    rid = env.run9(BASE, M)
    assert all("ad" in q["scope"]["ids"] for q in env.snap_json(rid)["quantities"])
    res = result(env, rid)
    assert "quantities" in res["uncertainty"]
    assert "quantities_unkeyed" not in res["uncertainty"]
    assert "quantities" not in res and "quantities_unkeyed" not in res  # S47


# ------------------------------------------------------------------ (g) plain and stable


def test_J9_g_json_plain_and_the_same_twice(env: J9Env) -> None:
    for rid in _comparison_runs(env):
        a = result(env, rid)
        b = result(env, rid)
        assert "quantities" in a["uncertainty"]
        assert is_json_plain(a), rid
        assert json.loads(json.dumps(a)) == a
        assert json.dumps(a) == json.dumps(b), rid


# ------------------------------------------------------------------ (l) fit_route


def test_J9_l_every_entry_s_fit_route_is_the_run_s(env: J9Env) -> None:
    def attempts(d: dict[str, Any]) -> None:
        d["fit_attempts"] = [
            {"step": "nuts_full", "try": 1, "seed": 11, "divergences": 2, "passed": False},
            {"step": "nuts_full", "try": 2, "seed": 12, "divergences": 0, "passed": True},
        ]

    for rid, want in (
        (env.run9(BASE, M), {"kind": "conjugate", "step": "conjugate", "try": None}),
        (
            env.run9(
                BASE + H1, M, route_kind="nuts", fit_step="nuts_full", adset=True, also=attempts
            ),
            {"kind": "nuts", "step": "nuts_full", "try": 2},
        ),
    ):
        res = result(env, rid)
        for v, by_name in qs(res).items():
            assert res["posterior"][v]["fit_route"] == want
            for name, entry in by_name.items():
                assert entry["fit_route"] == want, (rid, v, name)
        for e in res["uncertainty"].get("quantities_unkeyed", []):
            assert e["fit_route"] == want


# ------------------------------------------------------------------ (7), (i) every saved run


def test_J9_7_a_pre_D33_lead_run_with_contribution_per_click_gives_it(env: J9Env) -> None:
    rid = env.run9(BASE, M, kind=None, add=[{"ad": IMG2_ID, "name": "contribution_per_click"}])
    d = env.snap_json(rid)
    q = find_q(d, IMG2_ID, "contribution_per_click")
    entry = qs(result(env, rid))[LABELS[IMG2_ID]]["contribution_per_click"]
    assert entry["quantity_id"] == q["quantity_id"]
    assert entry["summary"] == q["estimate"]["summary"]
    assert entry["unit"] == {"numerator": "money", "denominator": "link_click", "currency": "USD"}
    assert entry["attribution_window"] == JO_WINDOW


def test_J9_i_every_run_of_a_series_gives_quantities_with_ctr_and_cvr(env: J9Env) -> None:
    """A synthetic series shaped like Jo's: three days of runs, most stating no kind, some lead;
    variants relabelled on some and not others; an ad dropping out; ctr not estimable; cpa
    below floor or not estimable; contribution_per_click present on an old lead run; one run on
    the joint route."""
    t = BASE
    plan: list[dict[str, Any]] = [
        {"kind": None},
        {"kind": None, "labels": None},
        {"kind": None, "not_estimable": [(IMG4_ID, "cpa")]},
        {"kind": None, "add": [{"ad": IMG3_ID, "name": "contribution_per_click"}]},
        {"kind": None, "absent": [IMG2_ID]},
        {"kind": None, "status": {(IMG3_ID, "cpa"): B, (IMG4_ID, "cvr"): E}},
        {"kind": None, "not_estimable": [(IMG2_ID, "ctr")]},
        {"kind": "lead", "ctr": E},
        {"kind": "lead", "labels": None, "absent": [IMG4_ID]},
        {"kind": "lead", "route_kind": "nuts", "fit_step": "fallback_conjugate"},
        {"kind": "lead", "status": {(IMG2_ID, "cvr"): B}, "not_estimable": [(IMG3_ID, "cpa")]},
        {"kind": "lead", "window": f"7d_click_1d_view then {JO_WINDOW}"},
    ]
    rids = []
    for i, kw in enumerate(plan):
        kw = dict(kw)
        ctr = kw.pop("ctr", M)
        rids.append(env.run9(t + dt.timedelta(hours=6 * i), ctr, **kw))
    for rid in rids:
        snap = env.snapshot9(rid)
        res = result(env, rid)
        q = qs(res)
        assert set(q) == set(snap.variants), rid
        for v in snap.variants:
            assert "ctr" in q[v] and "cvr" in q[v], (rid, v)
            assert q[v]["cvr"]["label"] == "sign-up rate", (rid, v)
            assert q[v]["cpa"]["label"] == "cost per sign-up", (rid, v)
            assert q[v]["cvr"]["attribution_window"] == JO_WINDOW, (rid, v)
            assert without_j9(q[v]["ctr"]) == res["posterior"][v], (rid, v)


# ------------------------------------------------------------------ S47 AtmaOS's result model


def test_J9_S47_result_of_still_fits_AtmaOS_BayesianResult(env: J9Env) -> None:
    """S47: the frozen ``BayesianResult`` forbids unknown top-level keys, so the new keys live
    under ``uncertainty`` and every result still validates."""
    for rid in _comparison_runs(env):
        res = result(env, rid)
        BayesianResult.model_validate(res)
        assert "quantities" in res["uncertainty"]
