"""Behavior of the read-only store attachment.

The caller observes one thing per cycle: either a usable read-only
connection to the Dayflow store, or an UNKNOWN attachment carrying a
single warning line. Every test here drives that seam against a real
SQLite file -- never an in-memory imitation -- because the guarantees
being pinned (read-only opens, WAL reads, silence on drift) are
properties of SQLite itself.
"""

import os
import sqlite3
import tempfile
import unittest

from dayflow_nudge import db_reader
from tests import fixtures

READER_LOGGER = "dayflow_nudge.db_reader"


class AttachUsableStore(unittest.TestCase):
    def test_open_store_yields_usable_connection(self):
        with fixtures.fixture_store() as store:
            store.add_card(title="One card")
            attachment = db_reader.attach_store(store.path)
            self.addCleanup(attachment.close)
            self.assertIs(attachment.state, db_reader.AttachmentState.OPEN)
            count = attachment.connection.execute(
                "SELECT COUNT(*) FROM timeline_cards").fetchone()[0]
            self.assertEqual(count, 1)

    def test_connection_cannot_write(self):
        with fixtures.fixture_store() as store:
            attachment = db_reader.attach_store(store.path)
            self.addCleanup(attachment.close)
            with self.assertRaises(sqlite3.OperationalError):
                attachment.connection.execute(
                    "INSERT INTO day_goals (day, focus_target_minutes,"
                    " distraction_limit_minutes, is_skipped, created_at, updated_at)"
                    " VALUES ('2026-01-01', 1, 1, 0, 0, 0)")

    def test_connection_cannot_create_tables(self):
        with fixtures.fixture_store() as store:
            attachment = db_reader.attach_store(store.path)
            self.addCleanup(attachment.close)
            with self.assertRaises(sqlite3.OperationalError):
                attachment.connection.execute(
                    "CREATE TABLE scratch (x INTEGER)")

    def test_uri_form_is_explicitly_read_only(self):
        uri = db_reader.read_only_uri("/tmp/some path/chunks.sqlite")
        self.assertTrue(uri.startswith("file:"))
        self.assertTrue(uri.endswith("?mode=ro"))
        self.assertIn("some%20path", uri)

    def test_reads_rows_written_by_a_concurrent_writer(self):
        # The live store is written by the Dayflow app while this daemon
        # reads; WAL mode is what lets both happen at once. The builder
        # connection stays open here to stand in for the writing app.
        with fixtures.fixture_store() as store:
            store.add_card(title="Row written next door", category="Distraction")
            attachment = db_reader.attach_store(store.path)
            self.addCleanup(attachment.close)
            count = attachment.connection.execute(
                "SELECT COUNT(*) FROM timeline_cards"
                " WHERE title = 'Row written next door'").fetchone()[0]
            self.assertEqual(count, 1)

    def test_close_releases_the_connection(self):
        with fixtures.fixture_store() as store:
            attachment = db_reader.attach_store(store.path)
            attachment.close()
            with self.assertRaises(sqlite3.ProgrammingError):
                attachment.connection.execute("SELECT 1")

    def test_close_on_unknown_attachment_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as root:
            missing = os.path.join(root, "absent.sqlite")
            with self.assertLogs(READER_LOGGER, level="WARNING"):
                attachment = db_reader.attach_store(missing)
            attachment.close()

    def test_goal_category_table_attaches_open(self):
        with fixtures.fixture_store() as store:
            store.add_goal_category(day="2026-08-28", category_name="YouTube")
            attachment = db_reader.attach_store(store.path)
            self.addCleanup(attachment.close)
            self.assertIs(attachment.state, db_reader.AttachmentState.OPEN)
            names = attachment.connection.execute(
                "SELECT category_name FROM day_goal_categories").fetchall()
            self.assertEqual([row[0] for row in names], ["YouTube"])

    def test_store_with_only_the_consumed_category_columns_attaches_open(self):
        # The probe requires what the daemon reads and tolerates the
        # absence of the rest: a store that never grew the display-only
        # category columns has not drifted.
        with fixtures.fixture_store(
                category_columns=["day", "kind", "category_name"]) as store:
            attachment = db_reader.attach_store(store.path)
            self.addCleanup(attachment.close)
            self.assertIs(attachment.state, db_reader.AttachmentState.OPEN)


