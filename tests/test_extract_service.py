"""Tests for the installer-relocation branch of ExtractService.extract.

Driven against the project's stub archiver (written through _write_stub) so the real extract() pipeline runs -
real Popen, real pipe, real progress callback - without a real 7-Zip. The stub's _extract calls zipfile.extractall,
so the archive's internal layout is what lands in the destination, which is exactly what the relocation decision is
made on.
"""

from __future__ import annotations

import os
import unittest

import pytest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from core.logger import AppLogger
from services.extract_service import ExtractService
from services.installer_detect import NEEDS_INSTALL_DIRNAME
from tests.test_services import _STUB_ARCHIVER, _write_stub


def _stub_on(bin_dir: Path) -> Path:
    _write_stub(bin_dir, "7z", _STUB_ARCHIVER)
    tool = bin_dir / ("7z.bat" if os.name == "nt" else "7z")
    assert tool.is_file(), f"the stub archiver was not written where it can be run: {tool}"
    return tool


def _service(bin_dir: Path, logger) -> ExtractService:
    service = ExtractService(logger)
    service.find_tool = lambda: (str(_stub_on(bin_dir)), None)
    # The real check needs a writable destination and enough room; neither is what these tests are about.
    service.check_space = lambda archive, destination: ""
    return service


def _zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as handle:
        for name, body in members.items():
            handle.writestr(name, body)
    return path


@pytest.mark.notkinter
class InstallerArchivesAreRelocated(unittest.TestCase):
    """A repack (.bin + setup.exe) and an ISO release both unpack into a Needs Install folder."""

    def setUp(self):
        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.base = Path(self.dir.name)
        self.logger = AppLogger(self.base / "x.log")
        self.bin_dir = self.base / "bin"

    def test_a_repack_is_relocated_into_needs_install(self):
        archive = _zip(
            self.base / "FitGirl.zip",
            {
                "setup.exe": b"MZ" * 20,
                "setup-1.bin": b"a" * 5000,
                "readme.txt": b"unpack me",
            },
        )
        dest = self.base / "out"
        result = _service(self.bin_dir, self.logger).extract(archive, dest)
        self.assertTrue(result.ok, f"extraction failed: {result.message}")
        self.assertTrue(result.needs_install, "an installer layout was not flagged")
        needs = dest.parent / NEEDS_INSTALL_DIRNAME / dest.name
        self.assertTrue((needs / "setup.exe").is_file(), "setup.exe was not moved into Needs Install")
        self.assertTrue((needs / "setup-1.bin").is_file(), ".bin was not moved into Needs Install")
        self.assertEqual(result.destination, needs, "the result did not point at the folder the files actually landed in")
        self.assertIn("installer archive", result.message, f"the message hid the installer fact: {result.message!r}")

    def test_an_iso_release_is_relocated_into_needs_install(self):
        archive = _zip(
            self.base / "Folklands.zip",
            {
                "Folklands.iso": b"CD001" + b"\x00" * 200,
                "setup.exe": b"MZ" * 20,
            },
        )
        dest = self.base / "out"
        result = _service(self.bin_dir, self.logger).extract(archive, dest)
        self.assertTrue(result.ok, f"extraction failed: {result.message}")
        self.assertTrue(result.needs_install)
        needs = dest.parent / NEEDS_INSTALL_DIRNAME / dest.name
        self.assertTrue((needs / "Folklands.iso").is_file(), "the ISO was not moved into Needs Install")
        self.assertIn("iso", result.message.lower(), f"the message did not name the iso to mount: {result.message!r}")

    def test_a_repack_wrapped_in_a_folder_still_relocates_to_the_needs_install_root(self):
        # Some archives self-nest or wrap contents in a top-level folder. Relocation targets the
        # Needs Install folder at the destination parent level so the catalog badge - which now checks
        # both <dest>/<stem> and <dest>/Needs Install/<stem> - can find the marker regardless of nesting.
        archive = _zip(
            self.base / "Wrapped.zip",
            {
                "Game Name/setup.exe": b"MZ" * 20,
                "Game Name/setup-1.bin": b"a" * 1000,
            },
        )
        dest = self.base / "out"
        result = _service(self.bin_dir, self.logger).extract(archive, dest)
        self.assertTrue(result.ok, f"extraction failed: {result.message}")
        self.assertTrue(result.needs_install)
        needs = dest.parent / NEEDS_INSTALL_DIRNAME / dest.name
        self.assertTrue((needs / "Game Name/setup.exe").is_file())
        self.assertTrue((needs / "Game Name/setup-1.bin").is_file())
        self.assertEqual(result.destination, needs, "the result did not point at the Needs Install folder at the parent level")

    def test_a_relocate_failure_leaves_the_extracted_files_in_place(self):
        """A move that faults must not turn a successful unpack into a failed one.

        The files stay where 7z wrote them and the run reports a normal success, so the user is not told the
        extraction broke when it did not.
        """
        archive = _zip(self.base / "Broken.zip", {"setup.exe": b"MZ", "data.bin": b"x" * 1000})
        dest = self.base / "out"
        # Force the fallback path: pre-check returns None, so the extract service falls back to
        # the post-extraction find_installer() scan, which then triggers relocation.
        with patch.object(ExtractService, "_pre_check_installer", return_value=None), patch.object(ExtractService, "_relocate_to_needs_install", side_effect=OSError("simulated move failure")):
            result = _service(self.bin_dir, self.logger).extract(archive, dest)
        self.assertTrue(result.ok, "a relocation failure was reported as an extraction failure")
        self.assertFalse(result.needs_install, "a failed move was still flagged as relocated")
        self.assertTrue((dest / "setup.exe").is_file(), "files were moved despite the failure")
        self.assertEqual(dest, result.destination, "the result still pointed at where the files actually are")

    def test_a_destination_already_inside_needs_install_is_not_double_wrapped(self):
        """plan_batch already places installer targets inside Needs Install/, so extract() must not add
        a second layer. Before the fix the batch path produced Needs Install/Needs Install/<game>/ -
        a nested folder the catalog badge scan could never match."""
        from services.installer_detect import InstallSignature

        dest = self.base / "out" / NEEDS_INSTALL_DIRNAME / "Game Name"
        dest.mkdir(parents=True)
        archive = _zip(self.base / "Repack.zip", {"setup.exe": b"MZ" * 20, "data.bin": b"a" * 1000})
        service = _service(self.bin_dir, self.logger)
        with patch.object(ExtractService, "_pre_check_installer", return_value=InstallSignature(kind="repack", program=Path("setup.exe"))):
            result = service.extract(archive, dest)
        self.assertTrue(result.ok, f"extraction failed: {result.message}")
        self.assertEqual(result.destination, dest, "extract() added a second Needs Install layer on top of an already-correct path")
        self.assertFalse((dest.parent / NEEDS_INSTALL_DIRNAME / NEEDS_INSTALL_DIRNAME).exists(), "a nested Needs Install/Needs Install/ folder was created")


