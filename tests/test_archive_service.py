"""Tests for ArchiveService.archive_installer_kind - the pre-extraction sniff that decides whether an archive is an
installer (repack or ISO) rather than a ready-to-play game.

2026-11-10: Added DiscoveryIncrementalCache test class covering _walk_changed_files() incremental discovery and
discover(use_cache=...): empty-cache returns all files, matching cache skips unchanged directories, new top-level
category triggers a re-walk, and use_cache=False always walks everything.

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
import time
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

# DiscoveryIncrementalCache extracted to tests\discovery_incremental_cache.py — see that module for its definition.
from tests.discovery_incremental_cache import DiscoveryIncrementalCache
# DiscoverySkipsTheAppProjectFolder extracted to tests\discovery_skips_the_app_project_folder.py — see that module for its definition.
from tests.discovery_skips_the_app_project_folder import DiscoverySkipsTheAppProjectFolder
# StubDrivenListing extracted to tests\stub_driven_listing.py — see that module for its definition.
from tests.test_stub_driven_listing import StubDrivenListing
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
        run = patch(
            "services.archive_service.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout),
        )
        find_tool = patch.object(ExtractService, "find_tool", return_value=(tool, None))
        with find_tool, run as mocked:
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



if __name__ == "__main__":
    unittest.main()

