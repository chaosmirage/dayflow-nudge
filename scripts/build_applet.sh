#!/bin/bash
# Compiles the notification poster applet into the daemon's owned directory.
# Safe to re-run: the previous app bundle is removed before compiling.
set -euo pipefail

OWNED_DIR="$HOME/Library/Application Support/dayflow-nudge"
APP_PATH="$OWNED_DIR/DayflowNudge.app"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$OWNED_DIR"
rm -rf "$APP_PATH"
osacompile -o "$APP_PATH" "$SCRIPT_DIR/applet.applescript"
