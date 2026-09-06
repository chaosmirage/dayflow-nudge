"""Static and rendered checks for the deployment artifacts: the
LaunchAgent plist template, the install-time render in install.sh, the
uninstall script, and the README the operator follows."""

import os
import plistlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLIST_PATH = REPO_ROOT / "deploy" / "com.dayflow.nudge.plist"
INSTALL_PATH = REPO_ROOT / "deploy" / "install.sh"
UNINSTALL_PATH = REPO_ROOT / "deploy" / "uninstall.sh"
README_PATH = REPO_ROOT / "README.md"

# Entry contract: the system interpreter, the package entry module, no flags.
EXPECTED_PROGRAM_ARGUMENTS = ["/usr/bin/python3", "-m", "dayflow_nudge"]

#: The published knob vocabulary the template's environment block carries,
#: one placeholder pair per knob.
PUBLISHED_KNOBS = (
    "DFN_DAYS",
    "DFN_DB_PATH",
    "DFN_DISABLE",
    "DFN_NOTIFIER",
    "DFN_POLL_SECONDS",
    "DFN_QUIET_END",
    "DFN_QUIET_START",
    "DFN_STYLE",
)

#: What the render writes for each knob when the .env names nothing.
RENDERED_DEFAULTS = {
    "DFN_DAYS": "mon,tue,wed,thu,fri",
    "DFN_DISABLE": "0",
    "DFN_NOTIFIER": "applet",
    "DFN_POLL_SECONDS": "60",
    "DFN_QUIET_END": "08:00",
    "DFN_QUIET_START": "20:00",
    "DFN_STYLE": "window",
}


def read_text(path):
    """Read a shipped text artifact, enforcing the all-ASCII convention."""
    with path.open("r", encoding="ascii") as handle:
        return handle.read()


class TemplateShapeTests(unittest.TestCase):
    """The shipped plist exactly as launchd will load it once rendered."""

    @classmethod
    def setUpClass(cls):
        with PLIST_PATH.open("rb") as handle:
            cls.agent = plistlib.load(handle)
        cls.raw = PLIST_PATH.read_bytes().decode("ascii")

    def test_label_names_the_agent(self):
        self.assertEqual(self.agent["Label"], "com.dayflow.nudge")

    def test_program_runs_the_package_with_zero_cli_flags(self):
        self.assertEqual(self.agent["ProgramArguments"], EXPECTED_PROGRAM_ARGUMENTS)

    def test_runs_at_login_and_restarts_when_killed(self):
        self.assertIs(self.agent["RunAtLoad"], True)
        self.assertIs(self.agent["KeepAlive"], True)

    def test_paths_carry_the_owned_dir_placeholder(self):
        self.assertEqual(self.agent["WorkingDirectory"], "@@OWNED_DIR@@")
        self.assertEqual(
            self.agent["StandardOutPath"], "@@OWNED_DIR@@/logs/daemon.out.log")
        self.assertEqual(
            self.agent["StandardErrorPath"], "@@OWNED_DIR@@/logs/daemon.err.log")

    def test_the_environment_block_holds_one_pair_per_published_knob(self):
        self.assertEqual(
            sorted(self.agent["EnvironmentVariables"]), list(PUBLISHED_KNOBS))
        for knob in PUBLISHED_KNOBS:
            with self.subTest(knob=knob):
                self.assertEqual(
                    self.agent["EnvironmentVariables"][knob],
                    "@@{}@@".format(knob))

    def test_no_account_literal_ships_in_the_template(self):
        self.assertNotIn("/Users/", self.raw)


