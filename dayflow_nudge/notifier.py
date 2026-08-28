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
CHANNEL_WINDOW = "window"
CHANNEL_OSASCRIPT = "osascript"
SOUND_FLAG = "sound"
NOTIFICATION_SOUND_NAME = "Glass"
STYLE_WINDOW = "window"
STYLE_NOTIFICATION = "notification"
WINDOW_GIVE_UP_SECONDS = 30
WINDOW_BUTTON_LABEL = "Back to work"

DEFAULT_OWNED_DIR = os.path.expanduser(
    "~/Library/Application Support/dayflow-nudge")
DEFAULT_APPLET_PATH = os.path.join(
    DEFAULT_OWNED_DIR, "DayflowNudge.app", "Contents", "MacOS", "applet")
DEFAULT_WINDOW_PATH = os.path.join(
    DEFAULT_OWNED_DIR, "DayflowNudgeWindow.app", "Contents", "MacOS",
    "DayflowNudgeWindow")

_OSASCRIPT_COMMAND = "osascript"
_TITLE_ENV = "DFN_TITLE"
_BODY_ENV = "DFN_BODY"
_SOUND_ENV = "DFN_SOUND"
_STYLE_ENV = "DFN_STYLE"
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
            style: str = STYLE_WINDOW,
            runner=subprocess.run,
            applet_path: str = DEFAULT_APPLET_PATH,
            window_path: str = DEFAULT_WINDOW_PATH,
            timeout: int = DELIVERY_TIMEOUT_SECONDS) -> DeliveryResult:
    """Post one nudge for ``command`` and report whether it was sent.

    Exactly one delivery attempt is made: a failure comes back as FAILED,
    is never retried here, and never raises into the calling cycle. Every
    outcome leaves one log line carrying the channel and the cause. The
    style selects the surface: the styled centered window (the default) or
    a standard notification. Each surface prefers its own attributable
    poster binary and degrades step by step down to bare osascript.
    """
    title = sanitize_text(command.title, TITLE_CAP)
    body = sanitize_text(command.body, BODY_CAP)
    channel, argv, env = _poster_command(
        preferred_channel, style, applet_path, window_path,
        title, body, command.sound)
    sent, cause = _run_once(argv, timeout, runner, env)
    _logger.info(
        "event=delivery channel=%s ok=%s detail=%s", channel, sent, cause)
    return DeliveryResult.SENT if sent else DeliveryResult.FAILED


def _poster_command(preferred_channel, style, applet_path, window_path,
                    title, body, sound):
    """Pick the poster for the requested surface and build its command.

    Window surface: the styled SwiftUI poster when its binary exists, then
    the applet's dialog (DFN_STYLE=window), then the osascript dialog.
    Notification surface: the applet (DFN_STYLE=notification), then the
    osascript notification. Poster binaries take no arguments -- the
    payload rides the environment; only osascript composes source text."""
    applet_available = preferred_channel == CHANNEL_APPLET and os.path.isfile(
        applet_path)

    if style == STYLE_WINDOW:
        if applet_available and os.path.isfile(window_path):
            return (CHANNEL_WINDOW, [window_path],
                    _build_env(title, body, sound, style))
        if applet_available:
            return (CHANNEL_APPLET, [applet_path],
                    _build_env(title, body, sound, style))
        return (CHANNEL_OSASCRIPT,
                [_OSASCRIPT_COMMAND, "-e",
                 _osascript_source(title, body, sound, style)], None)

    if applet_available:
        return (CHANNEL_APPLET, [applet_path],
                _build_env(title, body, sound, style))
    return (CHANNEL_OSASCRIPT,
            [_OSASCRIPT_COMMAND, "-e",
             _osascript_source(title, body, sound, style)], None)


def _build_env(title, body, sound, style):
    """Poster binaries carry the payload as environment variables:
    the inherited environment plus the four DFN_* overrides."""
    env = dict(os.environ)
    env[_TITLE_ENV] = title
    env[_BODY_ENV] = body
    env[_SOUND_ENV] = SOUND_FLAG if sound else ""
    env[_STYLE_ENV] = style
    return env


def _osascript_source(title, body, sound, style):
    """Compose the fallback source exclusively from escaped literals; the
    sound name, button label, and give-up window are fixed constants,
    never store data."""
    if style == STYLE_NOTIFICATION:
        source = (
            "display notification "
            + applescript_literal(body)
            + " with title "
            + applescript_literal(title)
        )
        if sound:
            source += ' sound name "' + NOTIFICATION_SOUND_NAME + '"'
        return source
    source = (
        "display dialog "
        + applescript_literal(body)
        + " with title "
        + applescript_literal(title)
        + ' buttons {"' + WINDOW_BUTTON_LABEL + '"} default button 1'
        + " giving up after " + str(WINDOW_GIVE_UP_SECONDS)
        + " with icon caution"
    )
    if sound:
        source = "beep 2" + "\n" + source
    return source


def _run_once(argv, timeout, runner, env=None):
    """Run one delivery attempt and map it to (sent, cause); expected
    failures are reported, never raised."""
    try:
        completed = runner(argv, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return False, "timeout after {}s".format(timeout)
    except OSError as error:
        return False, "cannot launch poster: {}".format(error)
    if completed.returncode == 0:
        return True, "exit 0"
    return False, "exit {}".format(completed.returncode)
