"""J5: the lead path in check_narrative (Brain join spec v0.3, J5; S11; D46).

Runs are built as in test_L5: ``refresh`` against ``FakeStore`` with real economics, a lead run
from ``conversion_event = {"meta": LEAD_EVENT}`` and a purchase run from the bare config, read
back with ``Env.snapshot``. The narrative and report go through the socket
(``socket.check_narrative``, ``socket.render_report``) with ``BAYES_DATA_DIR`` pointed at the
run's data dir. Each test writes its own client config into ``Env.config_root`` and points
``BAYES_CONFIG_DIR`` there, so ``conversion_kind_of``'s fallback for a pre-J5 snapshot reads a
tmp config and never ``configs/``.

Check (a) needs a cost per sign-up whose q50 is 3.35. The fixture run's own cpa is about 1.00,
so ``with_cpa_q50`` rewrites that one summary value in the saved snapshot file; nothing else in
the run changes.

Check (d), purchase half: the purchase report's HTML is pinned as a sha256 golden produced at
commit b3951bc (the J5 skeleton, before any wiring), as test_L10 pins request keys from 21f1b21.
The existing tests support no other "before" rendering: after the build the purchase tables are
the only path a purchase run takes, so a second render through them would compare the new code
with itself. The golden was taken by running ``purchase_report_html`` below at b3951bc, with the
pipeline clock pinned and the footer's inputs hash masked (its docstring says why).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from bayesian_marketing import core as C
from bayesian_marketing import pipeline
from bayesian_marketing.atmaos import socket as sock
from bayesian_marketing.claims import vocab as V
from tests.acceptance.test_L5 import LEAD_EVENT, Env, config

pytestmark = pytest.mark.piece("J5")

AD = "ad_a"
LEAD = {"conversion_event": {"meta": LEAD_EVENT}}

# Check (a), verbatim from the spec with <id> filled.
LEAD_TEXT = f"This estimate is still rough: ad {AD} had a cost per sign-up of $3.35."
# Check (b): the same text on a purchase run with "cost per order".
PURCHASE_TEXT = f"This estimate is still rough: ad {AD} had a cost per order of $3.35."

# Check (b) at b3951bc: what G5 returned for PURCHASE_TEXT on the purchase fixture run.
PURCHASE_B_PASSED = False
PURCHASE_B_REASONS = [
    "$3.35: number matches no bundle value for ad_a / cost per order at the registry's rounding"
]

# Check (d) at b3951bc: the purchase fixture run and its internal report (``purchase_report_html``).
PINNED_AT = dt.datetime(2026, 11, 7, 18, 30, tzinfo=dt.UTC)
PURCHASE_RUN_ID = "run_234920a3"
PURCHASE_REPORT_SHA = "05bae000628ec4a0f985cd6032fb244ce58f0863d5d093f82aba4a667b6833ad"

PURCHASE_WORD_RE = re.compile(
    r"(?<![\w-])(?:" + "|".join(re.escape(w) for w in V.PURCHASE_WORDS) + r")(?![\w-])",
    re.IGNORECASE,
)


# ------------------------------------------------------------------ helpers


class J5Env(Env):
    """test_L5's Env, with the client config written where ``conversion_kind_of`` reads it."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        super().__init__(tmp_path, monkeypatch)
        monkeypatch.setenv("BAYES_CONFIG_DIR", str(self.config_root))

    def write_config(self, cfg: C.ClientConfig) -> None:
        path = self.config_root / f"{cfg.client_id}.yaml"
        path.write_text(yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False))

    def run_with_config(self, cfg: C.ClientConfig) -> str:
        self.write_config(cfg)
        rec = self.run(cfg)
        assert rec.status == "ran", rec.reason
        return rec.run_id

    def in_data(self, fn: Any, *args: Any) -> Any:
        self.in_data_dir()
        try:
            return fn(*args)
        finally:
            self.mp.setenv("BAYES_DATA_DIR", self.iso)

    def snapshot_file(self, run_id: str) -> Path:
        return self.in_data(pipeline.snapshot_path, run_id)

    def rewrite(self, run_id: str, fn: Any) -> None:
        path = self.snapshot_file(run_id)
        data = json.loads(path.read_text())
        fn(data)
        path.write_text(json.dumps(data))

    def with_cpa_q50(self, run_id: str, ad: str, q50: float) -> None:
        def patch(d: dict[str, Any]) -> None:
            hits = [
                q for q in d["quantities"] if q["name"] == "cpa" and q["scope"]["ids"] == {"ad": ad}
            ]
            assert len(hits) == 1, hits
            hits[0]["estimate"]["summary"]["q50"] = q50

        self.rewrite(run_id, patch)

    def as_pre_j5(self, run_id: str) -> None:
        """The snapshot as saved before J5: no conversion kind."""
        self.rewrite(run_id, lambda d: d.update(conversion_kind=None))

    def check(self, run_id: str, text: str) -> dict[str, Any]:
        return self.in_data(sock.check_narrative, {"text": text}, run_id)

    def report(self, run_id: str, kind: str = "internal") -> str:
        return Path(self.in_data(sock.render_report, run_id, kind, [])).read_text()


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> J5Env:
    return J5Env(tmp_path, monkeypatch)


