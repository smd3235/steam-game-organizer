import unittest


import pytest
import json
import re
import shutil
import subprocess
import urllib.parse
import zipfile
from tempfile import TemporaryDirectory
from pathlib import Path
from core.logger import AppLogger
from services.catalog_service import CatalogService, sort_date
from services.banner_art import banner_svg, banner_data_uri
from core.constants import DEFAULT_CATEGORIES


def make_game(root, **metadata):
    game = root / "Simulation" / "Captain of Industry - 2024-01-01"
    game.mkdir(parents=True)
    (game / "Captain of Industry.zip").write_text("x")
    for name in ("header_image", "library_hero"):
        (game / f"Captain of Industry_{name}.jpg").write_bytes(b"\xff\xd8\xff\xdb" + b"0" * 2000)
    payload = {"appid": "1594320", "name": "Captain of Industry", "description": "desc", "release_date": "1 Jan, 2024", "genres": ["Simulation"]}
    payload.update(metadata)
    (game / ".game-info.json").write_text(json.dumps(payload))
    return game


@pytest.mark.notkinter
class TestCatalogService(unittest.TestCase):
    _make_game = staticmethod(make_game)

    def test_finds_multi_word_banner_asset_name(self):
        # Asset filenames like "<game>_header_image.jpg" contain underscores in the asset name itself;
        # the banner lookup must match the whole suffix, not just the text after the last underscore.
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root)
            service = CatalogService(AppLogger(root / "x.log"))
            prefix = service._asset_prefix(root / "Simulation" / "Captain of Industry - 2024-01-01", {"name": "Captain of Industry"})
            banner = service._find_banner(root / "Simulation" / "Captain of Industry - 2024-01-01", prefix)
            self.assertEqual(banner.name, "Captain of Industry_header_image.jpg")

    def test_card_markup_has_no_nested_anchor_tags(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root)
            paths = CatalogService(AppLogger(root / "x.log")).generate(root)
            for path in paths:
                text = path.read_text()
                # The tag must be matched as "<a" followed by whitespace or ">", otherwise "<article" also
                # matches and the check silently reports a nested anchor that is not there.
                self.assertIsNone(re.search(r"<a[\s>][^>]*>[^<]*<a[\s>]", text))
                # And confirm no anchor ever contains another anchor, regardless of intervening markup.
                for outer in re.findall(r"<a[\s>][^>]*>(.*?)</a>", text, re.S):
                    self.assertIsNone(re.search(r"<a[\s>]", outer))

    def test_installer_archive_gets_pre_extraction_installer_badge(self):
        # A zip that sniffs as a repack installer (setup.exe + setup-1.bin) gets the pre-extraction badge, with no
        # need for 7z on the machine - the zipfile branch of archive_installer_kind is used.
        with TemporaryDirectory() as d:
            root = Path(d)
            game = root / "Repacks" / "Airborne Empire [FitGirl Repack]"
            game.mkdir(parents=True)
            archive = game / "Airborne Empire [FitGirl Repack].zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("setup.exe", b"")
                handle.writestr("setup-1.bin", b"")
            (game / ".game-info.json").write_text(json.dumps({"appid": "123456", "name": "Airborne Empire", "description": "d", "release_date": "2020", "genres": ["Simulation"]}))
            paths = CatalogService(AppLogger(root / "x.log")).generate(root)
            html = " ".join(p.read_text(encoding="utf-8") for p in paths)
            self.assertIn("badge badge-install", html)
            self.assertIn("Installer</span>", html)
            # Pre-extraction only: no Unpacked/Needs-install state claim yet (match the span, not the CSS rule).
            self.assertNotIn('<span class="badge badge-done"', html)
            self.assertNotIn('<span class="badge badge-warn"', html)

    def test_long_description_with_html_entities_not_mangled_by_truncation(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root, description=('A & B <tag> "quoted" ' * 20))
            paths = CatalogService(AppLogger(root / "x.log")).generate(root)
            for path in paths:
                text = path.read_text()
                self.assertNotIn("&amp;lt;", text)
                self.assertIn("&lt;tag&gt;", text)

    def test_regenerating_deletes_previous_catalog_files(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root)
            # Left behind by earlier releases, so the next run has to clear them out.
            (root / "Game Library (Steam Deck) - 2026-01-01 000000.html").write_text("old")
            (root / "Game Library (Windows) - 2026-01-01 000000.html").write_text("old")
            service = CatalogService(AppLogger(root / "x.log"))
            service.generate(root)
            service.generate(root)
            service.generate(root)
            # One catalog, one name, no platform variants and no accumulating timestamped copies.
            self.assertEqual(sorted(p.name for p in root.glob("*.html")), ["Game Library.html"])

    def test_the_catalog_is_one_portable_file_for_both_platforms(self):
        # It used to be written twice, once per platform, with the cards pointing at different URLs. A single
        # page cannot know which machine is reading it, so the card is the https store page (which opens in a
        # browser everywhere) and the Steam client is an explicit second action.
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root)
            paths = CatalogService(AppLogger(root / "x.log")).generate(root)
            self.assertEqual([p.name for p in paths], ["Game Library.html"])
            text = paths[0].read_text()
            self.assertIn("https://store.steampowered.com/app/1594320/", text)
            self.assertIn("steam://store/1594320", text)
            self.assertNotIn("Steam Deck Edition", text)
            self.assertNotIn("Windows Edition", text)

    def test_a_chrome_launcher_is_written_only_when_no_browser_owns_html_files(self):
        # With no recorded text/html handler, double-clicking the catalog would not open a browser, so the
        # launcher is the fallback. Where a handler exists the catalog is enough, and an extra file in the
        # user's library root is pure clutter.
        #
        # It is a .url, not a .desktop. The original wrote a Linux desktop entry here, which Windows cannot
        # open at all - a launcher that exists but cannot be launched is worse than none, because it looks
        # like the job is handled. The .url is the format Windows actually opens, and it needs no command:
        # the shell resolves the URL through the same association check that produced it.
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root)
            CatalogService(AppLogger(root / "x.log")).generate(root, write_launcher=True)
            launcher = root / "Open Game Library.url"
            self.assertTrue(launcher.is_file(), f"no launcher written; found {sorted(p.name for p in root.iterdir())}")
            text = launcher.read_text()
            self.assertIn("[InternetShortcut]", text)
            self.assertIn("file://", text)
            self.assertFalse((root / "Open Game Library.desktop").exists(), "the dead Linux launcher is still sitting beside the working one")
            from urllib.parse import unquote

            self.assertIn("Game Library.html", unquote(text))
            # The machine already knows what to do with an .html file, so there is nothing to launch.
            (root / "Open Game Library.url").unlink()
            CatalogService(AppLogger(root / "x.log")).generate(root, write_launcher=False)
            self.assertFalse((root / "Open Game Library.url").exists(), "a launcher was written when the machine already opens HTML")

    def test_the_old_launcher_is_removed_once_the_catalog_opens_on_its_own(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root)
            old = root / "Open Game Library (Steam Deck).desktop"
            old.write_text("[Desktop Entry]\n")
            CatalogService(AppLogger(root / "x.log")).generate(root, write_launcher=True)
            self.assertFalse(old.exists(), "the superseded launcher was left in the library root")

    def test_catalog_open_folder_uses_the_protocol_handler_not_a_file_url(self):
        # A file:// directory link only shows a listing and is blocked in Chrome; it never opens the OS file
        # manager. The catalog uses the registered steamgameorganizer:// handler instead, which can hand a
        # folder path to Explorer. The user-facing label is "Open source" (library/archive folder).
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root)
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
            self.assertNotIn('href="file://', text)
            self.assertIn("steamgameorganizer://open-folder", text)
            self.assertIn('data-open-folder="steamgameorganizer://open-folder?', text)
            self.assertIn(">Open source<", text)

    def test_artwork_paths_are_relative_so_a_copied_library_still_shows_images(self):
        # Absolute artwork paths break the moment the Games folder is copied to another PC. Images and the
        # relative folder reference must both stay relative to the library root the catalog lives in.
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root)
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
            for reference in re.findall(r'(?:src="([^"]*)|url\(\'([^\']*))', text):
                value = next((v for v in reference if v), "")
                self.assertNotIn(str(root), value)
            self.assertIn('data-rel="Simulation/Captain of Industry - 2024-01-01"', text)

    def test_catalog_offers_a_copy_path_action(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root)
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
            self.assertIn("btn-copy", text)
            self.assertIn("data-copy=", text)
            self.assertIn(">Copy path<", text)
            # file:// pages are not a secure context, so the async clipboard API is unavailable there.
            self.assertIn("execCommand('copy')", text)

    def test_search_filter_has_a_haystack_for_every_card(self):
        # The client-side filter reads data-search; a card missing it would be unsearchable.
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root, genres=["Simulation", "Strategy"])
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
            cards = re.findall(r'<article class="card"[^>]*>', text)
            self.assertTrue(cards)
            self.assertTrue(all("data-search=" in card for card in cards))
            self.assertIn("captain of industry", text)

    def test_catalog_shows_the_archive_filename_present_in_the_folder(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root)
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
            self.assertIn("Captain of Industry.zip", text)


