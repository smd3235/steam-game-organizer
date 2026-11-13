"""Extracted from tests/test_uri_actions.py.

    PlayAndMarkerUriTests was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote
from core.uri_actions import UriRefused


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
        from core.parse_pick_launcher_uri import parse_pick_launcher_uri

        uri = f"steamgameorganizer://pick-launcher?path={quote(str(self.marker), safe='')}"
        self.assertEqual(parse_pick_launcher_uri(uri, [self.extract]).resolve(), self.marker.resolve())

    def test_mark_installed_requires_marker(self):
        from core.parse_mark_installed_uri import parse_mark_installed_uri

        uri = f"steamgameorganizer://mark-installed?path={quote(str(self.marker), safe='')}"
        self.assertEqual(parse_mark_installed_uri(uri, [self.extract]).resolve(), self.marker.resolve())

    def test_play_accepts_explicit_exe_under_extract_root(self):
        from core.parse_play_uri import parse_play_uri

        uri = f"steamgameorganizer://play?exe={quote(str(self.exe), safe='')}"
        req = parse_play_uri(uri, [self.extract])
        self.assertEqual(req.exe.resolve(), self.exe.resolve())

    def test_play_accepts_marker_path_with_persisted_launch_target(self):
        from core.parse_play_uri import parse_play_uri

        uri = f"steamgameorganizer://play?path={quote(str(self.marker), safe='')}"
        req = parse_play_uri(uri, [self.extract])
        self.assertEqual(req.exe.resolve(), self.exe.resolve())

    def test_play_refuses_exe_outside_extract_root(self):
        from core.parse_play_uri import parse_play_uri

        outside = self.root / "outside.exe"
        outside.write_bytes(b"MZ")
        uri = f"steamgameorganizer://play?exe={quote(str(outside), safe='')}"
        with self.assertRaises(UriRefused):
            parse_play_uri(uri, [self.extract])
