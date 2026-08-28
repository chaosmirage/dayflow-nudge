"""Behavior of the typed card and goal producers.

The caller observes snapshots: which timeline cards are visible in the
active window, exactly as stored, and what today's goal row says. The
tests below drive the producers through the read-only attachment the
daemon really uses, against a real SQLite store.
"""

import unittest
from datetime import datetime

from dayflow_nudge import card_provider, db_reader, goal_provider
from dayflow_nudge.models import CardSnapshot, GoalSnapshot
from tests import fixtures

NOW = 1758000000
TODAY_KEY = "2026-08-28"
YESTERDAY_KEY = "2026-08-27"


class CardWindow(unittest.TestCase):
    def attached(self, store):
        attachment = db_reader.attach_store(store.path)
        self.addCleanup(attachment.close)
        return attachment.connection

    def test_returns_cards_inside_the_lookback_only(self):
        with fixtures.fixture_store() as store:
            fixtures.persona_fresh(store, NOW)
            store.add_card(title="Too old", category="Work",
                           start_ts=fixtures.minutes_ago(NOW, 130),
                           end_ts=fixtures.minutes_ago(NOW, 61))
            snapshots = card_provider.load_card_snapshots(
                self.attached(store), NOW)
            self.assertEqual(
                sorted(snapshot.title for snapshot in snapshots),
                ["Fresh distraction", "Recent work"])

    def test_card_ending_exactly_at_cutoff_is_included(self):
        cutoff = NOW - card_provider.CARD_LOOKBACK_MINUTES * 60
        with fixtures.fixture_store() as store:
            store.add_card(title="On the edge", category="Work",
                           start_ts=cutoff - 600, end_ts=cutoff)
            store.add_card(title="Just outside", category="Work",
                           start_ts=cutoff - 601, end_ts=cutoff - 1)
            snapshots = card_provider.load_card_snapshots(
                self.attached(store), NOW)
            self.assertEqual(
                [snapshot.title for snapshot in snapshots], ["On the edge"])

    def test_maps_every_field_of_a_healthy_row(self):
        with fixtures.fixture_store() as store:
            fixtures.persona_fresh(store, NOW)
            snapshots = card_provider.load_card_snapshots(
                self.attached(store), NOW)
            fresh = [s for s in snapshots if s.title == "Fresh distraction"][0]
            self.assertEqual(
                fresh,
                CardSnapshot(
                    title="Fresh distraction",
                    summary="watched videos",
                    category="Distraction",
                    start_ts=datetime.fromtimestamp(
                        fixtures.minutes_ago(NOW, 30)),
                    end_ts=datetime.fromtimestamp(
                        fixtures.minutes_ago(NOW, 2)),
                    metadata=None))

    def test_deleted_and_unplaceable_rows_are_absent(self):
        with fixtures.fixture_store() as store:
            fixtures.persona_deleted_and_null(store, NOW)
            snapshots = card_provider.load_card_snapshots(
                self.attached(store), NOW)
            self.assertEqual(
                sorted(snapshot.title for snapshot in snapshots),
                ["Healthy card", "Unknown start"])

    def test_null_timestamps_and_metadata_are_tolerated(self):
        with fixtures.fixture_store() as store:
            fixtures.persona_deleted_and_null(store, NOW)
            snapshots = card_provider.load_card_snapshots(
                self.attached(store), NOW)
            unknown_start = [s for s in snapshots
                             if s.title == "Unknown start"][0]
            self.assertIsNone(unknown_start.start_ts)
            self.assertEqual(
                unknown_start.end_ts,
                datetime.fromtimestamp(fixtures.minutes_ago(NOW, 3)))
            self.assertEqual(unknown_start.summary, "")
            self.assertIsNone(unknown_start.metadata)

    def test_metadata_blob_is_decoded_to_a_dict(self):
        with fixtures.fixture_store() as store:
            store.add_card(title="Tagged card", category="Work",
                           start_ts=fixtures.minutes_ago(NOW, 10),
                           end_ts=fixtures.minutes_ago(NOW, 5),
                           metadata='{"site": "youtube.com"}')
            snapshots = card_provider.load_card_snapshots(
                self.attached(store), NOW)
            self.assertEqual(snapshots[0].metadata, {"site": "youtube.com"})

    def test_broken_metadata_degrades_to_none_without_hiding_the_card(self):
        with fixtures.fixture_store() as store:
            store.add_card(title="Broken blob", category="Work",
                           start_ts=fixtures.minutes_ago(NOW, 10),
                           end_ts=fixtures.minutes_ago(NOW, 5),
                           metadata='{"site": "youtube.com')
            snapshots = card_provider.load_card_snapshots(
                self.attached(store), NOW)
            self.assertEqual(len(snapshots), 1)
            self.assertEqual(snapshots[0].title, "Broken blob")
            self.assertIsNone(snapshots[0].metadata)

    def test_category_values_round_trip_verbatim(self):
        # Normalization belongs to the detector; the producer must hand
        # on exactly what the store keeps, whitespace included.
        with fixtures.fixture_store() as store:
            fixtures.persona_category_variants(store, NOW)
            snapshots = card_provider.load_card_snapshots(
                self.attached(store), NOW)
            self.assertEqual(
                sorted(snapshot.category for snapshot in snapshots),
                sorted(["Distraction", "  distraction  ", "DISTRACTION",
                        "Deep Work"]))
            self.assertIn("  distraction  ",
                          [snapshot.category for snapshot in snapshots])

    def test_empty_store_yields_no_snapshots(self):
        with fixtures.fixture_store() as store:
            fixtures.persona_empty(store)
            snapshots = card_provider.load_card_snapshots(
                self.attached(store), NOW)
            self.assertEqual(snapshots, [])

    def test_lookback_is_pinned_at_sixty_minutes(self):
        self.assertEqual(card_provider.CARD_LOOKBACK_MINUTES, 60)


