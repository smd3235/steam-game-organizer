"""Tests for ArchiveService.archive_installer_kind - the pre-extraction sniff that decides whether an archive is an
installer (repack or ISO) rather than a ready-to-play game.

The zipfile branch is driven against real in-memory zips; the 7z/rar listing branch is driven against canned
`7z l -slt` output with the tool and subprocess patched, so the parse logic is pinned without a 7-Zip dependency.
A third case drives that same branch through the stub archiver end to end - real subprocess, real `l -slt` stream -
so the argv the sniffer builds and the live parse are pinned together without a 7-Zip dependency and without canned
output.
"""

from __future__ import annotations

import io
import os
import subprocess
import tarfile
import unittest

import pytest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from core.logger import AppLogger
from services.archive_service import ArchiveService
from services.extract_service import ExtractService
from services.installer_detect import InstallSignature


def _zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as handle:
        for name, body in members.items():
            handle.writestr(name, body)
    return path


def _service(tmp: Path) -> ArchiveService:
    return ArchiveService(AppLogger(tmp / "log.txt"))


def _slt(names: list[str]) -> subprocess.CompletedProcess:
    """A canned 7z `l -slt` listing built from member names."""
    blocks = "\n\n".join(f"Path = {n}\nFolder = -\nSize = 0\n" for n in names)
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=blocks + "\n" if blocks else "")


