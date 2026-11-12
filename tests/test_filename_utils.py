# Replaced boring "Test Game" names with fun creative fictional names to make tests more engaging while avoiding intellectual property concerns. Full dated entry in CHANGELOG.md.

import unittest


import pytest
from utils.filename_utils import normalize_name, identity_key, version_key


@pytest.mark.notkinter
class TestFilename(unittest.TestCase):
    def test_archive_and_version(self):
        self.assertEqual(normalize_name("Alpha Forge v 0 8.zip"), "Alpha Forge")

    def test_camel_case_splits_without_a_hand_written_alias(self):
        # These three each needed an entry in a 52-row lookup table that spelled the official title out by hand. The
        # title now comes from the AppID the archive ships, so the only thing left to get right here is that the
        # filename still normalizes to something a Steam search can be built from.
        self.assertEqual(normalize_name("GachaCapsuleShopSimulatorAkihabara.zip"), "Gacha Capsule Shop Simulator Akihabara")
        self.assertEqual(normalize_name("MySummerCar Repack 2024-01-02.zip"), "My Summer Car")
        self.assertEqual(normalize_name("Nebula Noodle 1-0.zip"), "Nebula Noodle")

    def test_a_tagged_name_needs_no_alias_either(self):
        self.assertEqual(normalize_name("NovaForgeFitGirl.zip"), "Nova Forge")
        self.assertEqual(normalize_name("FarmToTable10122.zip"), "Farm To Table")

    def test_identity(self):
        self.assertEqual(identity_key("Epsilon Online"), "epsilononline")

    def test_version(self):
        self.assertGreater(version_key("Game 1-10-0.zip"), version_key("Game 1-9-9.zip"))

    def test_version_handles_spaced_and_attached_releases(self):
        self.assertEqual(version_key("Game v 1 10.zip"), (1, 10))
        self.assertGreater(version_key("Game 20260808.zip"), version_key("Game 20250101.zip"))


