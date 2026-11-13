"""Extracted from tests/test_batch_extract.py.

    BatchLinkNamesACategoryAndNothingElse was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import tempfile
import unittest
from pathlib import Path
from core.constants import LIBRARY_RESERVED_DIRS
from core.uri_actions import UriRefused
from tests.test_helpers import _game
from core.parse_batch_uri import parse_batch_uri


class BatchLinkNamesACategoryAndNothingElse(unittest.TestCase):
    """The security property. Everything else about the feature is convenience; this is the part that matters."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "Games"
        self.dest = Path(temporary.name) / "Out"
        self.dest.mkdir(parents=True)
        _game(self.root, "Idle", "Loop Miner")
        _game(self.root, "Idle", "Fellwood")
        _game(self.root, "RPG", "Deep Signal")

    def _parse(self, uri):
        return parse_batch_uri(uri, self.root, [self.dest])

    def test_a_category_link_resolves_to_that_folder(self):
        request = self._parse("steamgameorganizer://extract-all?category=Idle")
        self.assertEqual(request.category, "Idle")
        self.assertEqual(request.destination, self.dest)

    def test_the_link_carries_no_archive_paths_at_all(self):
        """The point of the design, asserted on the parsed request: there is nowhere for a page to put a source.

        A BatchExtractRequest has no field a path could be smuggled into, so this cannot regress into accepting
        one without the dataclass changing - a visible change rather than a silent one.
        """
        request = self._parse("steamgameorganizer://extract-all?category=Idle")
        extra = [name for name in request.__dataclass_fields__ if name not in ("category", "destination")]
        self.assertEqual(extra, [], f"BatchExtractRequest grew a field, so it can now be told what to unpack: {extra}")

    def test_a_src_parameter_in_the_link_is_ignored_rather_than_obeyed(self):
        """A page trying the single-extract trick anyway gets a category request, not a chosen file."""
        request = self._parse("steamgameorganizer://extract-all?category=Idle&src=C:/Windows/System32/config/SAM")
        self.assertEqual(request.category, "Idle")
        self.assertNotIn("archive", request.__dataclass_fields__)

    def test_a_bare_link_names_the_whole_library(self):
        """An extract-all link with no category selects every archive in the library.
        The category folder check is skipped for the empty case, which _handle_batch_uri
        treats as "whole library" rather than a refusal."""
        request = self._parse("steamgameorganizer://extract-all")
        self.assertEqual(request.category, "")
        self.assertEqual(request.destination, self.dest)

    def test_a_category_that_is_not_a_real_folder_is_refused(self):
        with self.assertRaises(UriRefused):
            self._parse("steamgameorganizer://extract-all?category=Nope")

    def test_a_category_cannot_walk_out_of_the_library(self):
        for hostile in ("..", "..%2F..", "Idle/../../Windows", "C:/Windows", "Idle\\..\\..", "Idle/"):
            with self.subTest(category=hostile):
                with self.assertRaises(UriRefused):
                    self._parse(f"steamgameorganizer://extract-all?category={hostile}")

    def test_the_apps_own_folders_are_not_categories(self):
        """Archive/ holds duplicates set aside on purpose and Processing/ holds a build in flight. Unpacking
        either would re-do work the app deliberately did not do."""
        for reserved in sorted(LIBRARY_RESERVED_DIRS):
            with self.subTest(folder=reserved):
                (self.root / reserved).mkdir(exist_ok=True)
                with self.assertRaises(UriRefused):
                    self._parse(f"steamgameorganizer://extract-all?category={reserved}")

    def test_a_hidden_folder_is_not_a_category(self):
        (self.root / ".stversions").mkdir()
        with self.assertRaises(UriRefused):
            self._parse("steamgameorganizer://extract-all?category=.stversions")

    def test_the_destination_follows_the_same_rules_as_a_single_extract(self):
        """The free-text case is a security boundary, and a second copy of it would be a second thing to get
        wrong. Proving the batch path refuses what the single path refuses is what keeps the two in step."""
        with self.assertRaises(UriRefused):
            self._parse("steamgameorganizer://extract-all?category=Idle&dest=not-a-full-path")
        with self.assertRaises(UriRefused):
            self._parse(f"steamgameorganizer://extract-all?category=Idle&dest={self.root}/Inside")
        request = self._parse(f"steamgameorganizer://extract-all?category=Idle&dest={self.dest}/Somewhere")
        self.assertEqual(request.destination, self.dest / "Somewhere")

    def test_a_single_extract_link_is_not_a_batch(self):
        with self.assertRaises(UriRefused):
            self._parse("steamgameorganizer://extract?src=x")
