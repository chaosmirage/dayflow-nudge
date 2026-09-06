"""Behavior of the environment-driven configuration.

Every runtime value comes from exactly eight DFN_* variables with sane
defaults. An absent or empty value is the silent documented happy path
(or every unset knob would warn on every tick); a present but malformed
value yields that knob's documented default plus exactly one warning
line, so a broken environment can never crash a tick and can never go
unnoticed either.
"""

import dataclasses
import datetime
import os
import unittest
from unittest import mock

from dayflow_nudge import notifier
from dayflow_nudge.config import Config, load_config

#: The published knob vocabulary, spelled once more so any drift between
#: the parsers and the surfaces that document them fails here.
PUBLISHED_KNOBS = frozenset({
    "DFN_DISABLE", "DFN_NOTIFIER", "DFN_POLL_SECONDS", "DFN_STYLE",
    "DFN_DAYS", "DFN_QUIET_START", "DFN_QUIET_END", "DFN_DB_PATH",
})

MONDAY_THROUGH_FRIDAY = frozenset({0, 1, 2, 3, 4})


class ConfigTestCase(unittest.TestCase):
    """Shared helper: the warning lines one load emits, none omitted."""

    def warnings_from(self, environ):
        """(config, warning lines) for one load; no lines means none."""
        try:
            with self.assertLogs("dayflow_nudge", level="WARNING") as captured:
                config = load_config(environ)
        except AssertionError:
            # assertLogs raises when nothing was logged: the silent path.
            return load_config(environ), []
        return config, [record.getMessage()
                        for record in captured.records]


