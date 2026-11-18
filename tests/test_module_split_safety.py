"""Safety checks for module splits.

These tests ensure that when a large source file is broken down into smaller
modules, the test suite is updated to match and nothing is missed:

1. No oversized source file is left unsplit — `audit_module_splits.py` audit
   logic runs in-process and fails if any file exceeds the threshold.
2. Every source module under core/, services/, app/, ui/ has at least one test
   file under tests/ that imports from it — an unsplit source module without test
   coverage is a defect waiting to happen.
3. Every symbol a test file imports from a source module actually exists — stale
   imports left behind after a split are caught by name, not by opaque failures.

Run as part of the suite:  runtime\python.exe -m unittest discover -q
"""

from __future__ import annotations

import ast
import importlib
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Directories that hold source modules that must have test coverage.
SOURCE_DIRS = ("core", "services", "app", "ui")

# Source package names (top-level) used to decide whether an import targets
# a source module vs. a third-party package or a test-internal helper.
SOURCE_PACKAGES = set(SOURCE_DIRS)

# Symbols that are re-exports or deliberately not tested individually.
# Format: ("module.path", "symbol_name")
UNTESTED_SYMBOLS = {
    ("steam_game_organizer", "AppConfig"),
    ("steam_game_organizer", "AppLogger"),
    # Pre-existing `from services import X` patterns: services/ has no __init__.py,
    # so these package-level imports cannot resolve as attributes. Not split-related.
    ("services", "batch_extract_service"),
    ("services", "setup_service"),
}


def iter_source_modules(root: Path):
    """Yield (module_path, module_name) for every .py in source dirs."""
    for directory in SOURCE_DIRS:
        src_dir = root / directory
        if not src_dir.is_dir():
            continue
        for path in sorted(src_dir.rglob("*.py")):
            if path.name == "__init__.py":
                continue
            yield path, path.relative_to(root).as_posix().replace("/", ".")[:-3]


def test_file_references_module(test_path: Path, module_name: str) -> bool:
    """Return True if test_path's text imports or references module_name."""
    try:
        text = test_path.read_text(encoding="utf-8")
    except OSError:
        return False
    if f"import {module_name}" in text or f"from {module_name} import" in text:
        return True
    if module_name.count(".") > 0:
        parent = module_name.rsplit(".", 1)[0]
        if f"import {parent}" in text or f"from {parent} import" in text:
            return True
    return False


def is_source_module_import(module_name: str) -> bool:
    """True when module_name names something under a source package."""
    top = module_name.split(".", 1)[0]
    return top in SOURCE_PACKAGES


class TestNoOversizedSourceFiles(unittest.TestCase):
    """Reports oversized source files that are candidates for splitting.

    A file over 300 lines / 15 KB should be split into focused modules. This test
    reports them but does not fail the suite — many UI files already exceed the
    threshold and will be split incrementally. Run
    `python tools\audit_module_splits.py` to see the full list and
    `python tools\audit_module_splits.py --heal FILE:SYMBOL` to extract symbols.
    """

    OVER_SIZE_LINES = 300
    OVER_SIZE_BYTES = 15000

    def test_report_oversized_source_files(self):
        from tools.audit_module_splits import audit_file, iter_source_files

        oversized = []
        for path in iter_source_files(PROJECT_ROOT):
            info = audit_file(path, self.OVER_SIZE_LINES, self.OVER_SIZE_BYTES)
            if info is None:
                continue
            if info["oversized"]:
                oversized.append(
                    f"  {path.relative_to(PROJECT_ROOT)}: {info['total_lines']} lines, "
                    f"{info['total_bytes']:,} bytes"
                )
        if oversized:
            report = "\n".join(sorted(oversized))
            print(
                f"\n{len(oversized)} oversized source file(s) are candidates for splitting:\n{report}\n"
                "Run: python tools\\audit_module_splits.py --heal FILE:SYMBOL"
            )


class TestEverySourceModuleHasTestCoverage(unittest.TestCase):
    """Every source module under core/, services/, app/, ui/ must be imported by
    at least one test file under tests/.

    A source module with no test coverage means its behaviour is unchecked and a
    future refactor can break it silently.
    """

    def test_each_source_module_has_at_least_one_test_file(self):
        test_files = list((PROJECT_ROOT / "tests").rglob("test_*.py"))
        missing = []
        for path, module_name in iter_source_modules(PROJECT_ROOT):
            referenced = any(test_file_references_module(tf, module_name) for tf in test_files)
            if not referenced:
                missing.append(f"  {path.relative_to(PROJECT_ROOT)} ({module_name})")
        report = "\n".join(sorted(missing))
        self.assertEqual(
            [],
            missing,
            f"source modules with no test coverage:\n{report}\n"
            "Create tests/test_<module>.py that imports from it.",
        )


