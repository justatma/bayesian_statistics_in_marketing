#!/bin/sh
# Installs the daily export launchd job alone, leaving the poll and view jobs as they are.
set -eu
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
label="com.atma.bayes.daily_export"
dest="$AGENTS/$label.plist"
mkdir -p "$AGENTS" "$REPO/data/live/logs"
launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
sed -e "s#@REPO@#$REPO#g" "$REPO/scripts/live/$label.plist.in" > "$dest"
plutil -lint "$dest" >/dev/null
launchctl bootstrap "gui/$(id -u)" "$dest"
echo "installed $label"
