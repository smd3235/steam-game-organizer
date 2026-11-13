"""Extracted from tests/test_uri_actions.py.

    TypedDestinationTests was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import tempfile
import unittest
import pytest
from pathlib import Path
from unittest.mock import patch
from core.uri_actions import UriRefused
from core.parse_uri import parse_uri
from tests.test_uri_actions import make_archive
from tests.test_uri_actions import uri_for
from core.safe_folder_name import safe_folder_name


class TypedDestinationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.library = self.root / "library"
        self.library.mkdir()
        self.bases = [self.root / "extract"]
        self.archive = make_archive(self.library)

    def parse(self, dest):
        return parse_uri(uri_for(self.archive, dest), self.library, self.bases)

    def test_a_typed_folder_outside_the_configured_ones_is_accepted(self):
        """The point of the text box: any real folder works, not just the configured ones."""
        elsewhere = self.root / "somewhere else"
        elsewhere.mkdir()
        request = self.parse(str(elsewhere))
        self.assertEqual(request.destination, elsewhere / safe_folder_name(self.archive.stem))

    def test_a_tilde_path_is_expanded(self):
        request = self.parse("~/TypedDestination")
        self.assertTrue(str(request.destination).startswith(str(Path.home())))
        self.assertEqual(request.destination.name, safe_folder_name(self.archive.stem))

    def test_each_game_gets_its_own_folder_under_a_typed_parent(self):
        """Two games typed to the same parent must not overwrite each other."""
        other = make_archive(self.library, "Other Game.7z")
        one = parse_uri(uri_for(self.archive, str(self.root)), self.library, self.bases).destination
        two = parse_uri(uri_for(other, str(self.root)), self.library, self.bases).destination
        self.assertNotEqual(one, two)

    def test_a_folder_that_does_not_exist_yet_is_fine(self):
        request = self.parse(str(self.root / "not" / "created" / "yet"))
        self.assertEqual(request.destination.parent.name, "yet")

    def test_a_relative_path_is_refused(self):
        with self.assertRaises(UriRefused) as caught:
            self.parse("Downloads/Extracted")
        self.assertIn("full path", str(caught.exception))

    def test_blank_input_falls_back_to_the_configured_folder(self):
        request = self.parse("   ")
        self.assertEqual(request.destination, self.bases[0] / safe_folder_name(self.archive.stem))

    def test_the_filesystem_root_is_refused(self):
        with self.assertRaises(UriRefused):
            self.parse("/")

    def test_system_folders_are_refused(self):
        for path in ("/etc", "/usr", "/bin", "/proc"):
            with self.subTest(path=path):
                with self.assertRaises(UriRefused):
                    self.parse(path)

    def test_the_home_folder_itself_is_refused(self):
        with self.assertRaises(UriRefused):
            self.parse(str(Path.home()))

    def test_a_destination_inside_the_game_library_is_refused(self):
        """Unpacking into the library would be re-discovered as new game folders on the next scan."""
        with self.assertRaises(UriRefused) as caught:
            self.parse(str(self.library / "Extracted"))
        self.assertIn("inside the game library", str(caught.exception))

    def test_a_file_is_not_a_destination(self):
        target = self.root / "a-file.txt"
        target.write_text("x")
        with self.assertRaises(UriRefused) as caught:
            self.parse(str(target))
        self.assertIn("not a folder", str(caught.exception))

    def test_a_source_outside_the_library_is_still_refused(self):
        outside = make_archive(self.root, "Elsewhere.7z")
        with self.assertRaises(UriRefused) as caught:
            parse_uri(uri_for(outside, str(self.root)), self.library, self.bases)
        self.assertIn("outside the game library", str(caught.exception))

    def test_a_non_archive_source_is_still_refused(self):
        plain = self.library / "notes.txt"
        plain.write_text("x")
        with self.assertRaises(UriRefused):
            parse_uri(uri_for(plain, str(self.root)), self.library, self.bases)

    def test_no_configured_folders_still_refuses_a_typed_path(self):
        """Without a configured folder the default is undefined, and the page has nothing to start from."""
        with self.assertRaises(UriRefused) as caught:
            parse_uri(uri_for(self.archive, str(self.root)), self.library, [])
        self.assertIn("No extract folder", str(caught.exception))

    def test_a_folder_that_cannot_be_created_is_refused(self):
        # Windows has no equivalent of a mode that stops a write, and it does not honour 0o500 at all, so
        # chmod-ing a real folder here would be testing Windows' leniency rather than the refusal - and root
        # on Linux can write anywhere, so the old version skipped itself out of existence on one host and
        # errored on the other. The rule being checked is "the closest existing folder is not writable", so
        # that is what is stubbed, and it is checked on every platform.
        locked = self.root / "locked"
        locked.mkdir()
        with patch("os.access", return_value=False):
            with self.assertRaises(UriRefused) as caught:
                self.parse(str(locked / "child"))
        self.assertIn("not writable", str(caught.exception))
