"""Static contract checks on the committed notification poster source: the
applet must notify (never dialog), take its values from argv, and honor the
sound argument."""

import os
import unittest

APPLET_SOURCE_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), os.pardir, "scripts", "applet.applescript"))


def read_applet_source():
    with open(APPLET_SOURCE_PATH, "r", encoding="utf-8") as handle:
        return handle.read()


class AppletScriptContractTest(unittest.TestCase):
    def test_the_applet_source_is_committed(self):
        self.assertTrue(os.path.isfile(APPLET_SOURCE_PATH))

    def test_displays_a_notification(self):
        self.assertIn("display notification", read_applet_source())

    def test_takes_title_and_body_from_argv_items(self):
        source = read_applet_source()
        self.assertIn("on run", source)
        self.assertIn("item 1", source)
        self.assertIn("item 2", source)

    def test_honors_the_sound_argument(self):
        source = read_applet_source()
        self.assertIn('"sound"', source)
        self.assertIn('sound name "Glass"', source)

    def test_uses_no_dismissible_dialog(self):
        self.assertNotIn("display dialog", read_applet_source())


if __name__ == "__main__":
    unittest.main()
