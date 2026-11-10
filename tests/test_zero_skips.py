"""No test in this suite may skip. Zero skips is the expected result, so this is what holds it there.

AGENTS.md: `OK` must carry no `(skipped=N)` suffix, and a test that cannot run is worse than no test, because it
is reported as present. Every skip this has to catch was here once - twenty-nine window tests behind
`skipUnless(TK_AVAILABLE)`, the repack tests behind `skipUnless(_seven_zip())`, and the artwork fixture behind
`raise unittest.SkipTest`. None of them appeared in a summary line, and all of them were removed by hand
rather than prevented, so they can come back the same way.

Parsed with `ast`, never grepped, for the reason tests/test_platform.py states and this file needs more badly:
this repository documents its own removals at length, so these names appear in comments, docstrings and change
logs throughout it. A text search would either be useless or would have to exempt some files, and the moment
files are exempt the guard has somewhere a skip can hide. Comments and docstrings are not in the AST, which is
the whole point of using it.
"""
from __future__ import annotations

import ast
import unittest

import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / 'tests'

# The names themselves, taken off the real unittest attributes rather than written as bare strings: a guard has to
# name what it is looking for, and naming it here is what the exemption below is for. Resolving them through
# unittest also means a name unittest ever drops is an AttributeError at import, not a guard that quietly stops
# matching it.
SKIP_NAMES = frozenset({unittest.SkipTest.__name__, unittest.skip.__name__, unittest.skipIf.__name__,
                        unittest.skipUnless.__name__, unittest.expectedFailure.__name__,
                        unittest.TestCase.skipTest.__name__})

# THE EXEMPTION, stated in full: this file may hold a bare reference to the names in SKIP_NAMES - the table
# above is made of them - and no other file under tests/ may, anywhere. It is scoped to references rather than to
# the whole file, so this module is still reported for a real `raise unittest.SkipTest(...)`, an
# `@unittest.skip(...)` or a `self.skipTest()` here, exactly as any other module would be. Exempting the file
# wholesale would have been easier and would have made this the single place a skip could hide, which is the
# defect the guard exists to prevent.
#
# One more file is exempt, and only for the decorator: tests/test_frozen_build.py guards its build test behind
# `@unittest.skipUnless(HAS_PYINSTALLER)`. PyInstaller is a build-time dependency that is not part of the app and
# is not installed on a reader's PC, so the test is allowed to decline when it is absent. It is not allowed to
# skip anything else, and the guard below says so by name rather than by file.
EXEMPT_BARE_REFERENCES = frozenset({Path(__file__).resolve(), Path(__file__).resolve().parent / "test_frozen_build.py"})
# The one place a test may actually decline to run, and only for the one test that needs a tool the app does not
# ship. Named apart from the bare-reference exemption so a second skip in that module is still reported.
EXEMPT_SKIP_DECORATORS = frozenset({Path(__file__).resolve().parent / "test_frozen_build.py"})


def _called_name(node: ast.AST) -> str | None:
    """The name an attribute or bare-name node refers to, or None if it is neither."""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def violations(tree: ast.AST, path: Path) -> list[tuple[int, str]]:
    """(line, detail) for every way this source could decline to run a test."""
    bare_exempt = path.resolve() in EXEMPT_BARE_REFERENCES
    # test_frozen_build.py is the one file allowed to actually skip, and only its build test: PyInstaller is a
    # build-time dependency that is not part of the app and is not installed on a reader's PC. It is named here
    # rather than exempted by file, so a second skip in that module is still reported.
    skip_exempt = path.resolve() in EXEMPT_SKIP_DECORATORS
    # A name used as the callee of a call, or as a decorator, is skipping. Any other mention is a loaded gun: a
    # bare `SKIP = unittest.skip` is one line away from `@SKIP` and reads as nothing at all.
    engaged = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            engaged.add(id(node.func))
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            engaged.update(id(deco.func if isinstance(deco, ast.Call) else deco) for deco in node.decorator_list)
    found = []
    for node in ast.walk(tree):
        name = _called_name(node)
        if name not in SKIP_NAMES:
            continue
        if id(node) in engaged:
            if skip_exempt:
                continue
            found.append((node.lineno, f'{name} is called, so a test can decline to run'))
        elif not bare_exempt:
            found.append((node.lineno, f'{name} is referenced without being called; only this guard may name it, '
                                       'in order to recognise it'))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            if alias.name in SKIP_NAMES:
                found.append((node.lineno, f'{alias.name} is imported, which is how a skip usually arrives'))
    return sorted(found)


