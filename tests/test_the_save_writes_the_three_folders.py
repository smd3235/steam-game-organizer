"""Extracted from tests/test_setup_flow.py.

    TheSaveWritesTheThreeFolders was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import json
import sys
import unittest
import unittest.mock
from pathlib import Path
from tempfile import TemporaryDirectory
from core.config import AppConfig
from core.constants import ENTRY_POINT
from core.logger import AppLogger
from tests.test_helpers import _RecordingRegister
from tests.test_helpers import _game
from services.setup_service import SetupService


class TheSaveWritesTheThreeFolders(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.sandbox = Path(temporary.name)
        self.library = self.sandbox / "Games"
        _game(self.library, "Idle", "Loop Miner")
        self.app = self.sandbox / "App"
        self.app.mkdir()
        (self.app / ENTRY_POINT).write_text("# the app\n", encoding="utf-8")
        self.extract = self.sandbox / "Out"
        self.extract.mkdir()
        self.register = _RecordingRegister()
        self.service = SetupService(AppLogger(self.sandbox / "x.log"), register_handler=self.register, registered_command=lambda: "HKCU command")
        self.config = AppConfig(self.sandbox)

    def _settings(self):
        return json.loads(self.config.settings_file.read_text(encoding="utf-8"))

    def test_a_valid_setup_saves_both_settings_and_registers_the_link(self):
        saved, rows = self.service.apply(self.config, self.library, self.app, self.extract)
        self.assertTrue(saved)
        self.assertNotIn("error", {level for level, _ in rows})
        self.assertEqual(self.config.library_root, self.library)
        self.assertEqual(self.config.extract_folders, [self.extract])
        on_disk = self._settings()
        self.assertEqual(on_disk["library_root"], str(self.library))
        self.assertEqual(on_disk["extract_folders"], [str(self.extract)])
        # The handler is registered against the app folder the user chose,
        # with the interpreter that is running the wizard.
        self.assertEqual(self.register.calls, [(sys.executable, self.app / ENTRY_POINT)])

    def test_a_missing_library_is_created_and_saved(self):
        saved, rows = self.service.apply(self.config, self.sandbox / "Nowhere", self.app, self.extract)
        self.assertTrue(saved)
        self.assertTrue((self.sandbox / "Nowhere").is_dir(), "apply() created the library folder")
        self.assertEqual(self.register.calls, [(sys.executable, self.app / ENTRY_POINT)])
        self.assertTrue(self.config.settings_file.exists())

    def test_an_extract_folder_inside_the_library_is_refused(self):
        inside = self.library / "Extracted"
        inside.mkdir()
        saved, _ = self.service.apply(self.config, self.library, self.app, inside)
        self.assertFalse(saved)
        self.assertEqual(self.register.calls, [])
        self.assertFalse(self.config.settings_file.exists())

    def test_a_missing_library_is_created_and_a_previous_setup_survives(self):
        self.service.apply(self.config, self.library, self.app, self.extract)
        saved, _ = self.service.apply(self.config, self.sandbox / "Nowhere", self.app, self.extract)
        self.assertTrue(saved)
        # The new save overwrites the previous one.
        self.assertEqual(self.config.library_root, self.sandbox / "Nowhere")

    def test_a_failed_registration_still_saves_the_paths(self):
        self.register.raise_ = OSError("registry locked")
        saved, rows = self.service.apply(self.config, self.library, self.app, self.extract)
        self.assertTrue(saved)
        self.assertEqual(self.config.library_root, self.library)
        self.assertEqual(self.config.extract_folders, [self.extract])
        self.assertIn("warn", {level for level, _ in rows})
        self.assertIn("could not be registered", " ".join(message for _, message in rows))
