"""Regression tests for UI behaviour.

These tests were extracted from tests/test_regressions.py to keep each test module
focused on one area of the app: scan button state, folder opening, setup button,
catalog launcher, and Done-screen fact reporting.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import tkinter as tk

from core.config import AppConfig
from core.logger import AppLogger
from core.models import ArtworkResult
from services.catalog_service import CatalogService
from services.library_service import LibraryService
from services.organizer_service import OrganizerService
from services.rollback_service import RollbackService
from ui.artwork_view import ArtworkView, _asset_prefix_for
from ui.done_view import DoneView
from ui.main_window import MainWindow
from utils.desktop import open_folder
from utils.filename_utils import identity_key
from utils.formatting import human_size

def _tmp_dir(test_case):
    """A temporary directory that is cleaned up when the test finishes."""
    tmp = Path(tempfile.mkdtemp())
    test_case.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    return tmp

def _label_texts(widget):
    """Collect the text of every label inside a widget, recursively."""
    found = []
    for child in widget.winfo_children():
        if child.winfo_class() == "Label":
            found.append(child.cget("text"))
        found.extend(_label_texts(child))
    return found

class TestScanButtonComesBackAfterAScan(unittest.TestCase):
    """The app's headline button went dead after the first scan, for the rest of the session.

    `begin_scan` and `progress_update` both set `scan_btn` to `disabled`, so it cannot be pressed twice while a
    run is in progress. Nothing ever set it back. `MainWindow._end` - the one place that ends a run and already
    turns the cancel button off - never touched it.

    So the button the app opens with, and the one the user presses to pick up games they have just downloaded,
    stopped working the first time they used it. Restarting the app was the only way back, which makes "did it
    find the game I just downloaded" answerable only by closing the program. `MainWindow.scan`'s
    `if self.busy: return` guard reads like a second scan is supported and simply is not reachable.

    Driven through the real MainWindow rather than a bare ScanView, because the omission is in MainWindow: the
    buttons are correct during a run and only ever brought back at the end, and a test that stops at
    `set_result` never reaches the code that owns the fix.

    Deliberately not asserting any of this by pressing the button. Its command was bound to MainWindow.scan when
    the button was created, so `invoke()` starts a real scan of the configured library root - and this machine's
    settings.json points at D:/Game Installers/Steam Games. While the button was disabled that call was a
    harmless no-op, which is how an earlier version of this test passed without ever pressing it.
    """

    def setUp(self):
        from tests.tk_support import require_tk, close_root, sandbox_app
        from tests.test_ui_geometry import _measured_window
        require_tk(self)
        self.root = tk.Tk()
        self.addCleanup(close_root, self.root)
        self.app = sandbox_app(self, self.root)
        _measured_window(self.root)
        self.window = self.app.window
        self.scan = self.window.views["scan"]
        self.window.show("scan")
        self.root.update()

    def _run_a_whole_scan(self):
        """Discovery, then the background verification that follows it, then the run ends."""
        self.window.scan_done(type("R", (), {"archives": [], "errors": []})())
        self.window.verification_done([])

    def test_the_button_starts_enabled(self):
        self.assertNotEqual(
            str(self.scan.scan_btn["state"]),
            "disabled",
            "the scan button is dead on a freshly opened window",
        )

    def test_a_finished_scan_leaves_the_button_usable(self):
        self.window.views["scan"].begin_scan()
        self.window._start("Scanning Games…")
        self.assertEqual(str(self.scan.scan_btn["state"]), "disabled", "the button was live during a running scan")
        self._run_a_whole_scan()
        self.assertFalse(self.window.busy, "the window still believes a run is in progress")
        self.assertFalse(self.scan.scanning, "the view still believes a scan is running")
        self.assertNotEqual(
            str(self.scan.scan_btn["state"]),
            "disabled",
            "the scan button is still disabled after the run finished, so the library cannot be "
            "scanned again without restarting the app",
        )

    def test_the_cancel_button_is_turned_off_when_the_run_ends(self):
        self.window.views["scan"].begin_scan()
        self.window._start("Scanning Games…")
        self.assertEqual(str(self.scan.cancel_btn["state"]), "normal", "cancel was not live during a run")
        self._run_a_whole_scan()
        self.assertEqual(str(self.scan.cancel_btn["state"]), "disabled", "the cancel button is still live after the run finished")

class TestTheSetupButtonIsInTheAppToolbar(unittest.TestCase):
    """A Setup button in the app's own toolbar.

    The catalog's Set up on this PC button goes through the protocol handler, which runs with no
    main window - so it cannot reach the app. A reader who already has the app running and needs to
    re-point it, because the app folder was moved, had no way to open the wizard at all: the only
    routes were --setup on the command line and the catalog button, both of which assume the app is
    not already open. The button lives in the footer bar beside System Health and Diagnostics.
    """

    def setUp(self):
        from tests.tk_support import require_tk, close_root, sandbox_app
        require_tk(self)
        self.close_root = close_root

        root = tk.Tk()
        self.addCleanup(self.close_root, root)
        self.app = sandbox_app(self, root)

    def test_the_button_is_present_and_open_setup_is_bound_to_it(self):
        self.assertTrue(hasattr(self.app.window, "setup_btn"), "the app toolbar has no Setup button")
        self.assertTrue(hasattr(self.app.window, "open_setup"), "MainWindow has no open_setup handler for the button")

    def test_opening_setup_opens_the_wizard(self):
        with patch("ui.setup_window.SetupWindow") as wizard:
            self.app.window.open_setup()
        wizard.assert_called_once()
        args, kwargs = wizard.call_args
        self.assertIs(args[0], self.app.root)
        self.assertIs(args[1], self.app.config)
        self.assertIs(args[2], self.app.logger)

# Extracted test classes imported at the end to avoid circular imports:
# those modules import _tmp_dir and _label_texts from this module, which are defined above.
from tests.test_the_catalog_launcher_is_usable import TestTheCatalogLauncherIsUsable
from tests.test_open_folder_is_not_linux_only import TestOpenFolderIsNotLinuxOnly

