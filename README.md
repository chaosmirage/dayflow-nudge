# dayflow-nudge

A per-user macOS daemon that nudges you when Dayflow says you drifted.

## What it is

dayflow-nudge is a small Python 3 daemon (standard library only) that runs as
a per-user LaunchAgent. It watches the timeline Dayflow records and shows a
centered focus window -- or, if you prefer, a macOS notification -- when you
drift into one of the distraction categories you selected for the day in
Dayflow. It never writes to Dayflow: the Dayflow database is opened strictly
read-only.

## Quick start

From a checkout of this repository, on the Mac that runs Dayflow:

    deploy/install.sh
    # MANDATORY next step (see the section below) or no nudge ever shows:
    #   System Settings -> Focus -> Work -> Allowed Notifications -> Apps -> DayflowNudge
    launchctl print gui/$(id -u)/com.dayflow.nudge | head -n 5

The install works as-is with the default settings. To change any setting,
copy .env-example to .env, edit it, and re-run deploy/install.sh (see
Configuration). The agent starts at install (RunAtLoad + KeepAlive), so
there is nothing else to run. Nudges appear once Dayflow records a card in
one of today's distraction categories and the two-check confirmation
passes; see How it works for the full silence conditions.

## How it works

Every 60 seconds the daemon:

1. Re-reads its configuration -- the eight environment variables named
   under Configuration -- and checks the kill
   switch (DFN_DISABLE=1 skips the whole cycle and touches no state).
2. Opens Dayflow's store
   (~/Library/Application Support/Dayflow/chunks.sqlite) read-only and
   probes its schema.
3. Checks freshness: if the newest timeline card is older than ~25 minutes,
   it stays silent.
4. Classifies the current activity. The trigger is the distraction-category
   selection you made in Dayflow's Daily tab for today: a card whose
   category is one of those selected categories counts as off task. The
   selection is re-read every cycle, so a change you make in the Daily tab
   takes effect on the next cycle (within about a minute). Only when the
   day has no such selection does the fallback rule apply: a card whose
   category contains the word "Distraction" counts as off task.
5. Applies the nudge policy: a nudge needs two consecutive off-task checks,
   at most one nudge per 15 minutes, nothing during quiet hours
   (20:00-08:00 by default), and nothing on days outside the operating
   week (Monday-Friday by default); the first nudge is silent, a repeat
   nudge adds a sound.
6. Delivers through the compiled DayflowNudge.app poster and persists its
   small state file. The default surface is a window in the middle of the
   screen: the headline "Please focus on your main task" and the offending
   card's own name as the body, e.g. "Reddit scroll (14 min)". The window
   dismisses itself after 30 seconds (button: "Back to work"); a repeat
   nudge adds a beep. DFN_STYLE=notification switches to standard macOS
   notifications instead.

The daily distraction-limit minutes you set in Dayflow no longer produce notifications;
only the category trigger above nudges.

Everything it owns lives in one directory,
~/Library/Application Support/dayflow-nudge/ (the installed package copy,
DayflowNudge.app, state.json, and logs/).

## Tech stack

- Python 3, standard library only -- no third-party packages to install.
- launchd per-user LaunchAgent (RunAtLoad + KeepAlive).
- SQLite, opened read-only through the stdlib sqlite3 module.
- Notifications posted by an osacompile-built AppleScript applet
  (DayflowNudge.app), with a bare osascript fallback channel.

## Install

From the repository root:

    deploy/install.sh

The script copies the package and scripts into the owned dir, builds the
DayflowNudge.app poster with osacompile, renders
~/Library/LaunchAgents/com.dayflow.nudge.plist from the template in
deploy/ plus your .env (all paths land under your own home; nothing is
hand-edited), and registers it with launchd (RunAtLoad + KeepAlive, so it
starts at login and restarts if killed). Re-running it replaces a running
agent cleanly.

## Configuration

