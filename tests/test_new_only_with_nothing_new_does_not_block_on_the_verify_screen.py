"""Extracted from tests/test_scan_regressions.py.

    TestNewOnlyWithNothingNewDoesNotBlockOnTheVerifyScreen was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest


class TestNewOnlyWithNothingNewDoesNotBlockOnTheVerifyScreen(unittest.TestCase):
    """A New Only scan that finds nothing new must still be finishable.

    Under New Only a scan that has nothing new hands an empty list to the review screen, and the run
    is genuinely done: the audit and catalog phases already ran and wrote their pages. The CONTINUE
    button was gated on the list being non-empty, so it was disabled; Approve All Verified was itself
    disabled on an empty list, so the only button available could not be pressed and the run appeared
    to hang on the verify screen with no way to continue.
    """

    def setUp(self):
        from tests.tk_support import require_tk, close_root, sandbox_app
        require_tk(self)
        self.close_root = close_root
        import tkinter as tk

        root = tk.Tk()
        self.addCleanup(self.close_root, root)
        self.app = sandbox_app(self, root)
        self.view = self.app.window.views["review"]
        self.app.window.show("review")
        self.root = self.app.root
        self.root.update()

    def test_the_continue_button_is_enabled_on_an_empty_list(self):
        self.view.load([])
        self.root.update()
        self.assertEqual(
            str(self.view.continue_button.cget("state")),
            "normal",
            "a scan with nothing new left no way to finish the run",
        )

    def test_the_continue_button_is_disabled_while_games_are_unresolved(self):
        from core.models import GameArchive

        archive = GameArchive(
            self.app.config.library_root / "Game.zip",
            "Game",
            "game",
            "game",
            ".zip",
            (0,),
        )
        self.view.load([archive])
        self.root.update()
        self.assertEqual(str(self.view.continue_button.cget("state")), "disabled")

    def test_the_empty_list_says_the_run_is_done(self):
        self.view.load([])
        self.root.update()
        self.assertIn("CONTINUE TO ORGANIZATION", self.view.continue_button.cget("text"))
        self.assertIn("already ran", self.view.subtitle.cget("text"))
