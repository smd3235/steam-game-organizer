"""Extracted from tests/test_category_evidence.py.

    TestTheTwoPathsAgree was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import ast
import unittest
import pytest
from core.constants import suggest_category
from tests.test_category_evidence import CASES
from tests.test_category_evidence import ROOT
from core.constants import suggest_category_with_evidence


class TestTheTwoPathsAgree(unittest.TestCase):
    def test_the_string_and_evidence_paths_give_the_same_category(self):
        for args, expected in CASES:
            with self.subTest(case=args):
                category, evidence = suggest_category_with_evidence(*args)
                self.assertEqual(category, expected, "the evidence path changed the answer for %r" % (args,))
                self.assertEqual(suggest_category(*args), expected, "the string path changed the answer for %r" % (args,))
                self.assertEqual(evidence.chosen, expected, "the evidence names a different category than the function returned")

    def test_the_string_function_is_a_pure_wrapper(self):
        """The scoring has to live in one place. Asserted on the parsed code, because the
        wrapper's body is the whole contract: a docstring and one delegated return."""
        tree = ast.parse((ROOT / "core" / "constants.py").read_text(encoding="utf-8"))
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        body = functions["suggest_category"].body
        self.assertEqual(len(body), 2, "suggest_category is a docstring plus one delegated return, nothing else")
        self.assertIsInstance(body[0], ast.Expr, "the first statement is the docstring")
        returned = body[1].value
        self.assertIsInstance(returned, ast.Subscript, "suggest_category returns the delegated pair sliced to its first element")
        self.assertIsInstance(returned.value, ast.Call)
        self.assertEqual(ast.unparse(returned.value.func), "suggest_category_with_evidence")

    def test_the_scoring_tables_are_defined_inside_one_function_only(self):
        """Each scoring table is assigned exactly once in the module, inside the evidence
        function - a second copy of the logic would show up here as a second owner."""
        tree = ast.parse((ROOT / "core" / "suggest_category_with_evidence.py").read_text(encoding="utf-8"))
        owners = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Assign):
                    continue
                for target in sub.targets:
                    if isinstance(target, ast.Name) and target.id in ("inferred", "priority", "specificity"):
                        owners.setdefault(target.id, set()).add(node.name)
        for name in ("inferred", "priority", "specificity"):
            self.assertEqual(owners.get(name), {"suggest_category_with_evidence"}, "the %s table is defined outside the evidence function" % name)
