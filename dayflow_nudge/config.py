"""Runtime configuration read from the environment.

Configuration is environment variables only -- no config files, no
command-line flags. Exactly eight DFN_* variables are consulted, on
every cycle: DFN_DISABLE, DFN_NOTIFIER, DFN_POLL_SECONDS, DFN_STYLE,
DFN_DAYS, DFN_QUIET_START, DFN_QUIET_END, DFN_DB_PATH. An absent or
empty value is each knob's documented happy path and never warns (or
every unset knob would complain on every tick); a present but
malformed value falls back to that knob's documented default plus
exactly one warning line, so a broken environment can neither crash a
tick nor go unnoticed.
"""

from __future__ import annotations

import dataclasses
import datetime
import os
from collections.abc import Mapping

from dayflow_nudge.logging import log_event
from dayflow_nudge.quiet_hours import (
    DEFAULT_WEEKDAYS,
    QUIET_END,
    QUIET_START,
)

__all__ = ["Config", "load_config"]

ENV_DISABLE = "DFN_DISABLE"
ENV_NOTIFIER = "DFN_NOTIFIER"
ENV_POLL_SECONDS = "DFN_POLL_SECONDS"
ENV_STYLE = "DFN_STYLE"
ENV_DAYS = "DFN_DAYS"
ENV_QUIET_START = "DFN_QUIET_START"
ENV_QUIET_END = "DFN_QUIET_END"
ENV_DB_PATH = "DFN_DB_PATH"

DISABLED_TOKEN = "1"
NOTIFIER_APPLET = "applet"
NOTIFIER_OSASCRIPT = "osascript"
# The environment token selecting the fallback channel is the short
# spelling; the Config value is the channel name the notifier compares.
NOTIFIER_FALLBACK_TOKEN = "oscript"
POLL_SECONDS = 60
STYLE_WINDOW = "window"
STYLE_NOTIFICATION = "notification"

#: The accepted day spellings, both the three-letter and the full
#: English names, mapped to the datetime.weekday() convention (Monday
#: is 0). The render layer mirrors this table in bash; the two stay in
#: step through their shared tests.
DAY_TOKENS = {
    "mon": 0, "monday": 0,
    "tue": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}


@dataclasses.dataclass(frozen=True)
class Config:
    """One cycle's runtime configuration, re-read from scratch every tick.

    An immutable value: nothing downstream can cache or bend a cycle's
    settings, because the next cycle simply loads a fresh one. The
    calendar fields arrive typed (a frozenset of weekday numbers and
    two times of day) and ``db_path`` stays a verbatim string whose
    empty value means "the default store path" -- existence of that
    path belongs to the store seam, never to the parser.
    """

    disable: bool = False
    notifier: str = NOTIFIER_APPLET
    poll_seconds: int = POLL_SECONDS
    style: str = STYLE_WINDOW
    weekdays: frozenset = DEFAULT_WEEKDAYS
    quiet_start: datetime.time = QUIET_START
    quiet_end: datetime.time = QUIET_END
    db_path: str = ""


def load_config(environ: Mapping[str, str] | None = None) -> Config:
    """Read the eight DFN_* variables into a typed Config.

    The kill switch arms only on the exact token "1", so a malformed
    value can only ever leave nudging on. The notifier variable accepts
    the applet channel or the fallback token; anything else means the
    default channel. The poll must parse as a positive integer or the
    default poll wins, so the loop can never spin on a zero-second
    tick. The style selects the nudge surface: the centered
    self-dismissing window (the default) or a standard notification;
    anything malformed means the default window. The weekdays variable
    is comma-separated day names, case-insensitive, with empty
    segments dropped and duplicates collapsed; one unknown token
    invalidates the whole value to the default week. The quiet bounds
    are H:MM or HH:MM on a 24-hour clock, each falling back alone when
    malformed and both falling back together when they parse equal --
    an always-quiet or never-quiet reading of equal bounds is exactly
    the ambiguity the default resolves. The store path is kept
    verbatim when it is a single non-empty line.
    """
    source = os.environ if environ is None else environ
    quiet_start, quiet_end = _quiet_bounds(source)
    return Config(
        disable=source.get(ENV_DISABLE) == DISABLED_TOKEN,
        notifier=_notifier_channel(source.get(ENV_NOTIFIER)),
        poll_seconds=_poll_seconds(source.get(ENV_POLL_SECONDS)),
        style=_style(source.get(ENV_STYLE)),
        weekdays=_weekdays(source.get(ENV_DAYS)),
        quiet_start=quiet_start,
        quiet_end=quiet_end,
        db_path=_db_path(source.get(ENV_DB_PATH)),
    )


