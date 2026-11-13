"""Extracted from tests/test_cleanup_regressions.py.

    TestSyncthingTempFilesAreCleanedUp was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import os
import time
import unittest
from pathlib import Path
from core.logger import AppLogger
from tests.test_helpers import _tmp_dir
from services.library_service import LibraryService


class TestSyncthingTempFilesAreCleanedUp(unittest.TestCase):
    """Syncthing writes its in-flight transfers under two different names, and only one was recognised.

    Found in the real library, not in a fixture: three files sat in the library root named

        ~syncthing~Game Library (Steam Deck) - 2026-10-02 115241.html.tmp   (399 KB)
        ~syncthing~Game Library (Windows) - 2026-10-02 115241.html.tmp     (396 KB)
        ~syncthing~Open Game Library (Steam Deck).desktop.tmp             (335 bytes)

    `SYNC_FILE_PATTERNS` listed `*.syncthing.*.tmp` - the tilde-free infix form - so cleanup walked straight past
    all three. They had been there two days. The irony is that the stranded files are named after the old
    Steam Deck catalogs, so the very artifacts this app was supposed to be deleting are the ones it kept.

    Nothing had noticed because every test used the infix spelling, which is the one form the code handles.
    """

    def _service(self, root):
        return LibraryService(AppLogger(Path(root) / "x.log"))

    def _debris(self, root, name):
        path = Path(root) / name
        path.write_text("x" * 4096)
        # Aged past any grace period, so only the pattern can decide whether it is removed.
        old = time.time() - 30 * 24 * 3600
        os.utime(path, (old, old))
        return path

    def test_the_tilde_spelling_is_recognised(self):
        for name in (
            "~syncthing~Game Library (Steam Deck) - 2026-10-02 115241.html.tmp",
            "~syncthing~Open Game Library (Steam Deck).desktop.tmp",
            "~syncthing~game.7z.tmp",
        ):
            with self.subTest(name=name):
                root = Path(_tmp_dir(self))
                debris = self._debris(root, name)
                self._service(root).cleanup_leftovers(root, grace_seconds=0)
                self.assertFalse(debris.exists(), f"{name} was left behind; cleanup does not match this spelling")

    def test_the_infix_spelling_still_works(self):
        """Both spellings, because the fix must not have been to swap one for the other."""
        root = Path(_tmp_dir(self))
        debris = self._debris(root, "game.7z.syncthing.abc.tmp")
        self._service(root).cleanup_leftovers(root, grace_seconds=0)
        self.assertFalse(debris.exists(), "the spelling that already worked stopped being cleaned up")

    def test_a_transfer_still_in_flight_is_left_alone(self):
        """The grace period is the reason any of this is safe, so it is asserted for the new pattern too.

        A '~syncthing~' file that is minutes old may be an in-flight transfer on the other machine, and deleting it
        would destroy the copy being written.
        """
        root = Path(_tmp_dir(self))
        live = root / "~syncthing~game.7z.tmp"
        live.write_text("x" * 4096)
        self._service(root).cleanup_leftovers(root, grace_seconds=3600)
        self.assertTrue(live.exists(), "a transfer that is still in flight was deleted")

    def test_a_real_game_file_is_never_matched(self):
        """The pattern is a prefix, so it is worth proving it cannot reach a game archive."""
        root = Path(_tmp_dir(self))
        keep = root / "~syncthing notes.txt"
        keep.write_text("x")
        self._service(root).cleanup_leftovers(root, grace_seconds=0)
        self.assertTrue(keep.exists(), "a file merely starting with ~syncthing~ was deleted")
