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


if __name__ == "__main__":
    unittest.main()
