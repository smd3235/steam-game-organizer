"""Tests for the steamgameorganizer:// handler, which the catalog page's free-text destination box feeds.

The destination used to have to be one of the configured extract folders, which made the page a dropdown. A text
box is what was asked for, so these tests pin down what a typed path still has to satisfy - and, just as
importantly, that a typed path cannot be used to write outside the places it should be able to write.
"""

from __future__ import annotations

import tempfile
import unittest

import pytest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

from core.uri_actions import UriRefused, parse_uri, safe_folder_name, parse_multi_uri, MultiBatchRequest, parse_open_folder_uri


def make_archive(library: Path, name: str = "Some Game.7z") -> Path:
    path = library / name
    path.write_bytes(b"not really an archive")
    return path


def uri_for(archive: Path, dest: str | None = None) -> str:
    link = f"steamgameorganizer://extract?src={quote(str(archive), safe='')}"
    if dest is not None:
        link += f"&dest={quote(dest, safe='')}"
    return link


@pytest.mark.notkinter
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
        with patch("core.uri_actions.os.access", return_value=False):
            with self.assertRaises(UriRefused) as caught:
                self.parse(str(locked / "child"))
        self.assertIn("not writable", str(caught.exception))


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
        from core.uri_actions import parse_batch_uri

        no_library = self._refused(parse_batch_uri, "steamgameorganizer://extract-all?category=Idle", None, self.bases)
        self.assertIn("No game library", no_library)
        self.assertIn("Set up on this PC", no_library)
        no_extract = self._refused(parse_batch_uri, "steamgameorganizer://extract-all?category=Idle", self.library, [])
        self.assertIn("No extract folder", no_extract)
        self.assertIn("Set up on this PC", no_extract)


class MultiBatchTests(unittest.TestCase):
    """parse_multi_uri must validate each source individually and require two or more."""

    def setUp(self):
        import tempfile

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


if __name__ == "__main__":
    unittest.main()
from core.uri_actions import parse_open_extracted_uri


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


class PlayAndMarkerUriTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.extract = self.root / "extract"
        self.extract.mkdir()
        self.marker = self.extract / "Game"
        self.marker.mkdir()
        self.exe = self.marker / "game.exe"
        self.exe.write_bytes(b"MZ")
        self.marker_file = self.marker / ".sgo-extract-info"
        self.marker_file.write_text('{"launch_target": "%s"}' % str(self.exe).replace("\\", "\\\\"), encoding="utf-8")

    def test_pick_launcher_requires_marker(self):
        from core.uri_actions import parse_pick_launcher_uri

        uri = f"steamgameorganizer://pick-launcher?path={quote(str(self.marker), safe='')}"
        self.assertEqual(parse_pick_launcher_uri(uri, [self.extract]).resolve(), self.marker.resolve())

    def test_mark_installed_requires_marker(self):
        from core.uri_actions import parse_mark_installed_uri

        uri = f"steamgameorganizer://mark-installed?path={quote(str(self.marker), safe='')}"
        self.assertEqual(parse_mark_installed_uri(uri, [self.extract]).resolve(), self.marker.resolve())

    def test_play_accepts_explicit_exe_under_extract_root(self):
        from core.uri_actions import parse_play_uri

        uri = f"steamgameorganizer://play?exe={quote(str(self.exe), safe='')}"
        req = parse_play_uri(uri, [self.extract])
        self.assertEqual(req.exe.resolve(), self.exe.resolve())

    def test_play_accepts_marker_path_with_persisted_launch_target(self):
        from core.uri_actions import parse_play_uri

        uri = f"steamgameorganizer://play?path={quote(str(self.marker), safe='')}"
        req = parse_play_uri(uri, [self.extract])
        self.assertEqual(req.exe.resolve(), self.exe.resolve())

    def test_play_refuses_exe_outside_extract_root(self):
        from core.uri_actions import parse_play_uri

        outside = self.root / "outside.exe"
        outside.write_bytes(b"MZ")
        uri = f"steamgameorganizer://play?exe={quote(str(outside), safe='')}"
        with self.assertRaises(UriRefused):
            parse_play_uri(uri, [self.extract])
