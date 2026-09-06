#!/bin/bash
#
# Install dayflow-nudge as a per-user LaunchAgent.
#
# Creates the owned dir (~/Library/Application Support/dayflow-nudge),
# copies the package and the applet build scripts into it, builds the
# DayflowNudge.app notification poster, renders the LaunchAgent plist
# from the template plus the user's .env, and registers it with launchd.
# Safe to re-run: a running agent is replaced cleanly.
#
# Test seam:  deploy/install.sh render <template> <env_file> <output>
# performs only the plist render and exits -- no owned dir, no launchd.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OWNED_DIR="$HOME/Library/Application Support/dayflow-nudge"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_NAME="com.dayflow.nudge.plist"
AGENT_ID="com.dayflow.nudge"
SESSION="gui/$(id -u)"

# The eight published knobs and their documented defaults -- the same
# vocabulary .env-example and README name. The daemon re-validates every
# value every cycle; these defaults are what the render writes whenever
# the .env names nothing or names something it cannot accept.
DEFAULT_DFN_DISABLE="0"
DEFAULT_DFN_NOTIFIER="applet"
DEFAULT_DFN_POLL_SECONDS="60"
DEFAULT_DFN_STYLE="window"
DEFAULT_DFN_DAYS="mon,tue,wed,thu,fri"
DEFAULT_DFN_QUIET_START="20:00"
DEFAULT_DFN_QUIET_END="08:00"
DEFAULT_DFN_DB_PATH="$HOME/Library/Application Support/Dayflow/chunks.sqlite"

# --- the render ------------------------------------------------------------

trim() {
    # Drop leading and trailing whitespace; interior characters stay.
    local text="$1"
    text="${text#"${text%%[![:space:]]*}"}"
    text="${text%"${text##*[![:space:]]}"}"
    printf '%s' "$text"
}

lower() {
    printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

strip_quotes() {
    # Remove one pair of optional matching quotes around the value.
    local text="$1"
    if [ "${#text}" -ge 2 ]; then
        case "$text" in
            \"*\") text="${text#\"}"; text="${text%\"}" ;;
            \'*\') text="${text#\'}"; text="${text%\'}" ;;
        esac
    fi
    printf '%s' "$text"
}

xml_escape() {
    # Escape the three characters XML reserves, ampersand first so an
    # earlier escape is never escaped again.
    local text="$1"
    text="${text//&/&amp;}"
    text="${text//</&lt;}"
    text="${text//>/&gt;}"
    printf '%s' "$text"
}

valid_clock() {
    # H:MM or HH:MM within 00:00-23:59 -- the same spellings the
    # daemon's own parser accepts, on both sides of the hour.
    case "$1" in
        [0-9]:[0-5][0-9]|[0-1][0-9]:[0-5][0-9]|2[0-3]:[0-5][0-9]) return 0 ;;
        *) return 1 ;;
    esac
}

valid_days() {
    # Every comma token must name a weekday and at least one day must
    # survive; one unknown token invalidates the whole value, exactly as
    # the daemon's parser rules.
    local token found=0
    local tokens
    IFS=',' read -r -a tokens <<< "$1"
    for token in "${tokens[@]}"; do
        token="$(lower "$(trim "$token")")"
        case "$token" in
            "") ;;
            mon|monday|tue|tuesday|wed|wednesday|thu|thursday|fri|friday|sat|saturday|sun|sunday)
                found=1 ;;
            *) return 1 ;;
        esac
    done
    [ "$found" -eq 1 ]
}

positive_integer() {
    # Digits only, and at least one of them nonzero.
    case "$1" in
        ''|*[!0-9]*|0) return 1 ;;
        *) return 0 ;;
    esac
}

