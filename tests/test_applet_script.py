"""Static contract checks on the committed notification poster sources: the
applet must notify (never dialog), read its values from the environment, and
honor the sound variable; the build script must give the bundle a stable
identifier so the notification center can register the app."""

import os
import unittest

APPLET_SOURCE_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), os.pardir, "scripts", "applet.applescript"))
WINDOW_SOURCE_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), os.pardir, "scripts", "window.swift"))
BUILD_SCRIPT_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), os.pardir, "scripts", "build_applet.sh"))


def read_applet_source():
    with open(APPLET_SOURCE_PATH, "r", encoding="utf-8") as handle:
        return handle.read()


def read_build_script():
    with open(BUILD_SCRIPT_PATH, "r", encoding="utf-8") as handle:
        return handle.read()


class AppletScriptContractTest(unittest.TestCase):
    def test_the_applet_source_is_committed(self):
        self.assertTrue(os.path.isfile(APPLET_SOURCE_PATH))

    def test_displays_a_notification(self):
        self.assertIn("display notification", read_applet_source())

    def test_takes_title_and_body_from_environment_variables(self):
        # Compiled applets on current macOS receive no command-line
        # arguments, so the payload rides the environment instead.
        source = read_applet_source()
        self.assertIn('system attribute "DFN_TITLE"', source)
        self.assertIn('system attribute "DFN_BODY"', source)
        self.assertIn('system attribute "DFN_SOUND"', source)

    def test_reads_no_command_line_arguments(self):
        source = read_applet_source()
        self.assertNotIn("on run argv", source)
        self.assertNotIn("item 1", source)

    def test_defaults_keep_missing_values_from_erroring(self):
        # Every read value falls back before use, so no invocation path can
        # raise (and a raised AppleScript error would surface as a dialog).
        source = read_applet_source()
        self.assertIn("missing value", source)

    def test_honors_the_sound_variable(self):
        source = read_applet_source()
        self.assertIn('"sound"', source)
        self.assertIn('sound name "Glass"', source)

    def test_the_default_surface_is_a_centered_dialog_that_gives_up(self):
        # The architect's standing choice: a window in the middle of the
        # screen. It must dismiss itself, so nothing ever blocks the
        # machine on a forgotten dialog.
        source = read_applet_source()
        self.assertIn("display dialog", source)
        self.assertIn("giving up after 30", source)
        self.assertIn('"Back to work"', source)

    def test_the_notification_surface_stays_available(self):
        # DFN_STYLE=notification selects the standard notification instead
        # of the window.
        source = read_applet_source()
        self.assertIn('"notification"', source)
        self.assertIn("display notification", source)


class BuildScriptContractTest(unittest.TestCase):
    def test_the_build_script_is_committed(self):
        self.assertTrue(os.path.isfile(BUILD_SCRIPT_PATH))

    def test_assigns_a_stable_bundle_identifier(self):
        # Without a bundle identifier the notification center never
        # registers the poster, and it stays invisible in Settings.
        script = read_build_script()
        self.assertIn("CFBundleIdentifier", script)
        self.assertIn("com.adel.dayflownudge", script)

    def test_keeps_the_poster_out_of_the_dock(self):
        self.assertIn("LSUIElement", read_build_script())

    def test_resigns_the_bundle_after_editing_the_plist(self):
        script = read_build_script()
        self.assertIn("plutil", script)
        self.assertIn("codesign", script)

    def test_builds_the_styled_window_poster_when_swiftc_exists(self):
        script = read_build_script()
        self.assertIn("swiftc", script)
        self.assertIn("window.swift", script)
        # A machine without the compiler must still install cleanly.
        self.assertIn("command -v swiftc", script)


class WindowPosterContractTest(unittest.TestCase):
    def read_window_source(self):
        with open(WINDOW_SOURCE_PATH, "r", encoding="utf-8") as handle:
            return handle.read()

    def test_the_window_source_is_committed(self):
        self.assertTrue(os.path.isfile(WINDOW_SOURCE_PATH))

    def test_the_panel_never_steals_keyboard_focus(self):
        self.assertIn("nonactivatingPanel", self.read_window_source())

    def test_the_card_closes_itself(self):
        self.assertIn("GIVE_UP_SECONDS", self.read_window_source())

    def test_reads_the_payload_from_the_environment(self):
        source = self.read_window_source()
        self.assertIn('env["DFN_TITLE"]', source)
        self.assertIn('env["DFN_BODY"]', source)


if __name__ == "__main__":
    unittest.main()
