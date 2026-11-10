"""Catalog render-state tests for actionable HTML across extraction/install states.

These tests focus on rendered button states and embedded data needed for safe actions:
Extract, Re-extract (stale), Open extracted, Open installer, secondary stale access,
and marker-resolved extracted paths.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest

import pytest
import zipfile
from pathlib import Path

from core.logger import AppLogger
from services.catalog_service import CatalogService
from services.installer_detect import NEEDS_INSTALL_DIRNAME


@pytest.mark.notkinter
class CatalogRenderStates(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.root = Path(self.td.name)
        self.lib = self.root / "Games"
        self.extract = self.root / "Extracted"
        self.logger = AppLogger(self.root / "test.log")

    def _game(self, category, folder_name, archive_name, meta, members=None):
        g = self.lib / category / folder_name
        g.mkdir(parents=True, exist_ok=True)
        arc = g / archive_name
        with zipfile.ZipFile(arc, "w") as z:
            for k, v in (members or {"readme.txt": b"x"}).items():
                z.writestr(k, v)
        (g / ".game-info.json").write_text(json.dumps(meta), encoding="utf-8")
        return g, arc

    def _marker(self, dest: Path, arc: Path, *, needs_install=False, root=None):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / ".sgo-extract-info").write_text(
            json.dumps(
                {
                    "extracted_root": str(root or dest),
                    "archive_size": arc.stat().st_size,
                    "archive_mtime_ns": arc.stat().st_mtime_ns,
                    "extracted_at": "2026-01-01 00:00",
                    "needs_install": bool(needs_install),
                }
            ),
            encoding="utf-8",
        )
        if not any(dest.iterdir() if False else []):
            pass
        if not (dest / "payload.txt").exists():
            (dest / "payload.txt").write_text("x", encoding="utf-8")

    def _render(self):
        svc = CatalogService(self.logger, extract_folders=[self.extract])
        return svc.generate(self.lib)[0].read_text(encoding="utf-8")

    def test_not_extracted_archive_renders_extract_action(self):
        self._game("Action", "Fresh - 2024", "Fresh.zip", {"appid": "1", "name": "Fresh", "release_date": "2024", "genres": ["Action"], "description": "d"})
        html = self._render()
        self.assertRegex(html, r'class="btn btn-extract"[^>]*data-extract="steamgameorganizer://extract\?')
        self.assertIn(">Extract</a>", html)

    def test_extracted_ready_game_renders_play_when_launcher_saved(self):
        g, arc = self._game("Action", "Ready - 2024", "Ready.zip", {"appid": "2", "name": "Ready", "release_date": "2024", "genres": ["Action"], "description": "d"})
        dest = self.extract / "Ready"
        self._marker(dest, arc, needs_install=False)
        exe = dest / "game.exe"
        exe.write_text("MZ", encoding="utf-8")
        marker = json.loads((dest / ".sgo-extract-info").read_text(encoding="utf-8"))
        marker["launch_target"] = str(exe)
        (dest / ".sgo-extract-info").write_text(json.dumps(marker), encoding="utf-8")
        html = self._render()
        self.assertRegex(html, r'data-play="1"[^>]*>Play</a>')
        self.assertRegex(html, r'data-launch-target="[^"]*game\.exe"')
        self.assertRegex(html, r'data-pick-launcher="1"[^>]*data-marker-dir="')
        self.assertNotRegex(html, r"Ready[\s\S]{0,200}btn-reextract")

    def test_extracted_installer_renders_open_installer(self):
        g, arc = self._game("Repacks", "Setup - 2024", "Setup.zip", {"appid": "3", "name": "Setup", "release_date": "2024", "genres": ["Simulation"], "description": "d"}, members={"setup.exe": b"MZ", "setup-1.bin": b"x"})
        self._marker(self.extract / NEEDS_INSTALL_DIRNAME / "Setup", arc, needs_install=True)
        html = self._render()
        self.assertIn("Open installer", html)
        self.assertIn('data-needs-install="1"', html)

    def test_stale_extracted_game_renders_reextract_and_keeps_secondary_open_access(self):
        g, arc = self._game("Action", "Stale - 2024", "Stale.zip", {"appid": "4", "name": "Stale", "release_date": "2024", "genres": ["Action"], "description": "d"})
        dest = self.extract / "Stale"
        self._marker(dest, arc, needs_install=False)
        # Make archive "changed" after marker by changing mtime/size semantics through rewrite.
        with zipfile.ZipFile(arc, "a") as z:
            z.writestr("extra.bin", b"x" * 50)
        html = self._render()
        self.assertIn("Re-extract", html)
        self.assertIn("btn-reextract", html)
        # Secondary access to existing files should remain for stale items.
        self.assertRegex(html, r'Re-extract[\s\S]{0,1800}data-open-extracted="1"[\s\S]{0,400}Open extracted[\s\S]{0,2000}Open source')
        self.assertIn('data-stale="1"', html)

    def test_marker_extracted_root_in_alternate_layout_is_used(self):
        g, arc = self._game("Action", "Alt - 2024", "Alt.zip", {"appid": "5", "name": "Alt", "release_date": "2024", "genres": ["Action"], "description": "d"})
        # Found by conventional probe path, but marker points to a nested/actual root.
        probe = self.extract / "Alt"
        actual = probe / "Nested" / "Game"
        actual.mkdir(parents=True)
        (actual / "game.exe").write_text("x", encoding="utf-8")
        probe.mkdir(parents=True, exist_ok=True)
        (probe / "payload.txt").write_text("x", encoding="utf-8")
        self._marker(probe, arc, needs_install=False, root=actual)
        html = self._render()
        self.assertRegex(html, r'data-extracted-path="[^"]*Nested[\\/]+Game[^"]*"')

    def test_open_source_and_path_metadata_are_always_safe_hooks(self):
        self._game("Action", "Meta - 2024", "Meta.zip", {"appid": "6", "name": "Meta", "release_date": "2024", "genres": ["Action"], "description": "d"})
        html = self._render()
        self.assertIn("Open source", html)
        self.assertRegex(html, r'data-open-folder="steamgameorganizer://open-folder\?path=')
        self.assertRegex(html, r'data-rel="Action/Meta - 2024"|data-rel="Action\\Meta - 2024"')
        self.assertIn("data-extract=", html)


if __name__ == "__main__":
    unittest.main()