render_plist() {
    # Render the template with the owned dir and the eight knob values,
    # reading the .env strictly as data: a line loop, a known-key
    # allowlist, per-knob validation, XML escaping, and one transcript
    # line per decision. Nothing here hands the file to an interpreter.
    local template="$1" env_file="$2" output="$3"
    local line key value
    local quiet_start="" quiet_end=""
    local v_disable="$DEFAULT_DFN_DISABLE" v_notifier="$DEFAULT_DFN_NOTIFIER"
    local v_poll="$DEFAULT_DFN_POLL_SECONDS" v_style="$DEFAULT_DFN_STYLE"
    local v_days="$DEFAULT_DFN_DAYS"
    local v_quiet_start v_quiet_end
    local v_db_path="$DEFAULT_DFN_DB_PATH"
    local rendered

    if [ -f "$env_file" ] && [ -r "$env_file" ]; then
        while IFS= read -r line || [ -n "$line" ]; do
            line="${line%$'\r'}"
            line="$(trim "$line")"
            case "$line" in
                ''|'#'*) continue ;;
            esac
            key="${line%%=*}"
            if [ "$key" = "$line" ]; then
                echo "render: ignoring a line with no assignment: $line"
                continue
            fi
            value="$(strip_quotes "$(trim "${line#*=}")")"
            case "$key" in
                DFN_DISABLE)
                    case "$value" in
                        '') ;;
                        0|1)
                            v_disable="$value"
                            echo "render: DFN_DISABLE=$value" ;;
                        *)
                            v_disable="$DEFAULT_DFN_DISABLE"
                            echo "render: DFN_DISABLE: expected 0 or 1; keeping $v_disable" ;;
                    esac ;;
                DFN_NOTIFIER)
                    case "$(lower "$value")" in
                        '') ;;
                        applet)
                            v_notifier="applet"
                            echo "render: DFN_NOTIFIER=applet" ;;
                        oscript)
                            v_notifier="oscript"
                            echo "render: DFN_NOTIFIER=oscript" ;;
                        *)
                            echo "render: DFN_NOTIFIER: expected applet or oscript; keeping $v_notifier" ;;
                    esac ;;
                DFN_POLL_SECONDS)
                    if [ -n "$value" ]; then
                        if positive_integer "$value"; then
                            v_poll="$value"
                            echo "render: DFN_POLL_SECONDS=$value"
                        else
                            v_poll="$DEFAULT_DFN_POLL_SECONDS"
                            echo "render: DFN_POLL_SECONDS: expected a positive integer; keeping $v_poll"
                        fi
                    fi ;;
                DFN_STYLE)
                    case "$(lower "$value")" in
                        '') ;;
                        window)
                            v_style="window"
                            echo "render: DFN_STYLE=window" ;;
                        notification)
                            v_style="notification"
                            echo "render: DFN_STYLE=notification" ;;
                        *)
                            echo "render: DFN_STYLE: expected window or notification; keeping $v_style" ;;
                    esac ;;
                DFN_DAYS)
                    if [ -n "$value" ]; then
                        if valid_days "$value"; then
                            v_days="$value"
                            echo "render: DFN_DAYS=$value"
                        else
                            v_days="$DEFAULT_DFN_DAYS"
                            echo "render: DFN_DAYS: expected comma-separated day names (mon..sun); keeping $v_days"
                        fi
                    fi ;;
                DFN_QUIET_START)
                    if [ -n "$value" ]; then
                        if valid_clock "$value"; then
                            quiet_start="$value"
                            echo "render: DFN_QUIET_START=$value"
                        else
                            quiet_start=""
                            echo "render: DFN_QUIET_START: expected H:MM or HH:MM (00:00-23:59); keeping $DEFAULT_DFN_QUIET_START"
                        fi
                    fi ;;
                DFN_QUIET_END)
                    if [ -n "$value" ]; then
                        if valid_clock "$value"; then
                            quiet_end="$value"
                            echo "render: DFN_QUIET_END=$value"
                        else
                            quiet_end=""
                            echo "render: DFN_QUIET_END: expected H:MM or HH:MM (00:00-23:59); keeping $DEFAULT_DFN_QUIET_END"
                        fi
                    fi ;;
                DFN_DB_PATH)
                    case "$value" in
                        '') ;;
                        *)
                            # a leading ~/ is the one abbreviation the
                            # render expands, by prefix replacement only
                            v_db_path="${value/#\~\//$HOME/}"
                            echo "render: DFN_DB_PATH=$v_db_path" ;;
                    esac ;;
                *)
                    echo "render: ignoring unknown key $key" ;;
            esac
        done < "$env_file"
    else
        echo "render: cannot read $env_file; rendering the documented defaults"
    fi

    # The one pair rule: equal bounds are ambiguous between always-quiet
    # and never-quiet, so both return to their defaults on a single line.
    if [ -n "$quiet_start" ] && [ "$quiet_start" = "$quiet_end" ]; then
        quiet_start=""
        quiet_end=""
        echo "render: DFN_QUIET_START and DFN_QUIET_END are equal; keeping $DEFAULT_DFN_QUIET_START and $DEFAULT_DFN_QUIET_END"
    fi
    v_quiet_start="${quiet_start:-$DEFAULT_DFN_QUIET_START}"
    v_quiet_end="${quiet_end:-$DEFAULT_DFN_QUIET_END}"

    rendered="$(cat "$template")"
    # Unquoted replacements on purpose: inside a parameter expansion the
    # quotes themselves would land in the text, while the substituted
    # values are single words here no matter what they hold.
    rendered="${rendered//@@OWNED_DIR@@/$OWNED_DIR}"
    rendered="${rendered//@@DFN_DISABLE@@/$(xml_escape "$v_disable")}"
    rendered="${rendered//@@DFN_NOTIFIER@@/$(xml_escape "$v_notifier")}"
    rendered="${rendered//@@DFN_POLL_SECONDS@@/$(xml_escape "$v_poll")}"
    rendered="${rendered//@@DFN_STYLE@@/$(xml_escape "$v_style")}"
    rendered="${rendered//@@DFN_DAYS@@/$(xml_escape "$v_days")}"
    rendered="${rendered//@@DFN_QUIET_START@@/$(xml_escape "$v_quiet_start")}"
    rendered="${rendered//@@DFN_QUIET_END@@/$(xml_escape "$v_quiet_end")}"
    rendered="${rendered//@@DFN_DB_PATH@@/$(xml_escape "$v_db_path")}"
    printf '%s\n' "$rendered" > "$output"
    echo "render: wrote $output"
}

