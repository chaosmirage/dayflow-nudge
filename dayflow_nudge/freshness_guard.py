"""Pure freshness verdict for the newest timeline card.

The module answers one question: is the observed timeline current enough to
act on? It performs no I/O and no logging; the caller decides what silence
means.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum

FRESHNESS_THRESHOLD_MINUTES = 25


class Freshness(Enum):
    """Verdict on how current the observed timeline is."""

    FRESH = "FRESH"
    UNKNOWN = "UNKNOWN"


def evaluate_freshness(
    newest_end_ts: datetime | None,
    now: datetime,
    threshold_minutes: float = FRESHNESS_THRESHOLD_MINUTES,
) -> Freshness:
    """Judge whether the newest card's end timestamp is recent enough.

    Every uncertain case resolves to UNKNOWN so the caller stays silent:
    a missing card (empty window) counts as infinitely old, and the exact
    boundary age is treated as already stale. Only a card that ended
    strictly inside the threshold is FRESH; a timestamp slightly in the
    future is accepted as FRESH because an in-progress card legitimately
    ends after the current moment.
    """
    if newest_end_ts is None:
        return Freshness.UNKNOWN

    age = now - newest_end_ts
    if age >= timedelta(minutes=threshold_minutes):
        return Freshness.UNKNOWN

    return Freshness.FRESH
