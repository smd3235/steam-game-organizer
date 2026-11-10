"""Catalog page functional/interactive contract tests.

The catalog is a static `file://` HTML page with embedded JS. These tests validate that
all interactable controls, data attributes, protocol links, and JS wiring needed for
user actions are present and internally consistent in generated output. They do not
execute a browser; they assert the generated contracts that the page/app rely on.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest

import pytest
import zipfile
from pathlib import Path
from urllib.parse import quote, unquote

from core.logger import AppLogger
from core.uri_actions import parse_open_extracted_uri, parse_open_folder_uri, parse_uri
from services.catalog_service import CatalogService
from services.installer_detect import NEEDS_INSTALL_DIRNAME


def _write_game(game_dir: Path, *, name: str, appid: str = "123", archive: str | None = None, release_date: str = "2024-01-01", genres=None, tags=None, description: str = "desc", archive_members=None):
    game_dir.mkdir(parents=True, exist_ok=True)
    if archive:
        arc = game_dir / archive
        with zipfile.ZipFile(arc, "w") as z:
            for member, data in (archive_members or {"readme.txt": b"x"}).items():
                z.writestr(member, data)
    payload = {"appid": appid, "name": name, "release_date": release_date, "genres": genres or ["Action"], "tags": tags or [], "description": description}
    (game_dir / ".game-info.json").write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.notkinter
class CatalogPageInteractiveContracts(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.root = Path(self.td.name)
        self.lib = self.root / "Games"
        self.extract = self.root / "Extracted"
        self.logger = AppLogger(self.root / "test.log")
        # Ready extracted game
        _write_game(self.lib / "Action" / "Ready - 2024", name="Ready", appid="101", archive="Ready.zip", genres=["Action"], tags=["RPG"])
        ready_dest = self.extract / "Ready"
        ready_dest.mkdir(parents=True)
        (ready_dest / "game.exe").write_bytes(b"MZ")
        arc = self.lib / "Action" / "Ready - 2024" / "Ready.zip"
        (ready_dest / ".sgo-extract-info").write_text(json.dumps({"extracted_root": str(ready_dest), "archive_size": arc.stat().st_size, "archive_mtime_ns": arc.stat().st_mtime_ns, "extracted_at": "2026-01-01 00:00", "needs_install": False}), encoding="utf-8")
        # Needs-install extracted game
        _write_game(self.lib / "Repacks" / "SetupGame - 2024", name="SetupGame", appid="102", archive="SetupGame.zip", genres=["Simulation"], archive_members={"setup.exe": b"MZ", "setup-1.bin": b"x" * 10})
        inst = self.extract / NEEDS_INSTALL_DIRNAME / "SetupGame"
        inst.mkdir(parents=True)
        (inst / "setup.exe").write_bytes(b"MZ")
        arc2 = self.lib / "Repacks" / "SetupGame - 2024" / "SetupGame.zip"
        (inst / ".sgo-extract-info").write_text(json.dumps({"extracted_root": str(inst), "archive_size": arc2.stat().st_size, "archive_mtime_ns": arc2.stat().st_mtime_ns, "extracted_at": "2026-01-01 00:00", "needs_install": True}), encoding="utf-8")
        # Not extracted
        _write_game(self.lib / "Action" / "Fresh - 2024", name="Fresh", appid="103", archive="Fresh.zip")
        self.svc = CatalogService(self.logger, extract_folders=[self.extract])
        self.html = self.svc.generate(self.lib)[0].read_text(encoding="utf-8")

    def test_all_key_interactive_controls_exist(self):
        required_ids = [
            "search",
            "game-folder",
            "extract-dest",
            "setup-link",
            "refresh-catalog",
            "multi-btn",
            "extract-selected",
            "clear-selection",
            "theme",
            "to-top",
            "setup-copy",
            "batch-status",
            "run-status",
            "toast",
            "progress-bar",
        ]
        for rid in required_ids:
            self.assertRegex(self.html, rf'id=["\']{re.escape(rid)}["\']', f"missing interactive control #{rid}")

    def test_sort_filter_chip_and_path_controls_have_expected_attrs(self):
        for attr in ('data-sort="name"', 'data-sort="date"', 'data-sort="size"', "data-filter=", "data-batch=", "data-extract=", "data-open-folder=", "data-rel=", "data-extracted-rel=", "data-extracted-path=", 'data-setup="steamgameorganizer://setup"', 'data-refresh="steamgameorganizer://refresh-catalog"', 'aria-label="Search games"'):
            self.assertIn(attr, self.html, f"missing control/data attribute: {attr}")

    def test_action_buttons_use_expected_labels_and_protocol_hooks(self):
        # State-aware labels present. Ready extracted games may show Play/Open extracted
        # depending on whether a launcher is saved; pick launcher/mark installed are state-dependent.
        for label in ("Open source", "Open installer", "Extract"):
            self.assertIn(label, self.html)
        self.assertRegex(self.html, r'data-open-extracted="1"|data-play="1"')
        self.assertRegex(self.html, r'data-marker-dir="')
        self.assertIn("Refresh catalog", self.html)
        self.assertIn("Set up on this PC", self.html)
        # JS protocol wiring for interactable actions
        for needle in (
            "querySelectorAll('.btn-extract')",
            "querySelectorAll('[data-open-extracted]')",
            "querySelectorAll('[data-play]')",
            "querySelectorAll('[data-pick-launcher]')",
            "querySelectorAll('[data-mark-installed]')",
            "querySelectorAll('.btn-folder')",
            "querySelectorAll('.btn-copy')",
            "steamgameorganizer://open-extracted?path=",
            "steamgameorganizer://open-folder?path=",
            "steamgameorganizer://play?",
            "steamgameorganizer://pick-launcher?path=",
            "steamgameorganizer://mark-installed?path=",
            "steamgameorganizer://refresh-catalog",
            "execCommand('copy')",
            "getElementById('refresh-catalog')",
        ):
            self.assertIn(needle, self.html, f"missing JS wiring: {needle}")

    def test_open_extracted_prefers_marker_resolved_absolute_path(self):
        # Ready has marker extracted_root -> card and JS should carry absolute data-extracted-path.
        self.assertRegex(self.html, r'data-extracted-path="[^"]*Ready[^"]*"')
        self.assertIn("oe.getAttribute('data-extracted-path')", self.html)

    def test_generated_action_targets_are_accepted_by_uri_handlers(self):
        # Extract target from a generated extract href/data
        m = re.search(r'data-extract="(steamgameorganizer://extract\?[^"]+Fresh[^"]+)"', self.html)
        self.assertIsNotNone(m, "missing extract URI for Fresh")
        extract_uri = m.group(1).replace("&amp;", "&")
        req = parse_uri(extract_uri, self.lib, [self.extract])
        self.assertTrue(req.archive.name.startswith("Fresh"))
        # Open folder target for a known library folder
        folder = self.lib / "Action" / "Ready - 2024"
        parse_open_folder_uri("steamgameorganizer://open-folder?path=" + quote(str(folder), safe=""), self.lib)
        # Open extracted target from generated absolute path
        m2 = re.search(r'data-extracted-path="([^"]*Ready[^"]*)"', self.html)
        self.assertIsNotNone(m2)
        p = unquote(m2.group(1))
        parse_open_extracted_uri("steamgameorganizer://open-extracted?path=" + quote(p, safe=""), [self.extract])

    def test_localstorage_defaults_and_link_rebuild_hooks_exist(self):
        for needle in ("catalog-root", "catalog-dest", "localStorage", "applyLinks", "typedRoot", "joinPath", "encodePath"):
            self.assertIn(needle, self.html)

    def test_catalog_is_single_portable_html_file_with_status_script(self):
        files = sorted(p.name for p in self.lib.glob("*.html"))
        self.assertEqual(files, ["Game Library.html"])
        self.assertIn("Game Library.status.js", self.html)
        self.assertIn('src="Game Library.status.js"', self.html)


if __name__ == "__main__":
    unittest.main()
