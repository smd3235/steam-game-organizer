"""Tests for core.safe_folder_name: filesystem-safe folder name generation.

safe_folder_name() turns arbitrary text into a single path component that is
safe on every filesystem: unsafe characters are replaced, Windows reserved
device names fall back to a default, trailing dots/spaces are stripped, and
names are truncated to 120 characters.
"""

import unittest

from core.safe_folder_name import safe_folder_name


class TestSafeFolderNameUnsafeCharacters(unittest.TestCase):
    """Unsafe filesystem characters are replaced with spaces."""

    def test_slash_and_backslash_become_spaces(self):
        self.assertEqual(safe_folder_name("a/b\\c"), "a b c")

    def test_colon_becomes_space(self):
        self.assertEqual(safe_folder_name("Settlements: Legacy"), "Settlements Legacy")

    def test_quote_and_angle_brackets_become_spaces(self):
        self.assertEqual(safe_folder_name('a<>"b|c'), "a b c")

    def test_multiple_unsafe_chars_collapse_to_one_space(self):
        self.assertEqual(safe_folder_name("a///b"), "a b")


class TestSafeFolderNameReservedNames(unittest.TestCase):
    """Windows reserved device names return the fallback."""

    def test_con_returns_fallback(self):
        self.assertEqual(safe_folder_name("CON"), "Extracted")

    def test_prn_returns_fallback(self):
        self.assertEqual(safe_folder_name("PRN"), "Extracted")

    def test_aux_returns_fallback(self):
        self.assertEqual(safe_folder_name("AUX"), "Extracted")

    def test_nul_returns_fallback(self):
        self.assertEqual(safe_folder_name("NUL"), "Extracted")

    def test_com1_through_com9_return_fallback(self):
        for i in range(1, 10):
            self.assertEqual(safe_folder_name(f"COM{i}"), "Extracted")

    def test_lpt1_through_lpt9_return_fallback(self):
        for i in range(1, 10):
            self.assertEqual(safe_folder_name(f"LPT{i}"), "Extracted")

    def test_reserved_names_are_case_insensitive(self):
        self.assertEqual(safe_folder_name("con"), "Extracted")
        self.assertEqual(safe_folder_name("Con"), "Extracted")


class TestSafeFolderNameTrimming(unittest.TestCase):
    """Trailing dots and spaces are stripped."""

    def test_trailing_dot_is_stripped(self):
        self.assertEqual(safe_folder_name("Game."), "Game")

    def test_trailing_space_is_stripped(self):
        self.assertEqual(safe_folder_name("Game "), "Game")

    def test_trailing_dot_and_space_are_stripped(self):
        self.assertEqual(safe_folder_name("Game. "), "Game")


class TestSafeFolderNameLengthLimit(unittest.TestCase):
    """Names longer than 120 characters are truncated."""

    def test_name_over_120_chars_is_truncated(self):
        long_name = "a" * 200
        result = safe_folder_name(long_name)
        self.assertEqual(len(result), 120)

    def test_name_exactly_120_chars_is_unchanged(self):
        name = "a" * 120
        self.assertEqual(safe_folder_name(name), name)


class TestSafeFolderNameEmptyAndFallback(unittest.TestCase):
    """Empty input returns the fallback; a custom fallback is honored."""

    def test_empty_string_returns_default_fallback(self):
        self.assertEqual(safe_folder_name(""), "Extracted")

    def test_none_returns_default_fallback(self):
        self.assertEqual(safe_folder_name(None), "Extracted")

    def test_whitespace_only_returns_default_fallback(self):
        self.assertEqual(safe_folder_name("   "), "Extracted")

    def test_custom_fallback_is_returned_for_reserved_name(self):
        self.assertEqual(safe_folder_name("CON", fallback="MyGame"), "MyGame")

    def test_custom_fallback_is_returned_for_empty(self):
        self.assertEqual(safe_folder_name("", fallback="MyGame"), "MyGame")


if __name__ == "__main__":
    unittest.main()
