"""Extracted from tests/test_filename_utils.py.

    TestReleaseTagTitles was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
from utils.filename_utils import normalize_name
from utils.filename_utils import identity_key


class TestReleaseTagTitles(unittest.TestCase):
    """A release-group tag is packaging, not the game, and the app has to cut it off before it can look the game up.

    This class guards that rule from both sides, because the two mistakes look identical in a diff and undo each
    other:

      TAGGED - spellings that really do ship, each with the title it should collapse to. When a folder arrives with
               a tag this list has never seen, add the row here rather than loosening the pattern: a spelling
               nobody wrote down is exactly how twelve Steam lookups failed in one run.
      REAL   - titles carrying a tag-like word as ordinary English. These must survive untouched. They are what
               stops the rule being made greedier to fix the first table, which is how "Some Game Multiplayer"
               became "Some Game player" and "Game Properly Done" became "Game ly Done" - the old pattern matched
               with no trailing boundary at all.

    The invariant under both tables is the same: a tagged folder name must normalize to precisely what its clean
    twin normalizes to, so the two spellings collapse to one identity key and the Steam cache is hit."""

    TAGGED = [
        ("Stellar.Squirrel-SteamRIP.com", "Stellar Squirrel"),
        ("Mars Drifts-Steam RIP com", "Mars Drifts"),
        ("Nebula Nights-Steam RIP com", "Nebula Nights"),
        ("Sun Topia-Steam RIP com", "Sun Topia"),
        ("Some Game-SteamRG.com", "Some Game"),
        ("Some Game-RELOADED", "Some Game"),
        ("Some Game.REPACKED", "Some Game"),
        ("Some Game REPACKED", "Some Game"),
        ("Some Game FitGirl Repack", "Some Game"),
        ("Some Game DODI", "Some Game"),
        ("Some Game-Razor1911", "Some Game"),
        ("Some Game DRM Free", "Some Game"),
        ("Some Game [NoDLC]", "Some Game"),
        ("Some Game (ElAmigos)", "Some Game"),
        ("SynthRide Repack 2026-03-15.zip", "Synth Ride"),
        # Packaged styles copied from real downloaded archives (fictional titles, real packaging shapes):
        # release-group tags, dot-separated titles, version stamps, and date stamps.
        ("Nova Forge-SteamRIP.com", "Nova Forge"),
        ("Quantum Drift-TENOKE", "Quantum Drift"),
        ("Void Runners.FitGirl Repack", "Void Runners"),
        ("Neon Overdrive-DODI", "Neon Overdrive"),
        ("Iron Clad-RELOADED", "Iron Clad"),
        ("Deep Vault [NoDLC]", "Deep Vault"),
        ("Rift Walker (ElAmigos)", "Rift Walker"),
        ("Synth Wave DRM Free", "Synth Wave"),
        ("Pixel Raiders-Razor1911", "Pixel Raiders"),
        ("Astral Plains-SteamRG.com", "Astral Plains"),
        # Outlier styles found scanning every .7z in E:\Game Installers:
        # a bracketed release group after a hyphenated title keeps the hyphen; a trailing -RUNE is cut;
        # dot-separated titles with a trailing -RUNE collapse like any other tag.
        ("Galactic Frontier - Unknown Regions [FitGirl Repack]", "Galactic Frontier - Unknown Regions"),
        ("Star Horizon - Outposts Unknown [FitGirl Repack]", "Star Horizon - Outposts Unknown"),
        # Build stamps glued to the end of the title are stripped: alphanumeric mixes like "123r6s"
        # or "2v10112645585273", and short pure digits like "10" or "171".
        ("MegaMartTycoon2v10112645585273", "Mega Mart Tycoon"),
        ("Dungeon Realms 123r6s", "Dungeon Realms"),
        ("Pixel & Chase171", "Pixel & Chase"),
        ("Steam & Solder171", "Steam & Solder"),
    ]

    # A hyphen inside the title itself is kept, because it is part of the name: "Cyber-War 2" must not become
    # "Cyber War 2", and that would rename a real folder to chase cosmetics. What matters for these spellings is
    # that the two forms collapse to one identity, so the Steam cache is hit and the game is grouped once.
    TAGGED_HYPHENATED = [("Cosmic-New-Wonders-SteamRip-com", "Cosmic-New-Wonders"), ("Some-Game-SteamRIP.com", "Some-Game"), ("Quartz-RELOADED", "Quartz")]

    REAL = [
        "Astral Empires", "Chrono Travelers", "Cyber-War 2", "Dread Itself", "Crater Keeper",
        "Gateway 2", "Quartz", "Fantasy Gate 3", "Liberte", "Perfect Pests",
        "The Idle Class", "Multiplayer", "Portable Heirloom",
        # Short alphanumeric codes that look like build stamps but are part of the title:
        "Void Realms 7x9b",
    ]

    def test_every_tagged_spelling_collapses_to_its_clean_title(self):
        for tagged, clean in self.TAGGED:
            self.assertEqual(normalize_name(tagged), clean, tagged)

    def test_a_hyphen_inside_the_title_survives_but_still_collapses(self):
        for tagged, clean in self.TAGGED_HYPHENATED:
            self.assertEqual(identity_key(tagged), identity_key(clean), tagged)

    def test_a_tagged_name_and_its_clean_twin_share_one_identity(self):
        # The Steam cache, dedupe and category grouping all key off this, so a mismatch means one game is looked up
        # twice under two spellings and grouped as two games.
        for tagged, clean in self.TAGGED:
            self.assertEqual(identity_key(tagged), identity_key(clean), tagged)

    def test_ordinary_english_is_not_mistaken_for_a_tag(self):
        for title in self.REAL:
            self.assertEqual(normalize_name(title), title, title)

    def test_a_real_version_suffix_still_goes(self):
        # The tag rule cuts from the tag onwards, so it must not swallow a version that belongs to the title.
        self.assertEqual(normalize_name("Nebula Forge v 0 8.zip"), "Nebula Forge")
        self.assertEqual(normalize_name("PixelShopSimulatorTokyo.zip"), "Pixel Shop Simulator Tokyo")
        self.assertEqual(normalize_name("Nebula Noodle 1-0.zip"), "Nebula Noodle")
        # Outliers found scanning every .7z in E:\Game Installers:
        # a glued 8-digit date is stripped; a glued version glommed onto a huge number keeps only the letter-prefix.
        self.assertEqual(normalize_name("TimeScrolls20260107"), "Time Scrolls")
        self.assertEqual(normalize_name("MegaLauncher2v10112645585273"), "Mega Launcher")

    def test_real_world_outlier_patterns_are_normalized_correctly(self):
        # Edge cases found in the live library that must not be collapsed, mangled, or dropped:
        # camelCase with no separator keeps trailing digits; a camelCase lowercase run is not split;
        # odd casing splits at every uppercase boundary; an ampersand and trailing digits survive;
        # a mixed alphanumeric suffix survives; a single digit after a dot becomes " <digit>";
        # hyphenated words stay whole; a digit-hyphen-word stays whole.
        self.assertEqual(normalize_name("ZetaQuestAdventure10"), "Zeta Quest Adventure")
        self.assertEqual(normalize_name("TidyuptheCity10"), "Tidyupthe City")
        self.assertEqual(normalize_name("My.Weird.MORE.Title"), "My Weird MORE Title")
        self.assertEqual(normalize_name("Steam & Solder171"), "Steam & Solder")
        self.assertEqual(normalize_name("Galaxy Realms 7x9b"), "Galaxy Realms 7x9b")
        self.assertEqual(normalize_name("Toast.1"), "Toast 1")
        self.assertEqual(normalize_name("Omega Factor-X"), "Omega Factor-X")
        self.assertEqual(normalize_name("Deep Mine 7-Gold"), "Deep Mine 7-Gold")