def lead_run(env: J5Env) -> str:
    return env.run_with_config(config(**LEAD))


def purchase_run(env: J5Env) -> str:
    return env.run_with_config(config())


def body_text(html: str) -> str:
    """The report's visible words: the body with tags, styles and scripts removed."""
    body = html.split("<body", 1)[1]
    body = re.sub(r"<(style|script)\b.*?</\1>", " ", body, flags=re.S | re.I)
    return re.sub(r"<[^>]*>", " ", body)


FOOTER_HASH_RE = re.compile(r"(<footer>Inputs hash <code>)[0-9a-f]{64}(</code></footer>)")


def purchase_report_html(env: J5Env) -> tuple[str, str]:
    """The purchase fixture run's internal report, made comparable across processes: the
    pipeline clock is pinned (as test_L10 pins it), which fixes the run id; the footer's bundle
    inputs hash is masked, because it covers gate and diagnostics timestamps taken from the wall
    clock in modules the test does not pin. Everything else is compared byte for byte."""
    env.mp.setattr(pipeline, "utcnow", lambda: PINNED_AT)
    run_id = purchase_run(env)
    html = env.report(run_id)
    return run_id, FOOTER_HASH_RE.sub(r"\1<masked>\2", html)


# ------------------------------------------------------------------ conversion kind on the run


def test_J5_new_lead_run_records_lead(env: J5Env) -> None:
    s = env.snapshot(lead_run(env))
    assert s.conversion_kind == "lead"  # J5: new runs record their conversion kind


def test_J5_new_purchase_run_records_purchase(env: J5Env) -> None:
    s = env.snapshot(purchase_run(env))
    assert s.conversion_kind == "purchase"  # J5


def test_J5_conversion_kind_of_reads_the_snapshot_first(env: J5Env) -> None:
    run_id = purchase_run(env)
    s = env.snapshot(run_id)
    env.write_config(config(**LEAD))  # the config now disagrees; the snapshot's own kind wins
    assert sock.conversion_kind_of(s.model_copy(update={"conversion_kind": "lead"})) == "lead"
    assert (
        sock.conversion_kind_of(s.model_copy(update={"conversion_kind": "purchase"})) == "purchase"
    )


@pytest.mark.parametrize(
    ("events", "kind"),
    [
        ({"meta": LEAD_EVENT}, "lead"),
        ({"meta": "offsite_conversion.fb_pixel_purchase"}, "purchase"),
        ({}, "purchase"),
    ],
    ids=["lead", "purchase_event", "no_event"],
)
def test_J5_conversion_kind_of_pre_j5_snapshot_falls_back_to_config(
    env: J5Env, events: dict[str, str], kind: str
) -> None:
    run_id = purchase_run(env)
    old = env.snapshot(run_id).model_copy(update={"conversion_kind": None})
    env.write_config(config(conversion_event=events))  # live.refresh._conversion_kind's rule
    assert sock.conversion_kind_of(old) == kind


