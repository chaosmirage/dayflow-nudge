# dayflow_nudge

The daemon package: fifteen code modules, standard library only, one
module per stage of the tick that turns Dayflow's recorded timeline into
at most one macOS notification per decision. Python 3.9 is the floor
interpreter.

## Purpose

Name the module that owns a behavior before changing it. Every value
that crosses a stage boundary is a typed value declared in models.py, so
one stage does not import another just to share data.

## Commands

Run the suite covering this package from the repository root:

```sh
python3 -m unittest discover
```

Run the daemon loop by hand:

```sh
python3 -m dayflow_nudge
```

## Key pieces

- models.py -- every cross-stage value: CardSnapshot, GoalSnapshot,
  Observation, Verdict, NudgeCommand, PersistedNudgeState,
  DeliveryResult. The producer owns each invariant.
- daemon.py -- the tick orchestrator with the fixed stage order: kill
  switch, clock, read, freshness, state load, detect, policy, notify,
  settle, persist. A stage exception logs one warning and the
  cycle stays silent.
- __main__.py -- the thin entry delegating to daemon.main(); keep it
  free of logic.
- db_reader.py -- the only module that opens Dayflow's SQLite store
  (read-only, one connection per cycle) and the embedded schema probe;
  an unreadable or drifted store becomes UNKNOWN plus one warning line.
- card_provider.py and goal_provider.py -- typed producers over the
  active card window and today's goal row with its selected distraction
  categories; producers do not decide policy.
- freshness_guard.py -- the pure freshness verdict: the newest card
  older than 25 minutes reads UNKNOWN, and no I/O happens here.
- detector_api.py -- the pluggable detector contract: the abstract
  Detector, the typed Verdict, and the import-time variant registry;
  the daemon binds one variant at boot and does not switch mid-session.
- detector_distraction.py -- the registered variant: membership in the
  day's selected distraction categories, with normalized category
  containment on the token "distraction" only as the fallback for a day
  with no selection.
- nudge_policy.py -- the pure decision core: the two-check streak, then
  the 15-minute cooldown, then quiet hours; the distraction streak is
  the single cause that can notify, the offending card's title is the
  whole notification, and escalation advances only on verified delivery.
- quiet_hours.py -- the pure 23:00 to 09:00 test with the
  midnight-crossing branch.
- kill_switch.py -- DFN_DISABLE=1 read fresh each cycle; counters are
  untouched while it is armed.
- notifier.py -- delivery: one text boundary (sanitize_text,
  applescript_literal), the applet env channel (payload in DFN_TITLE,
  DFN_BODY, DFN_SOUND; applets receive no argv on current macOS) with
  the osascript fallback, shell=False, a 10-second timeout, and the
  typed DeliveryResult.
- state_store.py -- atomic persistence of state.json (write to a
  temporary file, fsync, os.replace); the record is schema 2 with
  exactly the keys schema_version, streak, last_nudge_epoch,
  escalation_level, and day_key, and an older schema-1 file migrates by
  leaving its threshold marks behind; a guarded read falls back to
  defaults plus one warning.
- config.py -- load_config(environ): exactly DFN_DISABLE, DFN_NOTIFIER,
  and DFN_POLL_SECONDS, re-read every cycle.
- logging.py -- one structured line per decision or event on stderr,
  built on the standard library logging module.

## How to extend safely

- Add a new detector as a module that registers itself against
  detector_api; do not branch inside nudge_policy on which detector ran.
- Extend cross-stage data by adding a field to the value in models.py
  and letting its producer fill it; do not parse another stage's output.
- Give a new nudge rule its own branch in nudge_policy and its own test
  module; prefer silence whenever the inputs are in doubt.
- Keep every import standard library or first party; the suite walks
  every syntax tree and fails otherwise.

## Conventions

- Keep the pure modules pure: freshness_guard, quiet_hours, and
  nudge_policy take values and return values.
- Log exactly one line per decision or event; do not log inside a loop
  iteration.
- Treat an unreadable input as UNKNOWN and stay silent; do not let a
  read failure raise into the tick.

## Constraints

- NEVER open Dayflow's store outside db_reader.py or in any mode but
  read-only; add query helpers to db_reader.py instead.
- NEVER match distraction on card titles or goal text; classify on the
  card category through detector_distraction.py instead.
- NEVER advance escalation without a verified DeliveryResult; treat an
  unobserved delivery as not delivered.
- NEVER derive a nudge from the day's goal minutes; the limit minutes
  carry no nudge meaning, only the distraction-category streak does.
