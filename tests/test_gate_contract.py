"""Repository layout contract for the dayflow-nudge daemon.

The daemon's runtime and deployment depend on files living where the
layout promises: the package's modules are imported by name, the
notification applet is compiled at install time from two committed
sources, and the per-user agent definition must be a well-formed property
list before launchd will load it. A file that drifts -- moved, emptied,
or malformed -- breaks far away from the change that broke it, so the
layout itself is pinned by tests.

The package's module set is pinned exactly: the ``.py`` files present in
``dayflow_nudge/`` must equal the pinned code modules plus the packaging
shims, so a module silently added or deleted fails the suite instead of
quietly changing what the daemon is. Every other pinned file is asserted
outright: a missing or emptied module, an emptied script source, or an
unparseable property list fails immediately, because a layout check that
skips on absence stops checking the layout the day a file goes missing.
"""

import plistlib
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The fifteen code modules of the dayflow_nudge package. Each one is
#: imported by name at run time or by the test suite, so an existing file
#: of any of these names must actually contain code, and the set of
#: module files present must equal this list plus the packaging shims.
CODE_MODULES = (
    "daemon.py",
    "config.py",
    "logging.py",
    "models.py",
    "db_reader.py",
    "card_provider.py",
    "goal_provider.py",
    "freshness_guard.py",
    "detector_api.py",
    "detector_distraction.py",
    "nudge_policy.py",
    "quiet_hours.py",
    "kill_switch.py",
    "notifier.py",
    "state_store.py",
)

#: Packaging shims that make the directory a package and give it a
#: ``python3 -m dayflow_nudge`` entry. Presence is the contract; an empty
#: ``__init__.py`` is idiomatic and allowed.
PACKAGING_SHIMS = ("__init__.py", "__main__.py")

#: Script sources compiled into the notification applet at install time.
#: Neither may be committed empty: an empty file compiles nothing and the
#: daemon silently loses its delivery channel.
SCRIPT_SOURCES = ("scripts/build_applet.sh", "scripts/applet.applescript")

#: The per-user agent definition; it must parse as a property list with
#: at least some definition inside.
PLIST_SOURCE = "deploy/com.dayflow.nudge.plist"

#: The published example of the configuration surface, copied to .env by
#: whoever wants to change a knob; it may never be committed with real
#: values because it is the template a published repository hands out.
ENV_EXAMPLE = ".env-example"

#: The eight knobs every publication surface must name identically --
#: and no other DFN_* name (the poster payload variables DFN_TITLE,
#: DFN_BODY, and DFN_SOUND are delivery plumbing, not user settings).
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


class PackageLayoutTest(unittest.TestCase):
    def test_the_package_module_set_is_exactly_the_pinned_modules(self):
        package_dir = REPO_ROOT / "dayflow_nudge"
        present = {
            path.name for path in package_dir.iterdir() if path.suffix == ".py"
        }

        self.assertEqual(
            present,
            set(CODE_MODULES) | set(PACKAGING_SHIMS),
            "the dayflow_nudge module set drifted from the pinned layout;"
            " adding or deleting a module must update this pin deliberately",
        )

    def test_code_modules_present_and_non_empty(self):
        for name in CODE_MODULES:
            path = REPO_ROOT / "dayflow_nudge" / name
            self.assertTrue(
                path.is_file(),
                "{0} is missing; a pinned module must exist, not skip"
                " its check".format(name))
            self.assertGreater(
                path.stat().st_size, 0,
                "{0} exists but is empty; a code module must contain"
                " code".format(name))

    def test_packaging_shims_present(self):
        for name in PACKAGING_SHIMS:
            path = REPO_ROOT / "dayflow_nudge" / name
            self.assertTrue(
                path.is_file(),
                "{0} is missing; the package needs its shims to import"
                " and to run".format(name))

    def test_applet_build_sources_present_and_non_empty(self):
        for relative in SCRIPT_SOURCES:
            path = REPO_ROOT / relative
            self.assertTrue(
                path.is_file(),
                "{0} is missing; the applet cannot be built without"
                " it".format(relative))
            self.assertGreater(
                path.stat().st_size, 0,
                "{0} exists but is empty; the applet cannot be built from"
                " it".format(relative))

    def test_launchagent_plist_parses(self):
        path = REPO_ROOT / PLIST_SOURCE
        self.assertTrue(
            path.is_file(),
            "the launch agent property list is missing; an agent that is"
            " never defined never runs")
        with path.open("rb") as handle:
            contents = plistlib.load(handle)
        self.assertIsInstance(contents, dict)
        self.assertTrue(
            contents,
            "{0} parses but defines nothing".format(PLIST_SOURCE))

    def test_env_example_present_non_empty_and_ascii(self):
        path = REPO_ROOT / ENV_EXAMPLE
        self.assertTrue(
            path.is_file(),
            "{0} is missing; a stranger cannot configure the daemon"
            " without it".format(ENV_EXAMPLE))
        self.assertGreater(
            path.stat().st_size, 0,
            "{0} exists but is empty; the example must carry the"
            " vocabulary".format(ENV_EXAMPLE))
        with path.open("r", encoding="ascii") as handle:
            contents = handle.read()
        # every knob ships as a commented line: uncommenting is the
        # documented mental model for changing a setting
        lines = contents.splitlines()
        for knob in PUBLISHED_KNOBS:
            with self.subTest(knob=knob):
                self.assertTrue(
                    any(line.lstrip().startswith("#") and knob in line
                        for line in lines),
                    "{0} must present {1} as a commented line".format(
                        ENV_EXAMPLE, knob))

    def test_the_local_env_file_is_ignored(self):
        lines = (REPO_ROOT / ".gitignore").read_text(encoding="ascii")
        self.assertIn(
            ".env",
            lines.splitlines(),
            "a local .env carries personal values; it must never reach"
            " the published tree")


class PublishedVocabularyTest(unittest.TestCase):
    """One vocabulary, named identically on every public surface."""

    SURFACES = (
        ".env-example",
        "deploy/install.sh",
        "README.md",
        "CLAUDE.md",
    )

    def _names_in(self, text):
        return sorted(set(re.findall(r"DFN_[A-Z]+(?:_[A-Z]+)*", text)))

    def test_every_publication_surface_names_exactly_the_eight_knobs(self):
        for relative in self.SURFACES:
            with self.subTest(surface=relative):
                path = REPO_ROOT / relative
                self.assertTrue(path.is_file())
                text = path.read_text(encoding="ascii")
                self.assertEqual(
                    self._names_in(text), list(PUBLISHED_KNOBS),
                    "{0} must name exactly the published knobs".format(
                        relative))


if __name__ == "__main__":
    unittest.main()