class TestCatalogBanners(unittest.TestCase):
    """The generated banner art and the per-banner jump-to-top control."""

    def test_every_category_gets_a_unique_deterministic_banner(self):
        # Two categories rendering identical art defeats the point of per-category banners, and art that
        # changes between regenerations makes the catalog look unstable. Both are checked over the real
        # category list plus the ad-hoc names users add themselves.
        names = list(DEFAULT_CATEGORIES) + ["Indie", "Simulation", "Early Access"]
        rendered = {banner_svg(name): name for name in names}
        self.assertEqual(len(rendered), len(set(names)), "two categories produced identical banner art")
        self.assertEqual(banner_svg("Adventure"), banner_svg("Adventure"), "banner art is not deterministic")
        self.assertNotEqual(banner_svg("Adventure"), banner_svg("Indie"))

    def test_banner_data_uri_is_embedded_safely_in_css(self):
        uri = banner_data_uri("Adventure")
        self.assertTrue(uri.startswith("data:image/svg+xml,"))
        # An unencoded '#' would terminate the url() early and drop the whole background image.
        self.assertNotIn("#", uri.split(",", 1)[1])
        self.assertNotIn('"', uri.split(",", 1)[1])
        self.assertNotIn(" ", uri.split(",", 1)[1])

    def test_every_category_header_has_a_jump_to_top_button(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            for folder, appid in (("Adventure", "11"), ("Strategy", "22"), ("RPG", "33")):
                game = root / folder / f"Game {appid} - 2020-01-01"
                game.mkdir(parents=True)
                (game / ".game-info.json").write_text(json.dumps({"appid": appid, "name": f"Game {appid}", "genres": ["G"]}))
                (game / f"Game {appid}.7z").write_bytes(b"7z\xbc\xaf\x27\x1c")
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
        self.assertEqual(text.count('class="jump-top"'), 3, "each category banner needs its own jump-to-top button")
        self.assertIn("querySelectorAll('.jump-top')", text, "jump-to-top buttons are not wired up")
        self.assertIn("toTopBtn.addEventListener('click',toTop)", text, "floating top button is not wired up")
        self.assertEqual(text.count('id="to-top"'), 1)

    def test_categories_without_art_still_get_a_banner(self):
        # No game in these folders has artwork, which used to produce a flat empty header.
        with TemporaryDirectory() as d:
            root = Path(d)
            for folder, appid in (("Adventure", "11"), ("Strategy", "22")):
                game = root / folder / f"Bare {appid} - 2020-01-01"
                game.mkdir(parents=True)
                (game / ".game-info.json").write_text(json.dumps({"appid": appid, "name": f"Bare {appid}"}))
                (game / f"Bare {appid}.7z").write_bytes(b"7z\xbc\xaf\x27\x1c")
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
        self.assertEqual(text.count("--gen:url("), 2, "artless categories lost their generated banner")
        self.assertEqual(text.count("--real:url("), 0, "no real art exists in this library")


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


class TestSetupButtonAndFallback(unittest.TestCase):
    """The setup button and the command beside it.

    A PC that has never run this app cannot click an Extract button at all - the handler is
    registered to open the app folder, so every link the page builds is refused against the app's
    own settings, which hold defaults. The button opens the wizard; the fallback beside it is the
    command a reader types into a terminal when the browser will not hand the link over.
    """

    def test_the_fallback_command_is_pasteable_in_cmd(self):
        """The fallback carries one backslash, not two.

        Written as a raw string with two, which is a doubled separator in the rendered page: a
        reader copies `runtime\\python.exe ...` and pastes it into cmd, where it is a path with a
        doubled separator and does not run. The command is meant to be typed in the app folder, so
        the relative form is right and the separator has to be single.
        """
        with TemporaryDirectory() as d:
            root = Path(d)
            make_game(root)
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
        match = re.search(r'<code class="setup-cmd"[^>]*>(.*?)</code>', text)
        self.assertIsNotNone(match, "the fallback command is not in the catalog")
        value = match.group(1)
        self.assertEqual(value, r"runtime\python.exe steam_game_organizer.py --setup", "the fallback command is not the one documented in the README")
        self.assertNotIn("\\\\", value, "the fallback command carries doubled backslashes and will not run in cmd")

    def test_the_setup_button_carry_the_page_boxes_with_it(self):
        """The link's query is rebuilt from the page's own boxes, so the wizard opens on them."""
        with TemporaryDirectory() as d:
            root = Path(d)
            make_game(root)
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
        link = re.search(r'<a class="btn btn-setup"[^>]*>', text)
        self.assertIsNotNone(link, "the Set up on this PC button is not in the catalog")
        self.assertIn("data-setup=", link.group(0))
        self.assertIn("steamgameorganizer://setup", text)
        # The script rebuilds the href from the boxes, so the page's own values seed the wizard.
        self.assertIn("setupLink.setAttribute", text)
        self.assertIn("params.push", text)


class TestReleaseDateSorting(unittest.TestCase):
    """Newest is meant to be newest release date, not newest added to the library.

    It was neither. The sort key came from stripping the non-digits off the date and taking the first four
    characters, so "Jun 24, 2026" became "6242" - the day - and the comparator was ascending, putting the
    oldest game first under a button labelled Newest.
    """

    def test_a_us_date_becomes_a_sortable_key(self):
        self.assertEqual(sort_date("Jun 24, 2026"), "20260624")

    def test_a_day_first_date_becomes_the_same_key_as_its_month_first_twin(self):
        self.assertEqual(sort_date("1 Jan, 2024"), sort_date("Jan 1, 2024"))

    def test_a_single_digit_day_is_padded_so_it_still_sorts(self):
        self.assertEqual(sort_date("May 5, 2026"), "20260505")
        self.assertLess(sort_date("May 5, 2026"), sort_date("May 6, 2026"))

    def test_the_day_is_not_mistaken_for_the_year(self):
        """The original bug, stated as a test: 24 comes first in the digits, not 2026."""
        self.assertTrue(sort_date("Jun 24, 2026").startswith("2026"))
        self.assertNotIn("24", sort_date("Jun 24, 2026")[:4])

    def test_a_year_only_date_lands_in_that_year(self):
        self.assertEqual(sort_date("2020"), "20200000")
        self.assertEqual(sort_date("Dec 2019"), "20191200")

    def test_a_missing_or_unreadable_date_sorts_last(self):
        self.assertEqual(sort_date(""), "00000000")
        self.assertEqual(sort_date(None), "00000000")
        self.assertEqual(sort_date("Unknown release date"), "00000000")

    def test_keys_sort_in_calendar_order(self):
        keys = [sort_date(d) for d in ("Jan 1, 2020", "Dec 31, 2020", "Feb 3, 2021", "Mar 15, 2019")]
        self.assertEqual(sorted(keys), ["20190315", "20200101", "20201231", "20210203"])

    def test_the_card_carries_the_parsed_date_not_the_raw_text(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            make_game(root, release_date="Jun 24, 2026")
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
        card = re.search(r'<article class="card"[^>]*>', text).group(0)
        self.assertIn('data-date="20260624"', card)
        self.assertNotIn("data-year", card)

    def test_the_year_banner_reports_a_real_range(self):
        """The same broken parser fed the year-range in the tagline, so it never rendered at all."""
        with TemporaryDirectory() as d:
            root = Path(d)
            make_game(root, release_date="Jun 24, 2019")
            # make_game always writes to one fixed folder, so a second game needs its own directory.
            other = root / "Simulation" / "Other Game - 2026-03-02"
            other.mkdir(parents=True)
            (other / "Other Game.zip").write_text("x")
            (other / ".game-info.json").write_text(json.dumps({"appid": "1", "name": "Other Game", "description": "d", "release_date": "Mar 2, 2026", "genres": ["Action"]}))
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
        self.assertIn("2019", text)
        self.assertIn("2026", text)

    def test_newest_and_largest_are_marked_descending(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            make_game(root)
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
        newest = re.search(r'<button[^>]*data-sort="date"[^>]*>', text).group(0)
        largest = re.search(r'<button[^>]*data-sort="size"[^>]*>', text).group(0)
        name = re.search(r'<button[^>]*data-sort="name"[^>]*>', text).group(0)
        self.assertIn('data-desc="1"', newest, "Newest sorted oldest first")
        self.assertIn('data-desc="1"', largest)
        self.assertNotIn("data-desc", name, "Name should stay alphabetical")

    def test_the_comparator_honours_the_descending_flag(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            make_game(root)
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
        self.assertIn("getAttribute('data-desc')==='1'", text, "the buttons must actually drive the comparator")
        self.assertIn("descending?-1:1", text)


class TestExtractDestinationBox(unittest.TestCase):
    """The destination is a free-text box, not a dropdown.

    There is no browser on the test machine, so instead of driving the script these pin the contract the script
    and the handler share: the box exists, the configured folders are suggestions rather than the only choices,
    and the link shape the script builds is one the handler actually accepts.
    """

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        make_game(self.root)
        self.folders = [self.root / "extract one", self.root / "extract two"]
        for folder in self.folders:
            folder.mkdir()
        service = CatalogService(AppLogger(self.root / "x.log"), extract_folders=self.folders)
        self.text = service.generate(self.root)[0].read_text()

    def test_the_destination_is_a_text_box(self):
        self.assertIn('id="extract-dest" type="text"', self.text)
        self.assertNotIn('<select id="extract-dest"', self.text)

    def test_the_box_starts_on_the_first_configured_folder(self):
        box = re.search(r'id="extract-dest"[^>]*value="([^"]*)"', self.text)
        self.assertIsNotNone(box, "the box must come pre-filled so a click works with no typing")
        self.assertEqual(box.group(1), str(self.folders[0]))

    def test_configured_folders_are_offered_as_suggestions(self):
        """A datalist, so they are one click away without being the only thing that can be typed."""
        self.assertIn('list="dest-choices"', self.text)
        choices = re.search(r'<datalist id="dest-choices">(.*?)</datalist>', self.text, re.S)
        self.assertIsNotNone(choices)
        for folder in self.folders:
            self.assertIn(f'value="{folder}"', choices.group(1))

    def test_the_choice_is_remembered_between_opens(self):
        self.assertIn("store('catalog-dest'", self.text)
        self.assertIn("savedDest=store('catalog-dest')", self.text)
        self.assertIn("if(savedDest) destBox.value=savedDest", self.text)

    def test_every_extract_link_carries_a_rewriteable_base(self):
        """data-extract holds the src-only link the script appends to.

        The script rebuilds each href from this attribute on every keystroke, so it has to stay the pristine
        base - if the script wrote its own output back here the destination would accumulate across typing.
        """
        bases = re.findall(r'data-extract="([^"]*)"', self.text)
        self.assertTrue(bases, "the page produced no extract links at all")
        for base in bases:
            self.assertIn("src=", base)
            self.assertNotIn("dest=", base)

    def test_the_link_the_script_builds_is_accepted_by_the_handler(self):
        """Closes the loop the markup test cannot: build the URL the script would, hand it to the handler.

        The script's only job here is string building, so if the shape it produces parses and lands where the
        user typed, the two halves agree even though no browser ran.
        """
        from urllib.parse import parse_qs, urlsplit

        typed = str(self.root / "a folder with spaces")
        base = re.findall(r'data-extract="([^"]*)"', self.text)[0].replace("&amp;", "&")
        link = base + "&dest=" + typed.replace(" ", "%20")
        query = parse_qs(urlsplit(link).query)
        self.assertEqual(query["dest"], [typed])
        archive = Path(query["src"][0])
        self.assertTrue(archive.is_file(), f"the page built a link to a file that is not there: {archive}")

    def test_a_path_typed_into_the_box_survives_being_written_into_a_url(self):
        """The whole reason the box is text: a folder with spaces and an ampersand in it still works."""
        from urllib.parse import parse_qs, urlsplit

        awkward = "/data/RPG & Co/extracted games"
        encoded = urllib.parse.quote(awkward, safe="")
        query = parse_qs(urlsplit(f"steamgameorganizer://extract?src=%2Flib%2Fa.7z&dest={encoded}").query)
        self.assertEqual(query["dest"], [awkward], "an ampersand in a typed folder split the query")


def _script_encoded_path(path):
    """The path the page's script would build, mirrored in Python.

    joinPath puts the library-relative folder under whatever is in the game folder box, and encodePath then
    escapes everything that would split the query string while leaving the separators and a Windows drive
    letter alone - which is exactly quote() with those two characters marked safe. No browser runs the suite,
    so this is how a link built in the page is handed to the handler that has to accept it.
    """
    return urllib.parse.quote(str(path), safe="/:")


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
            self.assertIn('data-rel="Simulation/Captain of Industry - 2024-01-01"', button)
            self.assertIn('data-archive="Captain of Industry.zip"', button)

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
        for index, (name, category, genres, art) in enumerate([("Captain of Industry", "Simulation", ["Simulation", "Strategy"], True), ("Hollow Signal", "Adventure", ["Horror", "Indie"], False)], 1):
            game = self.root / category / f"{name} - 2024-01-01"
            game.mkdir(parents=True)
            (game / f"{name}.zip").write_text("x")
            (game / ".game-info.json").write_text(json.dumps({"appid": str(1594320 + index), "name": name, "description": f"A quiet roguelike about {name}.", "release_date": "1 Jan, 2024", "genres": genres}))
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


class TestGamesWithoutASteamMatch(unittest.TestCase):
    """A game with no AppID still belongs on the shelf.

    `_read_game` ended with `if not appid: return None`, so any game folder whose `.game-info.json` had no
    AppID - or that had no `.game-info.json` at all - was dropped before it was ever rendered. That is a
    routine outcome for this library, not an edge case: the scan's own audit row reports "no Steam AppID" as
    one of the normal per-game results, and the folder is still sitting in the library either way.

    The cost was that the page quietly under-reported the library. A 10-game library rendered 8 cards, the
    hero said "8 games", and a category made up entirely of unmatched games disappeared from the rail
    altogether, because the category is only kept when it still has games in it. Nothing on the page said a
    game was missing; it simply was not there.

    The AppID is only needed for the two Steam actions. A game without one still has a name, artwork, an
    archive and a folder, so it still gets a card - just without the store link and the client link, and with
    a note saying why they are missing.
    """

    def setUp(self):
        parent = TemporaryDirectory()
        self.addCleanup(parent.cleanup)
        self.root = Path(parent.name) / "Games"
        fixtures = [
            ("Matched", "Simulation", {"appid": "1594320", "name": "Captain of Industry"}, True),
            ("No Appid", "Simulation", {"appid": "", "name": "Hollow Signal"}, True),
            ("Absent Key", "Adventure", {"name": "Quiet Harbor"}, False),
            ("No Metadata", "Adventure", None, False),
        ]
        for folder, category, metadata, art in fixtures:
            game = self.root / category / f"{folder} - 2024-01-01"
            game.mkdir(parents=True)
            (game / f"{folder}.zip").write_text("x")
            if metadata is not None:
                (game / ".game-info.json").write_text(json.dumps(metadata))
            if art:
                (game / f"{folder}_grid.jpg").write_bytes(b"\xff\xd8\xff\xd9" + b"0" * 400)
        self.text = CatalogService(AppLogger(self.root / "x.log")).generate(self.root)[0].read_text()

    def test_every_game_folder_on_disk_gets_a_card(self):
        cards = self.text.count('<article class="card"')
        self.assertEqual(cards, 4, f"{cards} cards for 4 game folders - a game with no Steam match was dropped")

    def test_the_hero_reports_the_number_of_games_that_are_actually_there(self):
        self.assertIn('<p class="tagline">4 games across', self.text, "the hero under-reports the library, so the missing games are invisible")
        self.assertIn('<span class="stat-value">4</span><span class="stat-label">Games</span>', self.text)

    def test_a_game_with_no_appid_says_so_instead_of_looking_broken(self):
        # On the badge, not on the phrase. The plain card link carries a title tooltip that also says "No Steam
        # match", so asserting the words alone was satisfied by the tooltip and never reached the badge at all.
        self.assertIn('<span class="badge badge-muted">No Steam match</span>', self.text, "a card with no store link has to show why, or it reads as a broken card")

    def test_no_card_points_at_a_store_page_with_no_appid_in_it(self):
        for url in re.findall(r'href="(https://store\.steampowered\.com[^"]*)"', self.text):
            self.assertRegex(url, r"/app/\d+/", f"a store link with no AppID in it: {url}")
        for url in re.findall(r'href="(steam://[^"]*)"', self.text):
            self.assertRegex(url, r"steam://store/\d+", f"a steam:// link with no AppID in it: {url}")

    def test_the_matched_game_keeps_both_steam_actions(self):
        # Dropping the AppID everywhere would "fix" the count by breaking the one card that can be opened.
        self.assertIn("https://store.steampowered.com/app/1594320/", self.text)
        self.assertIn("steam://store/1594320", self.text)

    def test_a_whitespace_only_title_falls_back_to_the_folder_name(self):
        # `"   "` is truthy, so `metadata.get('name') or <folder name>` kept it and rendered a card whose heading
        # is three spaces. The card exists but says nothing about which game it is, which on a shelf of 160 is the
        # same as the card being broken. A name that is only whitespace is no name.
        parent = TemporaryDirectory()
        self.addCleanup(parent.cleanup)
        root = Path(parent.name) / "Games"
        game = root / "Adventure" / "Quiet Harbor - 2024-01-01"
        game.mkdir(parents=True)
        (game / "Quiet Harbor.zip").write_text("x")
        (game / ".game-info.json").write_text(json.dumps({"appid": "1", "name": "   "}))
        text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
        headings = re.findall(r"<h3>([^<]*)</h3>", text)
        self.assertEqual(len(headings), 1, "the game lost its card")
        self.assertEqual(headings[0].strip(), "Quiet Harbor", f"a whitespace-only title rendered a blank card heading: {headings!r}")


def _rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def _contrast_ratio():
    """Reuse the app's own WCAG implementation so both palettes are judged by one formula."""
    import importlib.util

    path = Path(__file__).with_name("test_contrast.py")
    spec = importlib.util.spec_from_file_location("_app_contrast", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return lambda foreground, background: module.contrast(foreground, background)


if __name__ == "__main__":
    unittest.main()
