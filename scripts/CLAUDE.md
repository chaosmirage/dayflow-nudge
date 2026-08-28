# scripts

The notification poster sources: the AppleScript applet the daemon
executes to post an attributed macOS notification, and the shell script
that compiles it into the daemon's owned directory at install time.

## Purpose

Keep the delivery channel attributable: nudges post as DayflowNudge.app
so a Focus mode can allowlist exactly this tool, and the poster is
compiled from committed source rather than shipped as a binary. The
same two sources also feed the repository layout contract, so an
emptied source file fails the suite.

## Commands

Compile the poster into the owned directory (safe to re-run):

```sh
./scripts/build_applet.sh
```

## Key pieces

- applet.applescript -- the poster. The title, body, and the literal
  "sound" flag (escalation) arrive through the DFN_TITLE, DFN_BODY, and
  DFN_SOUND environment variables; compiled applets receive no
  command-line arguments on current macOS. It notifies only; nothing
  needs dismissing.
- build_applet.sh -- removes any previous bundle, compiles with
  osacompile into ~/Library/Application Support/dayflow-nudge/
  DayflowNudge.app, then gives the bundle a stable CFBundleIdentifier
  (com.adel.dayflownudge -- without it the notification center never
  registers the app), sets LSUIElement, and re-signs. The compiled
  bundle stays out of the repository.

## How to extend safely

- Change notification wording by editing the AppleScript source, then
  recompile; do not edit a compiled bundle.
- Extend the payload by extending the environment protocol at both
  ends: notifier.py writes the DFN_* variables and the applet reads
  them with `system attribute`, so keep every value a plain string and
  give every read a safe default (a raised AppleScript error would
  surface as a dialog).
- Keep tests/test_applet_script.py in step with the source; it pins the
  environment protocol and the source invariants.

## Conventions

- Keep the applet a plain AppleScript notifier compiled with osacompile;
  it is the attributable poster, not a general script runner.
- Keep the build re-runnable: remove the previous bundle, then compile.
- Pass text as argv items; the argv channel with shell=False is what
  makes the attribution and the injection safety hold.

## Constraints

- NEVER compose AppleScript source by concatenating user text outside
  the escaping helpers in notifier.py; pass values as argv items to the
  compiled applet instead.
- NEVER commit DayflowNudge.app or any compiled artifact; rebuild it at
  install time instead.