class TestGluedDigitStamp(unittest.TestCase):
    """A date or build number welded onto the last word is packaging, not part of the name.

    It used to be handled by a hand-written alias per title, which meant a stamp nobody had written down became
    part of the game's name and the search was then built from it. Four digits is the floor on purpose: "Portal2"
    and "GTA5" are titles, and a stamp is never that short."""

    GLUED = ["FarmToTable10122.zip", "Stellar Squirrel20260916", "Some Game20250101", "Star Miner v1.4.2.7z", "Cyber City 2026-11-01.zip"]
    KEPT = ["Portal2", "GTA5", "Half-Life 2", "Supercar Collection Simulator Racing Series 20260916", "Some Game 20260916"]

    def test_a_glued_stamp_is_cut(self):
        for name in self.GLUED:
            self.assertFalse(normalize_name(name)[-1].isdigit(), f"{name} kept its stamp: {normalize_name(name)!r}")

    def test_a_short_or_spaced_number_is_kept(self):
        for name in self.KEPT:
            self.assertEqual(normalize_name(name), name, name)


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
        ("Mars Attracts-Steam RIP com", "Mars Attracts"),
        ("Nivalis Nights-Steam RIP com", "Nivalis Nights"),
        ("Sintopia-Steam RIP com", "Sintopia"),
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
        ("MySummerCar Repack 2024-01-02.zip", "My Summer Car"),
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
        ("Star Trek - Outposts Unknown [FitGirl Repack]", "Star Trek - Outposts Unknown"),
        # Build stamps glued to the end of the title are stripped: alphanumeric mixes like "123r6s"
        # or "2v10112645585273", and short pure digits like "10" or "171".
        ("LawnMowingSimulator2v10112645585273", "Lawn Mowing Simulator"),
        ("Kingdoms and Castles 123r6s", "Kingdoms and Castles"),
        ("Fell&Sell171", "Fell&Sell"),
        ("Iron&Steel171", "Iron&Steel"),
    ]

    # A hyphen inside the title itself is kept, because it is part of the name: "Half-Life 2" must not become
    # "Half Life 2", and that would rename a real folder to chase cosmetics. What matters for these spellings is
    # that the two forms collapse to one identity, so the Steam cache is hit and the game is grouped once.
    TAGGED_HYPHENATED = [("Brave-New-Wonders-SteamRip-com", "Brave-New-Wonders"), ("Some-Game-SteamRIP.com", "Some-Game"), ("Rust-RELOADED", "Rust")]

    REAL = [
        "Stellar Empires", "Time Travelers", "Half-Life 2", "Fear Itself", "Dome Keeper",
        "Portal 2", "Rust", "Baldurs Gate 3", "Republique", "Perfect Vermin",
        "The Idle Class", "Multiplayer", "Portable Heirloom",
        # Short alphanumeric codes that look like build stamps but are part of the title:
        "Crystal Realms 7x9b",
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
        self.assertEqual(normalize_name("Alpha Forge v 0 8.zip"), "Alpha Forge")
        self.assertEqual(normalize_name("GachaCapsuleShopSimulatorAkihabara.zip"), "Gacha Capsule Shop Simulator Akihabara")
        self.assertEqual(normalize_name("Nebula Noodle 1-0.zip"), "Nebula Noodle")
        # Outliers found scanning every .7z in E:\Game Installers:
        # a glued 8-digit date is stripped; a glued version glommed onto a huge number keeps only the letter-prefix.
        self.assertEqual(normalize_name("ElderScrolls20260107"), "Elder Scrolls")
        self.assertEqual(normalize_name("NovaLauncher2v10112645585273"), "Nova Launcher")

    def test_real_world_outlier_patterns_are_normalized_correctly(self):
        # Edge cases found in the live library that must not be collapsed, mangled, or dropped:
        # camelCase with no separator keeps trailing digits; a camelCase lowercase run is not split;
        # odd casing splits at every uppercase boundary; an ampersand and trailing digits survive;
        # a mixed alphanumeric suffix survives; a single digit after a dot becomes " <digit>";
        # hyphenated words stay whole; a digit-hyphen-word stays whole.
        self.assertEqual(normalize_name("ZetaQuestAdventure10"), "Zeta Quest Adventure")
        self.assertEqual(normalize_name("TidyuptheCity10"), "Tidyupthe City")
        self.assertEqual(normalize_name("My.Weird.MORE.Title"), "My Weird MORE Title")
        self.assertEqual(normalize_name("Iron&Steel171"), "Iron&Steel")
        self.assertEqual(normalize_name("Crystal Realms 7x9b"), "Crystal Realms 7x9b")
        self.assertEqual(normalize_name("Toast.1"), "Toast 1")
        self.assertEqual(normalize_name("Omega Factor-X"), "Omega Factor-X")
        self.assertEqual(normalize_name("Deep Vault 7-Gold"), "Deep Vault 7-Gold")


class TestRegionLanguageTags(unittest.TestCase):
    """Region and language tags appended by scene releases are packaging, not the game title.

    These always sit at the end of a filename and describe which language pack or region the
    release targets. Steam's store indexes under the bare title, so the tag has to go before the
    lookup, or every region-tagged archive gets a separate Steam query that returns nothing.
    """

    TAGGED = [
        ("Some Game MULTI5", "Some Game"),
        ("Some Game MULTI6", "Some Game"),
        ("Some Game MULTI7", "Some Game"),
        ("Some Game MULTI8", "Some Game"),
        ("Some Game MULTI9", "Some Game"),
        ("Some Game MULTI10", "Some Game"),
        ("Some Game MULTI11", "Some Game"),
        ("Some Game MULTI12", "Some Game"),
        ("Some Game MULTI13", "Some Game"),
        ("Some Game USA", "Some Game"),
        ("Some Game EUR", "Some Game"),
        ("Some Game JAP", "Some Game"),
        ("Some Game JPN", "Some Game"),
        ("Some Game PAL", "Some Game"),
        ("Some Game NTSC", "Some Game"),
        ("Deep Vault MULTI5.zip", "Deep Vault"),
        ("Quantum Drift EUR.7z", "Quantum Drift"),
        ("Void Runners JAP.rar", "Void Runners"),
        # Combined with other packaging: region tag comes after release-group, both stripped.
        ("Some Game-TENOKE MULTI5", "Some Game"),
        ("Some Game FitGirl Repack USA", "Some Game"),
        # Region tags are only stripped from the end, never mid-string:
        ("USA Games Collection", "USA Games Collection"),
        ("Europa Universalis IV", "Europa Universalis IV"),
    ]

    REAL = [
        # Titles that contain a region-like word as ordinary English and must survive untouched.
        "Multiplayer Madness", "Portable Heirloom", "Universal Soldier",
        "Multi Theft Auto", "United States History", "Eurydice",
    ]

    def test_region_tag_is_stripped(self):
        for tagged, clean in self.TAGGED:
            self.assertEqual(normalize_name(tagged), clean, tagged)

    def test_english_words_are_not_region_tags(self):
        for title in self.REAL:
            self.assertEqual(normalize_name(title), title, title)

    def test_region_tag_and_clean_twin_share_one_identity(self):
        for tagged, clean in self.TAGGED:
            self.assertEqual(identity_key(tagged), identity_key(clean), tagged)


class TestCrackTags(unittest.TestCase):
    """Crack-by credits at the end of a filename describe the release group, not the game.

    "Cracked by GROUP", "CRACK: GROUP", "CRACKED-BY GROUP" are all stripped from the end
    so the Steam lookup is built from the bare title.
    """

    TAGGED = [
        ("Some Game CRACKED BY GROUP", "Some Game"),
        ("Some Game CRACK: GROUP", "Some Game"),
        ("Some Game CRACKED-BY GROUP", "Some Game"),
        ("Some Game CRACKED", "Some Game"),
        ("Deep Vault CRACKED BY CODEX", "Deep Vault"),
        ("Void Runners CRACK: TENOKE", "Void Runners"),
        ("Neon Overdrive CRACKED-BY RELOADED", "Neon Overdrive"),
        # Combined with region tag: both stripped.
        ("Some Game CRACKED BY GROUP MULTI5", "Some Game"),
    ]

    def test_crack_tag_is_stripped(self):
        for tagged, clean in self.TAGGED:
            self.assertEqual(normalize_name(tagged), clean, tagged)

    def test_crack_tag_and_clean_twin_share_one_identity(self):
        for tagged, clean in self.TAGGED:
            self.assertEqual(identity_key(tagged), identity_key(clean), tagged)


class TestContentTags(unittest.TestCase):
    """Content / packaging words at the end of a filename describe the release, not the game.

    UNCUT, UNCENSORED, GORE, NODVD, NO-DVD, FIX, STANDALONE, ONLY are all stripped from the
    end so the Steam lookup is built from the bare title.
    """

    TAGGED = [
        ("Some Game UNCUT", "Some Game"),
        ("Some Game UNCENSORED", "Some Game"),
        ("Some Game GORE", "Some Game"),
        ("Some Game NODVD", "Some Game"),
        ("Some Game NO-DVD", "Some Game"),
        ("Some Game FIX", "Some Game"),
        ("Some Game STANDALONE", "Some Game"),
        ("Some Game ONLY", "Some Game"),
        ("Deep Vault UNCUT.zip", "Deep Vault"),
        ("Quantum Drift NODVD.7z", "Quantum Drift"),
        # Combined with region tag: both stripped.
        ("Some Game UNCUT MULTI5", "Some Game"),
        ("Some Game FIX USA", "Some Game"),
    ]

    REAL = [
        # Titles that contain a content-tag-like word as ordinary English and must survive untouched.
        "Fix It Felix", "Only Connect", "Standalone Stories",
    ]

    def test_content_tag_is_stripped(self):
        for tagged, clean in self.TAGGED:
            self.assertEqual(normalize_name(tagged), clean, tagged)

    def test_english_words_are_not_content_tags(self):
        for title in self.REAL:
            self.assertEqual(normalize_name(title), title, title)


class TestVersionSuffixStripping(unittest.TestCase):
    """A version suffix glued to the title with a separator other than whitespace - the form packagings such
    as '-v1-5-4' actually use - must still be stripped, or the Steam query stays versioned and returns nothing."""

    def test_a_hyphen_attached_version_is_stripped_before_steam_lookup(self):
        # Reproduces a real miss from the log: "Tavern-Manager-Simulator-v1-5-4" produced exactly one query
        # variant (the versioned filename) and the Steam store returned nothing. The clean title is appid 2756770.
        self.assertEqual(normalize_name("Tavern-Manager-Simulator-v1-5-4"), "Tavern-Manager-Simulator")
        self.assertEqual(normalize_name("Some-Game-v2-0-1"), "Some-Game")
