# deploy

The LaunchAgent artifact set: the property list launchd loads and the
two shell scripts that install and remove it. Nothing here is Python;
tests/test_deploy.py and the repository layout contract pin the set.

## Purpose

Define exactly how the daemon reaches a user's machine: one owned
directory, a compiled notification poster, and a per-user agent that
starts at login and restarts if it dies.

## Commands

Install (build the applet, copy the package, register the agent):

```sh
./deploy/install.sh
```

Remove:

```sh
./deploy/uninstall.sh
```

Inspect the loaded agent:

```sh
launchctl print gui/$(id -u)/com.dayflow.nudge
```

## Key pieces

- com.dayflow.nudge.plist -- Label com.dayflow.nudge; ProgramArguments
  runs /usr/bin/python3 -m dayflow_nudge; RunAtLoad and KeepAlive are
  both on; WorkingDirectory and both log paths point into the owned
  directory ~/Library/Application Support/dayflow-nudge/ (logs/
  daemon.out.log and logs/daemon.err.log).
- install.sh -- creates the owned directory and its logs/, copies
  dayflow_nudge/ and scripts/ into it with rsync --delete, runs
  scripts/build_applet.sh, installs the plist into
  ~/Library/LaunchAgents, then boots the old agent out before
  bootstrapping so a re-run replaces a loaded agent cleanly.
- uninstall.sh -- boots the agent out and removes the plist and the
  owned directory copy.

## How to extend safely

- Change agent behavior through documented launchd keys; keep RunAtLoad
  and KeepAlive so start-at-login and restart-after-death hold.
- Keep install.sh idempotent: boot out before bootstrap, rsync with
  --delete, and no failure on a fresh machine.
- Extend test_deploy.py with any plist or script change; a deployment
  change without a test is unverified.
- Keep the plist paths inside the owned directory; the layout contract
  parses the plist, and launchd refuses a malformed one.

## Conventions

- Treat the owned directory as the single home: the installed package,
  the applet, state.json, and logs/ all live under it.
- Write only inside the owned directory and ~/Library/LaunchAgents;
  derive every path from those two roots.
- Derive the repository root from BASH_SOURCE; do not depend on the
  caller's working directory.
- Re-run install.sh after editing the plist so launchd registers the
  new definition.

## Constraints

- NEVER launch the daemon with anything but /usr/bin/python3; a bare OS
  install must run the agent unattended.
- NEVER commit a compiled app bundle; compile it at install time with
  scripts/build_applet.sh instead.
