"""Shared fixtures for the J2 and J3 acceptance sets (Brain join spec v0.4, J1 to J3, S28 to S35).

Everything lives under the test's ``tmp_path``: the live store is a real ``SqliteStore`` at
``tmp_path / "live" / "live.sqlite"``, the engine's data dir is the isolated ``BAYES_DATA_DIR``
(so the refresh's ``data_dir`` and ``pipeline.data_dir()`` name one folder, and the markers go
under it whichever the builder reads), and ``BAYES_NOTEBOOK_DIR`` is ``tmp_path / "notebook"``.
Nothing reads ``data/live/``, ``notebook/`` or ``configs/`` in the repository.

The history (``J2Env.history``) holds, for one client in America/New_York:

* P1: ads ``ad_a`` and ``ad_b`` for the seven days of the window, ``ad_b`` with a non-ASCII name.
* a poll of another client, in another time zone, in between (never counted).
* P2: ``ad_a`` renamed with its figures unchanged (a confirmed version, first names kept), and
  ``ad_b``'s last day restated (clicks 35 to 40, its v2). Every other ad-day confirms its v1.
* an interrupted poll (begun, never finished) and an error poll whose outcome names another time
  zone (neither counts).
* P4: ``ad_a``'s last day restated (its v2, first seen under the new name), ``ad_b``'s last day
  confirming its v2.
* optionally P5 (``flip=True``): ``ad_b``'s last day back to P1's figures.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import sqlite3
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from bayesian_marketing import core as C
from bayesian_marketing import pipeline
from bayesian_marketing.decision import run_record
from bayesian_marketing.live.contracts import LiveRow, PollRecord, RefreshRecord
from bayesian_marketing.live.refresh import data_dir_env, refresh
from bayesian_marketing.live.store import SqliteStore
from bayesian_marketing.notebook import release as nb_release
from bayesian_marketing.prior_registry import registry as prior_registry
from tests.acceptance import j2_oracle
from tests.fakes import builders as B
from tests.fakes.live import FakeStore, FixedClock

UTC = dt.UTC
CLIENT = "j2_client"
OTHER = "j2_other"
TZ = "America/New_York"
ACCOUNT = "act_777"
ECON_ID = "j2_econ"
T0 = dt.datetime(2026, 11, 7, 17, 30, 0, 123456, tzinfo=UTC)
WINDOW = (dt.date(2026, 11, 1), dt.date(2026, 11, 7))
DAYS = [WINDOW[0] + dt.timedelta(days=i) for i in range(7)]
LAST = DAYS[-1]
PREFIX = "bayes-rows-c1:"
EMPTY_SHA = hashlib.sha256(b"").hexdigest()

#: J1 point 1: exactly the keys the export writes.
J1_KEYS = frozenset(
    {
        "key",
        "restates",
        "describes",
        "known_at",
        "timezone",
        "poll_id",
        "platform",
        "account",
        "campaign",
        "ad_set",
        "ad",
        "names",
        "link_clicks",
        "impressions",
        "spend_amount",
        "spend_currency",
        "conversions_reported",
        "conversions_observed",
        "revenue_amount",
        "revenue_currency",
        "attribution_window",
        "objective",
    }
)
#: J3: the marker fields, exactly as the J3 table lists them.
ENGINE_RUN_FIELDS = frozenset(
    {
        "kind",
        "client_id",
        "run_id",
        "snapshot_path",
        "snapshot_sha256",
        "rows_form",
        "rows_sha256",
        "row_keys",
        "written_at",
    }
)
RELEASE_FIELDS = frozenset(
    {"kind", "client_id", "release_id", "release_path", "release_hash", "written_at"}
)

NAMES_A = {"account": "Acme", "campaign": "Spring", "ad_set": "Set 1", "ad": "Spring A"}
NAMES_A2 = {**NAMES_A, "ad": "Spring A, renamed"}
NAMES_B = {"account": "Acme", "campaign": "Spring", "ad_set": "Set 1", "ad": "Café ☕ naïve ü"}


# ------------------------------------------------------------------ J1 from its text alone


def _j1_value(v: Any) -> str:
    """J1 points 2 and 3, written from the text, not with ``json.dumps``: strings JSON-quoted with
    only the escapes JSON requires (no \\u for non-ASCII), integers bare, floats as Python's
    shortest repr (a REAL column reads back a float), null, true, false; objects with keys sorted by
    code point at every level (S4), no spaces."""
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        assert math.isfinite(v)
        return repr(v)
    if isinstance(v, str):
        out = ['"']
        for ch in v:
            if ch == '"':
                out.append('\\"')
            elif ch == "\\":
                out.append("\\\\")
            elif ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                out.append("\\r")
            elif ch == "\t":
                out.append("\\t")
            elif ch == "\b":
                out.append("\\b")
            elif ch == "\f":
                out.append("\\f")
            elif ord(ch) < 0x20:
                out.append(f"\\u{ord(ch):04x}")
            else:
                out.append(ch)
        out.append('"')
        return "".join(out)
    if isinstance(v, dict):
        return "{" + ",".join(f"{_j1_value(k)}:{_j1_value(v[k])}" for k in sorted(v)) + "}"
    if isinstance(v, list):
        return "[" + ",".join(_j1_value(x) for x in v) + "]"
    raise TypeError(type(v).__name__)


def j1_bytes(rows: list[dict[str, Any]]) -> bytes:
    """J1 point 4: rows by ``key`` ascending by code point, each serialised row plus 0x0A."""
    return b"".join(
        _j1_value(r).encode("utf-8") + b"\n" for r in sorted(rows, key=lambda r: r["key"])
    )


def j1_hash(rows: list[dict[str, Any]]) -> str:
    """J1 point 5."""
    return hashlib.sha256(j1_bytes(rows)).hexdigest()


def file_bytes(rows: list[dict[str, Any]]) -> bytes:
    """``polls.jsonl`` as the export writes it: the rows in the order given."""
    return b"".join(j2_oracle.canonical(r) + b"\n" for r in rows)


# ------------------------------------------------------------------ live rows and polls


def poll_id(client_id: str, started: dt.datetime) -> str:
    return (
        "poll_" + hashlib.sha256(f"{client_id}|meta|{started.isoformat()}".encode()).hexdigest()[:8]
    )


def live_row(pid: str, ad: str, day: dt.date, clicks: int, names: dict[str, str]) -> LiveRow:
    """``ad_a`` rows carry a float conversion count and no revenue; ``ad_b`` rows a null
    conversion count, observed conversions and revenue with a trailing zero."""
    a = ad == "ad_a"
    return LiveRow(
        poll_id=pid,
        client_id=CLIENT,
        platform="meta",
        entity_ids={"account": "777", "campaign": "c1", "ad_set": "s1", "ad": ad},
        entity_names=dict(names),
        objective="OUTCOME_SALES" if a else None,
        date=day,
        impressions=1000,
        clicks=clicks,
        spend=C.Money(amount=Decimal("10.00") if a else Decimal("12.30"), currency="USD"),
        conversions_reported=1.0 if a else None,
        conversions_observed=None if a else 2,
        revenue_reported=None if a else C.Money(amount=Decimal("45.60"), currency="USD"),
        attribution_window="7d_click_1d_view",
    )


def poll_record(
    client_id: str,
    started: dt.datetime,
    *,
    status: str = "ok",
    timezone: str | None = TZ,
    n_rows: int = 0,
    window: tuple[dt.date, dt.date] = WINDOW,
) -> PollRecord:
    pid = poll_id(client_id, started)
    return PollRecord(
        poll_id=pid,
        client_id=client_id,
        platform="meta",
        account_id=ACCOUNT,
        started_at=started,
        finished_at=started + dt.timedelta(seconds=5),
        window=window,
        status=status,  # type: ignore[arg-type]
        error="HTTP 500" if status == "error" else None,
        pull_id=f"pull_meta_{pid[5:]}" if status == "ok" else None,
        n_rows=n_rows,
        n_quarantined=0,
        empty_account=False,
        timezone=timezone,
        currency="USD",
        account={"currency": "USD", "timezone_name": timezone or ""},
        recording_dir=None,
    )


Figures = dict[tuple[str, dt.date], tuple[int, dict[str, str]]]


def base_figures(names_a: dict[str, str] = NAMES_A) -> Figures:
    out: Figures = {}
    for d in DAYS:
        out[("ad_a", d)] = (20, names_a)
        out[("ad_b", d)] = (35, NAMES_B)
    return out


def add_poll(
    store: Any,
    started: dt.datetime,
    figures: Figures,
    *,
    client_id: str = CLIENT,
    timezone: str | None = TZ,
) -> PollRecord:
    rec = poll_record(client_id, started, timezone=timezone, n_rows=len(figures))
    rows = [
        live_row(rec.poll_id, ad, day, clicks, names).model_copy(update={"client_id": client_id})
        for (ad, day), (clicks, names) in figures.items()
    ]
    store.begin_poll(rec)
    store.finish_poll(rec, rows)
    return rec


def add_error_poll(store: Any, started: dt.datetime, timezone: str | None) -> PollRecord:
    rec = poll_record(CLIENT, started, status="error", timezone=timezone)
    store.begin_poll(rec)
    store.finish_poll(rec, [])
    return rec


def add_interrupted_poll(store: Any, started: dt.datetime) -> PollRecord:
    rec = poll_record(CLIENT, started)
    store.begin_poll(rec)
    return rec


# ------------------------------------------------------------------ the environment


class J2Env:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tmp = tmp_path
        self.monkeypatch = monkeypatch
        self.data_dir = Path(os.environ["BAYES_DATA_DIR"])
        self.config_root = tmp_path / "configs"
        self.config_root.mkdir()
        self.nb_root = tmp_path / "notebook"
        self.nb_root.mkdir()
        monkeypatch.setenv("BAYES_NOTEBOOK_DIR", str(self.nb_root))
        self.store_path = tmp_path / "live" / "live.sqlite"
        self.store = SqliteStore.open(self.store_path)
        self.clock = FixedClock(T0 + dt.timedelta(minutes=10))
        self.polls: dict[str, PollRecord] = {}
        self.cfg: C.ClientConfig | None = None

    # setup

    def client(self) -> C.ClientConfig:
        """Approved economics and an approved client CTR prior, as test_L4 builds them."""
        econ = B.economics(
            economics_id=ECON_ID,
            client_id=CLIENT,
            loss_tolerance=150,
            fixed_price=795,
            variable_cost=235,
            approved=True,
        )
        path = self.config_root / "economics" / f"{ECON_ID}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(econ.model_dump_json())
        rec = B.prior_record("ctr", "beta", {"a": 2.0, "b": 98.0}, approved=False, client_id=CLIENT)
        pid = prior_registry.propose(rec)
        prior_registry.approve(pid, "owner")
        self.cfg = C.ClientConfig(
            client_id=CLIENT,
            timezone=TZ,
            currency="USD",
            accounts={"meta": ACCOUNT},
            economics_path=f"economics/{ECON_ID}.json",
            priors={"ctr": pid},
        )
        return self.cfg

    def history(self, *, flip: bool = False, upto: str = "P5") -> dict[str, PollRecord]:
        """The polls of the module docstring, added in time order and returned by name."""
        order = ["P1", "OTHER", "P2", "INT", "ERR", "P4", "P5"]
        steps: dict[str, Callable[[], PollRecord]] = {
            "P1": lambda: add_poll(self.store, T0, base_figures()),
            "OTHER": lambda: add_poll(
                self.store,
                T0 + dt.timedelta(minutes=30),
                {("ad_z", LAST): (5, {"ad": "Other"})},
                client_id=OTHER,
                timezone="Asia/Tokyo",
            ),
            "P2": lambda: add_poll(
                self.store,
                T0 + dt.timedelta(hours=1),
                {**base_figures(NAMES_A2), ("ad_b", LAST): (40, NAMES_B)},
            ),
            "INT": lambda: add_interrupted_poll(self.store, T0 + dt.timedelta(minutes=90)),
            "ERR": lambda: add_error_poll(self.store, T0 + dt.timedelta(hours=2), "Europe/London"),
            "P4": lambda: add_poll(
                self.store,
                T0 + dt.timedelta(hours=3),
                {
                    **base_figures(NAMES_A2),
                    ("ad_a", LAST): (22, NAMES_A2),
                    ("ad_b", LAST): (40, NAMES_B),
                },
            ),
            "P5": lambda: add_poll(self.store, T0 + dt.timedelta(hours=4), base_figures(NAMES_A2)),
        }
        for name in order:
            if name == "P5" and not flip:
                break
            if name not in self.polls:
                self.polls[name] = steps[name]()
            if name == upto:
                break
        return self.polls

    # the refresh

    def refresh(self, poll: PollRecord, store: Any = None) -> RefreshRecord:
        assert self.cfg is not None, "call client() first"
        self.clock.at = poll.started_at + dt.timedelta(minutes=10)
        return refresh(
            self.cfg,
            poll,
            store if store is not None else self.store,
            self.clock,
            data_dir=self.data_dir,
            config_root=self.config_root,
        )

    def snapshot(self, run_id: str) -> pipeline.RunSnapshot:
        return pipeline.load_snapshot(run_id)

    def snapshot_file(self, run_id: str) -> Path:
        return self.data_dir / "runs" / f"{run_id}.json"

    def record(self, run_id: str) -> C.RunRecord:
        got = run_record.read("RunRecord", run_id=run_id)
        assert len(got) == 1, got
        return got[0]  # type: ignore[return-value]

    def run_files(self) -> list[Path]:
        runs = self.data_dir / "runs"
        return sorted(runs.glob("run_*.json")) if runs.is_dir() else []

    # the oracle (the export's polls() at e983942)

    def oracle(
        self, client_id: str = CLIENT, tz: str = TZ
    ) -> tuple[list[dict[str, Any]], dict[str, list[str]], list[dict[str, Any]]]:
        conn = sqlite3.connect(f"{self.store_path.resolve().as_uri()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows, seen = j2_oracle.polls(conn, client_id, tz)
            reads = [dict(r) for r in j2_oracle.POLL_READS]
        finally:
            conn.close()
        return rows, seen, reads

    def oracle_pointer(self, pid: str) -> tuple[list[str], str]:
        """What the export's ``runs()`` at e983942 writes for a run of this poll: ``row_keys`` and
        ``rows_sha256`` (the latter by J1's text, ``j1_hash``)."""
        rows, seen, _ = self.oracle()
        by_key = {r["key"]: r for r in rows}
        keys = seen.get(pid, [])
        return keys, j1_hash([by_key[k] for k in keys])

    # markers

    @property
    def markers(self) -> Path:
        return self.data_dir / "markers"

    @property
    def done(self) -> Path:
        return self.markers / "done"

    def marker_files(self, folder: Path | None = None) -> list[Path]:
        """Marker files: regular files in the folder whose name does not start with a dot."""
        folder = folder or self.markers
        if not folder.is_dir():
            return []
        return sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith("."))

    def stray_files(self, folder: Path | None = None) -> list[Path]:
        folder = folder or self.markers
        if not folder.is_dir():
            return []
        return sorted(p for p in folder.iterdir() if p.is_file() and p.name.startswith("."))

    def run_marker(self, run_id: str, folder: Path | None = None) -> Path:
        """The one marker naming ``run_id``; its file name is one of the two readings of the J3
        table (``run_<run_id>.json`` taken literally, or the run id itself as the name)."""
        found = [p for p in self.marker_files(folder) if p.name in run_marker_names(run_id)]
        assert len(found) == 1, (run_id, [p.name for p in self.marker_files(folder)])
        return found[0]

    def release_marker(self, release_id: str, folder: Path | None = None) -> Path:
        found = [p for p in self.marker_files(folder) if p.name in release_marker_names(release_id)]
        assert len(found) == 1, (release_id, [p.name for p in self.marker_files(folder)])
        return found[0]

    # notebook releases

    def release(self, day: str = "20261120", *, client_id: str = CLIENT) -> Path:
        src = nb_release.source(
            "meta_object",
            {
                "object_type": "account",
                "object_id": ACCOUNT,
                "read_at": "2026-11-20T15:00:00+00:00",
            },
            {"id": ACCOUNT, "currency": "USD", "spend_cap": "150000"},
        )
        entry = {
            "entry_id": "e_limit",
            "kind": "constraint",
            "statement": "The account spending limit is $1,500.",
            "method": "observed",
            "date": "2026-11-20",
            "as_of": "2026-11-20",
            "basis": [{"source_id": src["source_id"], "role": "primary"}],
        }
        return nb_release.write_release(
            self.nb_root,
            client_id,
            [entry],
            [src],
            parent_release_id=None,
            engine_version="0.0.0-test",
            day=day,
        )

    # pre-J2 runs

    def capture_execute(self) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
        """Wrap ``pipeline.execute`` (the real one still runs) and record every call."""
        calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        real = pipeline.execute

        def spy(*args: Any, **kwargs: Any) -> Any:
            calls.append((args, dict(kwargs)))
            return real(*args, **kwargs)

        self.monkeypatch.setattr(pipeline, "execute", spy)
        self._real_execute = real
        return calls

    def pre_j2_run(self, call: tuple[tuple[Any, ...], dict[str, Any]]) -> pipeline.RunContext:
        """A run as every caller other than the live refresh makes one: the same arguments the
        refresh passed, without the three J2 keywords (S31)."""
        args, kwargs = call
        kw = {
            k: v
            for k, v in kwargs.items()
            if k not in ("extra_dataset_hashes", "row_keys", "rows_form")
        }
        with data_dir_env(self.data_dir):
            return self._real_execute(*args, **kw)


