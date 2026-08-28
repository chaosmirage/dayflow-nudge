"""Behavior of the persisted anti-spam counters on disk.

The store must survive a daemon restart with every counter intact, must never
expose a partially written state file, must fall back to safe defaults with a
single warning line when the file is missing, corrupt, or written under an
unknown schema version, and must carry a schema-1 file written by an earlier
release across the schema-2 boundary with its surviving counters preserved
and the discarded threshold marks reported once. The day-scoped counters roll
over on a local calendar-date change while the cooldown timestamp stays
meaningful.
"""

import dataclasses
import json
import logging
import os
import tempfile
import unittest
from datetime import datetime
from unittest import mock

from dayflow_nudge.models import PersistedNudgeState
from dayflow_nudge.state_store import (
    DEFAULT_STATE_PATH,
    SCHEMA_VERSION,
    StateStore,
)

TODAY = datetime(2026, 8, 28, 15, 4, 5)
TODAY_KEY = "2026-08-28"


class _WarningCounter(logging.Handler):
    """Counts the warning lines one logger emitted during a test."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.count = 0

    def emit(self, record):
        self.count += 1


class StateStoreTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "state.json")

    def make_store(self, at=None):
        moment = TODAY if at is None else at
        return StateStore(self.path, clock=lambda: moment)

    def count_warnings(self):
        counter = _WarningCounter()
        logger = logging.getLogger("dayflow_nudge.state_store")
        logger.addHandler(counter)
        self.addCleanup(logger.removeHandler, counter)
        return counter

    def full_state(self, day_key=TODAY_KEY, last_nudge_epoch=1234567.5):
        return PersistedNudgeState(
            schema_version=SCHEMA_VERSION,
            streak=2,
            last_nudge_epoch=last_nudge_epoch,
            escalation_level=1,
            day_key=day_key,
        )

    def assert_defaults(self, state):
        self.assertEqual(state.schema_version, SCHEMA_VERSION)
        self.assertEqual(state.streak, 0)
        self.assertIsNone(state.last_nudge_epoch)
        self.assertEqual(state.escalation_level, 0)
        self.assertEqual(state.day_key, TODAY_KEY)

    def write_raw(self, text):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def v1_record(self, **overrides):
        """A complete file as the schema-1 writer used to lay it down."""
        record = {
            "schema_version": 1,
            "streak": 2,
            "last_nudge_epoch": 1234567.5,
            "escalation_level": 1,
            "fired_thresholds": [0.5, 0.8],
            "day_key": TODAY_KEY,
        }
        record.update(overrides)
        return record


class RoundTripTest(StateStoreTestCase):
    def test_saved_state_survives_a_full_round_trip(self):
        self.make_store().save(self.full_state())

        loaded = self.make_store().load()

        self.assertEqual(loaded.schema_version, SCHEMA_VERSION)
        self.assertEqual(loaded.streak, 2)
        self.assertEqual(loaded.last_nudge_epoch, 1234567.5)
        self.assertEqual(loaded.escalation_level, 1)
        self.assertEqual(loaded.day_key, TODAY_KEY)

    def test_a_save_writes_exactly_the_five_schema_two_keys(self):
        self.make_store().save(self.full_state())

        with open(self.path, encoding="utf-8") as handle:
            on_disk = json.load(handle)

        self.assertEqual(
            sorted(on_disk),
            ["day_key", "escalation_level", "last_nudge_epoch", "schema_version",
             "streak"],
        )
        self.assertEqual(on_disk["schema_version"], 2)

    def test_restarted_store_keeps_the_cooldown_anchor(self):
        self.make_store().save(self.full_state(last_nudge_epoch=1750000000.0))

        loaded = self.make_store().load()

        self.assertEqual(loaded.last_nudge_epoch, 1750000000.0)


class SchemaMigrationTest(StateStoreTestCase):
    def test_a_schema_one_file_loads_with_every_surviving_counter(self):
        self.write_raw(json.dumps(self.v1_record()))
        counter = self.count_warnings()

        loaded = self.make_store().load()

        self.assertEqual(loaded.schema_version, 2)
        self.assertEqual(loaded.streak, 2)
        self.assertEqual(loaded.last_nudge_epoch, 1234567.5)
        self.assertEqual(loaded.escalation_level, 1)
        self.assertEqual(loaded.day_key, TODAY_KEY)
        self.assertEqual(counter.count, 1)

    def test_the_migration_warning_names_the_discarded_marks_once(self):
        self.write_raw(json.dumps(self.v1_record()))
        with self.assertLogs("dayflow_nudge.state_store",
                             level="WARNING") as captured:
            self.make_store().load()

        self.assertEqual(len(captured.records), 1)
        message = captured.records[0].getMessage()
        self.assertIn("schema 1", message)
        self.assertIn("fired_thresholds", message)

    def test_a_schema_one_file_without_threshold_marks_still_loads(self):
        # The discarded key is never read, so its absence in an old file
        # cannot reject the counters that did survive.
        record = self.v1_record()
        record.pop("fired_thresholds")
        self.write_raw(json.dumps(record))
        counter = self.count_warnings()

        loaded = self.make_store().load()

        self.assertEqual(loaded.streak, 2)
        self.assertEqual(loaded.escalation_level, 1)
        self.assertEqual(counter.count, 1)

    def test_a_loaded_schema_one_file_reserializes_as_schema_two(self):
        self.write_raw(json.dumps(self.v1_record()))

        store = self.make_store()
        store.save(store.load())

        with open(self.path, encoding="utf-8") as handle:
            on_disk = json.load(handle)
        self.assertEqual(on_disk["schema_version"], 2)
        self.assertNotIn("fired_thresholds", on_disk)


class GuardedReadTest(StateStoreTestCase):
    def test_missing_file_loads_safe_defaults_with_one_warning(self):
        counter = self.count_warnings()

        loaded = self.make_store().load()

        self.assert_defaults(loaded)
        self.assertEqual(counter.count, 1)

    def test_truncated_file_loads_safe_defaults_with_one_warning(self):
        self.write_raw('{"schema_version": 2, "streak": 2, "last_nud')
        counter = self.count_warnings()

        self.assert_defaults(self.make_store().load())
        self.assertEqual(counter.count, 1)

    def test_undecodable_file_loads_safe_defaults_with_one_warning(self):
        with open(self.path, "wb") as handle:
            handle.write(b"\xff\xfe\x00 not json")
        counter = self.count_warnings()

        self.assert_defaults(self.make_store().load())
        self.assertEqual(counter.count, 1)

    def test_unknown_schema_version_loads_safe_defaults_with_one_warning(self):
        self.write_raw(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION + 1,
                    "streak": 2,
                    "last_nudge_epoch": 1.0,
                    "escalation_level": 1,
                    "day_key": TODAY_KEY,
                }
            )
        )
        counter = self.count_warnings()

        self.assert_defaults(self.make_store().load())
        self.assertEqual(counter.count, 1)

    def test_wrong_typed_counter_loads_safe_defaults_with_one_warning(self):
        self.write_raw(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "streak": "two",
                    "last_nudge_epoch": 1.0,
                    "escalation_level": 1,
                    "day_key": TODAY_KEY,
                }
            )
        )
        counter = self.count_warnings()

        self.assert_defaults(self.make_store().load())
        self.assertEqual(counter.count, 1)

    def test_valid_file_loads_without_any_warning(self):
        self.make_store().save(self.full_state())
        counter = self.count_warnings()

        self.make_store().load()

        self.assertEqual(counter.count, 0)


class AtomicWriteTest(StateStoreTestCase):
    def test_file_is_complete_json_after_every_write(self):
        store = self.make_store()

        for streak in (1, 2, 3):
            store.save(dataclasses.replace(self.full_state(), streak=streak))

            self.assertTrue(os.path.exists(self.path))
            with open(self.path, encoding="utf-8") as handle:
                on_disk = json.load(handle)
            self.assertEqual(on_disk["streak"], streak)

    def test_write_leaves_no_temporary_sibling_behind(self):
        self.make_store().save(self.full_state())

        self.assertEqual(sorted(os.listdir(os.path.dirname(self.path))), ["state.json"])

    def test_failed_final_rename_leaves_the_previous_file_intact(self):
        store = self.make_store()
        store.save(self.full_state(last_nudge_epoch=111.0))

        with mock.patch(
            "dayflow_nudge.state_store.os.replace", side_effect=OSError("disk gone")
        ):
            with self.assertRaises(OSError):
                store.save(self.full_state(last_nudge_epoch=222.0))

        self.assertTrue(os.path.exists(self.path))
        with open(self.path, encoding="utf-8") as handle:
            on_disk = json.load(handle)
        self.assertEqual(on_disk["last_nudge_epoch"], 111.0)
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.path))), ["state.json"])


class DayRolloverTest(StateStoreTestCase):
    def test_new_local_day_resets_day_scoped_counters_and_keeps_cooldown(self):
        first_day = self.make_store(at=datetime(2026, 8, 27, 22, 0, 0))
        first_day.save(self.full_state(day_key="2026-08-27", last_nudge_epoch=999.0))

        loaded = self.make_store(at=datetime(2026, 8, 28, 9, 30, 0)).load()

        self.assertEqual(loaded.streak, 0)
        self.assertEqual(loaded.escalation_level, 0)
        self.assertEqual(loaded.day_key, TODAY_KEY)
        self.assertEqual(loaded.last_nudge_epoch, 999.0)

    def test_rollover_across_a_daylight_saving_change_is_decided_by_the_date_alone(self):
        evening_before = self.make_store(at=datetime(2026, 10, 31, 20, 0, 0))
        evening_before.save(self.full_state(day_key="2026-10-31"))

        after_the_clock_shift = self.make_store(at=datetime(2026, 11, 1, 0, 45, 0))

        loaded = after_the_clock_shift.load()

        self.assertEqual(loaded.day_key, "2026-11-01")
        self.assertEqual(loaded.streak, 0)

    def test_same_local_day_keeps_every_counter(self):
        store = self.make_store()
        store.save(self.full_state())

        loaded = store.load()

        self.assertEqual(loaded.streak, 2)
        self.assertEqual(loaded.escalation_level, 1)
        self.assertEqual(loaded.day_key, TODAY_KEY)

    def test_rollover_happens_on_read_without_touching_the_file(self):
        store = self.make_store()
        store.save(self.full_state(day_key="2026-08-27"))

        store.load()

        with open(self.path, encoding="utf-8") as handle:
            on_disk = json.load(handle)
        self.assertEqual(on_disk["day_key"], "2026-08-27")


class PinnedContractTest(StateStoreTestCase):
    def test_schema_version_is_pinned_at_two(self):
        self.assertEqual(SCHEMA_VERSION, 2)

    def test_default_state_path_lives_in_the_owned_directory(self):
        self.assertTrue(
            DEFAULT_STATE_PATH.endswith(os.path.join("dayflow-nudge", "state.json"))
        )
        self.assertIn("Application Support", DEFAULT_STATE_PATH)


if __name__ == "__main__":
    unittest.main()
