"""Extracted from tests/test_batch_extract.py.

    TheCatalogOffersTheBatchButtons was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import tempfile
import unittest
from pathlib import Path
from core.logger import AppLogger
from tests.test_helpers import _game
from services.catalog_service import CatalogService


class TheCatalogOffersTheBatchButtons(unittest.TestCase):
    """The page half. Every assertion is on the rendered text, because a button the reader cannot see is the
    whole failure and a helper that built one nobody renders would pass."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "Games"
        self.dest = Path(temporary.name) / "Out"
        self.dest.mkdir(parents=True)
        for category, name in (("Idle", "Loop Miner"), ("Idle", "Fellwood"), ("RPG", "Deep Signal")):
            _game(self.root, category, name)
        service = CatalogService(AppLogger(Path(temporary.name) / "x.log"), extract_folders=[self.dest])
        self.text = service.generate(self.root)[0].read_text(encoding="utf-8")

    def test_each_category_banner_offers_to_install_its_games(self):
        self.assertIn("Extract all 2", self.text, "the Idle category's two games are not offered as a batch")
        self.assertIn("Extract all 1", self.text, "the RPG category's single game is not offered as a batch")

    def test_the_toolbar_offers_the_whole_library(self):
        self.assertIn("Extract all 3", self.text, "there is no whole-library Extract all in the toolbar")

    def test_a_category_link_names_that_category(self):
        self.assertIn("steamgameorganizer://extract-all?category=Idle", self.text)

    def test_the_library_wide_link_names_no_category(self):
        """The library-wide button sends the action with no category, which the handler treats as the whole
        library rather than a named folder. The script on the page rebuilds this link the same way as the
        per-category ones, so it carries the same shape: steamgameorganizer://extract-all with no query."""
        import re

        library_links = re.findall(r'data-batch="(steamgameorganizer://extract-all[^"]*)"', self.text)
        self.assertTrue(library_links, "no batch link carries the data-batch the script rebuilds from")
        self.assertIn('steamgameorganizer://extract-all"', self.text, "the whole-library link does not end at the action with no query string")

    def test_the_buttons_state_how_many_games_they_cover(self):
        """A button reading 'Extract all' over a shelf of 176 games is not enough evidence to agree to hours of
        unpacking, so the count is on the button and the size is in the confirmation."""
        import re

        counts = re.findall(r'data-batch-count="(\d+)"', self.text)
        self.assertEqual(sorted(int(c) for c in counts), [1, 1, 2, 2, 3, 3], f"the batch buttons do not carry the real counts: {counts}")

    def test_the_batch_links_rebuild_from_the_destination_box(self):
        """Rebuilt from the pristine data-batch on every keystroke, exactly like the single Extract links, so
        typing in the box cannot accumulate a second dest parameter onto a link that already has one."""
        self.assertIn("data-batch=", self.text)
        self.assertIn("document.querySelectorAll('[data-batch]')", self.text)
        self.assertIn("var bbase=batch[j].getAttribute('data-batch')", self.text)

    def test_a_batch_is_confirmed_before_the_browser_hands_it_over(self):
        """preventDefault() has to be in there. Without it the run starts on the click and any prompt appears
        over a window that is already unpacking."""
        self.assertIn("confirmBatch(link)", self.text)
        self.assertIn("event.preventDefault()", self.text)

    def test_the_confirmation_names_the_count_and_the_destination(self):
        self.assertIn("data-batch-confirm=", self.text)
        self.assertIn("To: '+dest", self.text)
        self.assertIn("free space", self.text, "the prompt does not mention that a batch needs several times the archive size in room")

    def test_the_single_extract_links_are_left_alone(self):
        """One archive is small and reversible; a prompt on every card would make the button tiresome. So the
        confirmation is bound to the batch links only."""
        self.assertEqual(self.text.count("data-batch-count="), 6, "an unexpected number of batch buttons appeared")
        self.assertIn('class="btn btn-extract"', self.text, "the per-game Extract button is gone")
        self.assertIn("querySelectorAll('.btn-extract')", self.text, "the single Extract links are no longer rebuilt from the destination box")

    def test_the_single_game_button_is_still_on_the_card(self):
        """The whole point of the three levels: this one game, this category, everything."""
        self.assertEqual(self.text.count('class="btn btn-extract"'), 3, "one Extract button per game is expected")
