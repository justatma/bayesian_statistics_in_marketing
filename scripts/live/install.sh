#!/bin/sh
# Installs the two live view launchd jobs (spec v0.2 §5 L0). StartInterval comes from
# registries/live.yaml interval_seconds: a cadence change means running this again.
set -eu
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
INTERVAL="$("$REPO/.venv/bin/python" -c 'from bayesian_marketing.live import load_live_registry as l; print(l().interval_seconds)')"
mkdir -p "$AGENTS" "$REPO/data/live/logs"
for job in live_poll live_view; do
  label="com.atma.bayes.$job"
  dest="$AGENTS/$label.plist"
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  sed -e "s#@REPO@#$REPO#g" -e "s#@INTERVAL@#$INTERVAL#g" \
    "$REPO/scripts/live/$label.plist.in" > "$dest"
  plutil -lint "$dest" >/dev/null
  launchctl bootstrap "gui/$(id -u)" "$dest"
  echo "installed $label"
done
