"""Behavioral tests for notification delivery: the text boundary, channel
selection, the exact command form handed to the delivery runner, and the
outcome of a delivery attempt."""

import dataclasses
import enum
import os
import subprocess
import sys
import tempfile
import types
import unittest

NOTIFIER_LOGGER = "dayflow_nudge.notifier"


def _ensure_delivery_contracts():
    """Return the shared delivery contracts, standing in locally with the
    same shape when the shared module is unavailable, so delivery behavior
    stays testable in isolation."""
    try:
        import dayflow_nudge.models as contracts
        return contracts
    except ImportError:
        contracts = types.ModuleType("dayflow_nudge.models")

        @dataclasses.dataclass
        class NudgeCommand:
            title: str = ""
            body: str = ""
            sound: bool = False

        class DeliveryResult(str, enum.Enum):
            SENT = "SENT"
            FAILED = "FAILED"

        contracts.NudgeCommand = NudgeCommand
        contracts.DeliveryResult = DeliveryResult
        sys.modules["dayflow_nudge.models"] = contracts
        return contracts


_CONTRACTS = _ensure_delivery_contracts()
NudgeCommand = _CONTRACTS.NudgeCommand
DeliveryResult = _CONTRACTS.DeliveryResult

# Imported only after the contracts above are in place.
import dayflow_nudge.notifier as notifier


class RecordingRunner:
    """Stands in for the delivery runner, recording every command it receives."""

    def __init__(self, outcomes):
        self.attempts = []
        self._outcomes = list(outcomes)

    def __call__(self, argv, timeout=None, env=None):
        self.attempts.append(
            {"argv": argv, "timeout": timeout, "env": env})
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return subprocess.CompletedProcess(argv, outcome)


class SanitizeTextTest(unittest.TestCase):
    def test_removes_newlines_and_control_characters(self):
        self.assertEqual(
            notifier.sanitize_text("Dis\x00tract\x1fion\x9f\r\nnow", 200),
            "Distractionnow",
        )

    def test_caps_title_at_eighty_characters(self):
        self.assertEqual(notifier.sanitize_text("t" * 120, 80), "t" * 80)

    def test_caps_body_at_two_hundred_characters(self):
        self.assertEqual(notifier.sanitize_text("b" * 300, 200), "b" * 200)

    def test_leaves_plain_text_unchanged(self):
        self.assertEqual(notifier.sanitize_text("Back to the plan", 200),
                         "Back to the plan")


class ApplescriptLiteralTest(unittest.TestCase):
    def test_wraps_plain_value_in_double_quotes(self):
        self.assertEqual(notifier.applescript_literal("plain"), '"plain"')

    def test_escapes_double_quotes(self):
        self.assertEqual(notifier.applescript_literal('He said "hi"'),
                         '"He said \\"hi\\""')

    def test_escapes_backslash_before_quote(self):
        # A backslash must be escaped first, otherwise the quote-escape's own
        # backslash gets doubled and the literal breaks.
        backslash_then_quote = "\\" + '"'
        self.assertEqual(
            notifier.applescript_literal(backslash_then_quote),
            '"' + "\\\\" + '\\"' + '"',
        )


class AppletChannelTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.applet_path = os.path.join(
            tmp.name, "DayflowNudge.app", "Contents", "MacOS", "applet")
        os.makedirs(os.path.dirname(self.applet_path))
        with open(self.applet_path, "w", encoding="utf-8") as handle:
            handle.write("#!stub\n")
        # No styled window poster here: these tests exercise the applet
        # dialog fallback, so the window path must point nowhere real.
        self.missing_window = os.path.join(
            tempfile.gettempdir(), "dayflow-nudge-no-such-window-poster")

    def test_runs_the_applet_binary_with_the_payload_in_the_environment(self):
        runner = RecordingRunner([0])
        result = notifier.deliver(
            NudgeCommand(title="Focus drift", body="Back to the plan"),
            runner=runner,
            applet_path=self.applet_path,
            window_path=self.missing_window,
        )
        self.assertEqual(len(runner.attempts), 1)
        argv = runner.attempts[0]["argv"]
        # An argv list of plain strings cannot involve a shell by construction;
        # the applet itself takes no arguments at all.
        self.assertEqual(argv, [self.applet_path])
        env = runner.attempts[0]["env"]
        self.assertEqual(env["DFN_TITLE"], "Focus drift")
        self.assertEqual(env["DFN_BODY"], "Back to the plan")
        self.assertEqual(env["DFN_SOUND"], "")
        # The window surface is the default style.
        self.assertEqual(env["DFN_STYLE"], "window")
        # The inherited environment survives alongside the overrides.
        for key, value in os.environ.items():
            self.assertEqual(env.get(key), value)
        self.assertEqual(runner.attempts[0]["timeout"], 10)
        self.assertEqual(result, DeliveryResult.SENT)

    def test_the_applet_environment_carries_an_explicit_style(self):
        runner = RecordingRunner([0])
        notifier.deliver(
            NudgeCommand(title="Focus drift", body="Back to the plan"),
            style="notification",
            runner=runner,
            applet_path=self.applet_path,
        )
        self.assertEqual(
            runner.attempts[0]["env"]["DFN_STYLE"], "notification")

    def test_sets_the_sound_flag_for_escalated_nudges(self):
        runner = RecordingRunner([0])
        notifier.deliver(
            NudgeCommand(title="Focus drift", body="Back to the plan", sound=True),
            runner=runner,
            applet_path=self.applet_path,
            window_path=self.missing_window,
        )
        self.assertEqual(runner.attempts[0]["env"]["DFN_SOUND"], "sound")

    def test_passes_sanitized_values_through_the_environment(self):
        runner = RecordingRunner([0])
        notifier.deliver(
            NudgeCommand(
                title="Dis\x00tract\x1fion\r\nnow " + "x" * 100,
                body="b" * 300,
            ),
            runner=runner,
            applet_path=self.applet_path,
            window_path=self.missing_window,
        )
        env = runner.attempts[0]["env"]
        self.assertEqual(env["DFN_TITLE"], "Distractionnow " + "x" * 65)
        self.assertEqual(env["DFN_BODY"], "b" * 200)

    def test_a_title_only_command_carries_an_empty_body_variable(self):
        runner = RecordingRunner([0])
        notifier.deliver(
            NudgeCommand(title="Reddit scroll", body=""),
            runner=runner,
            applet_path=self.applet_path,
            window_path=self.missing_window,
        )
        # the empty body is delivered as an explicit empty variable, never
        # collapsed away, so the notification shows the card name only
        env = runner.attempts[0]["env"]
        self.assertEqual(env["DFN_TITLE"], "Reddit scroll")
        self.assertEqual(env["DFN_BODY"], "")


class WindowPosterTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = os.path.join(tmp.name, "Library")
        self.applet_path = os.path.join(
            base, "DayflowNudge.app", "Contents", "MacOS", "applet")
        self.window_path = os.path.join(
            base, "DayflowNudgeWindow.app", "Contents", "MacOS",
            "DayflowNudgeWindow")
        for path in (self.applet_path, self.window_path):
            os.makedirs(os.path.dirname(path))
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("#!stub\n")

    def test_the_window_style_prefers_the_styled_poster(self):
        runner = RecordingRunner([0])
        result = notifier.deliver(
            NudgeCommand(title="Focus drift", body="Back to the plan"),
            runner=runner,
            applet_path=self.applet_path,
            window_path=self.window_path,
        )
        argv = runner.attempts[0]["argv"]
        env = runner.attempts[0]["env"]
        self.assertEqual(argv, [self.window_path])
        self.assertEqual(env["DFN_TITLE"], "Focus drift")
        self.assertEqual(env["DFN_BODY"], "Back to the plan")
        self.assertEqual(env["DFN_STYLE"], "window")
        self.assertEqual(result, DeliveryResult.SENT)

    def test_the_notification_style_uses_the_applet(self):
        runner = RecordingRunner([0])
        notifier.deliver(
            NudgeCommand(title="Focus drift", body="Back to the plan"),
            style="notification",
            runner=runner,
            applet_path=self.applet_path,
            window_path=self.window_path,
        )
        self.assertEqual(
            runner.attempts[0]["argv"], [self.applet_path])
        self.assertEqual(
            runner.attempts[0]["env"]["DFN_STYLE"], "notification")

    def test_a_missing_window_poster_falls_back_to_the_applet_dialog(self):
        missing_window = os.path.join(
            tempfile.gettempdir(), "dayflow-nudge-no-such-window-poster")
        runner = RecordingRunner([0])
        notifier.deliver(
            NudgeCommand(title="Focus drift", body="Back to the plan"),
            runner=runner,
            applet_path=self.applet_path,
            window_path=missing_window,
        )
        self.assertEqual(runner.attempts[0]["argv"], [self.applet_path])
        self.assertEqual(
            runner.attempts[0]["env"]["DFN_STYLE"], "window")


