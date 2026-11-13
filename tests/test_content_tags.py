"""Extracted from tests/test_filename_utils.py.

    TestContentTags was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
from utils.filename_utils import normalize_name


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
