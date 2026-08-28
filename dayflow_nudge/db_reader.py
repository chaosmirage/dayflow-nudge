"""Read-only attachment to the Dayflow timeline store.

This module owns the single seam where the daemon touches Dayflow's
SQLite store: a fresh read-only connection each cycle plus an embedded
probe that checks the store still carries the columns the daemon's
queries consume. Anything that prevents a confident read -- a missing
file, an unparseable file, a drifted schema -- becomes an UNKNOWN
attachment carrying exactly one warning line, so a store the daemon
cannot trust silences it instead of crashing it. The connection is
opened read-only at the SQLite level, which makes writing to the store
impossible by construction rather than by discipline.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, Mapping, Optional
from urllib.parse import quote

DEFAULT_DB_PATH = Path.home() / "Library" / "Application Support" / "Dayflow" / "chunks.sqlite"

DB_BUSY_TIMEOUT = 2.0

# The columns the daemon's queries actually consume. A store that loses
# any of these has drifted; a store that merely grows new columns has
# not, which is why the probe checks for these names rather than for an
# exact table shape.
TIMELINE_CARDS_PINNED_COLUMNS = (
    "title", "summary", "category", "start_ts", "end_ts", "metadata", "is_deleted",
)
DAY_GOALS_PINNED_COLUMNS = (
    "day", "focus_target_minutes", "distraction_limit_minutes", "is_skipped",
)
# Only the columns the goal query consumes. The display-only columns
# beside them (color, id, sort order) are the store's own affair: a
# store that grows or drops those has not drifted, and requiring them
# would silence the daemon over a change it never reads.
DAY_GOAL_CATEGORIES_PINNED_COLUMNS = (
    "day", "kind", "category_name",
)

_PINNED_SCHEMA: Mapping[str, tuple] = {
    "timeline_cards": TIMELINE_CARDS_PINNED_COLUMNS,
    "day_goals": DAY_GOALS_PINNED_COLUMNS,
    "day_goal_categories": DAY_GOAL_CATEGORIES_PINNED_COLUMNS,
}

_logger = logging.getLogger(__name__)


class AttachmentState(Enum):
    """Whether a cycle may read the store it was offered."""

    OPEN = "open"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class StoreAttachment:
    """The outcome of one attachment attempt.

    An OPEN attachment owns a live read-only connection the caller must
    close; an UNKNOWN attachment never carries one, so no caller can
    accidentally read a store that failed the probe. ``detail`` states
    why the store was refused, for the one warning line that is logged.
    """

    state: AttachmentState
    connection: Optional[sqlite3.Connection]
    detail: str = ""

    def close(self) -> None:
        """Release the connection; closing an UNKNOWN attachment is a no-op."""
        if self.connection is not None:
            self.connection.close()


def read_only_uri(db_path) -> str:
    """The SQLite URI form that can open but never create or write a store."""
    return "file:{}?mode=ro".format(quote(str(db_path), safe="/"))


def attach_store(db_path=DEFAULT_DB_PATH,
                 busy_timeout: float = DB_BUSY_TIMEOUT) -> StoreAttachment:
    """Attach to the store for one cycle: open read-only, then probe.

    Never raises. Every failure path -- unopenable file, unreadable
    content, drifted schema -- returns UNKNOWN with one warning line so
    the caller can skip its cycle quietly and try again next tick.
    """
    try:
        connection = sqlite3.connect(
            read_only_uri(db_path), uri=True, timeout=busy_timeout)
    except (sqlite3.Error, OSError) as error:
        return _unknown("open failed: {}".format(error))
    try:
        drift = _schema_drift(connection)
    except sqlite3.Error as error:
        connection.close()
        return _unknown("probe failed: {}".format(error))
    if drift:
        connection.close()
        return _unknown("schema drift: {}".format(drift))
    return StoreAttachment(state=AttachmentState.OPEN, connection=connection)


def _schema_drift(connection: sqlite3.Connection) -> str:
    """Describe how the store's tables deviate from the pinned columns.

    Empty string means the store still has everything the queries need.
    The table names interpolated here come from this module's own
    constants, never from caller input.
    """
    missing: Dict[str, str] = {}
    for table, pinned in _PINNED_SCHEMA.items():
        present = {row[1] for row in
                   connection.execute("PRAGMA table_info({})".format(table))}
        absent = [column for column in pinned if column not in present]
        if absent:
            missing[table] = "missing {}".format(", ".join(absent))
    return "; ".join("{} {}".format(table, gap) for table, gap in missing.items())


def _unknown(detail: str) -> StoreAttachment:
    """Log one line and refuse the store: silence beats a crash loop."""
    _logger.warning("store attachment unknown: %s", detail)
    return StoreAttachment(state=AttachmentState.UNKNOWN, connection=None,
                           detail=detail)
