"""The installer badge survives the full extract lifecycle on one archive.

Pre-extraction, an installer repack draws the blue "Installer" preview badge (sniffed from the
archive's own index, no extraction). Post-extraction, ExtractService relocates the unpacked
payload into a "Needs Install" folder, and regenerating the catalog must show the amber
"Needs install" badge for the same game instead - with the preview badge retracted. The sniffer
and the move are two surfaces of one fact and cannot disagree; this is the test that ties them
together.

The stub 7z (tests.test_services._stub_archive_tools) runs the real extract() pipeline without
the real tool, so this is green on a machine that has no 7-Zip installed.
"""

from __future__ import annotations

import json
import os
import unittest

import pytest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from core.logger import AppLogger
from core.uri_actions import safe_folder_name
from services.catalog_service import CatalogService
from services.extract_service import ExtractService
from services.installer_detect import NEEDS_INSTALL_DIRNAME
from tests.test_services import _stub_archive_tools


@pytest.mark.notkinter
class InstallerBadgeSurvivesTheExtractLifecycle(unittest.TestCase):
    def setUp(self):
        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        self.library = self.root / "Games"
        self.game = self.library / "Repacks" / "Beta Voyager - 2024-01-01"
        self.game.mkdir(parents=True)
        self.archive_name = "Beta Voyager.zip"
        self.archive = self.game / self.archive_name
        with zipfile.ZipFile(self.archive, "w") as handle:
            handle.writestr("setup.exe", b"MZ" * 16)
            handle.writestr("setup-1.bin", b"a" * 2048)
            handle.writestr("readme.txt", b"unpack me")
        (self.game / ".game-info.json").write_text(json.dumps({"appid": "123456", "name": "Beta Voyager", "description": "d", "release_date": "2020", "genres": ["Action"]}), encoding="utf-8")
        # The extract destination the catalog checks must match the one extract writes into, which
        # is the catalog's own destination stem rule: <dest>/<safe_folder_name(archive-stem)>.
        self.dest = self.root / "Extracted"
        bin_dir = self.root / "bin"
        _stub_archive_tools(bin_dir, tools=("7z",))
        self.stub = bin_dir / ("7z.bat" if os.name == "nt" else "7z")
        self.logger = AppLogger(self.root / "x.log")
        self.extractor = ExtractService(self.logger)
        self.extractor.find_tool = lambda: (str(self.stub), None)
        # Neither the disk space check nor the real 7z are what this test is about.
        self.extractor.check_space = lambda archive, destination: ""

    def _page(self) -> str:
        paths = CatalogService(self.logger, extract_folders=[self.dest]).generate(self.library)
        self.assertTrue(paths, "catalog generation produced no catalog file")
        return paths[0].read_text(encoding="utf-8")

    def test_pre_extract_badge_then_extract_then_post_extract_badge(self):
        page = self._page()
        self.assertIn('class="badge badge-install"', page, "the archive did not get the pre-extraction installer preview badge")
        self.assertIn("Installer</span>", page)
        self.assertNotIn("badge badge-warn", page, "a post-extract mark appeared before anything was extracted")
        self.assertNotIn("badge badge-done", page)

        stem = safe_folder_name(Path(self.archive_name).stem)
        result = self.extractor.extract(self.archive, self.dest / stem)
        self.assertTrue(result.ok, f"extraction failed: {result.message}")
        self.assertTrue(result.needs_install, "a repack payload was not flagged as needing install")
        self.assertTrue((self.dest / NEEDS_INSTALL_DIRNAME / stem / "setup.exe").is_file(), "setup.exe was not extracted into the Needs Install folder at the destination root")
        self.assertEqual(result.destination, self.dest / NEEDS_INSTALL_DIRNAME / stem, "the result did not point at the Needs Install folder")

        page = self._page()
        self.assertIn("Needs install", page, "the amber badge text is missing after extraction")
        self.assertEqual(page.count('class="badge badge-warn"'), 1, "the Needs install badge was not drawn exactly once")
        self.assertNotIn('class="badge badge-install"', page, "the pre-extraction installer badge was not retracted after extraction")


if __name__ == "__main__":
    unittest.main()
