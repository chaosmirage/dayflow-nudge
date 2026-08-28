"""Delivery of focus nudges as macOS notifications.

Everything between a NudgeCommand and a posted notification lives here: the
single text boundary both channels pass through, the choice between the
attributable applet channel and the osascript fallback, and the typed
outcome of exactly one delivery attempt.
"""

import logging
import os
import subprocess
import unicodedata

from dayflow_nudge.models import DeliveryResult, NudgeCommand

TITLE_CAP = 80
BODY_CAP = 200
DELIVERY_TIMEOUT_SECONDS = 10
CHANNEL_APPLET = "applet"
CHANNEL_OSASCRIPT = "osascript"
SOUND_FLAG = "sound"
NOTIFICATION_SOUND_NAME = "Glass"

DEFAULT_OWNED_DIR = os.path.expanduser(
    "~/Library/Application Support/dayflow-nudge")
DEFAULT_APPLET_PATH = os.path.join(
    DEFAULT_OWNED_DIR, "DayflowNudge.app", "Contents", "MacOS", "applet")

_OSASCRIPT_COMMAND = "osascript"
_ARG_END_MARKER = "--"
_CONTROL_CATEGORY = "Cc"

_logger = logging.getLogger(__name__)


def sanitize_text(text, cap):
    """Make a stored value safe inside a notification command: control
    characters (newlines included) are removed and the length is capped, so
    no raw store value can alter the command's form."""
    visible = "".join(
        char for char in text
        if unicodedata.category(char) != _CONTROL_CATEGORY
    )
    return visible[:cap]


def applescript_literal(text):
    """Render text as a double-quoted AppleScript string literal. Backslashes
    are escaped before quotes so every escape survives exactly as written."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + escaped + '"'


def deliver(command: NudgeCommand, *,
            preferred_channel: str = CHANNEL_APPLET,
            runner=subprocess.run,
            applet_path: str = DEFAULT_APPLET_PATH,
            timeout: int = DELIVERY_TIMEOUT_SECONDS) -> DeliveryResult:
    """Post one notification for ``command`` and report whether it was sent.

    Exactly one delivery attempt is made: a failure comes back as FAILED,
    is never retried here, and never raises into the calling cycle. Every
    outcome leaves one log line carrying the channel and the cause.
    """
    title = sanitize_text(command.title, TITLE_CAP)
    body = sanitize_text(command.body, BODY_CAP)
    channel = _select_channel(preferred_channel, applet_path)
    argv = _build_argv(channel, applet_path, title, body, command.sound)
    sent, cause = _run_once(argv, timeout, runner)
    _logger.info(
        "event=delivery channel=%s ok=%s detail=%s", channel, sent, cause)
    return DeliveryResult.SENT if sent else DeliveryResult.FAILED


def _select_channel(preferred_channel, applet_path):
    """The attributable applet posts whenever it is preferred and present;
    any other preference, or a missing binary, degrades to osascript."""
    if preferred_channel == CHANNEL_APPLET and os.path.isfile(applet_path):
        return CHANNEL_APPLET
    return CHANNEL_OSASCRIPT


def _build_argv(channel, applet_path, title, body, sound):
    """Assemble the delivery command as an argv list, never a shell string."""
    if channel == CHANNEL_APPLET:
        argv = [applet_path, _ARG_END_MARKER, title, body]
        if sound:
            argv.append(SOUND_FLAG)
        return argv
    return [_OSASCRIPT_COMMAND, "-e", _osascript_source(title, body, sound)]


def _osascript_source(title, body, sound):
    """Compose the fallback source exclusively from escaped literals; the
    sound name is a fixed constant, never store data."""
    source = (
        "display notification "
        + applescript_literal(body)
        + " with title "
        + applescript_literal(title)
    )
    if sound:
        source += ' sound name "' + NOTIFICATION_SOUND_NAME + '"'
    return source


def _run_once(argv, timeout, runner):
    """Run one delivery attempt and map it to (sent, cause); expected
    failures are reported, never raised."""
    try:
        completed = runner(argv, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "timeout after {}s".format(timeout)
    except OSError as error:
        return False, "cannot launch poster: {}".format(error)
    if completed.returncode == 0:
        return True, "exit 0"
    return False, "exit {}".format(completed.returncode)
