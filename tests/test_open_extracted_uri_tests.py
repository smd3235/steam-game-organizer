"""Extracted from tests/test_uri_actions.py.

    OpenExtractedUriTests was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote
from core.uri_actions import UriRefused
from core.parse_open_extracted_uri import parse_open_extracted_uri


class OpenExtractedUriTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.extract = self.root / "extract"
        self.extract.mkdir()
        self.game = self.extract / "Game"
        self.game.mkdir()
        (self.game / ".sgo-extract-info").write_text("{}", encoding="utf-8")

    def test_valid_folder_inside_extract_root_returns_resolved_path(self):
        uri = f"steamgameorganizer://open-extracted?path={quote(str(self.game), safe='')}"
        result = parse_open_extracted_uri(uri, [self.extract])
        self.assertEqual(result.resolve(), self.game.resolve())

    def test_folder_outside_extract_roots_is_refused(self):
        outside = self.root / "outside"
        outside.mkdir()
        uri = f"steamgameorganizer://open-extracted?path={quote(str(outside), safe='')}"
        with self.assertRaises(UriRefused):
            parse_open_extracted_uri(uri, [self.extract])

    def test_missing_folder_is_refused(self):
        uri = f"steamgameorganizer://open-extracted?path={quote(str(self.extract / 'nope'), safe='')}"
        with self.assertRaises(UriRefused):
            parse_open_extracted_uri(uri, [self.extract])

    def test_no_extract_folder_configured_is_refused(self):
        uri = f"steamgameorganizer://open-extracted?path={quote(str(self.game), safe='')}"
        with self.assertRaises(UriRefused):
            parse_open_extracted_uri(uri, [])
