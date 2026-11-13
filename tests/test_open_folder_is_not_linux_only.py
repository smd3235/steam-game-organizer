"""Extracted from tests/test_ui_regressions.py.

    TestOpenFolderIsNotLinuxOnly was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import tkinter
from ui.artwork_view import ArtworkView
from utils.desktop import open_folder


class TestOpenFolderIsNotLinuxOnly(unittest.TestCase):
    """Both "open this folder" buttons were wired to xdg-open and nothing else.

    `MainWindow.open_library` and `ArtworkView._open_folder` both did `shutil.which('xdg-open')` and, finding
    nothing, did nothing at all - no message, no error, nothing in the log. On the platform this app is primarily
    run on that is every press: Done's "Open Library Folder" and every Artwork-screen "OPEN GAME FOLDER" were
    dead buttons. Verified on this host: `xdg-open` is not on PATH, `explorer` is, and `os.startfile` exists.

    The two call sites had drifted apart from each other as well, so the behaviour now lives in one helper that
    answers the question the buttons actually care about: did anything get launched.
    """

    def setUp(self):
        from tests.tk_support import require_tk, close_root, sandbox_app
        require_tk(self)
        self.close_root = close_root
        self._folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._folder.cleanup)
        self.folder = Path(self._folder.name)

    def test_opening_a_folder_launches_something_on_this_platform(self):
        if os.name != "nt":
            self.fail("this app is Windows-only now, so open_folder must refuse elsewhere rather than launch nothing")
        launched = []
        with patch("utils.desktop.os.startfile", side_effect=lambda p: launched.append(p)):
            self.assertTrue(open_folder(self.folder))
            self.assertEqual(launched, [str(self.folder)], "on Windows the folder was not handed to the shell, so the button did nothing")

    def test_it_reports_failure_instead_of_silently_doing_nothing(self):
        # The old code returned None whether or not anything happened, so a caller could not tell a launched file
        # manager from a dead button. Anything that cannot be launched is a False, never an exception at the caller.
        #
        # Both routes have to be closed off on Windows: os.startfile failing falls back to explorer, and this host
        # does have explorer, so blocking startfile alone would prove nothing.
        if os.name != "nt":
            self.fail("this app is Windows-only now, so open_folder must refuse elsewhere rather than launch nothing")
        with patch("utils.desktop.os.startfile", side_effect=OSError("no shell here")), patch(
            "utils.desktop.shutil.which", return_value=None
        ):
            self.assertFalse(open_folder(self.folder), "a failed launch was reported as a success")

    def test_a_folder_that_is_not_there_is_not_launched(self):
        self.assertFalse(
            open_folder(self.folder / "no-such-folder"),
            "a missing folder was handed to the shell instead of being refused",
        )

    def test_the_library_button_goes_through_the_helper(self):
        from tests.test_ui_geometry import _measured_window
        from tests.tk_support import sandbox_app
        import tkinter as tk

        root = tk.Tk()
        self.addCleanup(self.close_root, root)
        app = sandbox_app(self, root)
        _measured_window(root)
        app.config.library_root = self.folder
        with patch("utils.desktop.open_folder", return_value=True) as helper:
            app.window.open_library()
            helper.assert_called_once_with(self.folder)

    def test_the_artwork_screen_goes_through_the_helper(self):
        import tkinter as tk

        root = tk.Tk()
        self.addCleanup(self.close_root, root)
        view = ArtworkView(tk.Frame(root), lambda: None)
        with patch("utils.desktop.open_folder", return_value=True) as helper:
            view._open_folder(self.folder)
            helper.assert_called_once_with(self.folder)
