# Fictional Steam game data used only in tests to avoid intellectual property concerns.
# These names and AppIDs do not correspond to any real Steam products.

import unittest
from unittest.mock import patch
from services.steam_service import SteamService
from core.logger import AppLogger


class TestSteamQueryVariants(unittest.TestCase):
    """Guard that _query_variants generates the variants needed to match archives whose
    filenames carry scene packaging against Steam's store index."""

    def setUp(self):
        from pathlib import Path
        self.service = SteamService(AppLogger(Path("test.log")), mock=True)

    def _variants(self, title):
        """Call _query_variants with a no-op context so no network calls are made."""
        class NoopCtx:
            def checkpoint(self):
                pass
        return self.service._query_variants(title, title, NoopCtx())

    def test_region_tag_variant_is_generated(self):
        # MULTI5 at the end should be stripped so the bare title is queried.
        variants = self._variants("Deep Vault MULTI5")
        self.assertIn("Deep Vault", variants, variants)
        # MULTI13, USA, EUR, JAP, PAL, NTSC all stripped
        for tag in ("MULTI13", "USA", "EUR", "JAP", "JPN", "PAL", "NTSC"):
            variants = self._variants(f"Some Game {tag}")
            self.assertIn("Some Game", variants, f"{tag} variant missing: {variants}")

    def test_region_tag_only_stripped_from_end(self):
        # A region-like word mid-string is not stripped.
        variants = self._variants("USA Games Collection")
        self.assertIn("USA Games Collection", variants, variants)
        self.assertNotIn("Games Collection", variants, variants)

    def test_the_reorder_variant_is_generated(self):
        # "X, The" -> "The X" so Steam indexes the title under "The X".
        variants = self._variants("Ancient Tomes, The")
        self.assertIn("The Ancient Tomes", variants, variants)
        variants = self._variants("Ring, The")
        self.assertIn("The Ring", variants, variants)

    def test_the_reorder_only_for_trailing_the(self):
        # "The" mid-string is not reordered.
        variants = self._variants("The Ancient Tomes")
        self.assertIn("The Ancient Tomes", variants, variants)
        self.assertNotIn("Ancient Tomes The", variants, variants)

    def test_combined_packaging_variants(self):
        # Region tag + crack tag combined should still yield the bare title variant.
        variants = self._variants("Deep Vault CRACKED BY GROUP MULTI5")
        self.assertIn("Deep Vault", variants, variants)

    def test_variants_are_deduplicated(self):
        variants = self._variants("Some Game")
        self.assertEqual(len(variants), len(set(v.lower() for v in variants)), variants)

    def test_original_title_is_always_first(self):
        variants = self._variants("Deep Vault MULTI5")
        self.assertEqual(variants[0], "Deep Vault MULTI5", variants)
