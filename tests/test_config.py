"""Behavior of the environment-driven configuration.

Every runtime value comes from exactly three DFN_* variables with sane
defaults; anything missing, empty, or malformed falls back, so a broken
environment can never crash a tick.
"""

import dataclasses
import os
import unittest
from unittest import mock

from dayflow_nudge.config import Config, load_config


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


class VariableSurfaceTest(unittest.TestCase):
    def test_only_the_dfn_variables_are_consulted(self):
        strict = _OnlyDfnEnv({"DFN_POLL_SECONDS": "45"})
        self.assertEqual(load_config(strict).poll_seconds, 45)

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
