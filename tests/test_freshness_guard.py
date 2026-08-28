"""Behavior of the freshness verdict for the newest timeline card.

UNKNOWN means the observed timeline is not current enough to act on: every
uncertain case (no card, boundary age, stale data) must resolve to UNKNOWN
so the calling cycle stays silent rather than acting on doubtful data.
"""

import unittest
from datetime import datetime, timedelta

from dayflow_nudge.freshness_guard import (
    FRESHNESS_THRESHOLD_MINUTES,
    Freshness,
    evaluate_freshness,
)


class EvaluateFreshnessTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 28, 12, 0, 0)

    def test_card_ended_well_inside_the_window_is_fresh(self):
        newest_end = self.now - timedelta(minutes=5)
        self.assertIs(evaluate_freshness(newest_end, self.now), Freshness.FRESH)

    def test_card_one_second_inside_the_threshold_is_fresh(self):
        newest_end = self.now - (timedelta(minutes=25) - timedelta(seconds=1))
        self.assertIs(evaluate_freshness(newest_end, self.now), Freshness.FRESH)

    def test_card_exactly_at_the_threshold_is_unknown(self):
        newest_end = self.now - timedelta(minutes=25)
        self.assertIs(evaluate_freshness(newest_end, self.now), Freshness.UNKNOWN)

    def test_card_older_than_the_threshold_is_unknown(self):
        newest_end = self.now - timedelta(minutes=26)
        self.assertIs(evaluate_freshness(newest_end, self.now), Freshness.UNKNOWN)

    def test_missing_newest_card_is_unknown(self):
        self.assertIs(evaluate_freshness(None, self.now), Freshness.UNKNOWN)

    def test_card_ending_slightly_in_the_future_is_fresh(self):
        newest_end = self.now + timedelta(minutes=2)
        self.assertIs(evaluate_freshness(newest_end, self.now), Freshness.FRESH)

    def test_threshold_is_injectable(self):
        twelve_minutes_old = self.now - timedelta(minutes=12)
        nine_minutes_old = self.now - timedelta(minutes=9)
        self.assertIs(
            evaluate_freshness(twelve_minutes_old, self.now, threshold_minutes=10),
            Freshness.UNKNOWN,
        )
        self.assertIs(
            evaluate_freshness(nine_minutes_old, self.now, threshold_minutes=10),
            Freshness.FRESH,
        )

    def test_default_threshold_is_25_minutes(self):
        self.assertEqual(FRESHNESS_THRESHOLD_MINUTES, 25)


if __name__ == "__main__":
    unittest.main()
