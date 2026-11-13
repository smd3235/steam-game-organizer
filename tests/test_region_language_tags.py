"""Extracted from tests/test_filename_utils.py.

    TestRegionLanguageTags was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
from utils.filename_utils import normalize_name
from utils.filename_utils import identity_key


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
        ("Empire Universalis IV", "Empire Universalis IV"),
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
