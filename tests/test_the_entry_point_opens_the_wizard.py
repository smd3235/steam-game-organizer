"""Extracted from tests/test_setup_flow.py.

    TheEntryPointOpensTheWizard was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import sys
import unittest
import unittest.mock
from pathlib import Path
from tempfile import TemporaryDirectory
import steam_game_organizer
from core.config import AppConfig
from core.logger import AppLogger
from tests.tk_support import require_tk


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