# --- the render subcommand (test seam; nothing else runs here) --------------

if [ "${1:-}" = "render" ]; then
    if [ "$#" -ne 4 ]; then
        echo "usage: deploy/install.sh render <template> <env_file> <output>" >&2
        exit 2
    fi
    render_plist "$2" "$3" "$4"
    exit 0
fi

# --- the install ------------------------------------------------------------

echo "==> Preparing $OWNED_DIR"
mkdir -p "$OWNED_DIR/logs" "$OWNED_DIR/dayflow_nudge" "$OWNED_DIR/scripts" \
    "$LAUNCH_AGENTS_DIR"

echo "==> Copying the package and scripts into the owned dir"
rsync -a --delete "$REPO_ROOT/dayflow_nudge/" "$OWNED_DIR/dayflow_nudge/"
rsync -a --delete "$REPO_ROOT/scripts/" "$OWNED_DIR/scripts/"

echo "==> Building the DayflowNudge.app notification poster"
(cd "$REPO_ROOT" && ./scripts/build_applet.sh)

echo "==> Rendering the LaunchAgent plist from your .env"
rendered_plist="$(mktemp -t dfn-plist)"
render_plist "$REPO_ROOT/deploy/$PLIST_NAME" "$REPO_ROOT/.env" "$rendered_plist"
mv -f "$rendered_plist" "$LAUNCH_AGENTS_DIR/$PLIST_NAME"

echo "==> Registering the agent with launchd"
# Bootout first so a re-run replaces an already-loaded agent; a fresh
# machine has none, so a missing service is not an error here.
launchctl bootout "$SESSION/$AGENT_ID" 2>/dev/null || true
launchctl bootstrap "$SESSION" "$LAUNCH_AGENTS_DIR/$PLIST_NAME"

cat <<'EOF'

Installed. One step is left, and it is mandatory:

  System Settings -> Focus -> Work -> Allowed Notifications -> Apps -> DayflowNudge

Without that allowlist entry Work Focus swallows every nudge this daemon
sends. To change a setting later: edit .env (see .env-example) and
re-run deploy/install.sh. Logs land in:
  ~/Library/Application Support/dayflow-nudge/logs/daemon.err.log
EOF