class GoalOfDay(unittest.TestCase):
    def attached(self, store):
        attachment = db_reader.attach_store(store.path)
        self.addCleanup(attachment.close)
        return attachment.connection

    def test_today_row_maps_every_field(self):
        with fixtures.fixture_store() as store:
            fixtures.persona_goal_active(store, TODAY_KEY,
                                         focus_target_minutes=240,
                                         distraction_limit_minutes=60)
            snapshot = goal_provider.load_goal_snapshot(
                self.attached(store), TODAY_KEY)
            self.assertEqual(
                snapshot,
                GoalSnapshot(day=TODAY_KEY, focus_target_minutes=240,
                             distraction_limit_minutes=60, is_skipped=False))

    def test_skipped_day_is_reported_as_skipped(self):
        with fixtures.fixture_store() as store:
            fixtures.persona_goal_skipped(store, TODAY_KEY)
            snapshot = goal_provider.load_goal_snapshot(
                self.attached(store), TODAY_KEY)
            self.assertTrue(snapshot.is_skipped)

    def test_zero_limit_is_reported_verbatim(self):
        # Whether a zero limit deactivates the daily nudge is a policy
        # decision; the producer must not silently rewrite the goal.
        with fixtures.fixture_store() as store:
            fixtures.persona_goal_zero_limit(store, TODAY_KEY)
            snapshot = goal_provider.load_goal_snapshot(
                self.attached(store), TODAY_KEY)
            self.assertEqual(snapshot.distraction_limit_minutes, 0)

    def test_missing_row_yields_none(self):
        with fixtures.fixture_store() as store:
            fixtures.persona_goal_missing(store)
            snapshot = goal_provider.load_goal_snapshot(
                self.attached(store), TODAY_KEY)
            self.assertIsNone(snapshot)

    def test_only_the_requested_day_is_returned(self):
        with fixtures.fixture_store() as store:
            fixtures.persona_goal_active(store, YESTERDAY_KEY,
                                         distraction_limit_minutes=30)
            fixtures.persona_goal_active(store, TODAY_KEY,
                                         distraction_limit_minutes=60)
            snapshot = goal_provider.load_goal_snapshot(
                self.attached(store), TODAY_KEY)
            self.assertEqual(snapshot.day, TODAY_KEY)
            self.assertEqual(snapshot.distraction_limit_minutes, 60)


