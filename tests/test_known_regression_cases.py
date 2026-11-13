"""Extracted from tests/test_scan_regressions.py.

    TestKnownRegressionCases was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch
from core.config import AppConfig
from ui.main_window import MainWindow
from utils.filename_utils import identity_key
from tests.test_scan_regressions import _tmp_dir
from utils.filename_utils import normalize_name


class TestKnownRegressionCases(unittest.TestCase):
    def test_known_identities(self):
        # 2026-11-10: "Incremental" is a legitimate game genre (idle/incremental games), so
        # "Delta Realm Incremental.zip" folds to "deltarealmincremental", not "deltarealm".
        # Replaced a real Steam game name with fictional "Nebula Online" per the
        # no-real-game-names rule (see tools/validate_game_names.py deny list).
        expected = {
            "Alpha Forge v 0 8.zip": "alphaforge",
            "Gamma Quest v 1 0.zip": "gammaquest",
            "Delta Realm Incremental.zip": "deltarealmincremental",
            "Nebula Online.zip": "nebulaonline",
        }
        for name, key in expected.items():
            self.assertEqual(identity_key(name), key, name)

    # The titles here are the real folders from one library, and every one of them failed to find its Steam name.
    # The cause was the tag stripper, not Steam: it only fired on whitespace-delimited tags, so the hyphenated
    # and dotted spellings these folders actually use survived into the search query, which then asked the store
    # for "Nebula Attracts-Steam" and never for "Nebula Attracts". The stripper is fixed and covered in
    # tests/test_filename_utils.py; this pins the outcome, so a change to the tag rules that brings any of these
    # back fails here by name.
    def test_tagged_library_folders_still_find_their_real_game(self):
        expected = {
            "Stellar.Squirrel-SteamRIP.com": "Stellar Squirrel",
            "Nebula Attracts-Steam RIP com": "Nebula Attracts",
            "Nebula Nights-Steam RIP com": "Nebula Nights",
            "Sun Topia-Steam RIP com": "Sun Topia",
        }
        for tagged, clean in expected.items():
            self.assertEqual(normalize_name(tagged), clean, tagged)
            self.assertEqual(identity_key(tagged), identity_key(clean), tagged)

    # Both the fake home and the project root hang off one temporary tree, which is the point. They used to be
    # Path('/tmp/...'), and on Windows a leading slash is not absolute - it resolves against whatever drive happens
    # to be current. So the mkdir created C:\tmp\portable-home\Downloads\Games and AppConfig rooted its config,
    # cache and log directories at C:\tmp\project-root: two directories outside this repository, on the one platform
    # whose own guard (tests/test_platform.py) forbids POSIX paths, created by the test asserting nothing is
    # hard-coded. C:\tmp is not a harmless accident either - ArtworkService deletes from whatever cache directory it
    # is handed, and a sibling test handed it C:\tmp\artwork-cache.
    def test_default_library_root_is_portable(self):
        root = Path(_tmp_dir(self))
        home = root / "portable-home"
        with patch("pathlib.Path.home", return_value=home):
            expected = home / "Downloads" / "Games"
            expected.mkdir(parents=True, exist_ok=True)
            config = AppConfig(root / "project-root")
            self.assertEqual(config.library_root, expected)

    def test_scan_done_keeps_scan_visible_until_verification_finishes(self):
        window = SimpleNamespace()
        window.closing = False
        window.views = {"scan": Mock(), "review": Mock()}
        window.views["scan"].art_var = SimpleNamespace(get=lambda: True)
        window.show = Mock()
        window.status = Mock()
        result = SimpleNamespace(archives=[object()])

        MainWindow.scan_done(window, result)

        window.views["scan"].set_result.assert_called_once_with(result)
        window.views["review"].load.assert_called_once_with(result.archives, download_artwork=True)
        window.status.configure.assert_called_once()
        window.show.assert_called_once_with("scan")

    def test_scan_new_artwork_done_routes_to_review_without_calling_end(self):
        """Reproduced before the fix: _scan_new_artwork_done called _end and stopped on Scan, so the
            newly-discovered archives were never loaded into Review and the user could not accept them."""
        from ui.main_window import MainWindow

        window = SimpleNamespace()
        window.closing = False
        window.views = {"scan": Mock(), "review": Mock()}
        window.show = Mock()
        window.status = Mock()
        archives = [object(), object()]

        MainWindow._scan_new_artwork_done(window, archives)

        window.views["scan"].finish_artwork_scan.assert_called_once_with(archives)
        window.views["review"].load.assert_called_once_with(archives, download_artwork=True)
        window.status.configure.assert_called_once()
        window.show.assert_called_once_with("scan")
        # Must NOT have called _end: verification_done owns the run termination.
        self.assertFalse(
            hasattr(window, "_end") and window._end.called,
            "_scan_new_artwork_done called _end, which would leave verification without a run guard",
        )
