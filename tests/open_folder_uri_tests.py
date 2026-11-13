"""Extracted from tests/test_uri_actions.py.

    OpenFolderUriTests was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import tempfile
import unittest
import pytest
from pathlib import Path
from urllib.parse import quote
from core.uri_actions import UriRefused
from core.parse_open_folder_uri import parse_open_folder_uri


class OpenFolderUriTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.library = self.root / "library"
        self.library.mkdir()
        self.sub = self.library / "Game Folder"
        self.sub.mkdir()

    def test_valid_folder_inside_library_returns_path(self):
        uri = f"steamgameorganizer://open-folder?path={quote(str(self.sub), safe='')}"
        result = parse_open_folder_uri(uri, self.library)
        self.assertEqual(result, self.sub)

    def test_folder_outside_library_is_refused(self):
        uri = f"steamgameorganizer://open-folder?path={quote(str(self.root), safe='')}"
        with self.assertRaises(UriRefused) as caught:
            parse_open_folder_uri(uri, self.library)
        self.assertIn("outside the game library", str(caught.exception))

    def test_no_library_is_refused(self):
        uri = f"steamgameorganizer://open-folder?path={quote(str(self.sub), safe='')}"
        with self.assertRaises(UriRefused) as caught:
            parse_open_folder_uri(uri, None)
        self.assertIn("No game library", str(caught.exception))
