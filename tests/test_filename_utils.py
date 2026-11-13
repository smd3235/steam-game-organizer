# Replaced boring "Test Game" names with fun creative fictional names to make tests more engaging while avoiding intellectual property concerns. Full dated entry in CHANGELOG.md.

import unittest

import pytest
from utils.filename_utils import normalize_name, identity_key, version_key

# TestReleaseTagTitles extracted to tests\test_release_tag_titles.py — see that module for its definition.
from tests.test_release_tag_titles import TestReleaseTagTitles
# TestRegionLanguageTags extracted to tests\test_region_language_tags.py — see that module for its definition.
from tests.test_region_language_tags import TestRegionLanguageTags
# TestContentTags extracted to tests\test_content_tags.py — see that module for its definition.
from tests.test_content_tags import TestContentTags
@pytest.mark.notkinter
class TestFilename(unittest.TestCase):
    def test_archive_and_version(self):
        self.assertEqual(normalize_name("Nebula Forge v 0 8.zip"), "Nebula Forge")

    def test_camel_case_splits_without_a_hand_written_alias(self):
        # These three each needed an entry in a 52-row lookup table that spelled the official title out by hand. The
        # title now comes from the AppID the archive ships, so the only thing left to get right here is that the
        # filename still normalizes to something a Steam search can be built from.
        self.assertEqual(normalize_name("PixelShopSimulatorTokyo.zip"), "Pixel Shop Simulator Tokyo")
        self.assertEqual(normalize_name("SynthRide Repack 2026-03-15.zip"), "Synth Ride")
        self.assertEqual(normalize_name("Nebula Noodle 1-0.zip"), "Nebula Noodle")

    def test_a_tagged_name_needs_no_alias_either(self):
        self.assertEqual(normalize_name("NovaForgeFitGirl.zip"), "Nova Forge")
        self.assertEqual(normalize_name("FarmToTable10122.zip"), "Farm To Table")

    def test_identity(self):
        self.assertEqual(identity_key("Omega Online"), "omegaonline")

    def test_version(self):
        self.assertGreater(version_key("Game 1-10-0.zip"), version_key("Game 1-9-9.zip"))

    def test_version_handles_spaced_and_attached_releases(self):
        self.assertEqual(version_key("Game v 1 10.zip"), (1, 10))
        self.assertGreater(version_key("Game 20260808.zip"), version_key("Game 20250101.zip"))

class TestGluedDigitStamp(unittest.TestCase):
    """A date or build number welded onto the last word is packaging, not part of the name.

    It used to be handled by a hand-written alias per title, which meant a stamp nobody had written down became
    part of the game's name and the search was then built from it. Four digits is the floor on purpose: "Tunnel Runner2"
    and "Grand Crime City5" are titles, and a stamp is never that short."""

    GLUED = ["FarmToTable10122.zip", "Stellar Squirrel20260916", "Some Game20250101", "Glitch Racer v1.4.2.7z", "Neon District 2026-11-01.zip"]
    KEPT = ["Tunnel Runner2", "Grand Crime City5", "Bio-Hazard 2", "Space Racer Collection Series 20260916", "Some Game 20260916"]

    def test_a_glued_stamp_is_cut(self):
        for name in self.GLUED:
            self.assertFalse(normalize_name(name)[-1].isdigit(), f"{name} kept its stamp: {normalize_name(name)!r}")

    def test_a_short_or_spaced_number_is_kept(self):
        for name in self.KEPT:
            self.assertEqual(normalize_name(name), name, name)


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

class TestVersionSuffixStripping(unittest.TestCase):
    """A version suffix glued to the title with a separator other than whitespace - the form packagings such
    as '-v1-5-4' actually use - must still be stripped, or the Steam query stays versioned and returns nothing."""

    def test_a_hyphen_attached_version_is_stripped_before_steam_lookup(self):
        # Reproduces a real miss from the log: "Tavern-Manager-Simulator-v1-5-4" produced exactly one query
        # variant (the versioned filename) and the Steam store returned nothing. The clean title is appid 2756770.
        self.assertEqual(normalize_name("Tavern-Manager-Simulator-v1-5-4"), "Tavern-Manager-Simulator")
        self.assertEqual(normalize_name("Some-Game-v2-0-1"), "Some-Game")
