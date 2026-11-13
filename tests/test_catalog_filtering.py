"""Extracted from tests/test_catalog_library.py.

    TestCatalogFiltering was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
import json
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
from pathlib import Path
from core.logger import AppLogger
from services.catalog_service import CatalogService


class TestCatalogFiltering(unittest.TestCase):
    """What the shelf says back while it is being narrowed, and what each control does to the cards.

    The page previously narrowed silently: the rail kept reporting the unfiltered totals, nothing anywhere said
    how many games a search had matched, clicking a genre threw away whatever had been typed into the search
    box, and the hero's "missing art" figure was a number with nothing behind it. These assert the hooks that
    the client-side script drives, plus the one behaviour that is decided in Python - what goes in the haystack.
    """

    def setUp(self):
        parent = TemporaryDirectory()
        self.addCleanup(parent.cleanup)
        self.root = Path(parent.name) / "Games"
        self.root.mkdir()
        # Two games in two categories, one with artwork and one without, so the art filter has both a hit and
        # a miss to sort out and the rail has more than one count to keep honest.
        for index, (name, category, genres, art) in enumerate([("Alpha Forge", "Simulation", ["Simulation", "Strategy"], True), ("Hollow Signal", "Adventure", ["Horror", "Indie"], False)], 1):
            game = self.root / category / f"{name} - 2024-01-01"
            game.mkdir(parents=True)
            (game / f"{name}.zip").write_text("x")
            (game / ".game-info.json").write_text(json.dumps({"appid": str(100001 + index), "name": name, "description": f"A quiet roguelike about {name}.", "release_date": "1 Jan, 2024", "genres": genres}))
            if art:
                (game / f"{name}_grid.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        self.page = CatalogService(AppLogger(self.root / "x.log")).generate(self.root)[0]
        self.text = self.page.read_text()

    def test_the_page_reports_how_many_games_a_search_matched(self):
        # Typing into a 166-card shelf with no feedback means not knowing whether a search found nothing, found
        # one game, or quietly failed to run at all. The only thing the page said was a hidden "no games match"
        # message, which appears in exactly one of those three cases.
        self.assertIn('id="result-count"', self.text)
        self.assertIn("tally.textContent=filtering?shown+' of '+cards.length", self.text)
        self.assertIn(".result-count.is-filtering", CatalogService._css(CatalogService.__new__(CatalogService)))

    def test_the_rail_counts_what_the_filter_left_visible(self):
        # The numbers beside every category used to keep reporting the unfiltered totals, so a search matching
        # twelve games still showed 166 in the rail - a count of nothing the reader can see on the page.
        # The rail is rendered from markup, so only the markup form proves the hook reached the page. Asserting
        # on the bare name would also match the script's own querySelector('[data-toc-count=...') calls.
        self.assertIn('<span class="count" data-toc-count="', self.text)
        self.assertIn("sec.querySelectorAll('.card:not(.is-hidden)').length", self.text)
        self.assertIn(".toc-link.is-muted", CatalogService._css(CatalogService.__new__(CatalogService)))

    def test_a_genre_chip_does_not_throw_away_the_search_that_was_typed(self):
        # The chip handler used to set search.value='' on every click, so narrowing a search you had already
        # typed silently discarded it. The two now narrow together, which is what clicking a chip after typing
        # reads as meaning.
        #
        # The handler has to be cut out by offset, not by split(). It contains the chip selector a second time
        # - clearing every other chip's pressed state - and a split() on the selector ends the region at that
        # inner loop, before the line under test, which is a test that can never fail.
        marker = "document.querySelectorAll('.chip-btn').forEach(function(chip){"
        start = self.text.index(marker)
        handler = self.text[start : self.text.index("document.querySelectorAll('.stat-filter')", start)]
        # Guard the cut itself: an empty or truncated region would satisfy assertNotIn without testing anything.
        self.assertIn("state.genre=", handler, "the extracted chip handler is not the real handler")
        self.assertIn("apply()", handler, "the extracted chip handler stops before it filters the cards")
        self.assertNotIn("search.value=''", handler, "clicking a genre still clears the search box")

    def test_the_missing_art_figure_is_a_filter_and_not_only_a_number(self):
        # The hero already reported how many games have no artwork, which on a shelf where a third of the cards
        # are placeholders is the one figure worth acting on - and there was nothing to act with. It is now a
        # toggle over the cards that have none, and it reports its pressed state for a screen reader.
        self.assertIn('data-filter="noart"', self.text)
        self.assertIn('data-filter="noart" aria-pressed="false"', self.text)
        self.assertIn('data-art="0"', self.text)
        self.assertIn("!state.noart||card.getAttribute('data-art')==='0'", self.text)
        self.assertIn(".stat-filter.is-active", CatalogService._css(CatalogService.__new__(CatalogService)))

    def test_search_covers_the_description_and_the_release_date(self):
        # The haystack was name, category, developer, publisher, archive and genres, which left the two most
        # identifying things about a game - what it is about, and when it came out - unsearchable. The
        # placeholder offers to search genres and developers, so the haystack is what backs that promise.
        haystack = re.search(r'data-search="([^"]*)"', self.text).group(1).lower()
        self.assertIn("quiet roguelike", haystack, "the description is not searchable")
        self.assertIn("2024", haystack, "the release year is not searchable")

    def test_tied_sorts_do_not_reshuffle_the_shelf(self):
        # Every game with no release date shares a sort key, and so do every archive of the same size. With no
        # tie-break the order came out of the sort at random, so switching between two sorts that tied read as
        # the page rearranging itself for no reason.
        self.assertIn("var an=a.getAttribute('data-name')||'', bn=b.getAttribute('data-name')||''", self.text)

    def test_the_generated_script_is_valid_javascript(self):
        # None of the above is worth anything if the script does not parse: a syntax error leaves a page that
        # looks finished and does nothing, and no amount of reading the source proves the file is loadable.
        node = shutil.which("node")
        if not node:
            self.fail("node is not on PATH, so the generated script cannot be checked for syntax")
        script = self.text.split("<script>", 1)[1].rsplit("</script>", 1)[0]
        page = self.root / "page.js"
        page.write_text(script, encoding="utf-8")
        check = subprocess.run([node, "--check", str(page)], capture_output=True, text=True, timeout=60)
        self.assertEqual(check.returncode, 0, f"the generated script is not valid JavaScript:\n{check.stderr}")
