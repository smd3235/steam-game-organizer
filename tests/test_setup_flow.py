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
from core.uri_actions import UriRefused, parse_setup_uri
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


class TheEntryPointOpensTheWizard(unittest.TestCase):
    def setUp(self):
        require_tk(self)
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.sandbox = Path(temporary.name)
        self.config = AppConfig(self.sandbox)
        self.logger = AppLogger(self.sandbox / "x.log")

    def test_a_setup_link_opens_the_wizard_with_the_page_paths(self):
        opened = []
        with unittest.mock.patch.object(steam_game_organizer, "_open_setup", side_effect=lambda *args, **kwargs: opened.append((args, kwargs)) or 0):
            code = steam_game_organizer._handle_uri("steamgameorganizer://setup?library=F%3A%2FFunZone&extract=F%3A%2FOut", self.config, self.logger)
        self.assertEqual(code, 0)
        self.assertEqual(len(opened), 1)
        args, kwargs = opened[0]
        self.assertEqual(args, (self.config, self.logger))
        self.assertEqual(kwargs["prefill"].library, "F:/FunZone")
        self.assertEqual(kwargs["prefill"].extract, "F:/Out")

    def test_an_extract_link_is_not_a_setup_link(self):
        # The setup branch must not swallow the extract action: a link
        # naming an archive outside the configured library is refused,
        # not opened as a setup wizard.
        with unittest.mock.patch.object(steam_game_organizer, "_open_setup") as wizard:
            code = steam_game_organizer._handle_uri("steamgameorganizer://extract?src=F%3A%2FFunZone%2Fgame.7z", self.config, self.logger)
        wizard.assert_not_called()
        self.assertEqual(code, 2)

    def test_the_setup_flag_opens_the_wizard(self):
        opened = []
        with (
            unittest.mock.patch.object(steam_game_organizer, "_open_setup", side_effect=lambda *args, **kwargs: opened.append((args, kwargs)) or 0),
            unittest.mock.patch.object(steam_game_organizer, "AppConfig", lambda root, **kwargs: self.config),
            unittest.mock.patch.object(steam_game_organizer, "AppLogger", lambda path, **kwargs: self.logger),
            unittest.mock.patch.object(sys, "argv", ["steam_game_organizer.py", "--setup"]),
        ):
            code = steam_game_organizer.main()
        self.assertEqual(code, 0)
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0][0], (self.config, self.logger))

    def test_a_copied_folder_opens_the_wizard_on_launch(self):
        """A folder copied to a new PC has never been configured.

        settings.json is written only by the wizard, so on a copied folder it does not exist, and
        the default library root is a path that is not there either. Both mean the same thing to a
        reader opening the app: nothing is configured, so nothing will scan and every Extract
        button will be refused. The wizard opens first rather than leaving the reader in the Scan
        screen looking at an empty folder with no indication of what to do.
        """
        opened = []
        with (
            unittest.mock.patch.object(steam_game_organizer, "_open_setup", side_effect=lambda *args, **kwargs: opened.append((args, kwargs)) or 0),
            unittest.mock.patch.object(steam_game_organizer, "AppConfig", lambda root, **kwargs: self.config),
            unittest.mock.patch.object(steam_game_organizer, "AppLogger", lambda path, **kwargs: self.logger),
            unittest.mock.patch.object(sys, "argv", ["steam_game_organizer.py"]),
        ):
            code = steam_game_organizer.main()
        self.assertEqual(code, 0)
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0][0], (self.config, self.logger))

    def test_a_configured_pc_launches_the_gui_instead(self):
        """Once the library root exists on disk, launch goes to the app rather than the wizard."""
        # Application is imported inside main(), so it cannot be patched on the module. The thing
        # that matters is that the wizard is not opened: a configured PC must reach the GUI.
        # AppConfig's default library root is Downloads/Games, which does not exist either, so
        # pointing the config at a real folder in the sandbox is what makes this a configured PC.
        opened = []
        games = self.sandbox / "Games"
        games.mkdir()
        self.config.library_root = games
        self.config.save()
        with (
            unittest.mock.patch.object(steam_game_organizer, "_open_setup", side_effect=lambda *args, **kwargs: opened.append((args, kwargs)) or 0),
            unittest.mock.patch.object(steam_game_organizer, "AppConfig", lambda root, **kwargs: self.config),
            unittest.mock.patch.object(steam_game_organizer, "AppLogger", lambda path, **kwargs: self.logger),
            unittest.mock.patch.object(sys, "argv", ["steam_game_organizer.py"]),
            unittest.mock.patch("app.application.Application") as app_class,
        ):
            app_class.return_value.run.return_value = 0
            code = steam_game_organizer.main()
        self.assertEqual(code, 0)
        self.assertEqual(len(opened), 0)
        app_class.assert_called_once()
