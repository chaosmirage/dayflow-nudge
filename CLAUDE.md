# dayflow-nudge

dayflow-nudge is a per-user macOS daemon, written in Python 3 on the
standard library alone, that watches the timeline Dayflow records and
posts an escalating macOS notification when you drift into one of the
day's selected distraction categories. It runs as a LaunchAgent and opens
Dayflow's database strictly read-only.

## Purpose

Route work to the floor that owns it. This file stays a router: each
directory keeps its own guide, and the directory guides own their
detail.

## Commands

Run the whole suite from the repository root (the accepted check):

```sh
python3 -m unittest discover
```

Run the import hygiene lock alone:

```sh
python3 -m unittest tests.test_import_hygiene -v
```

Build the notification poster into the daemon's owned directory:

```sh
./scripts/build_applet.sh
```

Install or remove the per-user LaunchAgent:

```sh
./deploy/install.sh
./deploy/uninstall.sh
```

## Key pieces

- dayflow_nudge/ -- the daemon package: fifteen code modules plus two
  packaging shims, one module per stage of the tick. See
  dayflow_nudge/CLAUDE.md.
- tests/ -- the unittest suite, the real-SQLite fixtures, the import
  hygiene lock, and the repository layout contract. See
  tests/CLAUDE.md.
- scripts/ -- the AppleScript notification poster source and the applet
  build script. See scripts/CLAUDE.md.
- deploy/ -- the LaunchAgent property list and the install and
  uninstall scripts. See deploy/CLAUDE.md.
- README.md -- the user-facing quick start, the mandatory Focus
  allowlist step, and the environment switches.

## How to extend safely

- Read the directory guide one floor down before changing a subsystem.
- Run the full suite from the repository root after any change; a green
  run on /usr/bin/python3 (3.9) and on the current python3 is the proof
  that a change holds.
- Keep new behavior inside the module that owns it; values that cross
  stages travel as the typed values declared in
  dayflow_nudge/models.py.
- Prefer silence on doubt in every nudge decision; a nudge the user
  learns to ignore is worse than none.

## Conventions

- Use the Python 3 standard library only, and treat Python 3.9 as the
  floor: the LaunchAgent starts /usr/bin/python3.
- Keep configuration to the eight published environment variables --
  DFN_DISABLE, DFN_NOTIFIER, DFN_POLL_SECONDS, DFN_STYLE, DFN_DAYS,
  DFN_QUIET_START, DFN_QUIET_END, DFN_DB_PATH -- read anew every cycle.
  .env-example and README.md enumerate them with defaults; the
  user-editable .env is consumed only at install time by
  deploy/install.sh, never read by the daemon.
- Keep one test module per code module, discovered from the repository
  root with unittest alone.
- Keep source files pure ASCII.

## Constraints

- NEVER import a third-party package; solve the problem with the
  standard library instead.
- NEVER write to Dayflow's database; reach it read-only through
  dayflow_nudge/db_reader.py instead.
