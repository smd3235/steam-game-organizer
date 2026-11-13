"""Extracted from tests/test_catalog_library.py.

    TestSetupButtonAndFallback was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
import pytest
import re
from tempfile import TemporaryDirectory
from pathlib import Path
from core.logger import AppLogger
from tests.test_catalog_library import make_game
from services.catalog_service import CatalogService


class TestSetupButtonAndFallback(unittest.TestCase):
    """The setup button and the command beside it.

    A PC that has never run this app cannot click an Extract button at all - the handler is
    registered to open the app folder, so every link the page builds is refused against the app's
    own settings, which hold defaults. The button opens the wizard; the fallback beside it is the
    command a reader types into a terminal when the browser will not hand the link over.
    """

    def test_the_fallback_command_is_pasteable_in_cmd(self):
        """The fallback carries one backslash, not two.

        Written as a raw string with two, which is a doubled separator in the rendered page: a
        reader copies `runtime\\python.exe ...` and pastes it into cmd, where it is a path with a
        doubled separator and does not run. The command is meant to be typed in the app folder, so
        the relative form is right and the separator has to be single.
        """
        with TemporaryDirectory() as d:
            root = Path(d)
            make_game(root)
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
        match = re.search(r'<code class="setup-cmd"[^>]*>(.*?)</code>', text)
        self.assertIsNotNone(match, "the fallback command is not in the catalog")
        value = match.group(1)
        self.assertEqual(value, r"runtime\python.exe steam_game_organizer.py --setup", "the fallback command is not the one documented in the README")
        self.assertNotIn("\\\\", value, "the fallback command carries doubled backslashes and will not run in cmd")

    def test_the_setup_button_carry_the_page_boxes_with_it(self):
        """The link's query is rebuilt from the page's own boxes, so the wizard opens on them."""
        with TemporaryDirectory() as d:
            root = Path(d)
            make_game(root)
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
        link = re.search(r'<a class="btn btn-setup"[^>]*>', text)
        self.assertIsNotNone(link, "the Set up on this PC button is not in the catalog")
        self.assertIn("data-setup=", link.group(0))
        self.assertIn("steamgameorganizer://setup", text)
        # The script rebuilds the href from the boxes, so the page's own values seed the wizard.
        self.assertIn("setupLink.setAttribute", text)
        self.assertIn("params.push", text)