@pytest.mark.notkinter
class ZipBranch(unittest.TestCase):
    def test_a_repack_zip_is_detected(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            archive = _zip(tmp / "setup.zip", {"setup.exe": b"", "setup-1.bin": b""})
            sig = _service(tmp).archive_installer_kind(archive)
            self.assertIsInstance(sig, InstallSignature)
            self.assertEqual(sig.kind, "repack")
            self.assertEqual(sig.program.name, "setup.exe")

    def test_an_iso_zip_is_detected(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            archive = _zip(tmp / "iso.zip", {"Folklands.iso": b""})
            sig = _service(tmp).archive_installer_kind(archive)
            self.assertEqual(sig.kind, "iso")
            self.assertEqual(sig.program.name, "Folklands.iso")

    def test_a_nested_wrapper_repack_is_detected(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            archive = _zip(tmp / "wrapped.zip", {"Airborne/setup.exe": b"", "Airborne/setup-2.bin": b""})
            sig = _service(tmp).archive_installer_kind(archive)
            self.assertEqual(sig.kind, "repack")
            self.assertEqual(sig.program.name, "setup.exe")

    def test_a_game_exe_with_a_bin_is_not_an_installer(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            archive = _zip(tmp / "game.zip", {"MyGame.exe": b"", "globalgamemanagers.bin": b""})
            self.assertIsNone(_service(tmp).archive_installer_kind(archive))

    def test_plain_data_bin_is_not_an_installer(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            archive = _zip(tmp / "data.zip", {"level1.bin": b"", "textures.dat": b""})
            self.assertIsNone(_service(tmp).archive_installer_kind(archive))


class SevenZListingBranch(unittest.TestCase):
    def _patched(self, tmp, stdout, returncode=0):
        tool, _reason = ExtractService.find_tool() or ("fake-7z", None)
        with patch.object(ExtractService, "find_tool", return_value=(tool, None)), patch("services.archive_service.subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout)) as mocked:
            sig = _service(tmp).archive_installer_kind(tmp / "game.7z")
        return sig, mocked

    def test_a_repack_7z_listing_is_detected(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            sig, mocked = self._patched(tmp, _slt(["setup.exe", "setup-1.bin"]).stdout)
            mocked.assert_called_once()
            self.assertEqual(sig.kind, "repack")
            self.assertEqual(sig.program.name, "setup.exe")

    def test_an_iso_7z_listing_is_detected(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            sig, _ = self._patched(tmp, _slt(["Folklands.iso"]).stdout)
            self.assertEqual(sig.kind, "iso")
            self.assertEqual(sig.program.name, "Folklands.iso")

    def test_a_game_7z_listing_is_not_an_installer(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            sig, _ = self._patched(tmp, _slt(["Game.exe", "globalgamemanagers.bin"]).stdout)
            self.assertIsNone(sig)

    def test_a_failed_7z_listing_returns_none_without_raising(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            sig, mocked = self._patched(tmp, "garbage", returncode=2)
            mocked.assert_called_once()
            self.assertIsNone(sig)


class GracefulFailure(unittest.TestCase):
    def test_a_missing_archive_returns_none_without_raising(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            # No 7z on the machine: the sniffer gives up before spawning a process. With 7z present, 7z errors
            # (rc!=0) on the nonexistent file and the sniffer still returns None rather than raising.
            self.assertIsNone(_service(tmp).archive_installer_kind(tmp / "does-not-exist.7z"))

    def test_no_tool_returns_none_without_spawning_a_process(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            archive = tmp / "game.7z"
            archive.write_bytes(b"")
            with patch.object(ExtractService, "find_tool", return_value=(None, "no 7z")):
                with patch("subprocess.run") as mocked:
                    self.assertIsNone(_service(tmp).archive_installer_kind(archive))
                    mocked.assert_not_called()


class StubDrivenListing(unittest.TestCase):
    """The 7z/rar listing path through a real subprocess and the stub archiver.

    The canned-output branch above patches `subprocess.run` out of existence, so it cannot prove the argv the
    sniffer builds is the one the tool expects, or that a live `l -slt` stream parses. This drives the same
    call through the stub 7z (which speaks `l -slt`), so the two sides are pinned together and the test stays
    green without a 7-Zip install.
    """

    def _stub_service(self, tmp: Path) -> ArchiveService:
        from tests.test_services import _stub_archive_tools

        bin_dir = tmp / "bin"
        _stub_archive_tools(bin_dir, tools=("7z",))
        stub = bin_dir / ("7z.bat" if os.name == "nt" else "7z")
        self.assertTrue(stub.is_file(), f"the stub archiver was not written where it can run: {stub}")
        # Point the sniffer at the stub rather than whatever real 7z this machine has, so the listing actually
        # runs against the stub and not the bundled runtime copy.
        patcher = patch.object(ExtractService, "find_tool", return_value=(str(stub), None))
        patcher.start()
        self.addCleanup(patcher.stop)
        return ArchiveService(AppLogger(tmp / "log.txt"))

    def test_a_real_listing_through_the_stub_sniffs_a_repack(self):
        # A tar archive wearing a .7z suffix: the stub opens it by content, so the format inside is
        # irrelevant - what is exercised is the sniffer's invocation and its parse of a real -slt stream.
        with TemporaryDirectory() as d:
            tmp = Path(d)
            archive = tmp / "setup.7z"
            with tarfile.open(archive, "w") as tar:
                for name, body in {"setup.exe": b"MZ" * 16, "setup-1.bin": b"a" * 64}.items():
                    info = tarfile.TarInfo(name=name)
                    info.size = len(body)
                    tar.addfile(info, io.BytesIO(body))
            sig = self._stub_service(tmp).archive_installer_kind(archive)
            self.assertIsInstance(sig, InstallSignature)
            self.assertEqual(sig.kind, "repack")
            self.assertEqual(sig.program.name, "setup.exe")

    def test_a_real_listing_through_the_stub_sniffs_an_iso(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            archive = tmp / "Folklands.7z"
            with tarfile.open(archive, "w") as tar:
                for name, body in {"Folklands.iso": b"CD001" + b"\x00" * 16}.items():
                    info = tarfile.TarInfo(name=name)
                    info.size = len(body)
                    tar.addfile(info, io.BytesIO(body))
            sig = self._stub_service(tmp).archive_installer_kind(archive)
            self.assertEqual(sig.kind, "iso")
            self.assertEqual(sig.program.name, "Folklands.iso")


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


if __name__ == "__main__":
    unittest.main()
