"""Import hygiene lock for the whole repository.

The daemon is deliberately built on the Python standard library alone so
it runs from a bare OS interpreter: nothing to install, no site-packages
to drift, no network fetch at deploy time. A property that lives only in
review discipline erodes the first time someone adds one small helpful
dependency, so it is enforced mechanically here.

Every Python file of the shipped package and of the test suite that exists
at run time is parsed and each import target is collected from the syntax
tree -- nothing is imported to be checked, and mentions inside strings or
comments never count. A target is allowed only when its top-level package
is a standard-library module or one of this repository's own packages.
This test also checks itself, which keeps the walk honest end to end.

Files are read as they exist when the suite runs, so a repository that is
still being filled in asserts only over what is present; one third-party
import anywhere in an existing file fails the lock.
"""

import ast
import importlib.machinery
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Directories whose Python sources the lock walks, as they exist now.
WALKED_SOURCE_DIRS = ("dayflow_nudge", "tests")

#: Top-level packages that belong to this repository. Anything else that is
#: not standard library is third-party by construction: an allowed root
#: must be code that ships inside this repository.
PROJECT_PACKAGES = frozenset({"dayflow_nudge", "tests"})


class ImportViolation(NamedTuple):
    """One import statement whose target is neither stdlib nor first-party.

    source  repository-relative path of the file holding the statement
    lineno  line the import statement starts on
    target  the import target exactly as written
    root    the target's top-level package name (the checked part)
    """

    source: str
    lineno: int
    target: str
    root: str


def resolve_stdlib_roots():
    """Return the interpreter's top-level standard-library module names.

    ``sys.stdlib_module_names`` is the authoritative set where it exists;
    on older interpreters it is derived conservatively from the builtin
    modules plus the entries of the running interpreter's library
    directory, so the lock keeps working instead of erroring out.
    """
    names = getattr(sys, "stdlib_module_names", None)
    if names is not None:
        return frozenset(names)
    return derive_stdlib_roots(Path(os.__file__).parent)


def extension_module_name(entry_name):
    """Return the module name of a compiled extension file, else None.

    Compiled stdlib modules ship as shared objects named after the
    running interpreter's own extension suffixes; ``unicodedata`` exists
    only in that shape on interpreters that lack
    ``sys.stdlib_module_names``. Only such files contribute a name here,
    and the identifier check keeps stray files out of the allowed set.
    """
    for suffix in importlib.machinery.EXTENSION_SUFFIXES:
        if entry_name.endswith(suffix):
            stem = entry_name[: -len(suffix)]
            return stem if stem.isidentifier() else None
    return None


def derive_stdlib_roots(library_dir):
    """Derive top-level stdlib module names from a library directory.

    This is the fallback used when the interpreter does not provide
    ``sys.stdlib_module_names``. The names come from the interpreter's
    own layout only -- builtin modules, plus the plain modules, packages
    and compiled extension files found at the top of the library
    directory and in its ``lib-dynload`` subdirectory -- so nothing
    outside the standard library can be admitted.
    """
    derived = set(sys.builtin_module_names)
    for directory in (library_dir, library_dir / "lib-dynload"):
        if not directory.is_dir():
            continue
        for entry in directory.iterdir():
            if entry.suffix == ".py":
                derived.add(entry.stem)
            elif entry.is_dir() and entry.name.isidentifier():
                derived.add(entry.name)
            else:
                module_name = extension_module_name(entry.name)
                if module_name is not None:
                    derived.add(module_name)
    return frozenset(derived)


def find_python_sources(repo_root):
    """List repository-relative paths of every walked Python source present.

    A source directory that does not exist yet contributes nothing; an
    absent file asserts nothing. The result is sorted so failure messages
    stay stable across runs.
    """
    sources = []
    for name in WALKED_SOURCE_DIRS:
        directory = repo_root / name
        if not directory.is_dir():
            continue
        sources.extend(path.relative_to(repo_root).as_posix()
                       for path in directory.glob("*.py"))
    return sorted(sources)