class TestTestImportsResolve(unittest.TestCase):
    """Every `from X import Y` or `import X` in a test file that targets a source
    module (core/, services/, app/, ui/) must resolve to a real symbol.

    After a module split, a test file may still import a symbol from the old
    location where it no longer exists. This catches those stale imports by name
    rather than letting them surface as opaque failures in behaviour tests.

    Third-party imports (PIL, etc.) and test-internal imports (tests.*) are
    intentionally skipped — they are not source-module imports.
    """

    def _collected_source_imports(self):
        """Return list of (test_file, module_name, symbol_name_or_None, line_no)
        for imports that target source packages."""
        found = []
        for tf in sorted((PROJECT_ROOT / "tests").rglob("test_*.py")):
            try:
                tree = ast.parse(tf.read_text(encoding="utf-8"), filename=str(tf))
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module is None:
                        continue
                    if not is_source_module_import(node.module):
                        continue
                    for alias in node.names:
                        if alias.name == "*":
                            continue
                        found.append((tf, node.module, alias.name, node.lineno))
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if not is_source_module_import(alias.name):
                            continue
                        found.append((tf, alias.name, None, node.lineno))
        return found

    def test_every_source_module_import_in_tests_resolves(self):
        failures = []
        for test_file, module_name, symbol, lineno in self._collected_source_imports():
            try:
                mod = importlib.import_module(module_name)
            except (ImportError, ModuleNotFoundError):
                failures.append(
                    f"  {test_file.relative_to(PROJECT_ROOT)}:{lineno}: "
                    f"cannot import module '{module_name}'"
                )
                continue
            if symbol is not None:
                if (module_name, symbol) in UNTESTED_SYMBOLS:
                    continue
                if not hasattr(mod, symbol):
                    failures.append(
                        f"  {test_file.relative_to(PROJECT_ROOT)}:{lineno}: "
                        f"module '{module_name}' has no attribute '{symbol}'"
                    )
        report = "\n".join(sorted(failures))
        self.assertEqual(
            [],
            failures,
            f"test imports from source modules that do not resolve (stale after a split?):\n{report}\n"
            "Update the import to point at the symbol's new module.",
        )


class TestTestModulesHaveNoImportCycles(unittest.TestCase):
    """No pair of test modules may import each other.

    A split moves a class into a new module and leaves `from tests.new_module import TheClass` at the
    bottom of the original so discovery still exposes it. That is one direction, and it is safe. The
    reverse import - the new module reading a fixture back out of the original - makes the pair
    order-dependent: unittest discovery imports modules alphabetically, and whichever one it reaches
    second sees a partially initialised first, raising `ImportError: cannot import name X from partially
    initialized module`. That has broken this suite repeatedly (test_release_structure ↔
    test_version_rule_behaviour, test_uri_actions ↔ typed_destination_tests, test_workflow_smoke ↔
    test_real_workflow). Fixtures the new module needs belong in tests/test_helpers.py, which imports
    nothing from tests/ and can never take part in a cycle.

    Checked statically with `ast` so the answer does not depend on which modules happen to be imported
    already when this test runs.
    """

    def _test_module_imports(self, path: Path) -> set[str]:
        """Names of tests/*.py modules this file imports *at module scope*, from a static parse.

        Only module-scope imports can close a load-time cycle. An import inside a function runs when
        that function is called, long after discovery has finished importing every module, so it is not
        a cycle - and flagging it would push real fixes toward worse code.
        """
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            return set()
        found: set[str] = set()

        def scan(body):
            for node in body:
                if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("tests."):
                    found.add(node.module.split(".", 1)[1].split(".", 1)[0])
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("tests."):
                            found.add(alias.name.split(".", 1)[1].split(".", 1)[0])
                elif isinstance(node, (ast.If, ast.Try)):
                    # A module-level `if`/`try` body executes during import, so its imports count too.
                    scan(node.body)
                    scan(getattr(node, "orelse", []))
                    scan(getattr(node, "finalbody", []))

        scan(tree.body)
        return found

    def test_no_cycle_between_test_modules(self):
        tests_dir = PROJECT_ROOT / "tests"
        graph = {path.stem: self._test_module_imports(path) for path in sorted(tests_dir.glob("*.py"))}
        cycles = []
        for start in sorted(graph):
            stack = [(start, [start])]
            while stack:
                node, trail = stack.pop()
                for target in sorted(graph.get(node, ())):
                    if target == start:
                        cycles.append(" -> ".join(trail + [start]))
                    elif target in graph and target not in trail:
                        stack.append((target, trail + [target]))
        self.assertEqual(
            [],
            sorted(set(cycles)),
            "test modules import each other, so discovery order decides whether they load:\n  "
            + "\n  ".join(sorted(set(cycles)))
            + "\nMove the shared fixture into tests/test_helpers.py and import it from there in both.",
        )


if __name__ == "__main__":
    unittest.main()
