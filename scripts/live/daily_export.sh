#!/bin/sh
# The daily full-history export for each live client (D54), read by Arkwright's intake, which
# takes the newest folder under data/live/exports/<client>/. Loads the keys file into this process
# only, without printing it, as run_with_keys.sh does; no value is written anywhere.
set -eu
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
KEYS="${BAYES_KEYS_FILE:-/Users/atma1/.secrets/keys.env}"
if [ ! -r "$KEYS" ]; then
  echo "daily_export: keys file not readable: $KEYS" >&2
  exit 78
fi
set -a
# shellcheck disable=SC1090
. "$KEYS" >/dev/null 2>&1
set +a
cd "$REPO"
PY="$REPO/.venv/bin/python"
CLIENTS="$("$PY" -I -c 'from pathlib import Path; from bayesian_marketing.live.store import SqliteStore; s = SqliteStore.open(Path("data/live/live.sqlite"), read_only=True); print(" ".join(s.clients()))')"
status=0
for client in $CLIENTS; do
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) export $client"
  if out="$("$PY" -I scripts/export_history.py "$client")"; then
    echo "$out" | head -1
  else
    echo "daily_export: $client failed" >&2
    status=1
  fi
done
exit $status
