"""Extracted from tests/test_uri_actions.py.

    FreshPcRefusalsPointAtTheSetup was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import tempfile
import unittest
import pytest
from pathlib import Path
from core.uri_actions import UriRefused
from tests.test_helpers import make_archive
from tests.test_helpers import uri_for
from core.parse_uri import parse_uri


class FreshPcRefusalsPointAtTheSetup(unittest.TestCase):
    """The three refusals a PC that has never run the setup hits.

    Each carries the rule and the fix: the button at the top of the page
    that opens the wizard which sets the three folders. Without the pointer,
    a friend opening the catalog on a fresh machine is refused with nothing
    to do about it - the three folders are only settable by the app, and
    the page cannot write a file.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.library = self.root / "library"
        self.library.mkdir()
        self.bases = [self.root / "extract"]
        self.archive = make_archive(self.library)

    def _refused(self, parse, *args):
        try:
            parse(*args)
        except UriRefused as refused:
            return str(refused)
        return self.fail("the link was not refused")

    def test_a_source_outside_the_library_names_the_button(self):
        # The page names a folder this app was never set up to use: a
        # friend's disk at a different drive letter, or a fresh install.
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        outside = make_archive(elsewhere, "Elsewhere.7z")
        message = self._refused(parse_uri, uri_for(outside), self.library, self.bases)
        self.assertIn("outside the game library", message)
        self.assertIn("Set up on this PC", message)

    def test_no_extract_folder_names_the_button(self):
        message = self._refused(parse_uri, uri_for(self.archive), self.library, [])
        self.assertIn("No extract folder", message)
        self.assertIn("Set up on this PC", message)

    def test_no_game_library_names_the_button(self):
        message = self._refused(parse_uri, uri_for(self.archive), None, self.bases)
        self.assertIn("No game library", message)
        self.assertIn("Set up on this PC", message)

    def test_the_batch_form_carries_the_same_pointer(self):
        from core.parse_batch_uri import parse_batch_uri

        no_library = self._refused(parse_batch_uri, "steamgameorganizer://extract-all?category=Idle", None, self.bases)
        self.assertIn("No game library", no_library)
        self.assertIn("Set up on this PC", no_library)
        no_extract = self._refused(parse_batch_uri, "steamgameorganizer://extract-all?category=Idle", self.library, [])
        self.assertIn("No extract folder", no_extract)
        self.assertIn("Set up on this PC", no_extract)
