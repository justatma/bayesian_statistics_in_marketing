"""Loopback HTTP server for the live view (spec v0.2 §5 L3 C8). Piece L3. Standard library only.

Routes: ``GET /`` (index), ``GET /client/<id>`` (404 unless the id is in ``store.clients()`` and
has a config), ``GET /health`` (JSON). The path before ``?`` is routed. Any other method is 405,
any other path 404. The store is opened read-only once per request and closed after. One stdout
line per request: ``METHOD PATH STATUS MSms``.
"""

from __future__ import annotations

import json
import signal
import sys
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from bayesian_marketing.core import registries
from bayesian_marketing.live import view
from bayesian_marketing.live.config import load_client
from bayesian_marketing.live.contracts import Clock
from bayesian_marketing.live.registry import LiveRegistry
from bayesian_marketing.live.store import SqliteStore

HTML = "text/html; charset=utf-8"
JSON = "application/json"

Response = tuple[int, str, bytes]


def _handler(
    store_path: Path, registry: LiveRegistry, clock: Clock, data_dir: Path, config_root: Path
) -> type[BaseHTTPRequestHandler]:
    def index(store: SqliteStore) -> Response:
        return 200, HTML, view.render_index(store, clock, registry=registry).encode()

    def health(store: SqliteStore) -> Response:
        last: dict[str, str | None] = {}
        for c in store.clients():
            rec = store.latest_poll(c, ok_only=True)
            last[c] = rec.started_at.isoformat() if rec else None
        return 200, JSON, json.dumps({"ok": True, "last_poll": last}).encode()

    def client(store: SqliteStore, client_id: str) -> Response:
        if client_id not in store.clients():
            return 404, HTML, b""
        try:
            cfg = load_client(client_id, config_root)
        except (FileNotFoundError, ValueError):
            return 404, HTML, b""
        page = view.render(
            store,
            client_id,
            clock,
            registry=registry,
            phrasing=registries.load("phrasing"),
            data_dir=data_dir,
            config=cfg,
        )
        return 200, HTML, page.encode()

    def route(path: str) -> Callable[[SqliteStore], Response] | None:
        if path == "/":
            return index
        if path == "/health":
            return health
        parts = path.split("/")
        if len(parts) == 3 and parts[1] == "client" and parts[2]:
            return lambda store: client(store, parts[2])
        return None

    class Handler(BaseHTTPRequestHandler):
        server_version = "bayes-live"
        sys_version = ""

        def _path(self) -> str:
            return self.path.split("?", 1)[0].split("#", 1)[0]

        def _send(self, status: int, ctype: str, body: bytes, t0: float) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            ms = (time.perf_counter() - t0) * 1000
            print(f"{self.command} {self._path()} {status} {ms:.1f}ms", file=sys.stdout, flush=True)

        def do_GET(self) -> None:
            t0 = time.perf_counter()
            fn = route(self._path())
            if fn is None:
                self._send(404, HTML, b"", t0)
                return
            try:
                store = SqliteStore.open(store_path, read_only=True)
                try:
                    status, ctype, body = fn(store)
                finally:
                    store.close()
            except Exception as e:
                print(f"error {type(e).__name__}: {e}", file=sys.stderr, flush=True)
                status, ctype, body = 500, HTML, b""
            self._send(status, ctype, body, t0)

        def _not_allowed(self) -> None:
            self._send(405, HTML, b"", time.perf_counter())

        def __getattr__(self, name: str) -> Any:
            # BaseHTTPRequestHandler looks up do_<METHOD>; every method but GET is 405.
            if name.startswith("do_"):
                return self._not_allowed
            raise AttributeError(name)

        def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
            pass  # _send prints the one line per request

        def log_message(self, format: str, *args: Any) -> None:
            pass  # the default writes to stderr; the request line is printed by _send

    return Handler


def make_server(
    store_path: Path,
    *,
    registry: LiveRegistry,
    clock: Clock,
    data_dir: Path,
    config_root: Path,
    port: int | None = None,
) -> ThreadingHTTPServer:
    """Bound to ``registry.bind`` and ``port`` (``registry.port`` when None; 0 for ephemeral),
    not yet serving."""
    handler = _handler(Path(store_path), registry, clock, Path(data_dir), Path(config_root))
    srv = ThreadingHTTPServer((registry.bind, registry.port if port is None else port), handler)
    srv.daemon_threads = True
    return srv


def serve(
    store_path: Path, *, registry: LiveRegistry, clock: Clock, data_dir: Path, config_root: Path
) -> None:
    """``make_server`` then ``serve_forever``; SIGTERM shuts down cleanly."""
    srv = make_server(
        store_path, registry=registry, clock=clock, data_dir=data_dir, config_root=config_root
    )

    def on_term(signum: int, frame: Any) -> None:
        # shutdown() waits for serve_forever to return, so it must run off the serving thread.
        threading.Thread(target=srv.shutdown, daemon=True).start()

    previous = signal.signal(signal.SIGTERM, on_term)
    try:
        srv.serve_forever()
    finally:
        signal.signal(signal.SIGTERM, previous)
        srv.server_close()
