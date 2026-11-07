#!/bin/sh
# Removes the two live view launchd jobs. The store and recordings under data/live/ are kept.
set -eu
AGENTS="$HOME/Library/LaunchAgents"
for job in live_poll live_view; do
  label="com.atma.bayes.$job"
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  rm -f "$AGENTS/$label.plist"
  echo "removed $label"
done
