"""Typed values handed between the daemon's stages.

Every value that crosses a stage boundary lives in this one module so no
stage needs to import another stage just to share a type. Each value is a
small immutable contract: constructing it is the whole behavior, and the
producer owns the invariant (for example, the day's distraction-category
selection arrives already normalized, once, at its producer).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class DetectionState(str, Enum):
    """The three-way outcome of one detection check.

    UNKNOWN is its own answer, not a fallback: a doubtful window must
    report UNKNOWN so the policy resets its streak instead of guessing.
    """

    ON_TASK = "ON_TASK"
    OFF_TASK = "OFF_TASK"
    UNKNOWN = "UNKNOWN"


class DeliveryResult(str, Enum):
    """Outcome of one notification delivery attempt."""

    SENT = "SENT"
    FAILED = "FAILED"


@dataclass(frozen=True)
class CardSnapshot:
    """One timeline card as read from the store.

    Timestamps and the metadata blob are nullable in the store; a missing
    value stays None rather than being invented. A card with no category
    carries the empty string, which no distraction matcher treats as a
    hit.
    """

    title: str = ""
    summary: str = ""
    category: str = ""
    start_ts: datetime | None = None
    end_ts: datetime | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class GoalSnapshot:
    """Today's day-goal row.

    Unset minute columns stay None; a day with no row is represented by
    the producer omitting the goal entirely, not by a synthetic row.
    ``distraction_categories`` carries the day's selected distraction
    categories, normalized once by the producer; the empty set is itself
    a signal -- nothing selected today -- and the minute columns carry no
    match meaning at all.
    """

    day: str = ""
    focus_target_minutes: int | None = None
    distraction_limit_minutes: int | None = None
    is_skipped: bool = False
    distraction_categories: frozenset[str] = frozenset()


def normalize_category(name) -> str | None:
    """The one shared rule for reading a category name.

    A category name is compared stripped and case-folded, so letter case
    and padding never change a match, whether the name arrives from the
    day's selection or from a timeline card. A value that is not text --
    a missing category -- is not a name at all and yields None; the
    empty string is a real answer, and what an empty name means is each
    caller's decision. Both the goal producer and the distraction
    detector read category names through this one definition, so no two
    spellings of the rule can drift apart.
    """
    if not isinstance(name, str):
        return None
    return name.strip().casefold()


@dataclass(frozen=True)
class Observation:
    """The merged input one detection check sees.

    The card window and today's goal travel together, stamped with the
    moment the window was assembled so a detector can age its evidence
    without needing a clock of its own.
    """

    observed_at: datetime | None = None
    cards: tuple[CardSnapshot, ...] = ()
    goal: GoalSnapshot | None = None


@dataclass(frozen=True)
class Verdict:
    """The result of one detection check.

    ``state`` is the three-way outcome the policy reasons about;
    ``off_task`` is the boolean shorthand for it; ``evidence`` carries
    the offending card's title (empty when there is nothing to show);
    ``latency`` is the seconds between that evidence and the observation
    it was drawn from.
    """

    state: DetectionState
    off_task: bool
    evidence: str = ""
    latency: float = 0.0


@dataclass(frozen=True)
class NudgeCommand:
    """One notification to deliver.

    The offending card's title is the headline and the body stays empty;
    the producer stands a fixed line in for the title only when the card
    name strips to empty. Silent unless escalation asks for sound, so
    the default is the least intrusive delivery.
    """

    title: str = ""
    body: str = ""
    sound: bool = False


@dataclass(frozen=True)
class PersistedNudgeState:
    """The anti-spam counters that must survive a restart.

    ``last_nudge_epoch`` is POSIX seconds (the JSON state file stores it
    as a number or null); ``day_key`` is the local date the counters
    belong to. Under schema 2 these five keys are the whole record: a
    ``fired_thresholds`` key left in an older file is never read and
    never written back.
    """

    schema_version: int = 2
    streak: int = 0
    last_nudge_epoch: float | None = None
    escalation_level: int = 0
    day_key: str = ""
