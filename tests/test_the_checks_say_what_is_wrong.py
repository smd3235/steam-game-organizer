"""Extracted from tests/test_setup_flow.py.

    TheChecksSayWhatIsWrong was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
import unittest.mock
from pathlib import Path
from tempfile import TemporaryDirectory
from core.constants import ENTRY_POINT
from core.logger import AppLogger
from services import setup_service
from tests.test_setup_flow import _RecordingRegister
from tests.test_setup_flow import _game
from services.setup_service import SetupService


class TheChecksSayWhatIsWrong(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.library = self.root / "Games"
        _game(self.library, "Idle", "Loop Miner")
        self.app = self.root / "App"
        self.app.mkdir()
        (self.app / ENTRY_POINT).write_text("# the app\n", encoding="utf-8")
        self.extract = self.root / "Out"
        self.extract.mkdir()
        self.register = _RecordingRegister()
        self.service = SetupService(AppLogger(self.root / "x.log"), register_handler=self.register, registered_command=lambda: "HKCU command")

    def _rows(self, **overrides):
        values = {"library": self.library, "app": self.app, "extract": self.extract}
        values.update(overrides)
        return self.service.checks(values["library"], values["app"], values["extract"])

    def _levels(self, rows):
        return {level for level, _ in rows}

    def test_three_usable_folders_report_no_errors(self):
        rows = self._rows()
        self.assertNotIn("error", self._levels(rows))
        text = " ".join(message for _, message in rows)
        self.assertIn(str(self.library), text)
        self.assertIn(str(self.app), text)
        self.assertIn(str(self.extract), text)

    def test_a_missing_library_is_a_warning(self):
        rows = self._rows(library=self.root / "Nowhere")
        self.assertIn("warn", self._levels(rows))
        self.assertNotIn("error", self._levels(rows))

    def test_a_library_with_no_games_is_a_warning(self):
        empty = self.root / "Empty"
        empty.mkdir()
        rows = self._rows(library=empty)
        self.assertIn("warn", self._levels(rows))
        self.assertNotIn("error", self._levels(rows))

    def test_an_app_folder_without_the_entry_point_is_an_error(self):
        wrong = self.root / "NotTheApp"
        wrong.mkdir()
        rows = self._rows(app=wrong)
        self.assertIn("error", self._levels(rows))

    def test_an_extract_folder_that_is_a_file_is_an_error(self):
        file = self.root / "file.txt"
        file.write_text("x", encoding="utf-8")
        rows = self._rows(extract=file)
        self.assertIn("error", self._levels(rows))

    def test_an_extract_folder_inside_the_library_is_an_error(self):
        inside = self.library / "Idle" / "Extracted"
        inside.mkdir(parents=True)
        rows = self._rows(extract=inside)
        self.assertIn("error", self._levels(rows))
        self.assertIn("inside the game library", " ".join(m for _, m in rows))

    def test_the_extract_folder_equal_to_the_library_is_an_error(self):
        rows = self._rows(extract=self.library)
        self.assertIn("error", self._levels(rows))

    def test_a_missing_7zip_is_a_warning(self):
        with unittest.mock.patch.object(setup_service.ExtractService, "find_tool", return_value=(None, "no 7z anywhere")):
            rows = self._rows()
        self.assertIn("warn", self._levels(rows))
        self.assertIn("7-Zip", " ".join(message for _, message in rows))

    def test_an_unregistered_link_is_a_warning_and_a_registered_one_is_reported(self):
        unregistered = SetupService(AppLogger(self.root / "x.log"), register_handler=self.register, registered_command=lambda: None)
        rows = unregistered.checks(self.library, self.app, self.extract)
        self.assertIn("warn", self._levels(rows))
        self.assertIn("not registered", " ".join(message for _, message in rows))
        self.assertIn("HKCU command", " ".join(message for _, message in self._rows()))