@pytest.mark.notkinter
class TestNothingInThisSuiteCanSkip(unittest.TestCase):
 """AGENTS.md's zero-skips rule, enforced rather than stated.

 The rule was true by inspection, which is not the same as being true: a skip is invisible in a summary line
 unless somebody reads every test, and there are thirty files to read."""

 def _files(self):
    for path in sorted(TESTS.rglob('*.py')):
        if '__pycache__' not in path.parts:
            yield path

 def test_no_file_under_tests_can_skip(self):
    report = []
    walked = 0
    for path in self._files():
        walked += 1
        for lineno, detail in violations(ast.parse(path.read_text(encoding='utf-8')), path):
            report.append(f'  {path.relative_to(ROOT).as_posix()}:{lineno}: {detail}')
    self.assertEqual([], report, 'these tests can skip, and a skip reports exactly like a pass:\n'
                                 + '\n'.join(report))
    self.assertGreater(walked, 20, f'the walk reached {walked} files, so it is not looking at tests/')

 def test_the_walk_still_reaches_the_files_that_used_to_skip(self):
    """A guard that has quietly stopped finding files is worse than none, because it is still green.

    `rglob` over the wrong root, or a filter that stops matching, both leave a perfect run behind them. So the
    walk is checked against the files on disk rather than trusted, and the modules that each hid a class of
    tests are named one by one.
    """
    names = {path.name for path in self._files()}
    for required in ('test_artwork_render.py','tk_support.py','test_ui_geometry.py','test_conversion_safety.py',
                     'test_zero_skips.py'):
        self.assertIn(required, names, f'the walk no longer reaches {required}')

 def test_every_construct_the_rule_names_is_caught(self):
    """Each shape of skip is parsed here and has to be reported, or the rule above is decoration.

    The samples are string constants, so nothing in this test is itself a violation - which is also the answer
    to the objection that a guard naming what it forbids has to mention it somewhere.
    """
    samples = ("raise unittest.SkipTest('no fixture')",
               "self.skipTest('no fixture')",
               "@unittest.skip('always')\ndef test_one(self): pass",
               "@unittest.skip\ndef test_one(self): pass",
               "@unittest.skipIf(True, 'x')\ndef test_one(self): pass",
               "@unittest.skipUnless(False, 'x')\ndef test_one(self): pass",
               "@unittest.expectedFailure\ndef test_one(self): pass",
               "from unittest import skipIf",
               "SKIP = unittest.skip")
    for source in samples:
        self.assertTrue(violations(ast.parse(source), TESTS / 'sample.py'),
                        f'the guard does not notice this, which is one of the ways a skip hides:\n{source}')

 def test_a_file_that_only_mentions_them_is_left_alone(self):
    """Comments and docstrings are not in the AST, which is the reason this is a parser and not a grep.

    Every one of these names is in this repository's own prose about the skips it removed. A text search would
    have to exclude the files that document the rule in order to enforce it, and an exclusion is where a skip
    goes to hide.
    """
    source = ('"""A docstring mentioning unittest.SkipTest, skipIf, skipUnless and expectedFailure."""\n'
              '# And a comment naming self.skipTest and unittest.skip.\n'
              'import unittest\n\n'
              'class Compliant(unittest.TestCase):\n'
              '    def test_it_runs(self):\n'
              '        self.fail("deliberate")\n')
    self.assertEqual([], violations(ast.parse(source), TESTS / 'sample.py'))

 def test_a_compliant_file_is_not_reported_and_this_one_still_is(self):
    """The control, in both directions.

    Without the first half the rule above would be satisfied by a matcher that reports everything, which passes
    forever. Without the second it would be satisfied by the exemption being wider than it claims: this file
    names every construct it forbids, so if the exemption had been written as "skip the guard", this is where a
    real skip would go unnoticed.
    """
    compliant = "import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.fail('no')\n"
    self.assertEqual([], violations(ast.parse(compliant), TESTS / 'sample.py'))
    self.assertTrue(violations(ast.parse("raise unittest.SkipTest('x')"), Path(__file__).resolve()),
                    'the exemption covers this file wholesale, so a skip added here would go unreported')


if __name__ == '__main__':
    unittest.main()
