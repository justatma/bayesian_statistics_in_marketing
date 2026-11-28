"""One-time Google OAuth setup for ENG-BAYES (D21). Never prints a secret.

Reads the OAuth Desktop client JSON downloaded from the Cloud console (newest
~/Downloads/client_secret_*.json, or a path given as the first argument), runs the
loopback consent flow in the browser, and writes GOOGLE_ADS_CLIENT_ID,
GOOGLE_ADS_CLIENT_SECRET and GOOGLE_ADS_REFRESH_TOKEN into the repo's .env.
Scopes: Google Ads (adwords) and GA4 read-only (analytics.readonly).
Then lists the Google Ads customers the login can reach, as a check.

Run: .venv/bin/python scripts/google_oauth_setup.py
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import secrets
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
ENV = REPO / ".env"
SCOPES = [
    "https://www.googleapis.com/auth/adwords",
    "https://www.googleapis.com/auth/analytics.readonly",
]
ADS_VERSION = "v26"


def client_file() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1]).expanduser()
    found = sorted(
        (Path.home() / "Downloads").glob("client_secret_*.json"), key=lambda p: p.stat().st_mtime
    )
    if not found:
        sys.exit("No ~/Downloads/client_secret_*.json found. Download the client JSON first.")
    return found[-1]


def set_env(values: dict[str, str]) -> None:
    lines = ENV.read_text().splitlines() if ENV.exists() else []
    done = set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in values and not line.lstrip().startswith("#"):
            lines[i] = f"{key}={values[key]}"
            done.add(key)
    lines += [f"{k}={v}" for k, v in values.items() if k not in done]
    ENV.write_text("\n".join(lines) + "\n")
    ENV.chmod(0o600)


def main() -> None:
    path = client_file()
    cfg = json.loads(path.read_text())
    c = cfg.get("installed") or cfg.get("web")
    if not c:
        sys.exit(f"{path.name} is not an OAuth client file.")
    cid, csec = c["client_id"], c["client_secret"]

    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    state = secrets.token_urlsafe(16)
    got: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            if "code" in q or "error" in q:
                got.update(q)
            self.send_response(200)
            self.end_headers()
            msg = "Done. You can close this tab." if "code" in q else "Consent not given."
            self.wfile.write(msg.encode())

        def log_message(self, *a: object) -> None:
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    redirect = f"http://127.0.0.1:{srv.server_port}"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(
        {
            "client_id": cid,
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge.decode(),
            "code_challenge_method": "S256",
        }
    )
    t = threading.Thread(target=lambda: [srv.handle_request() for _ in range(5) if not got])
    t.start()
    print("Opening Google consent in your browser. Sign in as atma@atmangroup.org and click Allow.")
    print(f"If no page opens, paste this into Chrome:\n{url}", flush=True)
    webbrowser.open(url)
    t.join(timeout=600)
    srv.server_close()
    if got.get("state") != state or "code" not in got:
        sys.exit(f"No consent received ({got.get('error', 'timeout')}).")

    tok = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": got["code"],
            "client_id": cid,
            "client_secret": csec,
            "redirect_uri": redirect,
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        },
        timeout=30,
    ).json()
    if "refresh_token" not in tok:
        sys.exit(f"Token exchange failed: {tok.get('error')} {tok.get('error_description', '')}")
    set_env(
        {
            "GOOGLE_ADS_CLIENT_ID": cid,
            "GOOGLE_ADS_CLIENT_SECRET": csec,
            "GOOGLE_ADS_REFRESH_TOKEN": tok["refresh_token"],
        }
    )
    print(f"Saved client id, secret and refresh token to .env (scopes: {tok.get('scope')}).")

    r = httpx.get(
        f"https://googleads.googleapis.com/{ADS_VERSION}/customers:listAccessibleCustomers",
        headers={"Authorization": f"Bearer {tok['access_token']}"},
        timeout=30,
    )
    if r.status_code == 200:
        names = r.json().get("resourceNames", [])
        print(f"Google Ads customers reachable: {[n.split('/')[-1] for n in names] or 'none'}")
    else:
        err = r.json().get("error", {})
        print(f"Google Ads check: HTTP {r.status_code} {err.get('status')} {err.get('message')}")


if __name__ == "__main__":
    main()