def run_marker_names(run_id: str) -> set[str]:
    return {f"run_{run_id}.json", f"{run_id}.json"}


def release_marker_names(release_id: str) -> set[str]:
    return {f"nb_{release_id}.json", f"{release_id}.json"}


def marker_name_ok(name: str) -> bool:
    """A name a marker could have under either reading of the J3 table."""
    return name.endswith(".json") and (name.startswith("run_") or name.startswith("nb_"))


def canonical_marker(data: bytes) -> bool:
    """S33: canonical JSON (keys sorted, no spaces, UTF-8, no ASCII escaping) and one trailing
    line feed."""
    obj = json.loads(data.decode("utf-8"))
    want = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return data == want + b"\n"


def failing_replace(
    monkeypatch: pytest.MonkeyPatch, message: str = "disk full"
) -> Callable[[], None]:
    """Make ``os.replace`` raise ``OSError(message)`` for any destination inside a ``markers``
    folder (the write is interrupted before the rename), and pass every other call through, so
    the run file is still saved. Returns a function that puts the real one back."""
    real = os.replace

    def fake(src: Any, dst: Any, *a: Any, **k: Any) -> None:
        if "markers" in Path(os.fsdecode(dst)).parts:
            raise OSError(message)
        real(src, dst, *a, **k)

    monkeypatch.setattr(os, "replace", fake)
    from bayesian_marketing.live import markers as markers_mod

    if hasattr(markers_mod, "replace"):
        monkeypatch.setattr(markers_mod, "replace", fake)

    def restore() -> None:
        monkeypatch.setattr(os, "replace", real)
        if hasattr(markers_mod, "replace"):
            monkeypatch.setattr(markers_mod, "replace", real)

    return restore


def fake_store_copy(env: J2Env) -> FakeStore:
    """The same history in a ``FakeStore``, rebuilt from the SQLite store through the contract."""
    fake = FakeStore()
    for client in env.store.clients():
        for rec in sorted(env.store.polls(client, limit=10**9), key=lambda r: r.started_at):
            fake.begin_poll(rec)
            if rec.status != "interrupted":
                fake.finish_poll(rec, env.store.rows(rec.poll_id))
    return fake


def make_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[J2Env]:
    """The body of each test file's ``env`` fixture."""
    e = J2Env(tmp_path, monkeypatch)
    yield e
    e.store.close()
