#!/bin/bash
# Compiles both nudge posters into the daemon's owned directory:
#   1. DayflowNudge.app      -- the notification poster (AppleScript applet)
#   2. DayflowNudgeWindow.app -- the styled centered window (SwiftUI panel)
# Safe to re-run: previous bundles are removed before compiling.
#
# After osacompile the applet gets a stable identifier and UI-element flags:
# without CFBundleIdentifier the notification center never registers the
# app, and LSUIElement keeps the poster out of the Dock. The window app is
# built with swiftc when the compiler exists; when it does not, the script
# skips it and the daemon degrades to the applet's dialog surface.
set -euo pipefail

OWNED_DIR="$HOME/Library/Application Support/dayflow-nudge"
APP_PATH="$OWNED_DIR/DayflowNudge.app"
WINDOW_APP_PATH="$OWNED_DIR/DayflowNudgeWindow.app"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$OWNED_DIR"

# --- Notification poster (AppleScript applet) -----------------------------
rm -rf "$APP_PATH"
osacompile -o "$APP_PATH" "$SCRIPT_DIR/applet.applescript"
plutil -replace CFBundleIdentifier -string "com.adel.dayflownudge" \
  "$APP_PATH/Contents/Info.plist"
plutil -replace CFBundleDisplayName -string "DayflowNudge" \
  "$APP_PATH/Contents/Info.plist"
plutil -replace LSUIElement -bool true "$APP_PATH/Contents/Info.plist"
codesign --force --sign - "$APP_PATH"

# --- Styled window poster (SwiftUI panel) ----------------------------------
if command -v swiftc >/dev/null 2>&1; then
  rm -rf "$WINDOW_APP_PATH"
  mkdir -p "$WINDOW_APP_PATH/Contents/MacOS"
  swiftc -O -o "$WINDOW_APP_PATH/Contents/MacOS/DayflowNudgeWindow" \
    "$SCRIPT_DIR/window.swift"
  cat > "$WINDOW_APP_PATH/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key>
  <string>com.adel.dayflownudge.window</string>
  <key>CFBundleName</key>
  <string>DayflowNudgeWindow</string>
  <key>CFBundleExecutable</key>
  <string>DayflowNudgeWindow</string>
  <key>LSUIElement</key>
  <true/>
</dict>
</plist>
PLIST
  codesign --force --sign - "$WINDOW_APP_PATH"
else
  echo "swiftc not found: skipping the styled window poster" >&2
fi


