"""The timeline-category variant of the distraction detector.

The module registers itself in the detector registry at import time under
the id ``distraction``, so the daemon reaches it through the pluggable
detector contract without knowing which variant is active. Only the card
category is ever read for the decision, judged against the day's selected
distraction categories when a selection exists and against the legacy
category-word rule otherwise; titles and summaries travel as evidence at
most, never as a trigger, and goal text never reaches the match at all.
"""

from datetime import timedelta

from dayflow_nudge.detector_api import Detector, register
from dayflow_nudge.models import (
    DetectionState,
    Observation,
    PersistedNudgeState,
    Verdict,
    normalize_category,
)

VARIANT_ID = "distraction"

DISTRACTION_TOKEN = "distraction"

ACTIVE_WINDOW_MINUTES = 25


def is_distraction_category(category):
    """Decide whether a card category names a distraction by its word.

    The comparison is containment of the distraction token in the
    category as read by the shared rule from models -- stripped and
    case-folded -- so letter case and padding in the timeline never
    change the outcome. Anything that is not a string -- a missing
    category -- simply does not match. This rule stands on its own only
    as the fallback for a day with no category selection.
    """
    normalized = normalize_category(category)
    return normalized is not None and DISTRACTION_TOKEN in normalized


def _selected_categories(goal):
    """The day's trigger set; an absent goal reduces to the empty set.

    The producer normalizes the selection once, so the set is trusted as
    it arrives; emptiness is itself the signal to fall back to the
    category-word rule, never an error to report.
    """
    if goal is None:
        return frozenset()
    selected = getattr(goal, "distraction_categories", None)
    if not selected:
        return frozenset()
    return frozenset(selected)


def _category_matcher(selected):
    """Build the ONE effective predicate a check will use everywhere.

    A non-empty selection judges by membership in it; an empty selection
    falls back to the category-word rule. Both paths read the card's
    category through the one shared normalization rule, so the day's
    choice changes WHICH categories count, never how a category is read.
    """
    if selected:
        return lambda category: normalize_category(category) in selected
    return is_distraction_category


class DistractionDetector(Detector):
    """Classify the active window from the newest card inside it.

    The verdict reflects the card with the latest start inside the
    active window, picked and judged by the same effective predicate, so
    a boundary tie can never be preferred by one rule and labeled by
    another. When no card qualifies -- nothing recent, no clock reading,
    or only cards that cannot be placed -- the verdict is UNKNOWN, which
    keeps the daemon silent rather than guessing on stale or malformed
    data.
    """

    def detect(self, observation: Observation,
               state: PersistedNudgeState) -> Verdict:
        matches = _category_matcher(
            _selected_categories(observation.goal))
        card = _newest_card_in_active_window(
            observation.cards, observation.observed_at, matches)
        if card is None:
            return Verdict(state=DetectionState.UNKNOWN, off_task=False)
        if matches(card.category):
            return Verdict(
                state=DetectionState.OFF_TASK,
                off_task=True,
                evidence=_evidence_text(card.title),
                latency=_age_seconds(card.start_ts, observation.observed_at),
            )
        return Verdict(state=DetectionState.ON_TASK, off_task=False)


def _newest_card_in_active_window(cards, observed_at, matches):
    """Return the deciding card, or None when the window is unreadable.

    A card counts when it started inside the active window; among those,
    the latest start wins and a tie between a distraction card and an
    on-task card resolves toward on-task, so a boundary tie never
    produces a false accusation. The same predicate that will label the
    deciding card ranks the candidates, so the window cannot be won by a
    card the day's rule calls innocent.
    """
    if observed_at is None:
        return None
    window_start = observed_at - timedelta(
        minutes=ACTIVE_WINDOW_MINUTES)
    newest = None
    newest_rank = None
    for card in cards:
        started = card.start_ts
        if started is None or started < window_start or started > observed_at:
            continue
        rank = (started, 0 if matches(card.category) else 1)
        if newest_rank is None or rank > newest_rank:
            newest = card
            newest_rank = rank
    return newest


def _evidence_text(title):
    """Normalize the offending title for display; empty when unusable.

    Trimming to display width and stripping control characters belong to
    the notification boundary, so nothing is cut here.
    """
    if isinstance(title, str):
        return title.strip()
    return ""


def _age_seconds(started, observed_at):
    """Seconds between the evidence and the observation it was drawn from."""
    if started is None or observed_at is None:
        return 0.0
    return max((observed_at - started).total_seconds(), 0.0)


register(VARIANT_ID, DistractionDetector)