class DefaultsTest(unittest.TestCase):
    def test_empty_environment_yields_the_defaults(self):
        self.assertEqual(load_config({}), Config())

    def test_defaults_are_enabled_applet_and_sixty_seconds(self):
        config = Config()
        self.assertFalse(config.disable)
        self.assertEqual(config.notifier, "applet")
        self.assertEqual(config.poll_seconds, 60)

    def test_process_environment_is_the_default_source(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(load_config(), Config())


class DisableFlagTest(unittest.TestCase):
    def test_arms_only_on_the_exact_token_one(self):
        self.assertTrue(load_config({"DFN_DISABLE": "1"}).disable)

    def test_does_not_arm_on_any_other_value(self):
        for value in ("0", "true", "TRUE", "yes", " ", ""):
            with self.subTest(value=value):
                self.assertFalse(load_config({"DFN_DISABLE": value}).disable)


class NotifierChannelTest(unittest.TestCase):
    def test_absent_or_unknown_value_means_the_applet_channel(self):
        for value in ("", "applet", "APPLET", "terminal-notifier"):
            with self.subTest(value=value):
                self.assertEqual(
                    load_config({"DFN_NOTIFIER": value}).notifier, "applet"
                )

    def test_fallback_value_selects_the_osascript_channel(self):
        self.assertEqual(
            load_config({"DFN_NOTIFIER": "oscript"}).notifier, "osascript"
        )


class PollSecondsTest(unittest.TestCase):
    def test_well_formed_value_is_used(self):
        self.assertEqual(
            load_config({"DFN_POLL_SECONDS": "30"}).poll_seconds, 30
        )

    def test_malformed_value_falls_back_to_sixty(self):
        for value in ("abc", "1.5", "", "   "):
            with self.subTest(value=value):
                self.assertEqual(
                    load_config({"DFN_POLL_SECONDS": value}).poll_seconds, 60
                )

    def test_non_positive_value_falls_back_to_sixty(self):
        for value in ("0", "-5"):
            with self.subTest(value=value):
                self.assertEqual(
                    load_config({"DFN_POLL_SECONDS": value}).poll_seconds, 60
                )


class StyleTest(unittest.TestCase):
    def test_the_window_surface_is_the_default(self):
        self.assertEqual(load_config({}).style, "window")

    def test_missing_style_means_the_window(self):
        self.assertEqual(load_config({}).style, "window")

    def test_the_notification_token_selects_notifications(self):
        config = load_config({"DFN_STYLE": "notification"})
        self.assertEqual(config.style, "notification")

    def test_a_malformed_style_falls_back_to_the_window(self):
        config = load_config({"DFN_STYLE": "banner"})
        self.assertEqual(config.style, "window")


class WeekdaysTest(ConfigTestCase):
    def test_the_default_operating_week_is_monday_through_friday(self):
        self.assertEqual(
            load_config({}).weekdays, MONDAY_THROUGH_FRIDAY)

    def test_an_absent_value_means_the_default_week_silently(self):
        config, lines = self.warnings_from({})
        self.assertEqual(config.weekdays, MONDAY_THROUGH_FRIDAY)
        self.assertEqual(lines, [])

    def test_three_letter_and_full_names_name_the_same_day(self):
        for spelling in ("mon", "monday", "MON", " Monday "):
            with self.subTest(spelling=spelling):
                self.assertEqual(
                    load_config({"DFN_DAYS": spelling}).weekdays,
                    frozenset({0}))

    def test_a_comma_list_drops_empty_segments_and_duplicates(self):
        config = load_config({"DFN_DAYS": "Mon, monday,,sat,  sun "})
        self.assertEqual(config.weekdays, frozenset({0, 5, 6}))

    def test_the_whole_week_is_expressible(self):
        self.assertEqual(
            load_config({"DFN_DAYS": "mon,tue,wed,thu,fri,sat,sun"}).weekdays,
            frozenset({0, 1, 2, 3, 4, 5, 6}))

    def test_an_unknown_token_invalidates_the_whole_value_with_one_warning(self):
        config, lines = self.warnings_from({"DFN_DAYS": "mon,funday"})
        self.assertEqual(config.weekdays, MONDAY_THROUGH_FRIDAY)
        self.assertEqual(len(lines), 1)
        self.assertIn("config_default", lines[0])
        self.assertIn("knob=DFN_DAYS", lines[0])

    def test_a_value_of_only_commas_invalidates_the_whole_value(self):
        config, lines = self.warnings_from({"DFN_DAYS": ",,,"})
        self.assertEqual(config.weekdays, MONDAY_THROUGH_FRIDAY)
        self.assertEqual(len(lines), 1)

    def test_a_whitespace_only_value_is_the_silent_default(self):
        config, lines = self.warnings_from({"DFN_DAYS": "   "})
        self.assertEqual(config.weekdays, MONDAY_THROUGH_FRIDAY)
        self.assertEqual(lines, [])

    def test_the_week_is_an_immutable_field_of_the_config(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            load_config({}).weekdays = frozenset({6})


class QuietBoundsTest(ConfigTestCase):
    def test_the_default_window_is_eight_pm_to_eight_am(self):
        config = load_config({})
        self.assertEqual(config.quiet_start, datetime.time(20, 0))
        self.assertEqual(config.quiet_end, datetime.time(8, 0))

    def test_both_spellings_of_the_hour_are_accepted(self):
        for spelling in ("8:00", "08:00"):
            with self.subTest(spelling=spelling):
                config = load_config({"DFN_QUIET_END": spelling})
                self.assertEqual(config.quiet_end, datetime.time(8, 0))

    def test_an_intraday_window_is_configurable(self):
        config = load_config(
            {"DFN_QUIET_START": "13:00", "DFN_QUIET_END": "14:30"})
        self.assertEqual(config.quiet_start, datetime.time(13, 0))
        self.assertEqual(config.quiet_end, datetime.time(14, 30))

    def test_a_malformed_bound_falls_back_alone_with_one_warning(self):
        config, lines = self.warnings_from(
            {"DFN_QUIET_START": "25:00", "DFN_QUIET_END": "09:00"})
        self.assertEqual(config.quiet_start, datetime.time(20, 0))
        self.assertEqual(config.quiet_end, datetime.time(9, 0))
        self.assertEqual(len(lines), 1)
        self.assertIn("knob=DFN_QUIET_START", lines[0])

    def test_a_bound_equal_to_its_partner_invalidates_the_pair(self):
        config, lines = self.warnings_from(
            {"DFN_QUIET_START": "12:00", "DFN_QUIET_END": "12:00"})
        self.assertEqual(config.quiet_start, datetime.time(20, 0))
        self.assertEqual(config.quiet_end, datetime.time(8, 0))
        self.assertEqual(len(lines), 1)
        self.assertIn("DFN_QUIET_START", lines[0])
        self.assertIn("DFN_QUIET_END", lines[0])

    def test_each_malformed_bound_warns_on_its_own_line(self):
        config, lines = self.warnings_from(
            {"DFN_QUIET_START": "late", "DFN_QUIET_END": "8:0"})
        self.assertEqual(config.quiet_start, datetime.time(20, 0))
        self.assertEqual(config.quiet_end, datetime.time(8, 0))
        self.assertEqual(len(lines), 2)

    def test_absent_bounds_mean_the_defaults_silently(self):
        config, lines = self.warnings_from({"DFN_QUIET_START": "  "})
        self.assertEqual(config.quiet_start, datetime.time(20, 0))
        self.assertEqual(config.quiet_end, datetime.time(8, 0))
        self.assertEqual(lines, [])


class DbPathTest(ConfigTestCase):
    def test_absent_or_empty_means_the_default_store_path_silently(self):
        for environ in ({}, {"DFN_DB_PATH": ""}, {"DFN_DB_PATH": "  "}):
            with self.subTest(environ=environ):
                config, lines = self.warnings_from(environ)
                self.assertEqual(config.db_path, "")
                self.assertEqual(lines, [])

    def test_a_present_value_is_kept_verbatim(self):
        config = load_config({"DFN_DB_PATH": "/tmp/elsewhere/chunks.sqlite"})
        self.assertEqual(config.db_path, "/tmp/elsewhere/chunks.sqlite")

    def test_a_multiline_value_falls_back_with_one_warning(self):
        config, lines = self.warnings_from(
            {"DFN_DB_PATH": "/tmp/a\n/tmp/b"})
        self.assertEqual(config.db_path, "")
        self.assertEqual(len(lines), 1)
        self.assertIn("knob=DFN_DB_PATH", lines[0])


class PosterPayloadCollisionTest(unittest.TestCase):
    def test_the_poster_writes_only_the_style_name_among_the_knobs(self):
        # The poster payload rides its own variables into the child
        # process only; the single shared name is the style, which the
        # poster overwrites per delivery by design.
        with mock.patch.dict(os.environ, {}, clear=True):
            env = notifier._build_env("Title", "Body", False, "window")
        written = frozenset(env)
        self.assertEqual(written & PUBLISHED_KNOBS, {"DFN_STYLE"})
        self.assertEqual(
            written - {"DFN_STYLE"},
            {"DFN_TITLE", "DFN_BODY", "DFN_SOUND"})


class VariableSurfaceTest(unittest.TestCase):
    def test_only_the_dfn_variables_are_consulted(self):
        strict = _OnlyDfnEnv({"DFN_POLL_SECONDS": "45", "DFN_DAYS": "sat,sun"})
        config = load_config(strict)
        self.assertEqual(config.poll_seconds, 45)
        self.assertEqual(config.weekdays, frozenset({5, 6}))

    def test_config_is_an_immutable_value_object(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            load_config({}).disable = True


class _OnlyDfnEnv(dict):
    """Environment double that fails the test if anything outside DFN_* is read."""

    def __getitem__(self, key):
        self._check(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        self._check(key)
        return super().get(key, default)

    def __iter__(self):
        raise AssertionError(
            "configuration must fetch named variables, not scan the environment"
        )

    @staticmethod
    def _check(key):
        if not key.startswith("DFN_"):
            raise AssertionError("read outside the DFN_* surface: " + str(key))


if __name__ == "__main__":
    unittest.main()
