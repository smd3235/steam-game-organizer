"""Extracted from tests/test_review_context_panels.py.

    EmptyTagsRowIsSuppressed was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
import tkinter as tk
from pathlib import Path
from core.models import GameArchive
from core.models import SteamMatch
from ui.widgets.metadata_panel import MetadataPanel
from tests.tk_support import close_root
from tests.test_helpers import shown
from tests.tk_support import require_tk


class EmptyTagsRowIsSuppressed(unittest.TestCase):
    """tags is unobtainable: it is [] on all 165 sidecars and Steam's appdetails payload has no such field.

    An always-empty row would read as "this game has no tags", which is a claim about the game rather than
    about the feed we cannot get. The row is therefore suppressed, and suppressed only when empty.
    """

    def setUp(self):
        require_tk(self)
        self.root = tk.Tk()
        self.addCleanup(close_root, self.root)
        self.panel = MetadataPanel(self.root)
        self.panel.pack()
        self.root.update()

    def _archive(self, tags):
        archive = GameArchive(Path("Alpha Quest.7z"), "Alpha Quest", "Alpha Quest", "alpha quest", ".7z")
        archive.steam = SteamMatch(found=True, appid="1", name="Alpha Quest", genres=("Horror",), description="A game.", tags=list(tags), developer="Bewolba Studio")
        return archive

    def test_no_tags_row_when_the_list_is_empty(self):
        self.panel.show(self._archive(()))
        self.root.update()
        self.assertNotIn("TAGS", shown(self.panel))

    def test_the_tags_row_appears_when_tags_do(self):
        """Otherwise the suppression is a row that can never appear, which is indistinguishable from
        deleting the feature."""
        self.panel.show(self._archive(("Great Soundtrack",)))
        self.root.update()
        self.assertIn("Great Soundtrack", shown(self.panel))

    def test_the_match_trust_section_reports_what_the_match_was(self):
        archive = self._archive(())
        archive.steam.confidence = "High"
        archive.steam.source = "steam_appid"
        archive.steam.reason = "exact title"
        self.panel.show(archive)
        self.root.update()
        text = "\n".join(shown(self.panel))
        self.assertIn("MATCH TRUST", text)
        self.assertIn("High", text)
