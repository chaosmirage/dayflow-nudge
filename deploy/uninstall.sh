#!/bin/bash
#
# Remove the dayflow-nudge LaunchAgent and everything it owns.
# Stops the agent, removes the plist, and deletes the owned dir
# (installed package, DayflowNudge.app, state.json, and logs).

set -euo pipefail

OWNED_DIR="$HOME/Library/Application Support/dayflow-nudge"
PLIST_PATH="$HOME/Library/LaunchAgents/com.dayflow.nudge.plist"
AGENT_ID="com.dayflow.nudge"
SESSION="gui/$(id -u)"

echo "==> Stopping the agent"
# The agent may already be gone (fresh machine, partial install); that
# must not block the rest of the removal.
launchctl bootout "$SESSION/$AGENT_ID" 2>/dev/null || true

echo "==> Removing the LaunchAgent plist"
rm -f "$PLIST_PATH"

echo "==> Removing $OWNED_DIR (state.json and logs included)"
rm -rf "$OWNED_DIR"

echo "Done. dayflow-nudge is fully removed."
