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

The agent starts at install (RunAtLoad + KeepAlive), so there is nothing
else to run. Nudges appear once Dayflow records a card in one of today's
distraction categories and the two-check confirmation passes; see How it
works for the full silence conditions.

## How it works

Every 60 seconds the daemon:

1. Re-reads its configuration from the environment and checks the kill
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
   23:00-09:00; the first nudge is silent, a repeat nudge adds a sound.
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
DayflowNudge.app poster with osacompile, installs
~/Library/LaunchAgents/com.dayflow.nudge.plist, and registers it with
launchd (RunAtLoad + KeepAlive, so it starts at login and restarts if
killed). Re-running it replaces a running agent cleanly.

## Work Focus setup (needed for the notification surface)

The window surface is a real dialog, not a notification, so Work Focus
cannot silence it. The notification surface (DFN_STYLE=notification) IS
filtered by Focus, so if you plan to use it, allowlist the poster once:

    System Settings -> Focus -> Work -> Allowed Notifications -> Apps -> DayflowNudge

Add DayflowNudge there once. Only the applet channel carries this identity;
see the fallback caveat under Troubleshooting.

## Environment knobs

Configuration is environment variables only (no config files, no command
line flags). The plist ships an EnvironmentVariables block with commented
examples: uncomment what you need, then re-run deploy/install.sh so launchd
registers the agent with the new environment.

    DFN_DISABLE=1        Stop all nudging instantly. Re-read every cycle, so
                         it takes effect immediately; state is preserved and
                         disarming resumes correct behavior.
    DFN_NOTIFIER=applet  Delivery channel. "applet" (the default) posts
                         through the compiled DayflowNudge.app poster.
                         "oscript" degrades to bare osascript (attribution
                         caveat below).
    DFN_POLL_SECONDS=60  Poll interval in seconds. Malformed values fall
                         back to 60.
    DFN_STYLE=window     Nudge surface. "window" (the default) shows the
                         centered self-dismissing dialog; "notification"
                         shows a standard macOS notification. Malformed
                         values fall back to the window.

## Tests

From the repository root:

    python3 -m unittest discover

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
  older than ~25 minutes, during quiet hours (23:00-09:00), after
  DFN_DISABLE=1, and before two consecutive off-task checks have passed.
- Fallback attribution caveat. With DFN_NOTIFIER=oscript the notification is
  posted by osascript itself, so it carries the generic osascript identity
  instead of DayflowNudge, and Work Focus allowlisting is reliable only on
  the default applet channel. Prefer leaving DFN_NOTIFIER unset.
- Wrong machine paths. The plist pins absolute paths under
  /Users/<you>/Library/Application Support/dayflow-nudge. On another
  account, adjust WorkingDirectory, StandardOutPath, and StandardErrorPath
  in deploy/com.dayflow.nudge.plist before installing.
