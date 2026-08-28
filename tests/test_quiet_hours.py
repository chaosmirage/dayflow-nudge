"""Behavior of the quiet-hours gate.

The window runs from 23:00 to 09:00 and crosses midnight, so the boundary
instants themselves decide the rule: the evening start is inside the window,
the morning end is outside it, and every instant between the two -- including
the small hours after midnight -- is inside.
"""

import datetime
import unittest

from dayflow_nudge.quiet_hours import QUIET_END, QUIET_START, is_quiet


class QuietHoursBoundaryTest(unittest.TestCase):
    def test_the_minute_before_eleven_pm_is_loud(self):
        self.assertFalse(is_quiet(datetime.time(22, 59)))

    def test_eleven_pm_exactly_is_quiet(self):
        self.assertTrue(is_quiet(datetime.time(23, 0)))

    def test_half_past_midnight_is_quiet(self):
        self.assertTrue(is_quiet(datetime.time(0, 30)))

    def test_the_minute_before_nine_is_quiet(self):
        self.assertTrue(is_quiet(datetime.time(8, 59)))

    def test_nine_am_exactly_is_loud(self):
        self.assertFalse(is_quiet(datetime.time(9, 0)))

    def test_midday_is_loud(self):
        self.assertFalse(is_quiet(datetime.time(12, 0)))


class QuietHoursClockReadingTest(unittest.TestCase):
    def test_a_full_clock_reading_is_accepted(self):
        # the caller feeds the cycle clock straight into the gate, so a full
        # datetime must behave exactly like its time-of-day component
        self.assertTrue(is_quiet(datetime.datetime(2026, 8, 28, 23, 30)))
        self.assertTrue(is_quiet(datetime.datetime(2026, 8, 28, 0, 30)))
        self.assertFalse(is_quiet(datetime.datetime(2026, 8, 28, 12, 0)))

    def test_anything_but_a_time_or_clock_reading_is_rejected(self):
        with self.assertRaises(TypeError):
            is_quiet("23:00")


class QuietHoursPinningTest(unittest.TestCase):
    def test_the_window_is_pinned_to_eleven_pm_through_nine_am(self):
        self.assertEqual(QUIET_START, datetime.time(23, 0))
        self.assertEqual(QUIET_END, datetime.time(9, 0))


if __name__ == "__main__":
    unittest.main()
