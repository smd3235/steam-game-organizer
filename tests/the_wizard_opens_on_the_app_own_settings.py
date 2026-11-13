"""Extracted from tests/test_setup_flow.py.

    TheWizardOpensOnTheAppOwnSettings was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
import unittest.mock
from pathlib import Path
from tempfile import TemporaryDirectory
import tkinter as tk
from core.config import AppConfig
from core.logger import AppLogger
from tests.tk_support import close_root
from tests.tk_support import require_tk
from tests.test_setup_flow import _RecordingService
from tests.test_setup_flow import _game
from ui.setup_window import SetupWindow


class TheWizardOpensOnTheAppOwnSettings(unittest.TestCase):
    def setUp(self):
        require_tk(self)
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.sandbox = Path(temporary.name)
        self.games = self.sandbox / "Games"
        self.games.mkdir()
        _game(self.games, "Idle", "Loop Miner")
        self.config = AppConfig(self.sandbox, library_root=self.games)
        self.logger = AppLogger(self.sandbox / "x.log")

    def _window(self, prefill=None, service=None):
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(close_root, root)
        return SetupWindow(root, self.config, self.logger, prefill=prefill, service=service or _RecordingService())

    def test_the_boxes_start_on_the_app_own_answers(self):
        window = self._window()
        self.assertEqual(window.library_var.get(), str(self.games))
        self.assertEqual(window.extract_var.get(), str(self.config.extract_folder))
        # The app folder defaults to the copy that is running the wizard.
        self.assertEqual(window.app_var.get(), str(Path(__file__).resolve().parents[1]))

    def test_a_prefill_overrides_the_defaults(self):
        from core.uri_actions import SetupRequest

        window = self._window(prefill=SetupRequest(library="L", extract="E", app="A"))
        self.assertEqual((window.library_var.get(), window.extract_var.get(), window.app_var.get()), ("L", "E", "A"))

    def test_save_hands_the_boxes_to_the_service(self):
        service = _RecordingService()
        window = self._window(service=service)
        window.library_var.set("LIB")
        window.app_var.set("APP")
        window.extract_var.set("EXT")
        window.save()
        self.assertEqual(service.apply_calls, [("LIB", "APP", "EXT")])
        self.assertIn("Saved", window.status.cget("text"))

    def test_a_refused_save_says_why(self):
        service = _RecordingService()
        service.apply = lambda *args: (False, [("error", "No good")])
        window = self._window(service=service)
        window.save()
        self.assertIn("Not saved: No good", window.status.cget("text"))
