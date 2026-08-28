"""Typed producer of the active timeline-card window.

Turns raw ``timeline_cards`` rows into ``CardSnapshot`` values over the
lookback window the daemon reasons about. A soft-deleted row, or a row
whose end timestamp is missing, cannot be placed in the window and
counts as absent; a row that cannot be mapped at all is dropped rather
than allowed to poison a cycle. Text passes through exactly as stored --
normalizing and matching belong to the detector, not the producer -- and
the metadata blob is decoded so no consumer ever sees raw JSON text.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from dayflow_nudge.models import CardSnapshot

CARD_LOOKBACK_MINUTES = 60

_SELECT_ACTIVE_WINDOW = (
    "SELECT title, summary, category, start_ts, end_ts, metadata"
    " FROM timeline_cards"
    " WHERE is_deleted = 0 AND end_ts >= ?"
    " ORDER BY start_ts"
)

_logger = logging.getLogger(__name__)


def load_card_snapshots(connection, now_epoch: int,
                        lookback_minutes: int = CARD_LOOKBACK_MINUTES
                        ) -> List[CardSnapshot]:
    """Map every non-deleted card ending within the lookback to a snapshot.

    The window is anchored on card end times, because a card that has
    not ended yet or ended recently is the activity the daemon watches;
    cards that ended before the cutoff are history and stay in the
    store. Rows return in start order so consumers picking "the latest
    card" see a stable sequence.
    """
    cutoff = now_epoch - lookback_minutes * 60
    snapshots: List[CardSnapshot] = []
    for row in connection.execute(_SELECT_ACTIVE_WINDOW, (cutoff,)):
        snapshot = _map_row(row)
        if snapshot is not None:
            snapshots.append(snapshot)
    return snapshots


def _map_row(row) -> Optional[CardSnapshot]:
    """One row to one snapshot; an unmappable row counts as absent."""
    try:
        return CardSnapshot(
            title=row[0] or "",
            summary=row[1] or "",
            category=row[2] or "",
            start_ts=_as_datetime(row[3]),
            end_ts=_as_datetime(row[4]),
            metadata=_as_metadata(row[5]),
        )
    except (TypeError, ValueError, OverflowError, OSError):
        _logger.debug("dropping an unmappable timeline card row")
        return None


def _as_datetime(value) -> Optional[datetime]:
    """Store seconds to local datetime; a missing timestamp stays None."""
    if value is None:
        return None
    return datetime.fromtimestamp(int(value))


def _as_metadata(value) -> Optional[Dict[str, Any]]:
    """Decode the metadata blob; unreadable or non-object content is None.

    The blob is diagnostic detail about a card, never load-bearing for
    a decision, so a broken blob degrades to None instead of hiding the
    card it belongs to.
    """
    if value is None:
        return None
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return None
    return decoded if isinstance(decoded, dict) else None