class AttachFailingStore(unittest.TestCase):
    def test_missing_file_is_unknown_not_a_crash(self):
        with tempfile.TemporaryDirectory() as root:
            missing = os.path.join(root, "absent.sqlite")
            with self.assertLogs(READER_LOGGER, level="WARNING") as captured:
                attachment = db_reader.attach_store(missing)
            self.assertIs(attachment.state, db_reader.AttachmentState.UNKNOWN)
            self.assertIsNone(attachment.connection)
            self.assertTrue(attachment.detail)
            self.assertEqual(len(captured.records), 1)

    def test_garbage_file_is_unknown(self):
        with tempfile.TemporaryDirectory() as root:
            garbage = os.path.join(root, "garbage.sqlite")
            with open(garbage, "wb") as handle:
                handle.write(b"this is not a database")
            with self.assertLogs(READER_LOGGER, level="WARNING") as captured:
                attachment = db_reader.attach_store(garbage)
            self.assertIs(attachment.state, db_reader.AttachmentState.UNKNOWN)
            self.assertIsNone(attachment.connection)
            self.assertEqual(len(captured.records), 1)

    def test_missing_goal_table_is_unknown(self):
        with fixtures.fixture_store(with_goals=False) as store:
            with self.assertLogs(READER_LOGGER, level="WARNING") as captured:
                attachment = db_reader.attach_store(store.path)
            self.assertIs(attachment.state, db_reader.AttachmentState.UNKNOWN)
            self.assertIsNone(attachment.connection)
            self.assertIn("day_goals", attachment.detail)
            self.assertEqual(len(captured.records), 1)

    def test_missing_pinned_column_is_unknown(self):
        drifted_columns = [
            name for name, _ in fixtures.CARD_COLUMN_SPECS if name != "is_deleted"
        ]
        with fixtures.fixture_store(card_columns=drifted_columns) as store:
            with self.assertLogs(READER_LOGGER, level="WARNING") as captured:
                attachment = db_reader.attach_store(store.path)
            self.assertIs(attachment.state, db_reader.AttachmentState.UNKNOWN)
            self.assertIsNone(attachment.connection)
            self.assertIn("is_deleted", attachment.detail)
            self.assertEqual(len(captured.records), 1)

    def test_added_columns_are_not_drift(self):
        # The store legitimately grows columns over its life; only the
        # loss of a column the daemon reads is drift.
        with fixtures.fixture_store() as store:
            store.conn.execute(
                "ALTER TABLE timeline_cards ADD COLUMN future_column TEXT")
            store.conn.commit()
            attachment = db_reader.attach_store(store.path)
            self.addCleanup(attachment.close)
            self.assertIs(attachment.state, db_reader.AttachmentState.OPEN)

    def test_each_drift_episode_logs_exactly_one_line(self):
        drifted_columns = [
            name for name, _ in fixtures.CARD_COLUMN_SPECS if name != "category"
        ]
        with fixtures.fixture_store(card_columns=drifted_columns) as store:
            with self.assertLogs(READER_LOGGER, level="WARNING") as captured:
                for _ in range(2):
                    self.assertIs(
                        db_reader.attach_store(store.path).state,
                        db_reader.AttachmentState.UNKNOWN)
            self.assertEqual(len(captured.records), 2)

    def test_missing_goal_category_table_is_unknown(self):
        with fixtures.fixture_store(with_goal_categories=False) as store:
            with self.assertLogs(READER_LOGGER, level="WARNING") as captured:
                attachment = db_reader.attach_store(store.path)
            self.assertIs(attachment.state, db_reader.AttachmentState.UNKNOWN)
            self.assertIsNone(attachment.connection)
            self.assertIn("day_goal_categories", attachment.detail)
            self.assertEqual(len(captured.records), 1)

    def test_each_consumed_category_column_is_required(self):
        for dropped in ("day", "kind", "category_name"):
            with self.subTest(dropped=dropped):
                columns = [name for name, _ in fixtures.CATEGORY_COLUMN_SPECS
                           if name != dropped]
                with fixtures.fixture_store(category_columns=columns) as store:
                    with self.assertLogs(READER_LOGGER,
                                         level="WARNING") as captured:
                        attachment = db_reader.attach_store(store.path)
                    self.assertIs(attachment.state,
                                  db_reader.AttachmentState.UNKNOWN)
                    self.assertIn("day_goal_categories", attachment.detail)
                    self.assertIn(dropped, attachment.detail)
                    self.assertEqual(len(captured.records), 1)