def test_J5_conversion_kind_of_unconfigured_client_is_purchase(env: J5Env) -> None:
    s = env.snapshot(purchase_run(env))
    old = s.model_copy(update={"conversion_kind": None, "client_id": "no_such_client"})
    assert not (env.config_root / "no_such_client.yaml").exists()
    assert sock.conversion_kind_of(old) == "purchase"


def test_J5_conversion_kind_of_synthetic_client_is_purchase(env: J5Env) -> None:
    s = env.snapshot(purchase_run(env))
    old = s.model_copy(
        update={"conversion_kind": None, "synthetic": True, "client_id": "demo_synth"}
    )
    assert sock.conversion_kind_of(old) == "purchase"


def test_J5_bundle_of_sets_the_conversion_kind(env: J5Env) -> None:
    lead = env.snapshot(lead_run(env))
    assert sock.bundle_of(lead, "internal", []).conversion_kind == "lead"


def test_J5_bundle_of_purchase_run_is_purchase(env: J5Env) -> None:
    """Guard: passes before the build (the field defaults to purchase)."""
    s = env.snapshot(purchase_run(env))
    assert sock.bundle_of(s, "internal", []).conversion_kind == "purchase"


# ------------------------------------------------------------------ G5 on a lead run


def test_J5_a_lead_cost_per_sign_up_at_cents_passes(env: J5Env) -> None:
    run_id = lead_run(env)
    env.with_cpa_q50(run_id, AD, 3.35)
    g5 = env.check(run_id, LEAD_TEXT)
    assert g5["gate"] == "G5"
    assert g5["passed"] is True, g5["reasons"]  # J5 check (a)


def test_J5_a_pre_j5_lead_snapshot_reads_the_lead_tables(env: J5Env) -> None:
    run_id = lead_run(env)
    env.with_cpa_q50(run_id, AD, 3.35)
    env.as_pre_j5(run_id)  # conversion kind None: the client config (lead) decides
    g5 = env.check(run_id, LEAD_TEXT)
    assert g5["passed"] is True, g5["reasons"]  # J5 check (a), through conversion_kind_of


def test_J5_a_lead_cost_per_sign_up_wrong_cents_fails(env: J5Env) -> None:
    """Checked at unit_money_decimals: 3.36 is not 3.35."""
    run_id = lead_run(env)
    env.with_cpa_q50(run_id, AD, 3.35)
    g5 = env.check(run_id, LEAD_TEXT.replace("3.35", "3.36"))
    assert g5["passed"] is False
    assert any("cost per sign-up" in r for r in g5["reasons"]), g5["reasons"]  # lead label


def test_J5_lead_sign_up_rate_passes(env: J5Env) -> None:
    run_id = lead_run(env)
    s = env.snapshot(run_id)
    (cvr,) = [q for q in s.quantities if q.name == "cvr" and q.scope.ids == {"ad": AD}]
    shown = V.fmt_percent(cvr.estimate.summary["q50"])
    g5 = env.check(run_id, f"This estimate is still rough: ad {AD} had a sign-up rate of {shown}.")
    assert g5["passed"] is True, g5["reasons"]  # J5: cvr is "sign-up rate" on a lead run


def test_J5_lead_refuses_cost_per_order(env: J5Env) -> None:
    """A lead run converts on sign-ups: "cost per order" is refused even where its figure matches
    the cpa at the old whole-dollar rounding (q50 3.35 shows as $3 there)."""
    run_id = lead_run(env)
    env.with_cpa_q50(run_id, AD, 3.35)
    g5 = env.check(run_id, f"This estimate is still rough: ad {AD} had a cost per order of $3.")
    assert g5["passed"] is False, g5  # J5: a purchase word cannot describe a lead
    assert any(PURCHASE_WORD_RE.search(r) for r in g5["reasons"]), g5["reasons"]


