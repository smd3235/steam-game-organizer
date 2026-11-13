"""Extracted from tests/test_catalog_library.py.

    TestCatalogPresentation was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
import json
import re
from tempfile import TemporaryDirectory
from pathlib import Path
from core.logger import AppLogger
from tests.test_catalog_library import _contrast_ratio
from tests.test_catalog_library import _rgb
from tests.test_catalog_library import make_game
from services.catalog_service import CatalogService


class TestCatalogPresentation(unittest.TestCase):
    """The redesigned shell: themes, rail, motion and the fallback artwork behind a missing banner.

    None of this can be checked by looking at a picture, because no browser exists in the sandbox or on the
    host to render the file. These tests assert the things a screenshot would otherwise be the only way to
    notice: that both themes paint, that every colour is legible on the surface it sits on, and that the
    client-side script is actually wired to the markup the generator emits.
    """

    _make_game = staticmethod(make_game)

    @classmethod
    def setUpClass(cls):
        cls.css = CatalogService._css(CatalogService.__new__(CatalogService))

    def _theme_vars(self, prefix):
        # Neither theme block contains a nested brace, so the first closing brace ends it.
        steam_match = re.search(re.escape(prefix) + r"(.*?)\}", self.css, re.S)
        self.assertIsNotNone(steam_match, f"no {prefix} block in the stylesheet")
        # Keys come back without the leading dashes so a pair can be named as ('text','panel').
        return {name.lstrip("-"): value for name, value in re.findall(r"(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", steam_match.group(1))}

    def test_both_themes_define_the_same_custom_properties(self):
        dark = self._theme_vars(":root{color-scheme:dark;")
        light = self._theme_vars(':root[data-theme="light"]')
        # A property defined in only one theme silently falls back to nothing in the other, which is how a
        # panel ends up transparent against the page. The sets have to match exactly.
        self.assertEqual(set(dark), set(light))

    def test_no_declaration_depends_on_color_mix(self):
        # color-mix() arrived in Chromium 111. An engine without it drops the whole declaration, which for a
        # page background means the browser's default white behind near-white text, and for background-clip
        # text means an invisible heading. The catalogue is opened from whatever the machine has, so every
        # colour it paints has to be spelled out literally.
        declarations = [line for line in self.css.split("\n") if "color-mix" in line and not line.lstrip().startswith(("/*", "*"))]
        self.assertEqual(declarations, [], "these declarations would be dropped on pre-111 Chromium")

    def test_every_custom_property_used_is_declared(self):
        declared = set(re.findall(r"(--[a-z0-9-]+):", self.css))
        # --gen and --real are set inline on each category header, so they are not theme properties.
        used = set(re.findall(r"var\((--[a-z0-9-]+)", self.css)) - {"--gen", "--real"}
        self.assertEqual(sorted(used - declared), [], "a var() has no declaration to resolve to")

    def test_every_custom_property_declared_is_used(self):
        used = set(re.findall(r"var\((--[a-z0-9-]+)", self.css))
        declared = set(re.findall(r"(--[a-z0-9-]+):\s*(?:#|rgba?\()", self.css))
        self.assertEqual(sorted(declared - used), [], "a colour is declared but never painted")

    def test_text_colours_are_legible_on_every_surface_in_both_themes(self):
        contrast = _contrast_ratio()
        # (label, foreground, surface, minimum). Body copy is AA normal text at 4.5:1; the heading gradient's
        # weakest stop is large bold type, so it only has to clear 3:1.
        pairs = [
            ("text on page", "text", "bg", 4.5),
            ("text on card", "text", "panel", 4.5),
            ("muted on page", "muted", "bg", 4.5),
            ("muted on card", "muted", "panel", 4.5),
            ("muted on chip", "muted", "chip", 4.5),
            ("dim on page", "dim", "bg", 4.5),
            ("dim on card", "dim", "panel", 4.5),
            ("accent on page", "accent", "bg", 4.5),
            ("accent on card", "accent", "panel", 4.5),
            ("good on page", "good", "bg", 4.5),
            ("good on card", "good", "panel", 4.5),
            ("warn on card", "warn", "panel", 4.5),
            ("active sort label", "accent-ink", "accent", 4.5),
            ("heading gradient stop", "title-fade", "bg", 3.0),
        ]
        failures = []
        for theme, selector in (("dark", ":root{color-scheme:dark;"), ("light", ':root[data-theme="light"]{')):
            variables = self._theme_vars(selector)
            for label, fg, bg, minimum in pairs:
                ratio = contrast(_rgb(variables[fg]), _rgb(variables[bg]))
                if ratio < minimum:
                    failures.append(f"{theme}: {label} is {ratio:.2f}:1, needs {minimum}:1")
        self.assertEqual(failures, [])

    def test_a_game_without_art_gets_generated_art_instead_of_a_grey_block(self):
        # A missing banner used to render a flat placeholder reading "No artwork", which on a shelf of cards
        # looked broken rather than art-free. The card now uses the same deterministic banner the categories
        # use, keyed on the game's own name.
        with TemporaryDirectory() as d:
            root = Path(d)
            artless = root / "Adventure" / "Bare - 2020-01-01"
            artless.mkdir(parents=True)
            (artless / ".game-info.json").write_text(json.dumps({"appid": "11", "name": "Bare"}))
            (artless / "Bare.7z").write_bytes(b"7z\xbc\xaf\x27\x1c")
            with_art = root / "RPG" / "Painted - 2020-01-01"
            with_art.mkdir(parents=True)
            (with_art / "Painted_header_image.jpg").write_bytes(b"\xff\xd8\xff\xdb" + b"0" * 2000)
            (with_art / ".game-info.json").write_text(json.dumps({"appid": "22", "name": "Painted"}))
            (with_art / "Painted.7z").write_bytes(b"7z\xbc\xaf\x27\x1c")
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
        cards = re.findall(r'<img loading="lazy" src="([^"]+)"', text)
        self.assertEqual(len(cards), 2)
        self.assertTrue(cards[0].startswith("data:image/svg+xml,"), "artless card fell back to a placeholder block")
        self.assertTrue(cards[1].startswith("RPG/"), "real artwork must still be referenced as a relative file")
        self.assertNotIn("No artwork", text)

    def test_cards_carry_precomputed_sort_keys(self):
        # Sorting runs in the browser over 166 cards, so it must not parse the rendered date or size text to
        # do it: a text change would silently reorder the library.
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root)
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
        card = re.search(r'<article class="card"[^>]*>', text).group(0)
        for key in ("data-name", "data-date", "data-size"):
            self.assertIn(key, card, f"{key} is missing, so sorting falls back to parsing text")
        self.assertIn("grid.appendChild(card)", text, "cards must be reordered inside their own grid")
        self.assertIn("grid.children", text)

    def test_the_theme_toggle_is_switchable_and_remembered(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root)
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
        self.assertIn('<html lang="en" data-theme="dark">', text, "the page needs a theme to start from")
        self.assertIn('id="theme"', text)
        # Dark is the default rather than the OS preference: the generated banner art and card scrims are tuned
        # for it, and following the desktop's light mode served the palette the page was least designed for.
        self.assertIn("setTheme(saved||'dark')", text, "dark must be the default, with the stored choice ahead of it")
        self.assertNotIn("(prefers-color-scheme: light)", text, "the OS preference must not override dark")
        self.assertIn("store('catalog-theme',name)", text, "the chosen theme is not remembered")
        self.assertIn("setAttribute('aria-pressed'", text, "the toggle must report its state to assistive tech")
        # localStorage throws outright on a file:// page in some browsers rather than returning null.
        self.assertIn("try{", text)

    def test_the_rail_and_the_scroll_spy_agree_with_the_markup(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            for folder, appid in (("Adventure", "11"), ("Strategy", "22"), ("RPG", "33")):
                game = root / folder / f"Game {appid} - 2020-01-01"
                game.mkdir(parents=True)
                (game / ".game-info.json").write_text(json.dumps({"appid": appid, "name": f"Game {appid}", "genres": ["RPG"]}))
                (game / f"Game {appid}.7z").write_bytes(b"7z\xbc\xaf\x27\x1c")
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
        section_ids = set(re.findall(r'<section id="([^"]+)"', text))
        targets = set(re.findall(r'class="toc-link" href="#([^"]+)"', text))
        self.assertEqual(section_ids, targets, "the sidebar links and the sections must be the same set")
        self.assertTrue(section_ids)
        # The spy highlights whichever section has passed the reading line, so a stale or absent target would
        # silently leave the sidebar highlighting nothing at all.
        self.assertIn("link.getAttribute('data-target')===active.id", text)

    def test_genre_chips_are_derived_from_the_library_and_narrow_the_grid(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root, genres=["Simulation", "Strategy"])
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
        self.assertIn('data-genre="Strategy"', text, "a chip needs to know which genre it filters")
        self.assertIn("querySelectorAll('.chip-btn')", text, "the chips are not wired up")
        self.assertIn("card.getAttribute('data-genre')", text)
        # An empty section must collapse rather than leave its banner above zero cards.
        self.assertIn("sec.classList.toggle('is-empty',!any)", text)

    def test_a_filtered_out_catalog_still_explains_itself(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root)
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
        self.assertIn('id="empty"', text, "a search with no hits needs to say so")
        self.assertIn("empty.hidden=shown!==0", text)

    def test_the_keyboard_shortcuts_the_footer_advertises_are_implemented(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root)
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
        # The footer names "/" and Escape, so a reader who follows it must actually get somewhere.
        self.assertIn("event.key==='/'", text)
        self.assertIn("event.key==='Escape'", text)
        self.assertIn("search.focus()", text)

    def test_the_rail_collapses_instead_of_eating_a_narrow_window(self):
        # The page is read in a narrow window, which is narrower than the rail plus a usable
        # card grid. Below the breakpoint the sidebar has to become a horizontal strip, not stay a column.
        self.assertIn("@media (max-width:1080px)", self.css)
        collapse = self.css.split("@media (max-width:1080px){", 1)[1]
        self.assertIn("grid-template-columns:minmax(0,1fr)", collapse, "the rail must stop taking a column")
        self.assertIn("position:static", collapse, "a sticky rail has no room to stick")
        self.assertIn(".genres,.tags-nav,.rail-help{display:none;}", collapse, "the genre rail, the tag rail and the help disclosure are what fold first")

    def test_reduced_motion_and_print_are_honoured(self):
        self.assertIn("@media (prefers-reduced-motion:reduce)", self.css)
        self.assertIn("@media print", self.css)
