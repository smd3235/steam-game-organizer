"""Data the app has, and whether any of it reaches the screen.

Every item here is the same shape of defect, found by auditing the models against the views rather than by
reading the code for bugs: a field is fetched, stored, and never shown. Steam's tags were the clearest case -
the store *search* response does not carry them, and neither, as it turns out, does the appdetails payload the
9.23 fix moved them to, so every game in the library had an empty list and nothing downstream could have shown
one. Confidence was on the review card as words in grey body text, which is present but not legible as the
warning it is.

The tests are grouped by that theme rather than by the file the code lives in, because the interesting
assertion is usually about a chain: a field filled in one service, written to a sidecar, and read by a
generator. Asserting any single link of that chain would pass with the rest broken.
"""
from __future__ import annotations

import json
import re
import tempfile
import threading
import unittest
from pathlib import Path

from app.controller import AppController
from app.events import EventBus
from core.logger import AppLogger
from core.models import ArtworkResult,ScanResult,SteamMatch
from core.state import StateStore
from core.config import AppConfig
from services.catalog_service import CatalogService
from services.steam_service import SteamService
from ui.palette import GREEN,ORANGE
from ui.widgets.game_card import GameCard
from utils.filename_utils import identity_key


class SteamTagsAreActuallyRead(unittest.TestCase):
    """Both tag shapes are still parsed, although the store API sends neither.

    Kept, because they are what a working source would arrive in and the parse is what reads them. What these
    cannot test is whether Steam sends them at all - the fixtures here assert the parser, not the source. The
    class that covers the source is the one below.
    """

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.logger = AppLogger(self.base / "x.log")
        self.service = SteamService(self.logger, mock=True, cache_file=self.base / "cache.json")

    def _build(self, details):
        return self.service._build_match("1", {"name": "x"}, details)

    def test_tags_arrive_as_a_list_of_name_objects(self):
        """A list of {"id", "name"} objects, which is the shape a working source would send."""
        match = self._build({"tags": [{"id": 16689, "name": "Great Soundtrack"},
                                      {"id": 1038, "name": "Immersive Sim"}]})
        self.assertEqual(match.tags, ["Great Soundtrack", "Immersive Sim"])

    def test_tags_arrive_as_an_id_keyed_object(self):
        """The other documented shape.

        Without this the rule reads one shape and quietly returns nothing for the other - and an empty tag list
        is indistinguishable from a game that has no tags, so nothing downstream would ever report the miss.
        """
        match = self._build({"tags": {16689: "Great Soundtrack", 1038: "Immersive Sim"}})
        self.assertEqual(match.tags, ["Great Soundtrack", "Immersive Sim"])

    def test_a_missing_or_odd_tag_field_is_not_an_error(self):
        for details in ({}, {"tags": None}, {"tags": "Great Soundtrack"}, {"tags": [{"id": 1}]}):
            with self.subTest(details=details):
                self.assertEqual(self._build(details).tags, [])

    def test_a_tag_that_is_only_whitespace_is_dropped(self):
        """Whitespace-only tags would render as a blank chip on the card."""
        self.assertEqual(self._build({"tags": [{"name": "  "}, {"name": " Co-op "}]}).tags, ["Co-op"])

    def test_tags_come_from_the_details_and_not_the_search_hit(self):
        """Tags are read from the payload in hand rather than from the search hit.

        The search response carries an id, a name, a price and a thumbnail, so a tag read from it is nothing for
        every game, always. This was read as the defect in 9.23 and the read was moved here; it turned out to
        be no defect at all, because this payload has no tags either. The assertion is still the right one -
        the fields come from the one response that describes the game rather than from the one that merely
        matched its name - and it no longer claims to be the fix.
        """
        match = self.service._build_match("42", {"name": "Loop Miner", "id": 42},
                                          {"tags": [{"id": 1, "name": "Idle"}]})
        self.assertEqual(match.tags, ["Idle"], "tags are read from the search result, which carries none")


