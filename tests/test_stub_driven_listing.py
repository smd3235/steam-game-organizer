"""Extracted from tests/test_archive_service.py.

    StubDrivenListing was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import io
import os
import tarfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from core.logger import AppLogger
from services.archive_service import ArchiveService
from services.extract_service import ExtractService
from services.installer_detect import InstallSignature


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
