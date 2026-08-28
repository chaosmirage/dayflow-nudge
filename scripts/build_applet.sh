#!/bin/bash
# Compiles the notification poster applet into the daemon's owned directory.
# Safe to re-run: the previous app bundle is removed before compiling.
#
# After osacompile the bundle gets a stable identifier and UI-element flags:
# without CFBundleIdentifier the notification center never registers the
# app, and LSUIElement keeps the poster out of the Dock. The bundle is then
# re-signed so the modified Info.plist matches the code signature.
set -euo pipefail

OWNED_DIR="$HOME/Library/Application Support/dayflow-nudge"
APP_PATH="$OWNED_DIR/DayflowNudge.app"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$OWNED_DIR"
rm -rf "$APP_PATH"
osacompile -o "$APP_PATH" "$SCRIPT_DIR/applet.applescript"
plutil -replace CFBundleIdentifier -string "com.adel.dayflownudge" \
  "$APP_PATH/Contents/Info.plist"
plutil -replace CFBundleDisplayName -string "DayflowNudge" \
  "$APP_PATH/Contents/Info.plist"
plutil -replace LSUIElement -bool true "$APP_PATH/Contents/Info.plist"
codesign --force --sign - "$APP_PATH"

