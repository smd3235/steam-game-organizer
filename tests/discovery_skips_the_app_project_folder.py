"""Extracted from tests/test_archive_service.py.

    DiscoverySkipsTheAppProjectFolder was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
from pathlib import Path
from tests.test_helpers import _service
from tempfile import TemporaryDirectory


class DiscoverySkipsTheAppProjectFolder(unittest.TestCase):
    """Discovery walks the library root and never offered the app's own project folder as a game.

    When the app is installed inside the library root - which is the default - every scan walked it as a
    folder of one game: the app itself, and the feed listed its runtime files, its bundled Python and its
    timezone tables as archives. Discovery had no test for it at all; the audit, repair and catalog passes
    all had one and skipped it, which is why those phases were clean while discovery reported hundreds of
    files that were never games. The entry-point filename identifies the project regardless of what the
    folder is called, so renaming the project folder no longer re-adds it to the catalog.
    """

    def _library(self, tmp: Path) -> Path:
        library = tmp / "Games"
        library.mkdir()
        action = library / "Action"
        action.mkdir()
        game = action / "Loop Miner - 2020-01-01"
        game.mkdir()
        (game / "Loop Miner.zip").write_bytes(b"PK\x03\x04" + b"0" * 512)
        app = library / "Steam Game Organizer"
        app.mkdir()
        (app / "steam_game_organizer.py").write_text("# stub\n")
        (app / "state.py").write_text("x = 1\n")
        (app / "argparse.py").write_text("x = 1\n")
        rt = app / "runtime"
        rt.mkdir()
        (rt / "python.exe").write_bytes(b"\0" * 64)
        (rt / "tk86t.dll").write_bytes(b"\0" * 64)
        for name in ("cmd.py", "gzip.py", "random.py"):
            (rt / name).write_text("x = 1\n")
        tz = rt / "lib" / "tzdata"
        tz.mkdir(parents=True)
        for name in ("Accra", "Juba", "Tripoli", "Bahia"):
            (tz / name).write_text("x = 1\n")
        return library

    def test_the_app_folder_is_not_scanned_as_a_game(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            archives = _service(tmp).discover(self._library(tmp)).archives
            names = [a.path.name for a in archives]
            self.assertEqual(names, ["Loop Miner.zip"], f"expected only the game, got {names}")
            self.assertFalse(any("state.py" in n or "argparse.py" in n or "Accra" in n for n in names), "the app folder was scanned as a game")

    def test_renaming_the_project_folder_does_not_re_add_it(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            library = self._library(tmp)
            (library / "Steam Game Organizer").rename(library / "SGO Renamed")
            archives = _service(tmp).discover(library).archives
            names = [a.path.name for a in archives]
            self.assertEqual(names, ["Loop Miner.zip"], f"expected only the game after rename, got {names}")

    def test_the_library_root_is_scanned_when_it_is_the_app_folder(self):
        """The shared-library layout: the app is installed in the game folder, so the library root
        itself holds the entry point and IS the app folder.

        Refusing the library root outright would have found nothing at all - the verify screen would
        show no games with no way to continue, which is the failure this class exists to prevent in the
        other direction. The root is the thing being scanned; only a folder strictly inside it that
        happens to hold the entry point is the app's project folder.
        """
        with TemporaryDirectory() as d:
            tmp = Path(d)
            library = tmp / "Games"
            library.mkdir()
            action = library / "Action"
            action.mkdir()
            game = action / "Loop Miner - 2020-01-01"
            game.mkdir()
            (game / "Loop Miner.zip").write_bytes(b"PK\x03\x04" + b"0" * 512)
            # The library root itself is the app folder in this layout.
            (library / "steam_game_organizer.py").write_text("# stub\n")
            (library / "state.py").write_text("x = 1\n")
            rt = library / "runtime"
            rt.mkdir()
            (rt / "python.exe").write_bytes(b"\0" * 64)
            for name in ("cmd.py", "gzip.py"):
                (rt / name).write_text("x = 1\n")
            cache = library / "cache" / "artwork"
            cache.mkdir(parents=True)
            for name in ("1029780_steam_fallback.jpg", "header_image.jpg"):
                (cache / name).write_bytes(b"\xff\xd8\xff\xd9")
            archives = _service(tmp).discover(library).archives
            names = [a.path.name for a in archives]
            self.assertEqual(names, ["Loop Miner.zip"], f"the library root was treated as the app folder and nothing was found: {names}")
            self.assertFalse(any("state.py" in n or "cmd.py" in n or "steam_fallback" in n for n in names), "the app folder was scanned as a game")