class TriggerSetPersonas(unittest.TestCase):
    """Pins for the day-category persona builders.

    The personas are the shared stores every trigger-set rule will be
    exercised against, so their rows are pinned here like the rest of
    the fixture library: what each day's selection looks like in the
    store, exactly as the live app writes it.
    """

    DAY = "2026-08-28"

    def test_single_category_day_records_one_distraction_selection(self):
        with fixtures.fixture_store() as store:
            fixtures.persona_goal_single_category(
                store, self.DAY, category_name="YouTube")
            self.assertEqual(store.goal_category_names(self.DAY), ["YouTube"])

    def test_multi_category_day_records_every_selection_in_order(self):
        with fixtures.fixture_store() as store:
            fixtures.persona_goal_multi_category(
                store, self.DAY, category_names=("YouTube", "News", "Games"))
            self.assertEqual(store.goal_category_names(self.DAY),
                             ["YouTube", "News", "Games"])

    def test_no_categories_day_records_no_selection(self):
        # The empty selection is itself the fallback signal; the persona
        # must leave the category table empty, not invent a sentinel row.
        with fixtures.fixture_store() as store:
            fixtures.persona_goal_no_categories(store, self.DAY)
            self.assertEqual(store.goal_category_names(self.DAY), [])

    def test_focus_only_day_never_records_a_distraction_selection(self):
        with fixtures.fixture_store() as store:
            fixtures.persona_goal_focus_only(store, self.DAY)
            self.assertEqual(store.goal_category_names(self.DAY), [])
            self.assertEqual(store.goal_category_names(self.DAY, kind="focus"),
                             ["Deep Work", "Admin"])

    def test_category_name_spellings_are_stored_verbatim(self):
        # Normalization belongs to whichever producer reads the set; the
        # persona must hand on the raw spellings the live app writes,
        # whitespace and case included, plus one name that strips empty.
        with fixtures.fixture_store() as store:
            fixtures.persona_goal_category_variants(store, self.DAY)
            self.assertEqual(
                store.goal_category_names(self.DAY),
                ["YouTube", "  youtube  ", "YOUTUBE", "  News  ", "   "])

    def test_every_persona_day_is_a_store_the_reader_attaches_to(self):
        personas = (
            ("single", lambda store: fixtures.persona_goal_single_category(
                store, self.DAY)),
            ("multi", lambda store: fixtures.persona_goal_multi_category(
                store, self.DAY)),
            ("none", lambda store: fixtures.persona_goal_no_categories(
                store, self.DAY)),
            ("focus-only", lambda store: fixtures.persona_goal_focus_only(
                store, self.DAY)),
            ("variants", lambda store: fixtures.persona_goal_category_variants(
                store, self.DAY)),
        )
        for name, build in personas:
            with self.subTest(persona=name):
                with fixtures.fixture_store() as store:
                    build(store)
                    attachment = db_reader.attach_store(store.path)
                    self.addCleanup(attachment.close)
                    self.assertIs(attachment.state,
                                  db_reader.AttachmentState.OPEN)


class PinnedContract(unittest.TestCase):
    def test_busy_timeout_is_two_seconds(self):
        self.assertEqual(db_reader.DB_BUSY_TIMEOUT, 2.0)

    def test_default_path_points_at_the_dayflow_store(self):
        self.assertTrue(
            str(db_reader.DEFAULT_DB_PATH).endswith(
                "Library/Application Support/Dayflow/chunks.sqlite"))


if __name__ == "__main__":
    unittest.main()
