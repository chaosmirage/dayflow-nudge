"""Atomic persistence of the daemon's anti-spam counters.

Owns one secret: the on-disk format and integrity policy of ``state.json``.
Callers hand over and receive a persisted-state record and never see JSON,
temp files, or validation. The file is treated as untrusted data on the way
in, so a damaged or foreign record degrades to safe defaults instead of
poisoning the daemon, and no write ever exposes a partial file.
"""

import dataclasses
import json
import logging
import os
from datetime import datetime
from typing import Callable, Optional

from dayflow_nudge.models import PersistedNudgeState

SCHEMA_VERSION = 2

# The record shapes this build can load. Schema 1 carried a sixth key,
# the limit-threshold marks, which no code reads anymore; loading such a
# file migrates it by simply leaving that key behind.
SUPPORTED_SCHEMA_VERSIONS = (1, SCHEMA_VERSION)

OWNED_DIR = os.path.expanduser("~/Library/Application Support/dayflow-nudge")
DEFAULT_STATE_PATH = os.path.join(OWNED_DIR, "state.json")

DAY_KEY_FORMAT = "%Y-%m-%d"

_LOGGER = logging.getLogger(__name__)


def _is_count(value):
    """True for a plain non-negative integer (bool is not a counter)."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_epoch(value):
    """True for a missing or non-negative unix timestamp."""
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float)) and value >= 0


def _is_day_key(value):
    """True for a local calendar date written as YYYY-MM-DD."""
    if not isinstance(value, str):
        return False
    try:
        datetime.strptime(value, DAY_KEY_FORMAT)
    except ValueError:
        return False
    return True


# The five schema-2 keys: every surviving field has one accepted shape. A
# record that misses or bends any of them is rejected whole, because a
# partially trusted counter file is worse than a fresh start. Keys this
# schema no longer owns are simply never looked up.
_FIELD_VALIDATORS = (
    ("streak", _is_count),
    ("last_nudge_epoch", _is_epoch),
    ("escalation_level", _is_count),
    ("day_key", _is_day_key),
)


def _parse_record(raw_text):
    """Parsed record of a supported schema, or None when untrusted."""
    try:
        record = json.loads(raw_text)
    except ValueError:
        return None
    if not isinstance(record, dict):
        return None
    version = record.get("schema_version")
    if isinstance(version, bool) or version not in SUPPORTED_SCHEMA_VERSIONS:
        return None
    for field, is_valid in _FIELD_VALIDATORS:
        if field not in record or not is_valid(record[field]):
            return None
    return record


def _today_key(clock):
    """Local calendar date as YYYY-MM-DD, the same key the day goals use."""
    return clock().date().isoformat()


class StateStore:
    """Loads and persists the five schema-2 counter keys."""

    def __init__(
        self,
        path: Optional[str] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self._path = DEFAULT_STATE_PATH if path is None else path
        self._clock = datetime.now if clock is None else clock

    def load(self) -> PersistedNudgeState:
        """Persisted counters with the day rollover applied.

        Missing, unreadable, or unknown-schema files resolve to safe
        defaults with exactly one warning line, never an exception: a
        broken state file must cost the daemon a fresh start, not a
        crash loop. An older supported schema loads with its surviving
        counters intact and exactly one warning naming what was left
        behind.
        """
        record = self._read_record()
        if record is None:
            return self._defaults()
        if record["schema_version"] != SCHEMA_VERSION:
            _LOGGER.warning(
                "state file migrated from schema %d; fired_thresholds"
                " discarded: %s",
                record["schema_version"], self._path)
        return self._with_rollover(self._to_state(record))

    def save(self, state: PersistedNudgeState) -> None:
        """Persist the counters so a reader never sees a partial file."""
        record = {
            "schema_version": SCHEMA_VERSION,
            "streak": state.streak,
            "last_nudge_epoch": state.last_nudge_epoch,
            "escalation_level": state.escalation_level,
            "day_key": state.day_key,
        }
        self._write_atomically(record)

    def _read_record(self):
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                raw_text = handle.read()
        except FileNotFoundError:
            _LOGGER.warning("state file missing; counters start from defaults: %s", self._path)
            return None
        except (OSError, UnicodeDecodeError):
            _LOGGER.warning("state file unreadable; counters start from defaults: %s", self._path)
            return None
        record = _parse_record(raw_text)
        if record is None:
            _LOGGER.warning(
                "state file does not match schema %d; counters start from defaults: %s",
                SCHEMA_VERSION,
                self._path,
            )
        return record

    def _defaults(self):
        return PersistedNudgeState(
            schema_version=SCHEMA_VERSION,
            streak=0,
            last_nudge_epoch=None,
            escalation_level=0,
            day_key=_today_key(self._clock),
        )

    def _to_state(self, record):
        return PersistedNudgeState(
            schema_version=SCHEMA_VERSION,
            streak=record["streak"],
            last_nudge_epoch=record["last_nudge_epoch"],
            escalation_level=record["escalation_level"],
            day_key=record["day_key"],
        )

    def _with_rollover(self, state):
        today = _today_key(self._clock)
        if state.day_key == today:
            return state
        # A new local date starts the day-scoped counters over; the cooldown
        # timestamp survives so an outstanding window still expires by time
        # alone, never by arithmetic across a daylight-saving change.
        return dataclasses.replace(
            state,
            streak=0,
            escalation_level=0,
            day_key=today,
        )

    def _write_atomically(self, record):
        tmp_path = self._path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(record, handle, indent=2)
                handle.flush()
                # Sync before the rename: a crash may lose the write but can
                # never leave a half-written file at the final path.
                os.fsync(handle.fileno())
            os.replace(tmp_path, self._path)
        except BaseException:
            _discard(tmp_path)
            raise


def _discard(path):
    """Remove a leftover temp file after a failed write; silence is fine."""
    try:
        os.unlink(path)
    except OSError:
        pass
