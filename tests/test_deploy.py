"""Static checks for the deployment artifacts: the LaunchAgent plist, the
install/uninstall scripts, and the README the operator follows."""

import plistlib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLIST_PATH = REPO_ROOT / "deploy" / "com.dayflow.nudge.plist"
INSTALL_PATH = REPO_ROOT / "deploy" / "install.sh"
UNINSTALL_PATH = REPO_ROOT / "deploy" / "uninstall.sh"
README_PATH = REPO_ROOT / "README.md"

# Entry contract: the system interpreter, the package entry module, no flags.
EXPECTED_PROGRAM_ARGUMENTS = ["/usr/bin/python3", "-m", "dayflow_nudge"]

OWNED_DIR_SUFFIX = "/Library/Application Support/dayflow-nudge"


def read_text(path):
    """Read a shipped text artifact, enforcing the all-ASCII convention."""
    with path.open("r", encoding="ascii") as handle:
        return handle.read()


class LaunchAgentDefinitionTests(unittest.TestCase):
    """The plist exactly as launchd will load it."""

    @classmethod
    def setUpClass(cls):
        with PLIST_PATH.open("rb") as handle:
            cls.agent = plistlib.load(handle)

    def test_label_names_the_agent(self):
        self.assertEqual(self.agent["Label"], "com.dayflow.nudge")

    def test_program_runs_the_package_with_zero_cli_flags(self):
        self.assertEqual(self.agent["ProgramArguments"], EXPECTED_PROGRAM_ARGUMENTS)

    def test_runs_at_login_and_restarts_when_killed(self):
        self.assertIs(self.agent["RunAtLoad"], True)
        self.assertIs(self.agent["KeepAlive"], True)

    def test_working_directory_is_the_owned_install_dir(self):
        working_directory = self.agent["WorkingDirectory"]
        self.assertTrue(
            working_directory.endswith(OWNED_DIR_SUFFIX),
            f"WorkingDirectory should be the owned dir, got {working_directory!r}",
        )

    def test_launchd_output_lands_in_the_owned_logs_dir(self):
        workdir = self.agent["WorkingDirectory"]
        self.assertEqual(
            self.agent["StandardOutPath"], workdir + "/logs/daemon.out.log"
        )
        self.assertEqual(
            self.agent["StandardErrorPath"], workdir + "/logs/daemon.err.log"
        )

    def test_env_block_holds_optional_dfn_overrides(self):
        self.assertIsInstance(self.agent["EnvironmentVariables"], dict)


class InstallScriptTests(unittest.TestCase):
    """What running deploy/install.sh does to the machine."""

    @classmethod
    def setUpClass(cls):
        cls.script = read_text(INSTALL_PATH)

    def test_fails_fast_on_any_unexpected_error(self):
        self.assertIn("set -euo pipefail", self.script)

    def test_builds_the_notification_poster_applet(self):
        self.assertIn("build_applet.sh", self.script)

    def test_registers_the_agent_with_the_modern_launchctl_api(self):
        self.assertIn("launchctl bootstrap", self.script)

    def test_replaces_an_already_running_agent(self):
        # A reinstall must tolerate an agent that is not loaded yet.
        self.assertRegex(self.script, r"launchctl bootout[^\n]*\|\| true")

    def test_prints_the_work_focus_allowlist_step(self):
        self.assertIn("Allowed Notifications", self.script)


class UninstallScriptTests(unittest.TestCase):
    """What running deploy/uninstall.sh removes."""

    @classmethod
    def setUpClass(cls):
        cls.script = read_text(UNINSTALL_PATH)

    def test_stops_the_agent_before_removing_files(self):
        self.assertIn("launchctl bootout", self.script)

    def test_removes_the_plist_and_the_owned_dir(self):
        self.assertIn("LaunchAgents", self.script)
        self.assertIn("dayflow-nudge", self.script)


class ReadmeTests(unittest.TestCase):
    """The operator manual covers the steps the owner must take by hand."""

    @classmethod
    def setUpClass(cls):
        cls.text = read_text(README_PATH)

    def test_documents_the_work_focus_allowlist_step(self):
        self.assertIn("Allowed Notifications", self.text)
        self.assertIn("DayflowNudge", self.text)

    def test_documents_the_kill_switch(self):
        self.assertIn("DFN_DISABLE", self.text)

    def test_documents_the_notifier_and_poll_knobs(self):
        self.assertIn("DFN_NOTIFIER", self.text)
        self.assertIn("DFN_POLL_SECONDS", self.text)

    def test_documents_the_test_command(self):
        self.assertIn("python3 -m unittest discover", self.text)

    def test_documents_install_and_uninstall(self):
        self.assertIn("install.sh", self.text)
        self.assertIn("uninstall.sh", self.text)

    def test_names_the_daily_tab_trigger_and_its_fallback(self):
        # The trigger is the distraction-category selection made in
        # Dayflow's Daily tab; the category-word rule is only the fallback
        # for a day with no selection.
        self.assertIn("Daily tab", self.text)
        self.assertIn("fallback", self.text)

    def test_states_that_limit_minutes_no_longer_notify(self):
        # Whitespace is flattened first: the claim is pinned by its
        # wording, not by where the line wraps happen to fall. The removal
        # is the point: these minutes once notified and must not anymore.
        flat = " ".join(self.text.split())
        self.assertIn("no longer produce notifications", flat)

    def test_keeps_the_removed_budget_cause_out(self):
        # The burn-through-the-budget cause is gone; a README that
        # reintroduces it describes a trigger the daemon no longer has.
        self.assertNotIn("budget", self.text)


if __name__ == "__main__":
    unittest.main()
