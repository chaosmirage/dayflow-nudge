# tests

The unittest suite for the daemon: seventeen test modules plus
fixtures.py, standard library only, discovered from the repository root.
A green run on /usr/bin/python3 (3.9) and on the current python3 is the
proof a change holds.

## Purpose

Pin every behavioral rule and every pinned constant in a test module of
its own, so prose cannot drift from code. The suite is also the
repository's mechanical conscience: it enforces the import policy and
the layout contract, not just the nudge rules.

## Commands

Run the whole suite from the repository root:

```sh
python3 -m unittest discover
```

Run one module:

```sh
python3 -m unittest tests.test_nudge_policy -v
```

Run the import hygiene lock alone:

```sh
python3 -m unittest tests.test_import_hygiene -v
```

## Key pieces

- fixtures.py -- builders for real temporary SQLite stores (WAL mode,
  nullable unix-second timestamps, the soft-delete flag, the date-keyed
  day_goals table, the date-keyed day_goal_categories selection table)
  plus one persona builder per behavioral rule. Tests
  exercise actual SQLite behavior, not an imitation of it.
- test_import_hygiene.py -- parses every .py file in the repository and
  fails on any import whose top-level package is neither standard
  library nor first party; it checks itself too.
- test_gate_contract.py -- the repository layout contract: named
  modules must exist and be non-empty, the applet source must hold its
  invariants, the plist must parse, .env-example must present every
  published knob as a commented line, .gitignore must keep the local
  .env out of the tree, and every publication surface (.env-example,
  deploy/install.sh, README.md, CLAUDE.md) must name exactly the eight
  published knobs and no other DFN_* name.
- test_deploy.py -- the LaunchAgent property list and the install
  scripts.
- test_<module>.py per code module -- behavior lives next to the module
  it pins, and pinned constants are asserted at their design values
  (ACTIVE_WINDOW_MINUTES == 25 in test_detector_distraction,
  COOLDOWN_MINUTES == 15 in test_nudge_policy, SCHEMA_VERSION == 2 in
  test_state_store, QUIET_START 20:00 and QUIET_END 08:00 and the
  Monday-Friday DEFAULT_WEEKDAYS in test_quiet_hours).

## How to extend safely

- Add tests/test_<module>.py for each new code module so discovery and
  the layout contract both hold.
- Build stores and personas through fixtures.py; do not hand-roll SQL a
  builder already expresses.
- Assert each constant the change relies on at its design value; a
  constant used but never asserted is unpinned.
- Inject clocks, environments, and subprocess runners; do not sleep or
  spawn real osascript in a test.

## Conventions

- Use unittest alone: no pytest, no plugins, no network.
- Keep each test deterministic and local: temporary directories clean
  up, and nothing depends on the machine's real Dayflow data.
- Treat Python 3.9 as the floor: avoid syntax and library behavior
  newer than it.
- Keep fixtures to the representative persona builders; real rows with
  personal data stay off this machine.

## Constraints

- NEVER mock the SQLite store; build a real one through fixtures.py
  instead.
- NEVER weaken test_import_hygiene.py to admit a dependency; remove the
  dependency instead.
