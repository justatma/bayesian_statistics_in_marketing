"""HTTP for the connectors: live, record and replay (§5.1 C6). The only place httpx is used.

Modes, chosen from the environment when a pull starts:

- ``BAYES_REPLAY_DIR=<dir>``: every exchange is served from ``<dir>/exchange_*.json``. No socket is
  opened and no credential is needed.
- ``BAYES_RECORD_DIR=<dir>``: live calls, and each exchange is written to ``<dir>`` with
  Authorization headers, tokens and secrets replaced by ``"REDACTED"``, plus ``request.json``
  naming the pull (written by ``pull``).
- neither: live calls, nothing written.

A replayed request is matched to a recorded one by method, redacted URL and redacted body, in
recorded order for repeats (a retried call replays its recorded failures first).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

REPLAY_ENV = "BAYES_REPLAY_DIR"
RECORD_ENV = "BAYES_RECORD_DIR"
REDACTED = "REDACTED"
EXCHANGE_GLOB = "exchange_*.json"

# Credential environment variables (.env.example). Their values are scrubbed from every recording.
CREDENTIAL_ENV = (
    "META_ACCESS_TOKEN",
    "META_APP_SECRET",
    "META_CLIENT_TOKEN",
    "GOOGLE_ADS_CLIENT_ID",
    "GOOGLE_ADS_CLIENT_SECRET",
    "GOOGLE_ADS_REFRESH_TOKEN",
    "GOOGLE_ADS_DEVELOPER_TOKEN",
    "LINKEDIN_ACCESS_TOKEN",
    "LINKEDIN_CLIENT_SECRET",
)
# Names (header, query, form or JSON key) whose value is a secret. Matched case-insensitively.
SECRET_NAME = re.compile(
    r"(?i)^(authorization|proxy-authorization|cookie|set-cookie|access_token|refresh_token|"
    r"id_token|client_secret|fb_exchange_token|appsecret_proof|input_token|developer-token|"
    r"developer_token|api[-_]?key|private_key|password)$"
)
# Token shapes from the facts packs (F2 Meta, F3/F5 Google, F4 LinkedIn), scrubbed anywhere.
SECRET_SHAPES = (
    re.compile(r"EAA[A-Za-z0-9]{20,}"),
    re.compile(r"ya29\.[A-Za-z0-9_\-]{20,}"),
    re.compile(r"1//[A-Za-z0-9_\-]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"AQ[A-Za-z0-9_\-]{60,}"),
    re.compile(r"(?i)(bearer\s+)(?!redacted)[A-Za-z0-9._\-~+/=]{8,}"),
    # Live view L2 C3 (build log B1): any access_token= value in free text, e.g. an error message.
    re.compile(r"(access_token=)(?!REDACTED)[^&\s\"'<>]+"),
)

# Engineering choices, not in a registry yet (manifest open question): request timeout and the
# retry schedule. Backoff doubles from BACKOFF_BASE_S with no jitter so a run is reproducible.
TIMEOUT_S = 60.0
MAX_ATTEMPTS = 4
BACKOFF_BASE_S = 2.0


class ConnectorError(RuntimeError):
    """A call failed after retries, or returned an error that retrying cannot fix."""


class ReplayMiss(ConnectorError):
    """Replay mode received a request that has no recorded exchange."""


class MissingCredential(ConnectorError):
    """A live call needs a credential environment variable that is not set."""


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: Any  # parsed JSON, else text

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


# --------------------------------------------------------------------------- redaction


def _env_secrets() -> list[str]:
    vals = [os.environ.get(k, "") for k in CREDENTIAL_ENV]
    return sorted({v for v in vals if len(v) >= 8}, key=len, reverse=True)


def redact_text(text: str) -> str:
    for v in _env_secrets():
        text = text.replace(v, REDACTED)
    for pat in SECRET_SHAPES:
        text = pat.sub(lambda m: (m.group(1) if m.groups() else "") + REDACTED, text)
    return text


def redact_obj(obj: Any) -> Any:
    """Secrets in a JSON-like value replaced by REDACTED, by key name and by token shape."""
    if isinstance(obj, dict):
        return {
            k: (REDACTED if SECRET_NAME.match(str(k)) and v not in (None, "") else redact_obj(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact_obj(v) for v in obj]
    if isinstance(obj, str):
        return redact_url(obj) if obj.startswith(("http://", "https://")) else redact_text(obj)
    return obj


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    if not parts.query:
        return redact_text(url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    if any(SECRET_NAME.match(k) for k, _ in pairs):
        query = urlencode([(k, REDACTED if SECRET_NAME.match(k) else v) for k, v in pairs])
        url = urlunsplit(parts._replace(query=query))
    return redact_text(url)


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    return {k: (REDACTED if SECRET_NAME.match(k) else redact_text(v)) for k, v in headers.items()}


# --------------------------------------------------------------------------- transport


def _key(method: str, url: str, json_body: Any, form: dict[str, str] | None) -> str:
    body = redact_obj(json_body if json_body is not None else form)
    return json.dumps(
        [method.upper(), redact_url(url), body], sort_keys=True, separators=(",", ":")
    )


def _parse_body(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return text


@dataclass
class Transport:
    """One pull's HTTP session. Built by ``Transport.from_env()``."""

    replay_dir: Path | None = None
    record_dir: Path | None = None  # where exchanges are written (a staging dir in record mode)
    record_target: Path | None = None  # BAYES_RECORD_DIR, replaced only after a successful pull
    sleep: Callable[[float], None] = time.sleep
    _client: httpx.Client | None = None
    _replay: dict[str, deque[dict[str, Any]]] = field(default_factory=dict)
    _n: int = 0

    @classmethod
    def from_env(cls) -> Transport:
        replay, record = os.environ.get(REPLAY_ENV), os.environ.get(RECORD_ENV)
        if replay and record:
            raise ConnectorError(f"set only one of {REPLAY_ENV} and {RECORD_ENV}")
        if replay:
            t = cls(replay_dir=Path(replay), sleep=lambda s: None)
            t._load_replay()
            return t
        if record:
            target = Path(record)
            target.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.recording-", dir=target.parent))
            return cls(record_dir=staging, record_target=target)
        return cls()

    def commit_recording(self) -> None:
        """After a successful pull: the staged recording replaces the target directory."""
        if self.record_dir is None or self.record_target is None:
            return
        target, staging = self.record_target, self.record_dir
        old = None
        if target.exists():
            old = Path(tempfile.mkdtemp(prefix=f".{target.name}.old-", dir=target.parent))
            os.replace(target, old / target.name)
        os.replace(staging, target)
        if old is not None:
            shutil.rmtree(old)
        self.record_dir = target

    def discard_recording(self) -> None:
        """After a failed pull: the staged files are removed and the target is left as it was."""
        if self.record_dir is not None and self.record_target is not None:
            shutil.rmtree(self.record_dir, ignore_errors=True)
            self.record_dir = None

    @property
    def replaying(self) -> bool:
        return self.replay_dir is not None

    def _load_replay(self) -> None:
        assert self.replay_dir is not None
        files = sorted(self.replay_dir.glob(EXCHANGE_GLOB))
        if not files:
            raise ReplayMiss(f"no recorded exchanges ({EXCHANGE_GLOB}) in {self.replay_dir}")
        table: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
        for f in files:
            ex = json.loads(f.read_text())
            req = ex["request"]
            k = _key(req["method"], req["url"], req.get("json"), req.get("form"))
            table[k].append(ex["response"])
        self._replay = dict(table)

    def credential(self, name: str) -> str:
        """A credential from the environment. Replay needs none and gets a placeholder."""
        v = os.environ.get(name, "")
        if v:
            return v
        if self.replaying:
            return REDACTED
        raise MissingCredential(f"environment variable {name} is not set")

    def optional(self, name: str) -> str | None:
        return os.environ.get(name) or None

    def send(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: Any = None,
        form: dict[str, str] | None = None,
    ) -> Response:
        headers = dict(headers or {})
        if self.replaying:
            k = _key(method, url, json_body, form)
            queue = self._replay.get(k)
            if not queue:
                raise ReplayMiss(f"no recorded exchange for {method} {redact_url(url)}")
            r = queue.popleft()
            return Response(int(r["status"]), dict(r.get("headers", {})), r.get("body"))
        if self._client is None:
            self._client = httpx.Client(timeout=TIMEOUT_S)
        try:
            raw = self._client.request(method, url, headers=headers, json=json_body, data=form)
        except httpx.TransportError as e:  # retried by call(); recorded as status 0
            resp = Response(0, {}, {"transport_error": type(e).__name__})
        else:
            resp = Response(raw.status_code, dict(raw.headers), _parse_body(raw.text))
        if self.record_dir is not None:
            self._record(method, url, headers, json_body, form, resp)
        return resp

    def _record(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        json_body: Any,
        form: dict[str, str] | None,
        resp: Response,
    ) -> None:
        assert self.record_dir is not None
        self._n += 1
        ex = {
            "request": {
                "method": method.upper(),
                "url": redact_url(url),
                "headers": redact_headers(headers),
                "json": redact_obj(json_body),
                "form": redact_obj(form),
            },
            "response": {
                "status": resp.status,
                "headers": redact_headers(resp.headers),
                "body": redact_obj(resp.body),
            },
        }
        text = redact_text(json.dumps(ex, indent=1, sort_keys=True))
        (self.record_dir / f"exchange_{self._n:04d}.json").write_text(text + "\n")

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


def call(
    t: Transport,
    platform: str,
    method: str,
    url: str,
    *,
    retryable: Callable[[Response], bool],
    describe: Callable[[Response], str],
    headers: dict[str, str] | None = None,
    json_body: Any = None,
    form: dict[str, str] | None = None,
    accept: Callable[[Response], bool] | None = None,
) -> Response:
    """Send with retries. Returns a 2xx response (or one ``accept`` takes); raises otherwise."""
    resp: Response | None = None
    for attempt in range(MAX_ATTEMPTS):
        resp = t.send(method, url, headers=headers, json_body=json_body, form=form)
        if resp.ok or (accept is not None and accept(resp)):
            return resp
        if not (resp.status == 0 or retryable(resp)) or attempt == MAX_ATTEMPTS - 1:
            break
        t.sleep(BACKOFF_BASE_S * 2**attempt)
    assert resp is not None
    raise ConnectorError(
        redact_text(f"{platform}: {method} {redact_url(url)} -> {resp.status}: {describe(resp)}")
    )
