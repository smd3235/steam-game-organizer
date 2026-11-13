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
from tests.test_helpers import _game
from tests.test_helpers import _RecordingRegister
from tests.test_helpers import _RecordingService
from tests.tk_support import close_root, require_tk
from ui.setup_window import SetupWindow

# The game tree fixture and recording helpers now live in tests\test_helpers.py so the modules extracted
# from this one (TheCatalogPageCarriesTheButton, TheChecksSayWhatIsWrong, TheSaveWritesTheThreeFolders,
# TheWizardOpensOnTheAppOwnSettings) can import them without re-entering this partially initialized module.


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
from tests.test_the_entry_point_opens_the_wizard import TheEntryPointOpensTheWizard
from tests.test_the_checks_say_what_is_wrong import TheChecksSayWhatIsWrong
from tests.test_the_save_writes_the_three_folders import TheSaveWritesTheThreeFolders
from tests.test_the_wizard_opens_on_the_app_own_settings import TheWizardOpensOnTheAppOwnSettings
from tests.test_the_catalog_page_carries_the_button import TheCatalogPageCarriesTheButton


