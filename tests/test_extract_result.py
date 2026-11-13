"""Tests for services.extract_result.ExtractResult: the outcome of one extraction.

ExtractResult is a frozen-ish dataclass carrying the archive, destination,
success flag, message, and optional byte/file counts plus a needs_install flag.
"""

import unittest
from pathlib import Path

from services.extract_result import ExtractResult


class TestExtractResultDefaults(unittest.TestCase):
    """Optional fields default to zero/False."""

    def test_default_extracted_bytes_is_zero(self):
        result = ExtractResult(archive="a.7z", destination=Path("out"), ok=True, message="done")
        self.assertEqual(result.extracted_bytes, 0)

    def test_default_file_count_is_zero(self):
        result = ExtractResult(archive="a.7z", destination=Path("out"), ok=True, message="done")
        self.assertEqual(result.file_count, 0)

    def test_default_code_is_zero(self):
        result = ExtractResult(archive="a.7z", destination=Path("out"), ok=True, message="done")
        self.assertEqual(result.code, 0)

    def test_default_needs_install_is_false(self):
        result = ExtractResult(archive="a.7z", destination=Path("out"), ok=True, message="done")
        self.assertFalse(result.needs_install)


class TestExtractResultExplicitValues(unittest.TestCase):
    """All fields accept explicitly provided values."""

    def test_all_fields_are_set(self):
        from pathlib import Path
        result = ExtractResult(
            archive=Path("a.7z"),
            destination=Path("out"),
            ok=False,
            message="locked",
            extracted_bytes=1024,
            file_count=5,
            code=2,
            needs_install=True,
        )
        self.assertEqual(result.archive, Path("a.7z"))
        self.assertEqual(result.destination, Path("out"))
        self.assertFalse(result.ok)
        self.assertEqual(result.message, "locked")
        self.assertEqual(result.extracted_bytes, 1024)
        self.assertEqual(result.file_count, 5)
        self.assertEqual(result.code, 2)
        self.assertTrue(result.needs_install)


class TestExtractResultSummaryProperty(unittest.TestCase):
    """summary returns the message."""

    def test_summary_equals_message(self):
        result = ExtractResult(archive="a.7z", destination=Path("out"), ok=True, message="all done")
        self.assertEqual(result.summary, "all done")


if __name__ == "__main__":
    unittest.main()