def _default_used(knob: str, reason: str) -> None:
    """One line naming the knob that fell back, and why; nothing more."""
    log_event("config_default", level="warning", knob=knob, reason=reason)


def _style(raw) -> str:
    token = (raw or "").strip().casefold()
    if token == STYLE_NOTIFICATION:
        return STYLE_NOTIFICATION
    return STYLE_WINDOW


def _notifier_channel(raw) -> str:
    token = (raw or "").strip().casefold()
    if token == NOTIFIER_FALLBACK_TOKEN:
        return NOTIFIER_OSASCRIPT
    return NOTIFIER_APPLET


def _poll_seconds(raw) -> int:
    try:
        seconds = int(str(raw).strip())
    except (TypeError, ValueError):
        return POLL_SECONDS
    return seconds if seconds > 0 else POLL_SECONDS


def _weekdays(raw) -> frozenset:
    """The operating week from comma-separated day-name tokens.

    An absent or blank value is the default week, silently. Any present
    value must yield a non-empty set of known days: one unrecognized
    token invalidates the whole value -- a partially accepted week
    would run a silently wrong schedule -- and a value of only commas
    names no day at all.
    """
    text = (raw or "").strip()
    if not text:
        return DEFAULT_WEEKDAYS
    days = set()
    for token in text.split(","):
        token = token.strip().casefold()
        if not token:
            continue
        day = DAY_TOKENS.get(token)
        if day is None:
            _default_used(ENV_DAYS, "unknown day {!r}".format(token))
            return DEFAULT_WEEKDAYS
        days.add(day)
    if not days:
        _default_used(ENV_DAYS, "no day named")
        return DEFAULT_WEEKDAYS
    return frozenset(days)


def _quiet_bounds(source: Mapping[str, str]):
    """The quiet window as (start, end), defaults filling any gap.

    Each bound stands or falls alone; the one pair rule is equality --
    a start equal to its end is ambiguous between always-quiet and
    never-quiet, so both bounds return to their documented defaults
    under a single line naming the pair.
    """
    start = _clock_value(source.get(ENV_QUIET_START), ENV_QUIET_START)
    end = _clock_value(source.get(ENV_QUIET_END), ENV_QUIET_END)
    if start is not None and start == end:
        _default_used(
            "{}=={}".format(ENV_QUIET_START, ENV_QUIET_END),
            "equal bounds are ambiguous")
        return QUIET_START, QUIET_END
    return (QUIET_START if start is None else start,
            QUIET_END if end is None else end)


def _clock_value(raw, knob: str):
    """One quiet bound as a time of day, or None for its default.

    Accepts H:MM and HH:MM on a 24-hour clock; the two-digit minute is
    part of the contract so the installer's render, which matches the
    same shape, can never disagree with this parser about a spelling.
    """
    text = (raw or "").strip()
    if not text:
        return None
    if not _shaped_like_clock(text):
        _default_used(knob, "expected H:MM or HH:MM")
        return None
    try:
        return datetime.datetime.strptime(text, "%H:%M").time()
    except ValueError:
        _default_used(knob, "outside 00:00-23:59")
        return None


def _shaped_like_clock(text: str) -> bool:
    hour, separator, minute = text.partition(":")
    return (
        separator == ":"
        and hour.isdigit()
        and 1 <= len(hour) <= 2
        and minute.isdigit()
        and len(minute) == 2
    )


def _db_path(raw) -> str:
    """The store location verbatim, or "" for the default location.

    The empty value is the silent sentinel for "wherever the store
    seam looks by default"; only a value that cannot be one line at
    all -- a newline inside it -- is refused, with the one fallback
    line. Whether the path exists is never a parse question.
    """
    text = raw or ""
    if not text.strip():
        return ""
    if "\n" in text or "\r" in text:
        _default_used(ENV_DB_PATH, "the path must be a single line")
        return ""
    return text.strip()
