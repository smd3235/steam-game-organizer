"""Extracted from tests/test_setup_flow.py.

    TheCatalogPageCarriesTheButton was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
import unittest.mock
from pathlib import Path
from tempfile import TemporaryDirectory
from core.logger import AppLogger
from tests.test_helpers import _game
from services.catalog_service import CatalogService


class TheCatalogPageCarriesTheButton(unittest.TestCase):
    def test_the_page_carries_the_setup_button_and_the_script_hook(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            _game(root, "Idle", "Loop Miner")
            paths = CatalogService(AppLogger(root / "x.log")).generate(root)
            self.assertEqual(len(paths), 1)
            text = paths[0].read_text(encoding="utf-8")
            self.assertIn('id="setup-link"', text)
            self.assertIn('data-setup="steamgameorganizer://setup"', text)
            self.assertIn("Set up on this PC", text)
            self.assertIn(".btn-setup", text)
            self.assertIn("steam_game_organizer.py --setup", text)
            # The script rebuilds the link from the two boxes, the same
            # way it rebuilds the Extract links, so the wizard opens on
            # the folders the reader has already typed.
            script = text[text.index("<script>") :]
            self.assertIn("setup-link", script)
            self.assertIn("params.push('library='", script)
            self.assertIn("params.push('extract='", script)
