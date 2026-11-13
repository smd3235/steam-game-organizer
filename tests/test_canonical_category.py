"""Tests for core.canonical_category: category name normalization.

canonical_category() maps a raw category string through CATEGORY_ALIASES and
returns the canonical form. Unknown strings pass through unchanged. Matching is
case-insensitive and whitespace-tolerant.
"""

import unittest

# Imported first to resolve the circular import chain:
# core.canonical_category -> core.constants -> core.suggest_category_with_evidence -> core.canonical_category
import steam_game_organizer  # noqa: F401

from core.canonical_category import canonical_category


class TestCanonicalCategoryKnownAliases(unittest.TestCase):
    """Known category aliases map to their canonical form."""

    def test_indie_maps_to_indie(self):
        self.assertEqual(canonical_category("Indie"), "Indie")

    def test_indie_passes_through_unchanged(self):
        # "indie" is in IGNORED_AUTO_CATEGORIES, not CATEGORY_ALIASES, so it passes through.
        self.assertEqual(canonical_category("indie"), "indie")
        self.assertEqual(canonical_category("INDIE"), "INDIE")

    def test_indie_with_whitespace_normalizes(self):
        self.assertEqual(canonical_category("  Indie  "), "Indie")
        self.assertEqual(canonical_category("InDiE"), "InDiE")

    def test_simulation_maps_to_simulation(self):
        self.assertEqual(canonical_category("Simulation"), "Simulation")

    def test_action_maps_to_action(self):
        self.assertEqual(canonical_category("Action"), "Action")

    def test_fps_maps_to_first_person_shooter(self):
        self.assertEqual(canonical_category("FPS"), "First-Person Shooter")

    def test_idle_aliases_map_to_idle(self):
        for alias in ("idle", "IDLE", "clicker", "incremental game", "  Idle Game  "):
            self.assertEqual(canonical_category(alias), "Idle")

    def test_survival_aliases_map_to_survival(self):
        self.assertEqual(canonical_category("survivors"), "Survival")
        self.assertEqual(canonical_category("survival crafting"), "Survival")
        self.assertEqual(canonical_category("voxel"), "Survival")

    def test_tidy_up_aliases_map_to_tidy_up(self):
        self.assertEqual(canonical_category("cleanup"), "Tidy Up")
        self.assertEqual(canonical_category("decluttering"), "Tidy Up")
        self.assertEqual(canonical_category("tiding"), "Tidy Up")


class TestCanonicalCategoryUnknownPassesThrough(unittest.TestCase):
    """Unknown category strings pass through unchanged (normalized whitespace)."""

    def test_unknown_string_passes_through(self):
        self.assertEqual(canonical_category("Weird Genre"), "Weird Genre")

    def test_unknown_string_is_whitespace_normalized(self):
        self.assertEqual(canonical_category("  Weird   Genre  "), "Weird Genre")

    def test_empty_string_passes_through(self):
        self.assertEqual(canonical_category(""), "")

    def test_none_becomes_empty_string(self):
        self.assertEqual(canonical_category(None), "")

    def test_whitespace_only_becomes_empty_string(self):
        self.assertEqual(canonical_category("   "), "")


if __name__ == "__main__":
    unittest.main()