def test_J5_lead_refuses_cost_per_order_at_cents(env: J5Env) -> None:
    run_id = lead_run(env)
    env.with_cpa_q50(run_id, AD, 3.35)
    g5 = env.check(run_id, PURCHASE_TEXT)
    assert g5["passed"] is False, g5  # J5
    # The refusal is not read through the purchase table: no reason names cpa "cost per order".
    assert not any(f"for {AD} / cost per order" in r for r in g5["reasons"]), g5["reasons"]


# ------------------------------------------------------------------ G5 on a purchase run: unchanged


def test_J5_b_purchase_cost_per_order_as_before(env: J5Env) -> None:
    """Guard: J5 check (b), pinned at b3951bc; passes before the build."""
    run_id = purchase_run(env)
    env.with_cpa_q50(run_id, AD, 3.35)
    g5 = env.check(run_id, PURCHASE_TEXT)
    assert g5["gate"] == "G5" and g5["blocking"] is True
    assert g5["passed"] is PURCHASE_B_PASSED
    assert g5["reasons"] == PURCHASE_B_REASONS  # J5 check (b): exactly as before


def test_J5_b_purchase_whole_dollar_cost_per_order_as_before(env: J5Env) -> None:
    """Guard: a purchase cpa still displays at money_decimals, so $3 matches q50 3.35."""
    run_id = purchase_run(env)
    env.with_cpa_q50(run_id, AD, 3.35)
    g5 = env.check(run_id, f"This estimate is still rough: ad {AD} had a cost per order of $3.")
    assert g5["passed"] is True, g5["reasons"]  # J5 check (b)


# ------------------------------------------------------------------ the report


def test_J5_d_lead_report_says_sign_ups(env: J5Env) -> None:
    run_id = lead_run(env)
    s = env.snapshot(run_id)
    html = env.report(run_id)
    text = body_text(html)
    hits = PURCHASE_WORD_RE.findall(text)
    assert not hits, hits  # J5 check (d): a lead report never prints "order"
    assert "cost per sign-up" in text  # J5: the lead label
    assert "sign-up rate" in text
    for q in s.quantities:
        if q.name == "cpa":  # cost-per money at unit_money_decimals (2)
            places = int(V.phrasing()["rounding"]["unit_money_decimals"])
            want = f"{q.estimate.summary['mean']:,.{places}f}"
            assert f">{want}<" in html.replace(" ", ""), (q.quantity_id, want)


def test_J5_d_lead_report_quantity_labels_name_no_purchase(env: J5Env) -> None:
    """Every quantity label in the lead report's findings comes from labels("lead")."""
    run_id = lead_run(env)
    s = env.snapshot(run_id)
    html = env.report(run_id)
    lead_labels, _ = V.labels("lead")
    cells = re.findall(r"<td>([^<]*)</td>", html)
    for q in s.quantities:
        assert lead_labels[q.name] in cells, (q.name, lead_labels[q.name])
    for cell in cells:
        assert not PURCHASE_WORD_RE.search(cell), cell


def test_J5_d_purchase_report_byte_for_byte(env: J5Env) -> None:
    """Guard: J5 check (d), against the golden from b3951bc; passes before the build."""
    run_id, html = purchase_report_html(env)
    assert run_id == PURCHASE_RUN_ID  # the same fixture run as the golden
    assert hashlib.sha256(html.encode()).hexdigest() == PURCHASE_REPORT_SHA  # J5 check (d)


def test_J5_purchase_tables_unchanged() -> None:
    """Guard: labels("purchase") is the existing pair; passes before the build."""
    labels, aliases = V.labels("purchase")
    assert labels is V.METRIC_LABELS and aliases is V.METRIC_ALIASES
    assert labels["cpa"] == "cost per order" and labels["cvr"] == "conversion rate"