class PlainArchivesAreLeftAlone(unittest.TestCase):
    """The relocation must not fire for a normal, ready-to-play game."""

    def setUp(self):
        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.base = Path(self.dir.name)
        self.logger = AppLogger(self.base / "x.log")
        self.bin_dir = self.base / "bin"

    def test_a_game_exe_and_data_files_are_not_relocated(self):
        archive = _zip(
            self.base / "Game.zip",
            {
                "MyGame.exe": b"MZ" * 20,
                "globalgamemanagers.bin": b"a" * 500,
                "globalgamemanagers.assets": b"b" * 500,
            },
        )
        dest = self.base / "out"
        result = _service(self.bin_dir, self.logger).extract(archive, dest)
        self.assertTrue(result.ok, f"extraction failed: {result.message}")
        self.assertFalse(result.needs_install, "a game archive was mistaken for an installer")
        self.assertTrue((dest / "MyGame.exe").is_file(), "the game exe was moved by mistake")
        self.assertEqual(dest, result.destination)

    def test_a_successful_extraction_writes_a_marker(self):
        """The marker records the archive's size and mtime so a later catalog can detect staleness."""
        from services.extract_service import EXTRACT_MARKER
        import json as _json

        archive = _zip(self.base / "Game.zip", {"game.bin": b"a" * 100})
        dest = self.base / "out"
        result = _service(self.bin_dir, self.logger).extract(archive, dest)
        self.assertTrue(result.ok, f"extraction failed: {result.message}")
        marker = dest / EXTRACT_MARKER
        self.assertTrue(marker.is_file(), "the extract marker was not written after a successful extraction")
        info = _json.loads(marker.read_text(encoding="utf-8"))
        stat = archive.stat()
        self.assertEqual(info["archive_size"], stat.st_size, "the marker recorded the wrong archive size")
        self.assertEqual(info["archive_mtime_ns"], stat.st_mtime_ns, "the marker recorded the wrong archive mtime")

    def test_reextraction_preserves_launch_target_and_setup_done_marker_fields(self):
        from services.extract_service import EXTRACT_MARKER
        import json as _json

        archive = _zip(self.base / "Game.zip", {"game.bin": b"a" * 100})
        dest = self.base / "out"
        first = _service(self.bin_dir, self.logger).extract(archive, dest)
        self.assertTrue(first.ok, first.message)
        marker = dest / EXTRACT_MARKER
        info = _json.loads(marker.read_text(encoding="utf-8"))
        info["launch_target"] = "C:/Games/Game/game.exe"
        info["setup_done"] = True
        info["installed_at"] = "2026-01-01 00:00"
        marker.write_text(_json.dumps(info), encoding="utf-8")
        archive2 = _zip(self.base / "Game.zip", {"game.bin": b"b" * 150})
        second = _service(self.bin_dir, self.logger).extract(archive2, dest)
        self.assertTrue(second.ok, second.message)
        info2 = _json.loads((dest / EXTRACT_MARKER).read_text(encoding="utf-8"))
        self.assertEqual(info2.get("launch_target"), "C:/Games/Game/game.exe")
        self.assertTrue(info2.get("setup_done"))
        self.assertEqual(info2.get("installed_at"), "2026-01-01 00:00")
        self.assertEqual(info2.get("extracted_root"), str(dest))

    def test_a_lone_bin_without_an_installer_exe_is_not_relocated(self):
        archive = _zip(self.base / "Data.zip", {"level1.bin": b"a" * 500, "textures.dat": b"b"})
        dest = self.base / "out"
        result = _service(self.bin_dir, self.logger).extract(archive, dest)
        self.assertTrue(result.ok)
        self.assertFalse(result.needs_install, "plain data .bin files were mistaken for an installer")
        self.assertFalse((dest / NEEDS_INSTALL_DIRNAME).exists(), "a Needs Install folder was created for a non-installer")

    def test_a_lone_setup_exe_without_a_bin_is_not_relocated(self):
        archive = _zip(self.base / "Launcher.zip", {"setup.exe": b"MZ", "Game.exe": b"MZ"})
        dest = self.base / "out"
        result = _service(self.bin_dir, self.logger).extract(archive, dest)
        self.assertTrue(result.ok)
        self.assertFalse(result.needs_install)
        self.assertFalse((dest / NEEDS_INSTALL_DIRNAME).exists())


if __name__ == "__main__":
    unittest.main()