# The keys appdetails actually returned, recorded rather than re-measured, so the claim at the top of
# services/steam_service.py can be checked without a network call. One live request each on 2026-10-04:
#   https://store.steampowered.com/api/appdetails?appids=322330&cc=us&l=en   -> 36 keys, success=True
#   https://store.steampowered.com/api/appdetails?appids=1091500&cc=us&l=en  -> 38 keys, success=True
# The key set is the whole of what matters: which fields are absent. Both responses carry genres, categories,
# content_descriptors, ratings, supported_languages, metacritic, screenshots, movies and package_groups, and
# neither carries tags - Steam's store tags are community-curated and rendered into the store page's HTML.
APPDETAILS_KEYS_322330=frozenset({'about_the_game','background','background_raw','capsule_image','capsule_imagev5',
    'categories','content_descriptors','controller_support','detailed_description','developers','dlc','genres',
    'header_image','is_free','linux_requirements','mac_requirements','metacritic','movies','name','package_groups',
    'packages','pc_requirements','platforms','price_overview','publishers','ratings','recommendations',
    'release_date','required_age','screenshots','short_description','steam_appid','support_info',
    'supported_languages','type','website'})
APPDETAILS_KEYS_1091500=APPDETAILS_KEYS_322330|{'achievements','legal_notice'}


