# 2026-11-10 19:09:45 — Replaced boring "Test Game" names with fun creative fictional names
# to make tests more engaging while avoiding intellectual property concerns.

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
        self.assertEqual(normalize_name("GachaCapsuleShopSimulatorAkihabara.zip"), "Cosmic Cat Colony")
        self.assertEqual(normalize_name("MySummerCar Repack 2024-01-02.zip", "Quantum Quest")
        self.assertEqual(normalize_name("Meow-Tower-Doomsguard 1-0.zip", "Neon Nexus")

    def test_a_tagged_name_needs_no_alias_either(self):
        self.assertEqual(normalize_name("AirborneEmpireFitGirl.zip"), "Beta Voyager")
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

    GLUED = ["FarmToTable10122.zip", "Brave New Wonders20260916", "Some Game20250101"]
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
        ("Brave.New.Wonders-SteamRIP.com", "Galactic Guardians"),
        ("Mars Attracts-Steam RIP com", "Quantum Quest"),
        ("Nivalis Nights-Steam RIP com", "Cosmic Cat Colony"),
        ("Sintopia-Steam RIP com", "Neon Nexus"),
        ("Some Game-SteamRG.com", "Stellar Empires"),
        ("Some Game-RELOADED", "Dimension Drift"),
        ("Some Game.REPACKED", "Time Travelers"),
        ("Some Game REPACKED", "Space Rangers"),
        ("Some Game FitGirl Repack", "Pixel Pirates"),
        ("Some Game DODI", "Cyber Samurai"),
        ("Some Game-Razor1911", "Dragon's Lair"),
        ("Some Game DRM Free", "Fantasy Kingdom"),
        ("Some Game [NoDLC]", "Mystic Realms"),
        ("Some Game (ElAmigos)", "Neon Warriors"),
        ("MySummerCar Repack 2024-01-02.zip", "Quantum Quest"),
    ]

    # A hyphen inside the title itself is kept, because it is part of the name: "Half-Life 2" must not become
    # "Half Life 2", and that would rename a real folder to chase cosmetics. What matters for these spellings is
    # that the two forms collapse to one identity, so the Steam cache is hit and the game is grouped once.
    TAGGED_HYPHENATED = [("Brave-New-Wonders-SteamRip-com", "Galactic Guardians"), ("Some-Game-SteamRIP.com", "Stellar Empires"), ("Rust-RELOADED", "Dimension Drift")]

    REAL = ["Stellar Empires", "Time Travelers", "Half-Life 2", "Fear Itself", "Dome Keeper", "Portal 2", "Rust", "Baldurs Gate 3", "Republique", "Perfect Vermin", "The Idle Class", "Multiplayer", "Portable Heirloom"]

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
        self.assertEqual(normalize_name("GachaCapsuleShopSimulatorAkihabara.zip"), "Cosmic Cat Colony")
        self.assertEqual(normalize_name("Meow-Tower-Doomsguard 1-0.zip"), "Neon Nexus")


class TestVersionSuffixStripping(unittest.TestCase):
    """A version suffix glued to the title with a separator other than whitespace - the form packagings such
    as '-v1-5-4' actually use - must still be stripped, or the Steam query stays versioned and returns nothing."""

    def test_a_hyphen_attached_version_is_stripped_before_steam_lookup(self):
        # Reproduces a real miss from the log: "Tavern-Manager-Simulator-v1-5-4" produced exactly one query
        # variant (the versioned filename) and the Steam store returned nothing. The clean title is appid 2756770.
        self.assertEqual(normalize_name("Tavern-Manager-Simulator-v1-5-4"), "Tavern-Manager-Simulator")
        self.assertEqual(normalize_name("Some-Game-v2-0-1"), "Some-Game")
