"""Extracted from tests/test_end_to_end.py.

    CorruptSourceIsRefused was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import pytest
import shutil
import tempfile
import unittest
from pathlib import Path
from tests.test_helpers import build_game_tree
from tests.test_helpers import package_seven_zip
from tests.test_helpers import run_organize
from tests.test_helpers import seven_zip
from core.constants import ARCHIVE_EXTENSIONS


class CorruptSourceIsRefused(unittest.TestCase):
    """A truncated archive - what an interrupted download leaves - must never be consumed.

    The fixture is a real .7z cut short, because that is the shape this actually failed on: a library was found
    holding 82 truncated files that reported success as games and would each have been offered for conversion.
    """

    def setUp(self):
        self.tool = seven_zip()
        self.scratch = Path(tempfile.mkdtemp(prefix="e2e-bad-"))
        self.library = self.scratch / "Games"
        staging = self.scratch / "built"
        build_game_tree(staging, "Game")
        broken_dir = self.library / "Broken Game"
        broken_dir.mkdir(parents=True)
        whole = self.scratch / "whole.7z"
        package_seven_zip(self.tool, whole, staging / "Game")
        self.truncated_bytes = whole.read_bytes()[:4096]
        self.broken = broken_dir / "Broken Game.7z"
        self.broken.write_bytes(self.truncated_bytes)
        self.log_path = self.scratch / "e2e.log"

    def tearDown(self):
        shutil.rmtree(self.scratch, ignore_errors=True)

    def test_a_truncated_archive_is_left_alone_and_the_refusal_is_logged(self):
        discovered, _moved, _events = run_organize(self.library, self.log_path)
        self.assertEqual(discovered, 1, "the broken archive was not discovered")

        # Refusing to convert is not refusing to organise: the game is still filed under its category, and the
        # app still writes its own sidecar files beside it. What matters is that the only *archive* left is the
        # one that arrived, byte for byte.
        survivors = sorted(p for p in self.library.rglob("*") if p.is_file() and p.suffix.lower() in ARCHIVE_EXTENSIONS)
        self.assertEqual(len(survivors), 1, f"a truncated archive produced or removed archives: {survivors}")
        self.assertEqual(survivors[0].read_bytes(), self.truncated_bytes, "the truncated archive's bytes changed")
        text = self.log_path.read_text(encoding="utf-8", errors="replace")
        self.assertIn("SOURCE_INTEGRITY_FAILED", text, "the refusal was not recorded in the log")
