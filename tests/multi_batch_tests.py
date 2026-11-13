"""Extracted from tests/test_uri_actions.py.

    MultiBatchTests was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import tempfile
import unittest
import pytest
from pathlib import Path
from urllib.parse import quote
from core.uri_actions import UriRefused
from tests.test_uri_actions import make_archive
from core.parse_multi_uri import parse_multi_uri


class MultiBatchTests(unittest.TestCase):
    """parse_multi_uri must validate each source individually and require two or more."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.library = self.root / "library"
        self.library.mkdir()
        self.bases = [self.root / "extract"]
        self.a = make_archive(self.library, "Game A.7z")
        self.b = make_archive(self.library, "Game B.7z")

    def _uri(self, *archives, dest=None):
        parts = "steamgameorganizer://extract-multi?"
        params = [f"src={quote(str(a), safe='')}" for a in archives]
        if dest:
            params.append(f"dest={quote(dest, safe='')}")
        return parts + "&".join(params)

    def test_two_valid_archives_return_a_request_with_destinations(self):
        request = parse_multi_uri(self._uri(self.a, self.b), self.library, self.bases)
        self.assertEqual(len(request.archives), 2)
        self.assertEqual(request.archives[0][0], self.a)
        self.assertEqual(request.archives[1][0], self.b)
        self.assertEqual(request.destination, self.bases[0])

    def test_a_single_archive_is_refused(self):
        with self.assertRaises(UriRefused) as caught:
            parse_multi_uri(self._uri(self.a), self.library, self.bases)
        self.assertIn("at least two", str(caught.exception))

    def test_a_source_outside_the_library_is_refused(self):
        outside = self.root / "elsewhere.7z"
        outside.write_bytes(b"x")
        with self.assertRaises(UriRefused) as caught:
            parse_multi_uri(self._uri(self.a, outside), self.library, self.bases)
        self.assertIn("outside the game library", str(caught.exception))

    def test_a_non_archive_source_is_refused(self):
        plain = self.library / "notes.txt"
        plain.write_text("x")
        with self.assertRaises(UriRefused) as caught:
            parse_multi_uri(self._uri(self.a, plain), self.library, self.bases)
        self.assertIn("Not an archive", str(caught.exception))