class OsascriptFallbackTest(unittest.TestCase):
    def test_runs_osascript_when_it_is_the_preferred_channel(self):
        runner = RecordingRunner([0])
        result = notifier.deliver(
            NudgeCommand(title="Focus drift", body="Back to the plan"),
            preferred_channel="oscript",
            runner=runner,
        )
        # The fallback inherits the environment unchanged.
        self.assertIsNone(runner.attempts[0]["env"])
        argv = runner.attempts[0]["argv"]
        self.assertIsInstance(argv, list)
        self.assertTrue(all(isinstance(item, str) for item in argv))
        self.assertEqual(argv[0], "osascript")
        self.assertEqual(argv[1], "-e")
        # The default style is the centered window.
        self.assertIn("display dialog", argv[2])
        self.assertIn('"Back to the plan"', argv[2])
        self.assertIn('with title "Focus drift"', argv[2])
        self.assertEqual(runner.attempts[0]["timeout"], 10)
        self.assertEqual(result, DeliveryResult.SENT)

    def test_the_notification_style_keeps_the_notification_source(self):
        runner = RecordingRunner([0])
        notifier.deliver(
            NudgeCommand(title="Focus drift", body="Back to the plan"),
            preferred_channel="oscript",
            style="notification",
            runner=runner,
        )
        source = runner.attempts[0]["argv"][2]
        self.assertIn("display notification", source)
        self.assertIn('display notification "Back to the plan"', source)
        self.assertNotIn("display dialog", source)

    def test_falls_back_when_the_applet_binary_is_missing(self):
        runner = RecordingRunner([0])
        missing = os.path.join(
            tempfile.gettempdir(), "dayflow-nudge-no-such-applet-binary")
        result = notifier.deliver(
            NudgeCommand(title="Focus drift", body="Back to the plan"),
            runner=runner,
            applet_path=missing,
        )
        self.assertEqual(runner.attempts[0]["argv"][0], "osascript")
        self.assertEqual(result, DeliveryResult.SENT)

    def test_assembles_source_only_from_escaped_literals(self):
        runner = RecordingRunner([0])
        notifier.deliver(
            NudgeCommand(
                title='He said "hi"',
                body="half\\twice\r\nwith a newline",
            ),
            preferred_channel="oscript",
            style="notification",
            runner=runner,
        )
        source = runner.attempts[0]["argv"][2]
        self.assertIn('with title "He said \\"hi\\""', source)
        self.assertIn('display notification "half\\\\twicewith a newline"', source)
        self.assertNotIn("\r", source)

    def test_adds_the_sound_name_for_escalated_notification_nudges(self):
        runner = RecordingRunner([0])
        notifier.deliver(
            NudgeCommand(title="Focus drift", body="Back to the plan", sound=True),
            preferred_channel="oscript",
            style="notification",
            runner=runner,
        )
        source = runner.attempts[0]["argv"][2]
        self.assertTrue(source.endswith('sound name "Glass"'))

    def test_an_escalated_window_beeps_before_the_dialog(self):
        runner = RecordingRunner([0])
        notifier.deliver(
            NudgeCommand(title="Focus drift", body="Back to the plan", sound=True),
            preferred_channel="oscript",
            runner=runner,
        )
        source = runner.attempts[0]["argv"][2]
        self.assertTrue(source.startswith("beep 2"))
        self.assertIn("display dialog", source)

    def test_the_window_source_gives_up_by_itself(self):
        runner = RecordingRunner([0])
        notifier.deliver(
            NudgeCommand(title="Focus drift", body="Back to the plan"),
            preferred_channel="oscript",
            runner=runner,
        )
        source = runner.attempts[0]["argv"][2]
        self.assertIn("giving up after 30", source)
        self.assertIn('"Back to work"', source)


class DeliveryOutcomeTest(unittest.TestCase):
    def _applet_path(self):
        handle, path = tempfile.mkstemp()
        os.close(handle)
        self.addCleanup(os.unlink, path)
        return path

    def _deliver(self, runner):
        return notifier.deliver(
            NudgeCommand(title="Focus drift", body="Back to the plan"),
            runner=runner,
            applet_path=self._applet_path(),
            window_path=os.path.join(
                tempfile.gettempdir(), "dayflow-nudge-no-such-window-poster"),
        )

    def test_zero_exit_status_reports_sent_with_one_log_line(self):
        runner = RecordingRunner([0])
        with self.assertLogs(NOTIFIER_LOGGER, level="INFO") as captured:
            result = self._deliver(runner)
        self.assertEqual(result, DeliveryResult.SENT)
        self.assertEqual(len(captured.records), 1)
        line = captured.records[0].getMessage()
        self.assertIn("channel=applet", line)
        self.assertIn("exit 0", line)

    def test_nonzero_exit_status_reports_failed_with_one_log_line(self):
        runner = RecordingRunner([1])
        with self.assertLogs(NOTIFIER_LOGGER, level="INFO") as captured:
            result = self._deliver(runner)
        self.assertEqual(result, DeliveryResult.FAILED)
        self.assertEqual(len(captured.records), 1)
        line = captured.records[0].getMessage()
        self.assertIn("channel=applet", line)
        self.assertIn("exit 1", line)

    def test_timeout_reports_failed_without_raising(self):
        runner = RecordingRunner(
            [subprocess.TimeoutExpired(cmd=["poster"], timeout=10)])
        with self.assertLogs(NOTIFIER_LOGGER, level="INFO") as captured:
            result = self._deliver(runner)
        self.assertEqual(result, DeliveryResult.FAILED)
        self.assertIn("timeout", captured.records[0].getMessage())

    def test_unlaunchable_command_reports_failed_without_raising(self):
        runner = RecordingRunner([FileNotFoundError("poster is gone")])
        with self.assertLogs(NOTIFIER_LOGGER, level="INFO") as captured:
            result = self._deliver(runner)
        self.assertEqual(result, DeliveryResult.FAILED)
        self.assertIn("cannot launch", captured.records[0].getMessage())

    def test_a_failed_delivery_attempts_exactly_one_command(self):
        runner = RecordingRunner([27])
        result = self._deliver(runner)
        self.assertEqual(result, DeliveryResult.FAILED)
        self.assertEqual(len(runner.attempts), 1)


if __name__ == "__main__":
    unittest.main()