class TheSourceSaysWhenItHasNoTags(unittest.TestCase):
    """A tag list that is empty because nothing could be fetched has to say so.

    Measured on this machine, every `.game-info.json` sidecar in the real library reads `"tags": []` and so does
    every entry in config/steam-matches.json - 165 of 165 and 344 of 344 - and the app reported nothing for
    nine releases. The parse was never the whole problem: appdetails has no `tags` field at all, so no reshaping
    of it could return one, and the v9.23 note described a fix that cannot work. Without a second data source
    (a key-gated one, or scraping the store page, both of which are a person's decision and not this test's) the
    honest end state is an empty list that is no longer silent.

    A warning nobody sees is a warning nobody acts on, so every assertion here reads the log file the app
    already writes rather than a stub of the logger - which is the same thing a person opens to find out.
    """

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.log = self.base / "steam.log"
        self.logger = AppLogger(self.log)
        self.service = SteamService(self.logger, mock=True, cache_file=self.base / "cache.json")

    def _payload(self, keys=APPDETAILS_KEYS_322330):
        """A payload with the real field set, holding the four fields `_build_match` has to be able to read."""
        details = dict.fromkeys(keys)
        details.update(name="DOOM", steam_appid="322330", type="game",
                       genres=[{"id": 1, "description": "Action"}], categories=[{"id": 1, "description": "Single-player"}],
                       release_date={"coming_soon": False, "date": "Apr 21, 2016"}, short_description="A game.")
        return details

    def _logged(self):
        """Whatever the app wrote to its log, read as empty when it wrote nothing at all.

        `AppLogger` opens the file in append mode per line and swallows OSError, so a run that logs nothing
        leaves no file behind. Reading it unguarded raises FileNotFoundError, which reports a broken test
        instead of the silence under test - which is precisely the condition three of these assert.
        """
        return self.log.read_text(encoding="utf-8", errors="replace") if self.log.is_file() else ""

    def test_the_recorded_payload_is_the_one_that_was_measured_and_has_no_tag_field(self):
        """The finding everything else rests on, kept as data so it can be checked without the network.

        The counts are asserted as well as the absence, because a transcription that quietly dropped three keys
        would still satisfy an `assertNotIn('tags', ...)`. A test that cannot fail is worse than none.
        """
        self.assertEqual(36, len(APPDETAILS_KEYS_322330), "the recorded key set was transcribed wrongly")
        self.assertEqual(38, len(APPDETAILS_KEYS_1091500), "the recorded key set was transcribed wrongly")
        for keys in (APPDETAILS_KEYS_322330, APPDETAILS_KEYS_1091500):
            with self.subTest(tags_present='tags' in keys):
                self.assertNotIn('tags', keys, "appdetails does serve tags, so the source and this fix both change")

    def test_the_real_payload_shape_yields_no_tags_and_reports_it(self):
        """The defect, asserted on the shape the endpoint really returns.

        `tags: []` is the correct answer here - Steam sent no tags. What was wrong was that the app produced
        that same value, silently, from every game forever, which is indistinguishable from the bug it was.
        """
        match = self.service._build_match("322330", {"name": "DOOM"}, self._payload())
        self.assertEqual([], match.tags, "the recorded payload carries no tags, so there is nothing to return")
        self.assertEqual(["Action"], match.genres, "genres come from the same payload and are unaffected")
        text = self._logged()
        self.assertIn("TAGS_UNAVAILABLE", text,
                      "the payload has no tag field and nothing said so, so the empty list still means two things")
        self.assertIn("[WARN", text, "tags are unobtainable from this source and it was not worth a warning")
        self.assertIn("field=[tags]", text, "the report does not name the field that is missing")

    def test_a_lookup_reports_it_and_names_the_app_it_was_read_for(self):
        """Through the real path rather than the private helper, stubbed where the tests stub Steam.

        `_details` is the request boundary the rest of the Steam tests replace, so this exercises lookup's own
        reading of a payload rather than `_build_match` called directly.
        """
        self.service._details = lambda appid, ctx=None: self._payload()
        match = self.service._lookup_appid("322330", None)
        self.assertTrue(match.found, "the fixture failed to match, so nothing downstream ran")
        self.assertEqual([], match.tags)
        self.assertIn("appid=322330", self._logged(), "the report does not say which game it was read for")

    def test_a_run_of_games_reports_it_once_and_not_once_each(self):
        """A warning per game is 165 identical lines, and a log that says the same thing 165 times is a log
        nobody reads. Once per service says the same thing once and still says it."""
        for appid in ("1", "2", "3"):
            self.service._build_match(appid, {"name": "x"}, self._payload())
        self.assertEqual(1, self._logged().count("TAGS_UNAVAILABLE"),
                         "the same missing field was reported once per game rather than once")

    def test_a_source_that_does_carry_tags_is_not_reported_as_unavailable(self):
        """The other half, and the half that decides whether the warning is worth having.

        A warning that fires when there is nothing to report is worse than no warning, because it is the thing
        a person opens the log to find. If Steam ever serves the field, this shape must be silent about it.
        """
        details = self._payload()
        details["tags"] = [{"id": 16689, "name": "Great Soundtrack"}, {"id": 1038, "name": "Immersive Sim"}]
        match = self.service._build_match("322330", {"name": "DOOM"}, details)
        self.assertEqual(["Great Soundtrack", "Immersive Sim"], match.tags)
        text = self._logged()
        self.assertNotIn("TAGS_UNAVAILABLE", text, "this payload carried tags and was reported as carrying none")
        self.assertIn("TAGS_PRESENT", text, "tags arrived and nothing recorded that the source had them")


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
        (folder / ".game-info.json").write_text(
            json.dumps({"appid": "1", "name": name, "description": "A game.", "release_date": "1 Jan, 2024",
                        "genres": genres, "tags": tags, "developer": "Dev", "publisher": "Pub"}),
            encoding="utf-8")

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
        self.assertIn('class="chip chip-tag" title="Great Soundtrack"', page,
                      "a game Steam tags 'Great Soundtrack' does not show it")
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
        self.assertTrue(any("controller support" in haystack for haystack in self._search_indexes()),
                        "tags are shown but not in the search index, so the shelf cannot be searched by one")

    def test_the_rail_offers_a_tag_filter(self):
        page = self._page()
        self.assertIn('class="chip-btn chip-btn-tag"', page, "there is no tag filter in the rail")
        # Two games share it, and the count has to say so or the filter cannot be judged before it is used.
        # Matched on the whole chip rather than by string equality against it: the expected text left out the
        # chip's own visible label, which sits between the attribute and the count.
        chip = re.search(r'<button[^>]*data-genre="Great Soundtrack"[^>]*>.*?</button>', page, re.S)
        self.assertIsNotNone(chip, "there is no rail chip for the tag two games share")
        self.assertIn('<span class="chip-count">2</span>', chip.group(0),
                      "two games carry this tag and the count has to say so")

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
        self.assertIn('class="chip-btn chip-btn-tag"', control,
                      "control: the tagged fixture renders the rail, so what follows can only be suppression. "
                      "Without this, a tag rail that stopped rendering at all would pass every assertion below")
        for category, name in (("Idle", "Loop Miner"), ("RPG", "Deep Signal")):
            folder = self.root / category / name
            payload = json.loads((folder / ".game-info.json").read_text(encoding="utf-8"))
            payload["tags"] = []
            (folder / ".game-info.json").write_text(json.dumps(payload), encoding="utf-8")
        markup = self._markup()
        for fragment, consequence in (
            ('tags-nav', 'the Tags nav is rendered with an empty chip row under its heading'),
            ('>Tags</p>', 'the Tags heading survives with nothing under it'),
            ('aria-label="Tags"', 'the rail still announces a Tags group to a screen reader'),
            ('chip-btn-tag', 'a tag filter chip is rendered where there are no tags to filter by'),
            ('chip chip-tag', 'a tag chip is rendered on a card that has no tags'),
        ):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, markup, f"no game in this fixture has a tag, so {consequence}")

    def test_a_tag_filter_also_matches_a_game_that_only_has_that_tag(self):
        """Genres and tags share one facet attribute.

        Two chip kinds filtering through two attributes is how they come to disagree about what they match, and
        the visible symptom is a chip that is highlighted while showing nothing.
        """
        page = self._page()
        self.assertIn('data-genre="Controller Support"', page,
                      "the tag is in the rail but not on the card's facets, so clicking it would match nothing")

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


