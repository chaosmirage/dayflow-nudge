"""The quiet-hours gate: nothing notifies between 23:00 and 09:00.

The window crosses midnight, so membership is a disjunction rather than a
range: the evening start is inclusive (23:00 itself is quiet) and the
morning end is exclusive (09:00 itself is loud). Suppression is total,
and nothing suppressed here is ever held back for the morning -- the
episode keeps counting until the window opens, spending nothing.
"""

import datetime

QUIET_START = datetime.time(23, 0)
QUIET_END = datetime.time(9, 0)


def is_quiet(moment):
    """Whether ``moment`` falls inside the quiet window.

    Accepts the time of day directly or a full clock reading from the
    cycle's injectable clock; both answer from the local wall clock,
    which is the only clock the owner's day follows.
    """
    if isinstance(moment, datetime.datetime):
        moment = moment.time()
    if not isinstance(moment, datetime.time):
        raise TypeError(
            "the quiet-hours check needs a time or datetime, got {!r}".format(
                type(moment).__name__
            )
        )
    return moment >= QUIET_START or moment < QUIET_END
