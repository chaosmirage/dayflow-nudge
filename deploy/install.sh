#!/bin/bash
#
# Install dayflow-nudge as a per-user LaunchAgent.
#
# Creates the owned dir (~/Library/Application Support/dayflow-nudge),
# copies the package and the applet build scripts into it, builds the
# DayflowNudge.app notification poster, installs the LaunchAgent plist,
# and registers it with launchd. Safe to re-run: a running agent is
# replaced cleanly.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OWNED_DIR="$HOME/Library/Application Support/dayflow-nudge"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_NAME="com.dayflow.nudge.plist"
AGENT_ID="com.dayflow.nudge"
SESSION="gui/$(id -u)"

echo "==> Preparing $OWNED_DIR"
mkdir -p "$OWNED_DIR/logs" "$OWNED_DIR/dayflow_nudge" "$OWNED_DIR/scripts" \
    "$LAUNCH_AGENTS_DIR"

echo "==> Copying the package and scripts into the owned dir"
rsync -a --delete "$REPO_ROOT/dayflow_nudge/" "$OWNED_DIR/dayflow_nudge/"
rsync -a --delete "$REPO_ROOT/scripts/" "$OWNED_DIR/scripts/"

echo "==> Building the DayflowNudge.app notification poster"
(cd "$REPO_ROOT" && ./scripts/build_applet.sh)

echo "==> Installing the LaunchAgent plist"
cp "$REPO_ROOT/deploy/$PLIST_NAME" "$LAUNCH_AGENTS_DIR/$PLIST_NAME"

echo "==> Registering the agent with launchd"
# Bootout first so a re-run replaces an already-loaded agent; a fresh
# machine has none, so a missing service is not an error here.
launchctl bootout "$SESSION/$AGENT_ID" 2>/dev/null || true
launchctl bootstrap "$SESSION" "$LAUNCH_AGENTS_DIR/$PLIST_NAME"

cat <<'EOF'

Installed. One step is left, and it is mandatory:

  System Settings -> Focus -> Work -> Allowed Notifications -> Apps -> DayflowNudge

Without that allowlist entry Work Focus swallows every nudge this daemon
sends. Logs land in:
  ~/Library/Application Support/dayflow-nudge/logs/daemon.err.log
EOF