class TheScanSummaryReachesTheNextSession(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.config = AppConfig(self.base)
        self.logger = AppLogger(self.base / "x.log")

    def test_a_summary_round_trips(self):
        written = self.config.save_scan_summary({"archives": 176, "matched": 171, "artwork": 168})
        self.assertIsNotNone(written, "the summary was not written")
        read = self.config.load_scan_summary()
        self.assertEqual(read["archives"], 176)
        self.assertEqual(read["matched"], 171)
        self.assertIn("recorded_at", read, "the summary has no timestamp, so the panel cannot say how old it is")

    def test_the_config_lands_in_the_file_this_class_had_declared_and_never_used(self):
        """`state_file` was declared on AppConfig and read by nothing. Writing to it is what makes it a real
        declaration rather than a leftover."""
        self.config.save_scan_summary({"archives": 1})
        self.assertTrue(self.config.state_file.is_file(),
                        f"nothing was written to {self.config.state_file}")

    def test_a_missing_empty_or_non_object_file_is_not_fatal(self):
        """Read during layout, before anything else has run, so every broken shape has to answer None."""
        self.assertIsNone(self.config.load_scan_summary(), "no summary yet should read as None")
        self.config.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.config.state_file.write_text("", encoding="utf-8")
        self.assertIsNone(self.config.load_scan_summary(), "an empty file should read as None")
        self.config.state_file.write_text("[]", encoding="utf-8")
        self.assertIsNone(self.config.load_scan_summary(), "valid JSON that is not an object should read as None")

    def test_a_scan_still_completes_when_there_is_no_config_to_record_into(self):
        """The regression this work introduced, kept as a test.

        `AppController` is constructed without a config by half the test suite. The first version of the summary
        called `self.config.save_scan_summary()` before handing the result on, so the resulting AttributeError
        meant `done` was never called and four scan tests sat waiting out a thirty-second timeout instead of
        failing on the line that was wrong.
        """
        controller = AppController(StateStore(), EventBus(), self.logger, _Services(), _Jobs())
        self.assertIsNone(controller.config, "this test is only meaningful while a config-less controller exists")

        finished = threading.Event()
        results = []
        controller._scan_ok(ScanResult(archives=[]), lambda r: (results.append(r), finished.set()))
        self.assertTrue(finished.wait(5), "the scan never handed its result on")
        self.assertEqual(1, len(results))

    def test_a_scan_summary_counts_artwork_the_way_the_screens_do(self):
        """`artwork_ready` counted the primary image alone until 9.20, and the summary would have reintroduced it.

        A game whose pictures arrived as asset URLs has no primary path, so a primary-only count reports zero
        for a game folder holding five images - the exact defect 9.20 fixed, in a new place.
        """
        class _Assets(ArtworkResult):
            """One game's artwork as the asset-URL case really produces it: no primary path, several assets.

            Subclasses the real result and overrides only `files()`. The previous stand-in defined `present()`
            by calling the unbound `ArtworkResult.present` on itself, which is defined in terms of `files()` -
            a method it did not have. So it raised AttributeError every time, and what this test was reporting
            was its own broken double rather than anything about artwork counting.
            """

            def __init__(self, *paths):
                super().__init__()
                self.path = paths[0] if paths else ""
                self.assets = {f"asset{n}": p for n, p in enumerate(paths[1:], 1)}

            def files(self):
                named = ([self.path] if self.path else []) + list(self.assets.values())
                return [Path(p) for p in named if p]

        class _UnreadableArtwork:
            """Artwork whose present() raises, standing in for a malformed sidecar or a pruned cache."""

            path = ""
            assets: dict = {}

            def present(self):
                raise OSError("artwork record is unreadable")

        class _Archive:
            def __init__(self, size, artwork):
                self.size = size
                self.artwork = artwork
                self.steam = SteamMatch(found=True)

        archives = [_Archive(100, _Assets("", "a.jpg", "b.jpg")), _Archive(50, _Assets("c.jpg"))]
        result = ScanResult(archives=archives)
        controller = AppController(StateStore(), EventBus(), self.logger, _Services(), _Jobs())
        controller.config = self.config
        controller._record_scan(result)
        read = self.config.load_scan_summary()
        self.assertEqual(read["archives"], 2)
        self.assertEqual(read["artwork"], 2, "a game whose artwork arrived as assets was counted as having none")
        self.assertEqual(read["total_bytes"], 150)

    def test_one_unreadable_artwork_entry_does_not_cost_the_whole_summary(self):
        """Every number is built in one expression, so an entry that raises used to take all of them.

        The summary is a convenience readout, so the worst one malformed artwork record may cost is that one
        game counted as having no picture. It must not also cost the archive count, the byte total and the
        match count, which is what happened: the generator aborted the dict literal that was building them.
        """

        class _Archive:
            def __init__(self, size, artwork, found=True):
                self.size = size
                self.artwork = artwork
                self.steam = SteamMatch(found=found)

        class _Broken:
            path = ""
            assets: dict = {}

            def present(self):
                raise OSError("artwork record is unreadable")

        class _Good:
            path = ""
            assets: dict = {}

            def present(self):
                return True

        result = ScanResult(archives=[_Archive(100, _Broken()), _Archive(50, _Good(), found=False)])
        controller = AppController(StateStore(), EventBus(), self.logger, _Services(), _Jobs())
        controller.config = self.config
        controller._record_scan(result)
        read = self.config.load_scan_summary()
        self.assertIsNotNone(read, "one bad artwork record stopped the summary being recorded at all")
        self.assertEqual(read["archives"], 2, "the archive count was lost to one bad entry")
        self.assertEqual(read["total_bytes"], 150, "the byte total was lost to one bad entry")
        self.assertEqual(read["unmatched"], 1, "the match counts were lost to one bad entry")
        self.assertEqual(read["artwork"], 1, "the broken entry should count as no artwork, and the good one as some")


class _Services:
    organizer = None
    rollback = None


class _Jobs:
    def submit(self, *a, **k):
        raise AssertionError("the summary path must not submit work")


class MatchConfidenceIsVisibleAsAWarning(unittest.TestCase):
    """A doubtful match has to look doubtful, not merely be described in passing."""

    def setUp(self):
        try:
            import tkinter as tk
        except ImportError as exc:
            raise AssertionError(f"tkinter is required and is missing: {exc}") from exc
        self.tk = tk
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

    def _card(self, confidence, score=0.0):
        archive = _ArchiveForCard(confidence, score)
        return GameCard(self.root, archive, lambda a: None)

    def _colours(self, card):
        """The pill's own colours, read back off the widget rather than off the source."""
        return card.conf.cget("bg"), card.conf.cget("fg")

    def test_a_high_confidence_match_is_green(self):
        card = self._card("High", 0.98)
        background, _ = self._colours(card)
        self.assertEqual(background, GREEN, "a High confidence match is not distinguished from a doubtful one")
        self.assertIn("High", card.conf.cget("text"))
        self.assertIn("0.98", card.conf.cget("text"),
                      "the score is not shown, so 'High' cannot be judged against 'Medium'")

    def test_a_medium_confidence_match_is_not_green(self):
        """The whole point of the pill. In grey text it was present and invisible as a warning."""
        card = self._card("Medium", 0.71)
        background, _ = self._colours(card)
        self.assertNotEqual(background, GREEN, "a match the app called Medium confidence looks certain")

    def test_an_unset_confidence_is_not_green_either(self):
        card = self._card("", 0.0)
        background, _ = self._colours(card)
        self.assertNotEqual(background, GREEN, "a match with no confidence reads as certain")
        self.assertIn("Unscored", card.conf.cget("text"))

    def test_an_unmatched_game_shows_no_confidence_at_all(self):
        """There is nothing to be confident about, and a pill would imply there was."""
        card = GameCard(self.root, _ArchiveForCard("", 0.0, found=False), lambda a: None)
        self.assertEqual(card.conf.cget("text"), "", "an unmatched game is shown a confidence pill")

    def test_a_skipped_game_is_also_left_without_the_pill(self):
        archive = _ArchiveForCard("Medium", 0.7)
        archive.decision.skipped = True
        card = GameCard(self.root, archive, lambda a: None)
        self.assertEqual(card.badge.cget("text"), "SKIPPED")
        self.assertEqual(card.conf.cget("text"), "",
                         "a skipped archive shows a confidence pill beside its SKIPPED badge")
        self.assertNotEqual(card.conf.cget("bg"), ORANGE,
                            "an emptied pill kept the warning fill, so a skipped game still looks doubtful")

# GREEN is imported from ui.palette rather than written out here. It was a literal in this file, holding a
# value from the generated catalog's CSS (`--good`) rather than the Tkinter theme's green, so it had drifted
# from the colour the widget actually paints and the assertion could only ever fail. palette.py is kept
# tkinter-free for exactly this reason: the audit, the theme and this test all read one definition, and a
# colour cannot pass review here while differing from what the UI draws.


class _Decision:
    category = "Idle"
    changed_from_suggestion = False
    skipped = False


class _ArchiveForCard:
    """The three attributes GameCard reads. Everything else it touches is defensive."""

    def __init__(self, confidence, score, found=True):
        self.steam = SteamMatch(found=found, name="Loop Miner" if found else "", appid="1",
                                confidence=confidence, score=score)
        self.decision = _Decision()
        self.display_name = "Loop Miner"
        self.extension = ".zip"
        self.path = Path("Loop Miner.zip")
        self.identity_key = identity_key("Loop Miner")


if __name__ == "__main__":
        unittest.main()


