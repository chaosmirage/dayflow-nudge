"""Behavior of the calendar suppression gates.

The default quiet window runs from 20:00 to 08:00 and crosses midnight,
so the boundary instants themselves decide the rule: the evening start
is inside the window, the morning end is outside it, and every instant
between the two -- including the small hours after midnight -- is
inside. Explicit bounds choose between two readings with the same
inclusivity: a crossing window (start after end) answers by disjunction
and an intraday window (start before end) answers as a range, both with
the start inclusive and the end exclusive. The weekday gate answers
membership in the operating set for all seven days of the week.
"""

import dataclasses
import datetime
import unittest

from dayflow_nudge import quiet_hours
from dayflow_nudge.quiet_hours import QUIET_END, QUIET_START, is_quiet


class QuietHoursBoundaryTest(unittest.TestCase):
    def test_the_minute_before_eight_pm_is_loud(self):
        self.assertFalse(is_quiet(datetime.time(19, 59)))

    def test_eight_pm_exactly_is_quiet(self):
        self.assertTrue(is_quiet(datetime.time(20, 0)))

    def test_the_minute_before_eleven_pm_is_quiet(self):
        self.assertTrue(is_quiet(datetime.time(22, 59)))

    def test_half_past_midnight_is_quiet(self):
        self.assertTrue(is_quiet(datetime.time(0, 30)))

    def test_the_minute_before_nine_is_quiet(self):
        self.assertTrue(is_quiet(datetime.time(7, 59)))

    def test_nine_am_exactly_is_loud(self):
        self.assertFalse(is_quiet(datetime.time(8, 0)))

    def test_midday_is_loud(self):
        self.assertFalse(is_quiet(datetime.time(12, 0)))


class QuietHoursClockReadingTest(unittest.TestCase):
    def test_a_full_clock_reading_is_accepted(self):
        # the caller feeds the cycle clock straight into the gate, so a full
        # datetime must behave exactly like its time-of-day component
        self.assertTrue(is_quiet(datetime.datetime(2026, 8, 28, 20, 30)))
        self.assertTrue(is_quiet(datetime.datetime(2026, 8, 28, 0, 30)))
        self.assertFalse(is_quiet(datetime.datetime(2026, 8, 28, 12, 0)))

    def test_anything_but_a_time_or_clock_reading_is_rejected(self):
        with self.assertRaises(TypeError):
            is_quiet("23:00")


class QuietHoursPinningTest(unittest.TestCase):
    def test_the_window_is_pinned_to_eight_pm_through_eight_am(self):
        self.assertEqual(QUIET_START, datetime.time(20, 0))
        self.assertEqual(QUIET_END, datetime.time(8, 0))

    def test_the_default_operating_week_is_pinned_to_monday_through_friday(self):
        self.assertEqual(
            quiet_hours.DEFAULT_WEEKDAYS, frozenset({0, 1, 2, 3, 4}))

    def test_the_module_default_calendar_holds_the_pinned_defaults(self):
        expected = quiet_hours.OperatingCalendar(
            weekdays=frozenset({0, 1, 2, 3, 4}),
            quiet_start=datetime.time(20, 0),
            quiet_end=datetime.time(8, 0))
        self.assertEqual(quiet_hours.DEFAULT_CALENDAR, expected)

    def test_the_calendar_is_a_frozen_value(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            quiet_hours.DEFAULT_CALENDAR.weekdays = frozenset()


class ExplicitQuietBoundsTest(unittest.TestCase):
    """Membership under caller-chosen bounds: crossing versus intraday."""

    def test_a_crossing_window_keeps_the_disjunction_reading(self):
        start, end = datetime.time(22, 0), datetime.time(6, 0)
        self.assertFalse(is_quiet(datetime.time(21, 59), start, end))
        self.assertTrue(is_quiet(datetime.time(22, 0), start, end))
        self.assertTrue(is_quiet(datetime.time(3, 0), start, end))
        self.assertTrue(is_quiet(datetime.time(5, 59), start, end))
        self.assertFalse(is_quiet(datetime.time(6, 0), start, end))

    def test_an_intraday_window_answers_as_a_range(self):
        start, end = datetime.time(9, 0), datetime.time(17, 0)
        self.assertFalse(is_quiet(datetime.time(8, 59), start, end))
        self.assertTrue(is_quiet(datetime.time(9, 0), start, end))
        self.assertTrue(is_quiet(datetime.time(12, 0), start, end))
        self.assertTrue(is_quiet(datetime.time(16, 59), start, end))
        self.assertFalse(is_quiet(datetime.time(17, 0), start, end))

    def test_equal_bounds_read_as_an_empty_never_quiet_window(self):
        # both parse layers reject equal bounds; a hand-built bundle still
        # needs a deterministic answer, and it is the never-quiet reading
        bound = datetime.time(12, 0)
        for moment in (datetime.time(11, 59), bound, datetime.time(12, 1)):
            with self.subTest(moment=moment):
                self.assertFalse(is_quiet(moment, bound, bound))


class OffScheduleTest(unittest.TestCase):
    """The weekday gate across all seven days and custom operating sets."""

    #: One noon per weekday: 2026-08-31 is a Monday.
    SEVEN_NOONS = (
        (0, datetime.datetime(2026, 8, 31, 12, 0)),
        (1, datetime.datetime(2026, 9, 1, 12, 0)),
        (2, datetime.datetime(2026, 9, 2, 12, 0)),
        (3, datetime.datetime(2026, 9, 3, 12, 0)),
        (4, datetime.datetime(2026, 9, 4, 12, 0)),
        (5, datetime.datetime(2026, 8, 29, 12, 0)),
        (6, datetime.datetime(2026, 8, 30, 12, 0)),
    )

    def test_every_day_answers_at_the_default_operating_week(self):
        for weekday, moment in self.SEVEN_NOONS:
            with self.subTest(weekday=weekday):
                expected = weekday not in {0, 1, 2, 3, 4}
                self.assertIs(quiet_hours.is_off_schedule(moment), expected)

    def test_a_custom_operating_set_is_honored(self):
        weekend_only = frozenset({5, 6})
        self.assertFalse(quiet_hours.is_off_schedule(
            datetime.datetime(2026, 8, 29, 12, 0), weekend_only))
        self.assertTrue(quiet_hours.is_off_schedule(
            datetime.datetime(2026, 8, 31, 12, 0), weekend_only))

    def test_a_full_clock_reading_is_required(self):
        with self.assertRaises(TypeError):
            quiet_hours.is_off_schedule("monday")
        with self.assertRaises(TypeError):
            quiet_hours.is_off_schedule(datetime.time(12, 0))


if __name__ == "__main__":
    unittest.main()
