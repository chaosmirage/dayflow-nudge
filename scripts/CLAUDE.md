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

- applet.applescript -- the poster. argv item 1 is the title, item 2 the
  body, item 3 the literal "sound" when the nudge escalates. It notifies
  only; nothing needs dismissing.
- build_applet.sh -- removes any previous bundle, then compiles with
  osacompile into ~/Library/Application Support/dayflow-nudge/
  DayflowNudge.app. The compiled bundle stays out of the repository.

## How to extend safely

- Change notification wording by editing the AppleScript source, then
  recompile; do not edit a compiled bundle.
- Extend the payload by extending the argv protocol at both ends:
  notifier.py builds the argv list and the applet reads items by
  position, so keep every value a plain string.
- Keep tests/test_applet_script.py in step with the source; it pins the
  argv protocol and the source invariants.

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
