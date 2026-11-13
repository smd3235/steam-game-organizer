"""Extracted from tests/test_category_evidence.py.

    TestEvidenceShape was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
from core.constants import CategoryEvidence
from core.constants import UNSORTED_EVIDENCE
from core.constants import suggest_category_with_evidence


class TestEvidenceShape(unittest.TestCase):
    def test_a_description_win_names_the_rule_and_its_keywords(self):
        category, evidence = suggest_category_with_evidence(["Simulation"], "Alpha Forge", "Build and manage a factory with automation")
        self.assertEqual(category, "Automation")
        self.assertEqual(evidence, CategoryEvidence(chosen="Automation", score=104,
                                                    basis="description",
                                                    terms=("automation", "factory",
                                                             "build and manage a factory"),
                                                    runners_up=(("Simulation", 54),),
                                                    considered=2))

    def test_a_tag_win_is_a_rule_that_only_saw_tags_or_steam_categories(self):
        # An ignored genre leaves the field to the rule, so a hit that only the tags
        # knew about is reachable and must say so.
        category, evidence = suggest_category_with_evidence(["Indie"], "Whatever", "Nothing here", tags=["Farming"])
        self.assertEqual(category, "Farming")
        self.assertEqual(evidence, CategoryEvidence(chosen="Farming", score=38, basis="tag", terms=("farming",), runners_up=(), considered=1))

    def test_a_genre_win_carries_no_terms(self):
        category, evidence = suggest_category_with_evidence(["Simulation"], "Plain Title", "An ordinary description")
        self.assertEqual(category, "Simulation")
        self.assertEqual(evidence, CategoryEvidence(chosen="Simulation", score=54, basis="genre", terms=(), runners_up=(), considered=1))

    def test_a_genre_that_also_scored_as_a_rule_is_one_candidate(self):
        # "terrifying" feeds both the Horror rule and the Horror genre's own evidence
        # bonus. The genre pass out-scores the rule here, and the rule's score must not
        # resurface as a runner-up under the name that already won.
        category, evidence = suggest_category_with_evidence(["Horror"], "Haunted House", "A terrifying survival game")
        self.assertEqual(category, "Horror")
        self.assertEqual(evidence.basis, "genre")
        self.assertEqual(evidence.terms, ())
        self.assertEqual(evidence.score, 115)
        self.assertEqual(evidence.runners_up, ())
        self.assertEqual(evidence.considered, 1)

    def test_runners_up_are_capped_at_three_and_ordered_by_score_then_name(self):
        # Five rules tie at 85; Horror is the earliest in the rule table, so it wins and
        # the other four are runners-up, of which only three fit, by score then name.
        category, evidence = suggest_category_with_evidence(["Indie"], "Horror Puzzle Tactical Explore Stealth", "")
        self.assertEqual(category, "Horror")
        self.assertEqual(evidence.terms, ("horror",))
        self.assertEqual(evidence.runners_up, (("Adventure", 85), ("Puzzle", 85), ("Stealth", 85)), "runners_up must hold at most three, by score descending then name")
        self.assertEqual(evidence.considered, 5)

    def test_a_tie_is_won_by_the_rule_tested_first_and_lost_by_the_other(self):
        # Tidy Up and Puzzle both score 85; Tidy Up is earlier in the rule table, so it
        # wins and Puzzle is the runner-up at the same score.
        category, evidence = suggest_category_with_evidence(["Indie", "Casual"], "Cleaning Up The Puzzle Gallery", "Sort, sweep and tidy up a puzzle museum")
        self.assertEqual(category, "Tidy Up")
        self.assertEqual(evidence.basis, "description")
        self.assertEqual(evidence.terms, ("tidy up",))
        self.assertEqual(evidence.runners_up, (("Puzzle", 85), ("Casual", 19)))

    def test_every_path_to_unsorted_gives_the_same_fallback_evidence(self):
        for args in (([],), (None,), (["Indie"],), (["Indie", "Early Access"],)):
            with self.subTest(case=args):
                self.assertEqual(suggest_category_with_evidence(*args), ("Unsorted", UNSORTED_EVIDENCE))
        self.assertEqual(UNSORTED_EVIDENCE, CategoryEvidence(chosen="Unsorted", score=0, basis="fallback", terms=(), runners_up=(), considered=0))
