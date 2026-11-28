#!/bin/sh
# Loads the keys file into this process's environment without printing it, then runs the CLI.
# Used by both launchd jobs (a scheduled job does not read the login shell's settings).
# No value from the keys file is written anywhere by this script.
set -eu
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
KEYS="${BAYES_KEYS_FILE:-/Users/atma1/.secrets/keys.env}"
if [ ! -r "$KEYS" ]; then
  echo "run_with_keys: keys file not readable: $KEYS" >&2
  exit 78
fi
set -a
# shellcheck disable=SC1090
. "$KEYS" >/dev/null 2>&1
set +a
cd "$REPO"
exec "$REPO/.venv/bin/python" -m bayesian_marketing.cli "$@"
