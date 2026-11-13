"""Extracted from tests/test_displayed_data.py.

    TheCatalogShowsAndSearchesTags was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import json
import re
import tempfile
import unittest
from pathlib import Path
from core.logger import AppLogger
from services.catalog_service import CatalogService


class TheCatalogShowsAndSearchesTags(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "Games"
        self.dest = self.base / "Out"
        self.dest.mkdir(parents=True)
        self.logger = AppLogger(self.base / "x.log")
        self._game("Idle", "Loop Miner", ["Idle"], ["Great Soundtrack", "Controller Support", "Incremental"])
        self._game("RPG", "Deep Signal", ["RPG"], ["Turn-Based", "Great Soundtrack", "Replay Value"])

    def _game(self, category, name, genres, tags):
        folder = self.root / category / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{name}.zip").write_bytes(b"x" * 2048)
        (folder / ".game-info.json").write_text(json.dumps({"appid": "1", "name": name, "description": "A game.", "release_date": "1 Jan, 2024", "genres": genres, "tags": tags, "developer": "Dev", "publisher": "Pub"}), encoding="utf-8")

    def _page(self):
        return CatalogService(self.logger, extract_folders=[self.dest]).generate(self.root, "")[0].read_text("utf-8")

    def _markup(self):
        """The generated page with the stylesheet taken out.

        These tests are about what the reader is shown, and a chip class is named twice in a page: once in
        the CSS that styles it and once on the element itself. Searching the whole document for `chip-more`
        therefore matched the stylesheet rule rather than any chip, which is why the "no overflow chip is
        expected" assertion could never pass and the "the card says it left tags off" assertion passed on the
        stylesheet alone - the pair could neither fail when it should nor pass when it should.
        """
        return re.sub(r"<style\b.*?</style>", "", self._page(), flags=re.S | re.I)

    def _search_indexes(self):
        """Every card's search haystack, read off the attribute the page's own script filters on."""
        return [value.casefold() for value in re.findall(r'data-search="([^"]*)"', self._page())]

    def test_a_card_shows_its_tags(self):
        page = self._page()
        self.assertIn('class="chip chip-tag" title="Great Soundtrack"', page, "a game Steam tags 'Great Soundtrack' does not show it")
        self.assertIn('class="chip chip-tag" title="Incremental"', page)

    def test_a_card_caps_the_tags_it_shows_and_says_how_many_it_kept(self):
        """Uncapped, a well-tagged game's card is a wall of chips and the description is pushed off the card."""
        markup = self._markup()
        self.assertNotIn("chip-more", markup, "this fixture has three tags, so no overflow chip is expected")
        self._game("Idle", "Tagged", ["Idle"], [f"Tag {n}" for n in range(6)])
        markup = self._markup()
        self.assertEqual(markup.count('class="chip chip-tag" title="Tag 0"'), 1)
        self.assertNotIn('title="Tag 5"', markup, "the sixth tag was rendered, so nothing was capped")
        self.assertIn("chip-more", markup, "the card does not say that it left tags off")

    def test_a_tag_is_searchable(self):
        """The reason to have them at all: the search index never covered tags.

        `suggest_category` already consumed them to pick a folder and they were then dropped, so searching for
        a tag a game demonstrably has returned nothing.

        Asserted by reading the haystack the page's own script matches against. It used to assert that the
        Python expression `' '.join(game['tags'])` appeared in the generated HTML, which no page can ever
        contain - so the defect it describes was untestable and the assertion was guaranteed to fail.
        """
        page = self._page()
        self.assertIn('chip-tag" title="Controller Support"', page)
        self.assertTrue(any("controller support" in haystack for haystack in self._search_indexes()), "tags are shown but not in the search index, so the shelf cannot be searched by one")

    def test_the_rail_offers_a_tag_filter(self):
        page = self._page()
        self.assertIn('class="chip-btn chip-btn-tag"', page, "there is no tag filter in the rail")
        # Two games share it, and the count has to say so or the filter cannot be judged before it is used.
        # Matched on the whole chip rather than by string equality against it: the expected text left out the
        # chip's own visible label, which sits between the attribute and the count.
        chip = re.search(r'<button[^>]*data-genre="Great Soundtrack"[^>]*>.*?</button>', page, re.S)
        self.assertIsNotNone(chip, "there is no rail chip for the tag two games share")
        self.assertIn('<span class="chip-count">2</span>', chip.group(0), "two games carry this tag and the count has to say so")

    def test_a_library_with_no_tags_gets_no_tag_rail(self):
        """The tag rail is unreachable on this machine, and it renders as an empty row when it is.

        Steam's `appdetails` payload carries no `tags` field at all, so `tags` is `[]` on all 165 sidecars in
        the real library and in all 344 entries of the match cache. Every library this app has ever built
        therefore had nothing to put under a Tags heading, and the nav was emitted anyway: a heading, an empty
        chip row, and a filter that could only ever narrow the shelf to nothing. The whole `<nav>` is dropped
        when there is nothing to put in it, which is the same empty-state handling the Review screen's Tags row
        uses (ui/widgets/metadata_panel.py omits the row rather than rendering it blank), so the two do not
        drift into different answers about what a game with no tags should show.

        Read with the stylesheet stripped, because a chip class is named twice in a page: once in the CSS that
        styles it and once on the element itself, so searching the whole document matches the rule that styles
        the chip and this test could never fail.
        """
        control = self._markup()
        self.assertIn('class="chip-btn chip-btn-tag"', control, "control: the tagged fixture renders the rail, so what follows can only be suppression. Without this, a tag rail that stopped rendering at all would pass every assertion below")
        for category, name in (("Idle", "Loop Miner"), ("RPG", "Deep Signal")):
            folder = self.root / category / name
            payload = json.loads((folder / ".game-info.json").read_text(encoding="utf-8"))
            payload["tags"] = []
            (folder / ".game-info.json").write_text(json.dumps(payload), encoding="utf-8")
        markup = self._markup()
        for fragment, consequence in (
            ("tags-nav", "the Tags nav is rendered with an empty chip row under its heading"),
            (">Tags</p>", "the Tags heading survives with nothing under it"),
            ('aria-label="Tags"', "the rail still announces a Tags group to a screen reader"),
            ("chip-btn-tag", "a tag filter chip is rendered where there are no tags to filter by"),
            ("chip chip-tag", "a tag chip is rendered on a card that has no tags"),
        ):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, markup, f"no game in this fixture has a tag, so {consequence}")

    def test_a_tag_filter_also_matches_a_game_that_only_has_that_tag(self):
        """Genres and tags share one facet attribute.

        Two chip kinds filtering through two attributes is how they come to disagree about what they match, and
        the visible symptom is a chip that is highlighted while showing nothing.
        """
        page = self._page()
        self.assertIn('data-genre="Controller Support"', page, "the tag is in the rail but not on the card's facets, so clicking it would match nothing")

    def test_a_broken_tag_field_cannot_put_letters_in_the_search_index(self):
        """The sidecar is a JSON file a person can edit, and a string where a list was expected would iterate
        character by character - putting single letters into every haystack."""
        folder = self.root / "Idle" / "Loop Miner"
        payload = json.loads((folder / ".game-info.json").read_text(encoding="utf-8"))
        payload["tags"] = "Great Soundtrack"
        (folder / ".game-info.json").write_text(json.dumps(payload), encoding="utf-8")
        page = self._page()
        self.assertNotIn('title="G"', page, "a string was iterated per character and rendered as chips")
        self.assertIn('title="Great Soundtrack"', page, "a lone string should still be usable as one tag")
