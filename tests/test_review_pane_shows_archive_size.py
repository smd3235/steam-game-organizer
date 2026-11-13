"""Extracted from tests/test_run_reporting.py.

    ReviewPaneShowsArchiveSize was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import tkinter as tk
import unittest
from pathlib import Path
from core.models import GameArchive
from ui.theme import human_size
from utils.filename_utils import identity_key
from tests.test_helpers import _labels
from utils.filename_utils import normalize_name
from tests.tk_support import require_tk
from tests.tk_support import close_root
from tests.tk_support import sandbox_app


class ReviewPaneShowsArchiveSize(unittest.TestCase):
    def setUp(self):
        require_tk(self)
        self.root = tk.Tk()
        self.app = sandbox_app(self, self.root)
        self.view = self.app.window.views["review"]
        self.app.window.show("review")
        self.root.update()

    def tearDown(self):
        # The review and organize views keep a self-rescheduling ticker, as do the drain loop and the window
        # clock. close_root() cancels everything still pending before tearing the window down, so Tk does not
        # print 'invalid command name ..._tick' to stderr - noise that trains you to ignore this suite's
        # output, and it lands in exactly the place a real failing test would print.
        close_root(self.root)

    def _archive(self, path: Path, size: int) -> GameArchive:
        title = normalize_name(path.name)
        return GameArchive(path, title, title, identity_key(title), path.suffix.lower(), (), size=size)

    def test_selected_archive_shows_its_size_in_human_units(self):
        archive = self._archive(Path("Games/Deep Signal/Deep_Signal_v4.7z"), 5 * 1024 * 1024)
        self.view.archives = [archive]
        self.view.select(archive)
        self.root.update()
        text = " ".join(_labels(self.view.meta))
        self.assertIn("ARCHIVE SIZE", text)
        self.assertIn(human_size(5 * 1024 * 1024), text)

    def test_several_copies_report_the_combined_size(self):
        """A library holding a .zip and a .7z of one game is where wasted space hides, so the pane states the
        total across copies rather than only the selected one."""
        first = self._archive(Path("Games/H/H.zip"), 1024 * 1024)
        second = self._archive(Path("Games/H/H.7z"), 2 * 1024 * 1024)
        self.view.archives = [first, second]
        self.view.select(first)
        self.root.update()
        text = " ".join(_labels(self.view.meta))
        self.assertIn("2 copies", text)
        self.assertIn(human_size(3 * 1024 * 1024), text)

    def test_subtitle_carries_the_size_so_it_is_visible_without_scrolling(self):
        archive = self._archive(Path("Games/Q/Quiet Harbor.zip"), 700 * 1024)
        self.view.archives = [archive]
        self.view.select(archive)
        self.root.update()
        self.assertIn(human_size(700 * 1024), str(self.view.subtitle.cget("text")))

    def test_missing_size_is_reported_as_unknown_rather_than_zero(self):
        archive = self._archive(Path("Games/Q/Quiet Harbor.zip"), 0)
        self.view.archives = [archive]
        self.view.select(archive)
        self.root.update()
        self.assertIn("size unknown", str(self.view.subtitle.cget("text")))
        self.assertNotIn("0 B", str(self.view.subtitle.cget("text")))
