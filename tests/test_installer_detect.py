"""Tests for the installer-layout recogniser in services/installer_detect.

The predicate is the one both the extract step and the catalog badge lean on, so it is pinned directly and in
isolation: a game folder is not scanned with a stub archiver just to ask "does this look like a repack".
"""

from __future__ import annotations

import unittest

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

from services.installer_detect import NEEDS_INSTALL_DIRNAME, find_installer, has_needs_install_mark, looks_like_installer


@pytest.mark.notkinter
class LooksLikeAnInstaller(unittest.TestCase):
    def setUp(self):
        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)

    def _touch(self, *parts: str) -> Path:
        path = self.root / Path(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        return path

    def test_a_repack_setup_exe_with_a_bin_file_is_flagged(self):
        setup = self._touch("setup.exe")
        self._touch("setup-1.bin")
        sig = find_installer(self.root)
        self.assertIsNotNone(sig, "a setup.exe next to a .bin was not recognised")
        self.assertEqual(sig.kind, "repack")
        self.assertEqual(sig.program, setup, "the message could not name the installer to run")
        self.assertEqual(sig.program.name, "setup.exe")

    def test_an_iso_release_is_flagged_as_an_iso(self):
        iso = self._touch("Folklands.iso")
        sig = find_installer(self.root)
        self.assertIsNotNone(sig, "an archive that unpacks to a .iso was not recognised")
        self.assertEqual(sig.kind, "iso")
        self.assertEqual(sig.program, iso, "the .iso to mount was not the one returned for the message")

    def test_a_repack_signature_nested_in_a_wrapper_folder_is_still_found(self):
        self._touch("Airborne Empire/setup.exe")
        self._touch("Airborne Empire/setup-2.bin")
        self.assertTrue(looks_like_installer(self.root), "an installer nested inside a wrapper folder was missed")

    def test_a_setup_exe_without_a_bin_is_not_an_installer(self):
        # A launcher called setup.exe and nothing else is just a game, not a repack. Requiring the .bin is what
        # keeps a normal game from being filed as an installer.
        self._touch("setup.exe")
        self._touch("Game.exe")
        self._touch("data/mainData")
        self.assertFalse(looks_like_installer(self.root), "a lone setup.exe was mistaken for a repack")

    def test_a_bin_file_alone_is_not_an_installer(self):
        self._touch("level1.bin")
        self._touch("textures.dat")
        self.assertFalse(looks_like_installer(self.root), "plain data .bin files were mistaken for an installer")

    def test_a_game_exe_with_a_bin_is_not_an_installer(self):
        # The exe has to be a named installer, not the game's own binary. A Unity build ships mainData.bin and a
        # Game.exe; that combination must stay a ready-to-play game.
        self._touch("MyGame.exe")
        self._touch("globalgamemanagers.bin")
        self._touch("globalgamemanagers.assets")
        self.assertFalse(looks_like_installer(self.root), "a game's own .exe was mistaken for an installer")

    def test_an_iso_alongside_a_launcher_still_flags_the_iso(self):
        self._touch("setup.exe")
        iso = self._touch("Disk1.iso")
        sig = find_installer(self.root)
        self.assertIsNotNone(sig)
        self.assertEqual(sig.kind, "iso", "an ISO release should report the iso to mount")
        self.assertEqual(sig.program, iso)


class TheNeedsInstallMark(unittest.TestCase):
    def test_true_when_the_folder_is_inside_a_needs_install_directory(self):
        with TemporaryDirectory() as d:
            outer = Path(d) / NEEDS_INSTALL_DIRNAME
            game = outer / "Some Game"
            game.mkdir(parents=True)
            self.assertTrue(has_needs_install_mark(game), "a game folder inside Needs Install was not detected")

    def test_true_when_the_folder_contains_a_needs_install_subfolder(self):
        with TemporaryDirectory() as d:
            (Path(d) / NEEDS_INSTALL_DIRNAME).mkdir()
            self.assertTrue(has_needs_install_mark(d), "the old layout (Needs Install inside the game folder) was not detected")

    def test_false_when_it_does_not(self):
        with TemporaryDirectory() as d:
            self.assertFalse(has_needs_install_mark(d))

    def test_false_for_a_non_directory(self):
        with TemporaryDirectory() as d:
            (Path(d) / NEEDS_INSTALL_DIRNAME).write_bytes(b"x")
            self.assertFalse(has_needs_install_mark(d), "a file named 'Needs Install' was mistaken for the relocation folder")


if __name__ == "__main__":
    unittest.main()
