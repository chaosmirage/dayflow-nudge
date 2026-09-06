"""The calendar suppression gates: quiet hours and operating weekdays.

Two clock facts silence the daemon before any nudge exists. The quiet
window answers membership by the time of day; the weekday gate answers
membership in the operating set. The default quiet window runs 20:00 to
08:00 and crosses midnight, so membership is a disjunction rather than
a range: the evening start is inclusive (20:00 itself is quiet) and the
morning end is exclusive (08:00 itself is loud). Explicit bounds pick
their own reading -- a crossing window (start after end) answers by
disjunction, an intraday window (start before end) answers as a range
-- both with the same inclusivity. Suppression is total, and nothing
suppressed here is ever held back for the morning: the episode keeps
counting until the window opens, spending nothing. An excluded weekday
carries the same shape one floor wider: a non-operating day changes
nothing at all.

The module's constants are defaults, not laws: they anchor the
documented fallback of every calendar knob and assemble the module's
default OperatingCalendar, and the daemon derives a cycle's calendar
from its configuration instead.
"""

import dataclasses
import datetime

QUIET_START = datetime.time(20, 0)
QUIET_END = datetime.time(8, 0)
DEFAULT_WEEKDAYS = frozenset({0, 1, 2, 3, 4})


@dataclasses.dataclass(frozen=True)
class OperatingCalendar:
    """The calendar facts one cycle suppresses by, as one frozen value.

    ``weekdays`` is the set of datetime.weekday() integers the daemon
    operates on (Monday = 0); ``quiet_start`` and ``quiet_end`` bound
    the quiet window with the start inclusive and the end exclusive.
    Both parse layers reject equal bounds; a hand-built bundle carrying
    them still gets a deterministic answer from ``is_quiet`` -- the
    empty, never-quiet reading -- never an always-quiet one.
    """

    weekdays: frozenset = DEFAULT_WEEKDAYS
    quiet_start: datetime.time = QUIET_START
    quiet_end: datetime.time = QUIET_END


DEFAULT_CALENDAR = OperatingCalendar(
    weekdays=DEFAULT_WEEKDAYS, quiet_start=QUIET_START, quiet_end=QUIET_END)


def is_quiet(moment, start=QUIET_START, end=QUIET_END):
    """Whether ``moment`` falls inside the quiet window.

    Accepts the time of day directly or a full clock reading from the
    cycle's injectable clock; both answer from the local wall clock,
    which is the only clock the owner's day follows. Bounds that cross
    midnight (start after end) answer by disjunction -- the evening
    side or the morning side -- while intraday bounds answer as a
    range; both keep the start inclusive and the end exclusive.
    """
    if isinstance(moment, datetime.datetime):
        moment = moment.time()
    if not isinstance(moment, datetime.time):
        raise TypeError(
            "the quiet-hours check needs a time or datetime, got {!r}".format(
                type(moment).__name__
            )
        )
    if start > end:
        return moment >= start or moment < end
    return start <= moment < end


def is_off_schedule(moment, active_weekdays=DEFAULT_WEEKDAYS):
    """Whether ``moment`` falls on a day outside the operating set.

    Takes the full clock reading the cycle already holds -- the day of
    the week only exists on a date -- and answers a plain membership
    fact: nothing is spent, nothing mutated, the caller decides what
    silence means.
    """
    if not isinstance(moment, datetime.datetime):
        raise TypeError(
            "the weekday check needs a datetime, got {!r}".format(
                type(moment).__name__
            )
        )
    return moment.weekday() not in active_weekdays
