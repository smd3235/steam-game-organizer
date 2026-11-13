"""Extracted from tests/test_services.py.

    TestTheExtractorReportsWhyThereIsNoTool was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from core.logger import AppLogger
from services.extract_service import ExtractService


class TestTheExtractorReportsWhyThereIsNoTool(unittest.TestCase):
    r"""The finder knows which of PATH and the real install folders came up empty. That answer was thrown away.

    `extract()` bound `find_tool()`'s reason, then rebound the same name to the free-space check, and
    returned a hardcoded "not on PATH" instead. That has been wrong since v9.8, when the finder started
    looking in `C:\Program Files\7-Zip` - a machine where 7-Zip is installed and not on PATH is found
    correctly, and a machine with neither is told to fix a PATH that was never the problem.
    """

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.base = Path(self.folder.name)
        self.archive = self.base / "Cool Game.zip"
        self.archive.write_bytes(b"PK\x03\x04" + b"0" * 512)

    def test_the_finders_own_explanation_is_the_one_reported(self):
        service = ExtractService(AppLogger(self.base / "log.log"))
        reason = "7z/7za is not on PATH and no default 7-Zip install was found"
        with patch.object(ExtractService, "find_tool", staticmethod(lambda: (None, reason))):
            result = service.extract(self.archive, self.base / "out")
        self.assertFalse(result.ok)
        self.assertEqual(result.message, reason, "the specific reason the finder gave was discarded for a generic one")

    def test_a_missing_tool_is_not_reported_as_a_path_problem(self):
        service = ExtractService(AppLogger(self.base / "log.log"))
        with patch.object(ExtractService, "find_tool", staticmethod(lambda: (None, "nothing here at all"))):
            result = service.extract(self.archive, self.base / "out")
        self.assertNotIn("PATH", result.message, "the message blames PATH, but the finder also checks the real install folders")
