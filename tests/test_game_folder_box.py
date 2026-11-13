"""Extracted from tests/test_catalog_library.py.

    TestGameFolderBox was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
import re
import shutil
from tempfile import TemporaryDirectory
from pathlib import Path
from core.logger import AppLogger
from tests.test_catalog_library import _script_encoded_path
from tests.test_catalog_library import make_game
from services.catalog_service import CatalogService


class TestGameFolderBox(unittest.TestCase):
    """The page is told where the games are, so it keeps working wherever they now live.

    Artwork and the category links are relative to the page, so a copied library keeps its pictures and its
    navigation. The two paths that are not relative - the folder a card copies, and the source an Extract link
    points at - were absolute paths belonging to the machine that ran the scan, so the same page handed out
    paths to nowhere on a Steam Deck, on a desktop, or after the Games folder was moved to another drive. Both
    are rebuilt from a text box now, because a page cannot show a native folder picker: that is the same
    sandbox boundary that stops it running anything.
    """

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        make_game(self.root)
        self.text = CatalogService(AppLogger(self.root / "x.log")).generate(self.root)[0].read_text()

    def test_the_box_is_a_text_box_prefilled_with_the_library_root(self):
        box = re.search(r'id="game-folder"[^>]*value="([^"]*)"', self.text)
        self.assertIsNotNone(box, "the page has to be able to be told where the games are")
        # Not left empty: on the machine that ran the scan the right answer is the library the page was
        # written into, so copy and Extract are right before anything is typed.
        self.assertEqual(box.group(1), str(self.root))

    def test_both_path_buttons_carry_what_a_different_folder_needs(self):
        """The relative folder and the archive name, which are all a new root is missing."""
        copies = re.findall(r'<button class="btn btn-copy"[^>]*>', self.text)
        links = re.findall(r'<a class="btn btn-extract"[^>]*>', self.text)
        self.assertTrue(copies, "the page produced no copy-path buttons")
        self.assertTrue(links, "the page produced no extract links")
        for button in copies + links:
            self.assertIn('data-rel="Simulation/Alpha Forge - 2024-01-01"', button)
            self.assertIn('data-archive="Alpha Forge.zip"', button)

    def test_the_typed_folder_is_what_the_copy_and_the_link_are_built_from(self):
        """The script is the only thing that can join a root onto a relative folder, so the wiring is the test.

        The copy has to be built at click time and the link rebuilt on every change to either box, because a
        stale href is the failure mode here: it looks right on the card and resolves nowhere.
        """
        self.assertIn("function typedRoot()", self.text)
        self.assertIn("joinPath(root,rel)", self.text, "the copied path must be joined onto the typed folder")
        self.assertIn("var base=buttons[i].getAttribute('data-extract'), src=root?archiveSrc(buttons[i]):''", self.text, "the extract source must be rebuilt from the typed folder")
        self.assertRegex(self.text, r"(?m)^  applyLinks\(\);$", "the links are never rebuilt on open, so the remembered folder would be ignored")
        for event in ("input", "change"):
            self.assertIn(f"rootBox.addEventListener('{event}'", self.text)

    def test_the_choice_is_remembered_between_opens(self):
        self.assertIn("store('catalog-root'", self.text)
        self.assertIn("var savedRoot=store('catalog-root')", self.text)

    def test_an_empty_box_falls_back_to_the_folder_the_page_was_written_for(self):
        # Clearing the box must not make the page useless; the written path is still the best guess there is.
        self.assertIn("(btn.getAttribute('data-copy')||'')", self.text)
        self.assertIn("src=root?archiveSrc(buttons[i]):''", self.text)

    def test_an_extract_link_still_resolves_after_the_library_moves(self):
        """The whole reason the box exists, closed against the handler.

        The library is copied to a folder with spaces and an ampersand in the name - a Steam Deck SD card, an
        external drive - and the link is built the way the script builds it. The handler has to accept it
        there, and still refuse it against the old root, which is what proves the box is what moved the link
        rather than something else in the page.
        """
        from urllib.parse import urlsplit
        from core.uri_actions import UriRefused, parse_uri

        parent = TemporaryDirectory()
        self.addCleanup(parent.cleanup)
        moved = Path(parent.name) / "Deck SD (Games & More)"
        shutil.copytree(self.root, moved)
        base = re.findall(r'data-extract="([^"]*)"', self.text)[0].replace("&amp;", "&")
        rel = re.search(r'data-rel="([^"]*)"', self.text).group(1)
        archive = re.search(r'data-archive="([^"]*)"', self.text).group(1)
        parts = urlsplit(base)
        link = f"{parts.scheme}://{parts.netloc}?src={_script_encoded_path(moved / rel / archive)}"
        request = parse_uri(link, moved, [self.root / "extracted"])
        self.assertEqual(request.archive, moved / rel / archive)
        self.assertTrue(request.archive.is_file(), "the page pointed the handler at a file that is not there")
        with self.assertRaises(UriRefused):
            parse_uri(link, self.root, [self.root / "extracted"])

    def test_the_slash_shortcut_does_not_fire_inside_a_path_box(self):
        # Every Unix path opens with one, and a reader may well be typing a path into this box.
        self.assertIn("function typing()", self.text)
        self.assertIn("event.key==='/'&&!typing()", self.text)
        self.assertNotIn("event.key==='/'&&document.activeElement!==search", self.text, "the search shortcut still fires while a path is being typed")
