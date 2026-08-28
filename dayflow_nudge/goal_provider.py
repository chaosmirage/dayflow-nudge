"""Typed producer of one local day's goal row and category selection.

Fetches the ``day_goals`` row keyed by the local date string and today's
``day_goal_categories`` rows of the distraction kind, and maps them to a
``GoalSnapshot``. A day with no goal row yields None, which is the
caller's signal that nothing about the day is known. A skipped day or a
zero limit is reported verbatim, because whether either deactivates a
nudge is a decision for the policy, not for the producer; the same holds
for the category selection, which is carried as it was chosen, never
second-guessed here.
"""

from __future__ import annotations

from typing import Optional

from dayflow_nudge.models import GoalSnapshot, normalize_category

_SELECT_DAY_GOAL = (
    "SELECT day, focus_target_minutes, distraction_limit_minutes, is_skipped"
    " FROM day_goals WHERE day = ?"
)

DISTRACTION_KIND = "distraction"

_SELECT_DISTRACTION_CATEGORIES = (
    "SELECT category_name FROM day_goal_categories"
    " WHERE day = ? AND kind = ?"
)


def load_goal_snapshot(connection, day_key: str) -> Optional[GoalSnapshot]:
    """Map the goal row and category selection for one local day.

    The row is located by its date key alone, never by comparing
    timestamps against "now", so the answer is identical before and
    after midnight for any given key. Category names are normalized
    exactly once, here at the producer, so no consumer can disagree
    about what a selection matches.
    """
    row = connection.execute(_SELECT_DAY_GOAL, (day_key,)).fetchone()
    if row is None:
        return None
    try:
        return GoalSnapshot(
            day=row[0],
            focus_target_minutes=_as_minutes(row[1]),
            distraction_limit_minutes=_as_minutes(row[2]),
            is_skipped=bool(row[3]),
            distraction_categories=_distraction_categories(connection, day_key),
        )
    except (TypeError, ValueError):
        return None


def _distraction_categories(connection, day_key: str) -> frozenset:
    """Today's selected distraction names, normalized once.

    Each name is read through the shared rule from models -- stripped
    and case-folded -- and a name that normalizes to nothing is dropped:
    an absent selection is signaled by the empty set itself, never by a
    blank member. Selections of the focus kind are never read, and
    duplicate spellings collapse onto one member because the day's
    selection is a set, not a list.
    """
    names = connection.execute(
        _SELECT_DISTRACTION_CATEGORIES,
        (day_key, DISTRACTION_KIND)).fetchall()
    return frozenset(
        normalized
        for normalized in (
            normalize_category(name) for (name,) in names)
        if normalized
    )


def _as_minutes(value) -> Optional[int]:
    """Keep an unset minute column as None rather than inventing a zero."""
    if value is None:
        return None
    return int(value)