Configuration is environment variables only -- the daemon reads no config
file and takes no command-line flags. The eight knobs below are delivered
to the daemon through the rendered LaunchAgent plist, and the daemon
re-reads and re-validates every one of them on every cycle, falling back
to the documented default on any malformed value (the per-cycle validation
is the authoritative layer; a broken or hand-edited plist still degrades
safely).

To change a setting:

    cp .env-example .env
    # edit .env: uncomment the lines you want and set your values
    deploy/install.sh

The install script reads .env as data, validates each value, and renders
it into the agent's environment. Editing .env without re-running
deploy/install.sh changes nothing: the plist is the deliverer.

| Knob | Default | Meaning |
|---|---|---|
| DFN_DISABLE | 0 | 1 stops all nudging instantly; re-read every cycle, state preserved. |
| DFN_NOTIFIER | applet | Delivery channel: "applet" (the compiled DayflowNudge.app poster) or "oscript" (bare osascript; weaker Focus attribution). |
| DFN_POLL_SECONDS | 60 | Poll interval in seconds. |
| DFN_STYLE | window | Nudge surface: "window" (the centered self-dismissing dialog) or "notification" (a standard macOS notification). |
| DFN_DAYS | mon,tue,wed,thu,fri | Operating days: the days the daemon may nudge. Comma-separated day names, 3-letter or full, any case. |
| DFN_QUIET_START | 20:00 | Start of the daily quiet window (24-hour clock; 8:00 and 08:00 both accepted). |
| DFN_QUIET_END | 08:00 | End of the daily quiet window; must differ from the start. |
| DFN_DB_PATH | (the default Dayflow store) | Path to the Dayflow store to watch; leave unset for ~/Library/Application Support/Dayflow/chunks.sqlite. |

Malformed values fall back to the default with one warning line in the
daemon log per cycle, so a typo is visible but never breaks the agent.

## Work Focus setup (needed for the notification surface)

The window surface is a real dialog, not a notification, so Work Focus
cannot silence it. The notification surface (DFN_STYLE=notification) IS
filtered by Focus, so if you plan to use it, allowlist the poster once:

    System Settings -> Focus -> Work -> Allowed Notifications -> Apps -> DayflowNudge

Add DayflowNudge there once. Only the applet channel carries this identity;
see the fallback caveat under Troubleshooting.

## Tests

From the repository root:

    python3 -m unittest discover

## Roadmap

Development continues in small steps, and the line of travel is
visible in the history: the centered focus window, the quiet-hours and
operating-day gates, and the eight-knob configuration surface. Next
work stays on that line -- refining when a nudge appears and how it
looks -- under two fixed constraints: the Python standard library
only, and Dayflow's database opened strictly read-only.

## Uninstall

    deploy/uninstall.sh

Stops the agent, removes the plist, and deletes the owned dir including
state.json and logs.

## Troubleshooting

- No notifications at all. Do the Work Focus allowlist step above first.
  Then check the log:
  tail -f "$HOME/Library/Application Support/dayflow-nudge/logs/daemon.err.log".
- Is it running? launchctl print gui/$(id -u)/com.dayflow.nudge shows the
  agent state and its last exit status.
- Nothing fires although I am distracted. The daemon only reacts to today's
  distraction-category selection from Dayflow's Daily tab (the
  "Distraction" word rule applies only when nothing is selected for the
  day). It also stays silent by design when the newest timeline card is
  older than ~25 minutes, during quiet hours (20:00-08:00 by default), on
  days outside the operating week (Monday-Friday by default), after
  DFN_DISABLE=1, and before two consecutive off-task checks have passed.
- Fallback attribution caveat. With DFN_NOTIFIER=oscript the notification is
  posted by osascript itself, so it carries the generic osascript identity
  instead of DayflowNudge, and Work Focus allowlisting is reliable only on
  the default applet channel. Prefer leaving DFN_NOTIFIER unset.
- Another account or machine. The plist ships as a template: install.sh
  renders every path under the home of whoever runs it, so there is
  nothing to hand-edit. If the agent was installed before a path moved,
  re-run deploy/install.sh to re-render it.