class TriggerSetOfDay(unittest.TestCase):
    """Today's UI-selected distraction categories become the trigger set.

    The producer owns normalization once: each name is stripped and
    case-folded here, names that strip to empty are dropped, and the
    detector receives the set ready to match. The empty set is itself a
    signal -- nothing selected today -- never an error.
    """

    def attached(self, store):
        attachment = db_reader.attach_store(store.path)
        self.addCleanup(attachment.close)
        return attachment.connection

    def load(self, store, day_key=TODAY_KEY):
        return goal_provider.load_goal_snapshot(
            self.attached(store), day_key)

    def test_a_single_selected_category_lands_on_the_snapshot(self):
        with fixtures.fixture_store() as store:
            fixtures.persona_goal_single_category(
                store, TODAY_KEY, category_name="YouTube")
            self.assertEqual(self.load(store).distraction_categories,
                             frozenset({"youtube"}))

    def test_several_selected_categories_form_one_set(self):
        with fixtures.fixture_store() as store:
            fixtures.persona_goal_multi_category(
                store, TODAY_KEY, category_names=("YouTube", "News", "Games"))
            self.assertEqual(self.load(store).distraction_categories,
                             frozenset({"youtube", "news", "games"}))

    def test_names_are_normalized_once_at_the_producer(self):
        with fixtures.fixture_store() as store:
            fixtures.persona_goal_category_variants(store, TODAY_KEY)
            # Case and padding collapse onto one member per selection; a
            # name that strips to empty is dropped, not kept as "".
            self.assertEqual(self.load(store).distraction_categories,
                             frozenset({"youtube", "news"}))

    def test_a_day_with_no_selection_carries_the_empty_set(self):
        with fixtures.fixture_store() as store:
            fixtures.persona_goal_no_categories(store, TODAY_KEY)
            self.assertEqual(self.load(store).distraction_categories,
                             frozenset())

    def test_focus_kind_selections_never_enter_the_trigger_set(self):
        with fixtures.fixture_store() as store:
            fixtures.persona_goal_focus_only(store, TODAY_KEY)
            self.assertEqual(self.load(store).distraction_categories,
                             frozenset())

    def test_only_the_requested_day_s_selections_are_read(self):
        with fixtures.fixture_store() as store:
            fixtures.persona_goal_single_category(
                store, YESTERDAY_KEY, category_name="News")
            fixtures.persona_goal_single_category(
                store, TODAY_KEY, category_name="YouTube")
            self.assertEqual(self.load(store).distraction_categories,
                             frozenset({"youtube"}))

    def test_a_skipped_day_still_carries_its_category_selection(self):
        # Skipping the day never gated the category path; whether a
        # skipped day may nudge is the policy's decision.
        with fixtures.fixture_store() as store:
            fixtures.persona_goal_skipped(store, TODAY_KEY)
            store.add_goal_category(day=TODAY_KEY, category_name="YouTube")
            self.assertEqual(self.load(store).distraction_categories,
                             frozenset({"youtube"}))

    def test_a_missing_goal_row_yields_no_snapshot_at_all(self):
        with fixtures.fixture_store() as store:
            fixtures.persona_goal_missing(store)
            store.add_goal_category(day=TODAY_KEY, category_name="YouTube")
            self.assertIsNone(self.load(store))


class FixtureContract(unittest.TestCase):
    """The fixture library is shared by the whole suite; these pins keep
    its stores honest against the live-store facts they claim to mirror."""

    def test_store_runs_in_wal_mode(self):
        with fixtures.fixture_store() as store:
            self.assertEqual(store.journal_mode(), "wal")

    def test_rollover_persona_keys_rows_by_their_own_local_day(self):
        with fixtures.fixture_store() as store:
            fixtures.persona_midnight_rollover(
                store, yesterday_key=YESTERDAY_KEY, today_key=TODAY_KEY,
                late_yesterday_end=fixtures.minutes_ago(NOW, 5),
                early_today_end=fixtures.minutes_ago(NOW, 1))
            spans = store.conn.execute(
                "SELECT day, end_ts - start_ts FROM timeline_cards"
                " ORDER BY day").fetchall()
            self.assertEqual([row[0] for row in spans],
                             [YESTERDAY_KEY, TODAY_KEY])
            # each span lasts exactly as the persona promised: half an
            # hour late yesterday, twenty minutes early today
            self.assertEqual([row[1] for row in spans],
                             [30 * 60, 20 * 60])
            goals = store.conn.execute(
                "SELECT day FROM day_goals ORDER BY day").fetchall()
            self.assertEqual([row[0] for row in goals],
                             [YESTERDAY_KEY, TODAY_KEY])


if __name__ == "__main__":
    unittest.main()