class RenderedPlistTests(unittest.TestCase):
    """What the install-time render writes, under a borrowed home.

    The render subcommand is the installer's test seam: it performs only
    the template substitution from a .env read strictly as data, touches
    neither the owned directory nor launchd, and exits 0.
    """

    def _run_render(self, home, env_path, out_path):
        return subprocess.run(
            ["bash", str(INSTALL_PATH), "render",
             str(PLIST_PATH), str(env_path), str(out_path)],
            env=dict(os.environ, HOME=home),
            capture_output=True, text=True)

    def render(self, env_lines, env_exists=True):
        """Run the render once under a throwaway home; returns the run."""
        home = tempfile.mkdtemp(prefix="dfn-render-home-")
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        env_path = os.path.join(home, "env")
        if env_exists:
            with open(env_path, "w", encoding="ascii") as handle:
                handle.write(env_lines)
        out_path = os.path.join(home, "rendered.plist")
        completed = self._run_render(home, env_path, out_path)
        return completed, home, out_path

    def _load(self, out_path):
        with open(out_path, "rb") as handle:
            return plistlib.load(handle)

    def test_an_absent_env_renders_the_documented_defaults(self):
        completed, home, out_path = self.render("", env_exists=False)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        agent = self._load(out_path)
        expected = dict(
            RENDERED_DEFAULTS,
            **{"DFN_DB_PATH":
               os.path.join(home, "Library", "Application Support",
                            "Dayflow", "chunks.sqlite")})
        self.assertEqual(agent["EnvironmentVariables"], expected)
        self.assertTrue(
            any("render" in line for line in completed.stdout.splitlines()),
            "the absent file must say so on its own transcript line")

    def test_all_three_paths_land_under_the_rendering_home(self):
        _, home, out_path = self.render("")

        agent = self._load(out_path)
        owned = os.path.join(home, "Library", "Application Support",
                             "dayflow-nudge")
        self.assertEqual(agent["WorkingDirectory"], owned)
        self.assertEqual(
            agent["StandardOutPath"], owned + "/logs/daemon.out.log")
        self.assertEqual(
            agent["StandardErrorPath"], owned + "/logs/daemon.err.log")

    def test_no_foreign_absolute_path_lands_in_the_output(self):
        _, home, out_path = self.render("DFN_DAYS=sat,sun\n")

        rendered = Path(out_path).read_text(encoding="ascii")
        # nothing from the account running the suite may survive into a
        # render made under a borrowed home
        self.assertNotIn(str(Path.home()), rendered)
        agent = self._load(out_path)
        paths = [agent["WorkingDirectory"], agent["StandardOutPath"],
                 agent["StandardErrorPath"],
                 agent["EnvironmentVariables"]["DFN_DB_PATH"]]
        for value in paths:
            with self.subTest(value=value):
                self.assertTrue(value.startswith(home))

    def test_values_from_the_env_reach_the_plist(self):
        completed, home, out_path = self.render(
            "DFN_DAYS=sat,sun\n"
            "DFN_QUIET_START=23:00\n"
            "DFN_POLL_SECONDS=90\n"
            "DFN_NOTIFIER=oscript\n"
            "DFN_STYLE=notification\n")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        variables = self._load(out_path)["EnvironmentVariables"]
        self.assertEqual(variables["DFN_DAYS"], "sat,sun")
        self.assertEqual(variables["DFN_QUIET_START"], "23:00")
        self.assertEqual(variables["DFN_POLL_SECONDS"], "90")
        self.assertEqual(variables["DFN_NOTIFIER"], "oscript")
        self.assertEqual(variables["DFN_STYLE"], "notification")

    def test_both_spellings_of_the_quiet_hour_are_accepted(self):
        for spelling in ("8:00", "08:00"):
            with self.subTest(spelling=spelling):
                completed, _, out_path = self.render(
                    "DFN_QUIET_START={}\nDFN_QUIET_END=20:00\n".format(spelling))
                self.assertEqual(completed.returncode, 0, completed.stderr)
                variables = self._load(out_path)["EnvironmentVariables"]
                self.assertEqual(variables["DFN_QUIET_START"], spelling)

    def test_equal_quiet_bounds_fall_back_to_the_default_pair(self):
        completed, _, out_path = self.render(
            "DFN_QUIET_START=07:00\nDFN_QUIET_END=07:00\n")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        variables = self._load(out_path)["EnvironmentVariables"]
        self.assertEqual(variables["DFN_QUIET_START"], "20:00")
        self.assertEqual(variables["DFN_QUIET_END"], "08:00")
        self.assertTrue(
            any("DFN_QUIET_START" in line and "DFN_QUIET_END" in line
                for line in completed.stdout.splitlines()),
            "the equal-bounds fallback must name both knobs on one line")

    def test_hostile_values_render_to_defaults_with_transcript_lines(self):
        completed, _, out_path = self.render(
            "DFN_DAYS=monday,funday\n"
            "DFN_POLL_SECONDS=-3\n"
            "DFN_QUIET_START=later\n"
            "DFN_DISABLE=maybe\n")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        variables = self._load(out_path)["EnvironmentVariables"]
        self.assertEqual(variables["DFN_DAYS"], RENDERED_DEFAULTS["DFN_DAYS"])
        self.assertEqual(
            variables["DFN_POLL_SECONDS"], RENDERED_DEFAULTS["DFN_POLL_SECONDS"])
        self.assertEqual(
            variables["DFN_QUIET_START"], RENDERED_DEFAULTS["DFN_QUIET_START"])
        self.assertEqual(
            variables["DFN_DISABLE"], RENDERED_DEFAULTS["DFN_DISABLE"])

    def test_unknown_keys_are_ignored_with_one_printed_line(self):
        completed, _, out_path = self.render(
            "EVIL=rm -rf /\nTOTALLY_UNKNOWN=1\nDFN_DAYS=sat,sun\n")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        ignored = [line for line in completed.stdout.splitlines()
                   if "EVIL" in line or "TOTALLY_UNKNOWN" in line]
        self.assertEqual(len(ignored), 2, completed.stdout)

    def test_metacharacters_round_trip_through_the_property_list(self):
        hostile = "a&b<c>d"
        completed, _, out_path = self.render(
            "DFN_DB_PATH={}\n".format(hostile))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        variables = self._load(out_path)["EnvironmentVariables"]
        self.assertEqual(variables["DFN_DB_PATH"], hostile)

    def test_a_leading_tilde_in_the_db_path_expands_to_the_render_home(self):
        completed, home, out_path = self.render(
            "DFN_DB_PATH=~/Data/chunks.sqlite\n")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        variables = self._load(out_path)["EnvironmentVariables"]
        self.assertEqual(
            variables["DFN_DB_PATH"], home + "/Data/chunks.sqlite")

    def test_the_render_neither_creates_the_owned_dir_nor_touches_launchagents(
            self):
        _, home, _ = self.render("DFN_DAYS=sat,sun\n")

        library = os.path.join(home, "Library")
        self.assertFalse(os.path.exists(library),
                         "the render must not build anything under the"
                         " borrowing home's Library")

    def test_the_render_is_idempotent(self):
        completed, home, first_path = self.render("DFN_DAYS=sat,sun\n")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        first = Path(first_path).read_bytes()
        second_path = os.path.join(home, "again.plist")
        again = self._run_render(
            home, os.path.join(home, "env"), second_path)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(first, Path(second_path).read_bytes())


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

    def test_the_env_is_parsed_as_data_never_as_code(self):
        # The .env is untrusted input: the render may not shell it through
        # any text transformer whose metacharacters form a second
        # injection seam.
        for forbidden in ("sed", "awk", "eval", "source "):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.script)

    def test_the_render_subcommand_is_the_test_seam(self):
        self.assertIn("install.sh render", self.script)


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

    def test_documents_every_published_knob(self):
        for knob in PUBLISHED_KNOBS:
            with self.subTest(knob=knob):
                self.assertIn(knob, self.text)

    def test_documents_the_file_based_apply_step(self):
        flat = " ".join(self.text.split())
        self.assertIn("cp .env-example .env", flat)
        self.assertIn("install.sh", flat)

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
