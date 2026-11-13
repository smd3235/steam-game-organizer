"""The setup flow: the three folders a fresh PC needs, from the catalog's button.

The property that shapes all of this is asserted here rather than assumed. The Game folder
and Extract to boxes in the catalog are remembered by the browser alone - a file:// page
cannot write a file - so the folders the app itself checks every Extract link against (the
library root, the app folder the protocol handler opens, the extract folder a destination-less
link falls back to) can only be set by the app. The wizard is the one place that does it,
and every save is refused until the checks pass.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import unittest.mock
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

import tkinter as tk

import steam_game_organizer
from core.config import AppConfig
from core.constants import ENTRY_POINT
from core.logger import AppLogger
from core.uri_actions import UriRefused
from core.parse_setup_uri import parse_setup_uri
from services import setup_service
from services.catalog_service import CatalogService
from services.setup_service import SetupService
from tests.tk_support import close_root, require_tk
from ui.setup_window import SetupWindow

def _game(root: Path, category: str, name: str) -> Path:
    """An organized game folder: a category holding a game with an archive and a sidecar."""
    folder = root / category / f"{name} - 2024-01-01"
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(folder / f"{name}.zip", "w", zipfile.ZIP_DEFLATED) as handle:
        handle.writestr(f"{name}/game.bin", b"a" * 512)
    (folder / ".game-info.json").write_text(f'{{"appid":"1","name":"{name}","genres":["Idle"]}}', encoding="utf-8")
    return folder

class _RecordingService:
    """A SetupService stand-in that records what the wizard hands it."""

    def __init__(self, rows=None):
        self.checks_calls = []
        self.apply_calls = []
        self.rows = rows if rows is not None else [("ok", "all good")]

    def checks(self, library, app, extract):
        self.checks_calls.append((library, app, extract))
        return self.rows

    def apply(self, config, library, app, extract):
        self.apply_calls.append((library, app, extract))
        return True, [("ok", "Saved.")]

class _RecordingRegister:
    """Watches the handler registration without touching the registry."""

    def __init__(self, raise_=None):
        self.calls = []
        self.raise_ = raise_

    def __call__(self, python, entry):
        self.calls.append((python, entry))
        if self.raise_ is not None:
            raise self.raise_

class TheLinkCarriesTheThreeFolders(unittest.TestCase):
    def test_a_bare_link_carries_no_paths(self):
        request = parse_setup_uri("steamgameorganizer://setup")
        self.assertEqual((request.library, request.extract, request.app), ("", "", ""))

    def test_a_link_carries_the_page_paths(self):
        request = parse_setup_uri("steamgameorganizer://setup?library=F%3A%2FFunZone&extract=F%3A%2FOut&app=F%3A%2FApp")
        self.assertEqual(request.library, "F:/FunZone")
        self.assertEqual(request.extract, "F:/Out")
        self.assertEqual(request.app, "F:/App")

    def test_the_wrong_scheme_is_refused(self):
        with self.assertRaises(UriRefused):
            parse_setup_uri("http://example.com/setup?library=x")

    def test_another_action_is_refused(self):
        with self.assertRaises(UriRefused):
            parse_setup_uri("steamgameorganizer://extract?src=x")

    def test_a_hostile_value_is_cleaned_not_obeyed(self):
        # Control characters cannot sit in a path box, and a path is not a
        # megabyte long: both are dropped rather than carried into the wizard.
        long_path = "E:" + ("x" * 5000)
        request = parse_setup_uri(f"steamgameorganizer://setup?library={long_path}%0A%09&extract=&app=")
        self.assertEqual(len(request.library), 1000)
        self.assertNotIn("\n", request.library)
        self.assertNotIn("\t", request.library)

# Extracted test classes imported at the end to avoid circular imports:
# those modules import _RecordingRegister and _game from this module, which are defined above.
from tests.the_entry_point_opens_the_wizard import TheEntryPointOpensTheWizard
from tests.the_checks_say_what_is_wrong import TheChecksSayWhatIsWrong
from tests.the_save_writes_the_three_folders import TheSaveWritesTheThreeFolders
from tests.the_wizard_opens_on_the_app_own_settings import TheWizardOpensOnTheAppOwnSettings
from tests.the_catalog_page_carries_the_button import TheCatalogPageCarriesTheButton