def collect_import_violations(sources, repo_root, allowed_roots):
    """Collect every import in the given sources whose root is not allowed.

    Pure over its inputs: reads each listed source, parses it, and records
    an ImportViolation per non-relative import statement whose top-level
    package is outside ``allowed_roots``. Relative imports are intra-
    package by definition and never violations.
    """
    violations = []
    for source in sources:
        text = (repo_root / source).read_text(encoding="utf-8")
        tree = ast.parse(text, filename=source)
        for node in ast.walk(tree):
            targets = import_targets(node)
            for lineno, target in targets:
                root = target.split(".")[0]
                if root not in allowed_roots:
                    violations.append(
                        ImportViolation(source, lineno, target, root))
    return violations


def import_targets(node):
    """Return (lineno, target) pairs for one import-shaped syntax node.

    ``import a.b`` and ``import a.b as c`` each yield the full dotted
    target; ``from a.b import x`` yields the module part ``a.b``. Nodes
    that are not imports, and relative ``from . import x`` forms, yield
    nothing.
    """
    if isinstance(node, ast.Import):
        return [(node.lineno, alias.name) for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        return [(node.lineno, node.module)]
    return []


class ImportHygieneTest(unittest.TestCase):
    def test_every_import_is_stdlib_or_first_party(self):
        allowed_roots = resolve_stdlib_roots() | PROJECT_PACKAGES
        sources = find_python_sources(REPO_ROOT)
        violations = collect_import_violations(sources, REPO_ROOT,
                                               allowed_roots)
        details = "\n".join(
            "{0.source}:{0.lineno}: imports '{0.target}' -- '{0.root}' is"
            " not standard library and not this repository's code".format(
                violation)
            for violation in violations)
        self.assertEqual([], violations,
                         "imports outside the allowed set found:\n"
                         + details)

    def test_the_walk_covers_this_file(self):
        # Fail, never pass vacuously: if discovery ever matched no files,
        # the check above would approve an empty repository silently.
        sources = find_python_sources(REPO_ROOT)
        self.assertIn("tests/test_import_hygiene.py", sources)


class FallbackStdlibDerivationTest(unittest.TestCase):
    """Pin the derived fallback used without ``sys.stdlib_module_names``.

    Interpreters that predate ``sys.stdlib_module_names`` are exactly the
    bare OS ones the LaunchAgent deploys to, and on them compiled stdlib
    modules live as shared objects inside ``lib-dynload`` with no
    top-level ``.py`` file at all. The derivation is exercised against a
    synthetic layout here, so what it admits never depends on which
    interpreter happens to run the suite.
    """

    def setUp(self):
        # A real library directory always carries its own interpreter's
        # extension tag, so the fixtures are named with the running
        # interpreter's most specific suffix -- exactly what the fallback
        # finds on the machine it runs on.
        suffix = importlib.machinery.EXTENSION_SUFFIXES[0]
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.library_dir = self.root / "lib-python"
        dynload = self.library_dir / "lib-dynload"
        dynload.mkdir(parents=True)
        (dynload / ("unicodedata" + suffix)).touch()
        (dynload / ("_asyncio" + suffix)).touch()
        (self.library_dir / "json.py").touch()
        (self.library_dir / "README").touch()
        package = self.library_dir / "email"
        package.mkdir()
        (package / "__init__.py").touch()

    def write_source(self, text):
        source_dir = self.root / "pkg"
        source_dir.mkdir(exist_ok=True)
        source = source_dir / "demo.py"
        source.write_text(text, encoding="utf-8")
        return ["pkg/demo.py"]

    def test_derivation_covers_every_stdlib_shape(self):
        derived = derive_stdlib_roots(self.library_dir)
        for name in ("unicodedata", "_asyncio", "json", "email"):
            self.assertIn(name, derived)

    def test_derivation_ignores_files_that_are_not_modules(self):
        derived = derive_stdlib_roots(self.library_dir)
        self.assertNotIn("README", derived)

    def test_fallback_allows_compiled_stdlib_imports(self):
        allowed = derive_stdlib_roots(self.library_dir) | PROJECT_PACKAGES
        sources = self.write_source("import json\nimport unicodedata\n")
        self.assertEqual(
            [], collect_import_violations(sources, self.root, allowed),
            "a compiled stdlib module must not be reported as third-party")

    def test_fallback_still_flags_third_party_imports(self):
        allowed = derive_stdlib_roots(self.library_dir) | PROJECT_PACKAGES
        sources = self.write_source("import requests\n")
        violations = collect_import_violations(sources, self.root, allowed)
        self.assertEqual(1, len(violations))
        self.assertEqual("requests", violations[0].root)


if __name__ == "__main__":
    unittest.main()
