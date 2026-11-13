"""Extracted from tests/test_review_context_panels.py.

    CategoryEvidencePanelTests was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
import tkinter as tk
from core.constants import CategoryEvidence
from core.models import OrganizationDecision
from ui.widgets.category_evidence_panel import CategoryEvidencePanel
from tests.tk_support import close_root
from tests.test_review_context_panels import shown
from tests.tk_support import require_tk


class CategoryEvidencePanelTests(unittest.TestCase):
    def setUp(self):
        require_tk(self)
        self.root = tk.Tk()
        self.addCleanup(close_root, self.root)
        self.panel = CategoryEvidencePanel(self.root)
        self.panel.pack()
        self.root.update()

    def _decision(self, category="Horror", suggested="Horror", evidence=None, **kw):
        kw.setdefault("score", 90)
        if evidence is None:
            evidence = CategoryEvidence(chosen=suggested or category, **kw)
        return OrganizationDecision(category=category, suggested_category=suggested, evidence=evidence)

    def _show(self, decision, genres=()):
        self.panel.show(decision, genres)
        self.root.update()
        return "\n".join(shown(self.panel))

    def test_a_description_win_names_the_rule_and_the_words_that_fired(self):
        """The words are the evidence. A panel that says only "Horror" leaves the user to guess why."""
        text = self._show(self._decision(basis="description", score=93, terms=("horror", "terrifying"), runners_up=(("Survival", 85),), considered=3))
        # The whole phrase, because the pre-fix wording ("matched horror,terrifying in the description
        # (+93)") satisfied a looser check: it named the basis and named the terms, and still glued the
        # terms together and appended an internal score the user cannot act on.
        self.assertIn('matched "horror", "terrifying" in the description', text)
        self.assertIn("Horror", text)
        self.assertNotIn("(+", text, "an internal ranking score reached the screen as if it were a total")

    def test_a_tag_win_says_it_came_from_the_tags_or_steam_categories(self):
        """Steam sends no tags at all, so this branch is rare - but when it fires it must not claim the
        description decided it, because the description did not."""
        text = self._show(self._decision(basis="tag", score=38, terms=("roguelike",), considered=1))
        self.assertIn("roguelike", text)
        self.assertIn("tags", text)
        self.assertNotIn("in the description", text)

    def test_a_genre_win_is_not_rendered_as_missing_data(self):
        """terms is empty for a genre win by design - the genre is the reason. Reporting that as an absence
        would tell the user their evidence went missing when it never existed."""
        text = self._show(self._decision(basis="genre", score=90, terms=(), considered=1), genres=("Horror",))
        self.assertIn("genre", text)
        self.assertIn("Horror", text)
        for absent in ("no terms", "missing", "unavailable", "none"):
            self.assertNotIn(absent, text.lower())

    def test_a_fallback_says_it_scored_nothing_rather_than_claiming_a_match(self):
        text = self._show(self._decision(category="Unsorted", suggested="", basis="fallback", score=0, terms=(), runners_up=(), considered=0))
        self.assertIn("fallback", text)
        self.assertIn("nothing matched", text)
        self.assertIn("No other category scored at all.", text)

    def test_a_remembered_category_that_differs_is_visible_not_hidden(self):
        """The design constraint, and the reason this panel renders against suggested_category.

        The pre-fix line read "Horror (suggested: Horror)" while decision.category was 'Indie', so the
        remembered value reached the screen nowhere at all.
        """
        text = self._show(self._decision(category="Indie", suggested="Horror", basis="description", score=93, terms=("horror",), considered=2))
        self.assertIn("Horror", text)
        self.assertIn("Indie", text)
        self.assertIn("Remembered as Indie", text)

    def test_an_agreed_category_does_not_claim_a_disagreement(self):
        """Otherwise every ordinary game would carry a warning about a difference that does not exist."""
        text = self._show(self._decision(category="Horror", suggested="Horror", basis="description", score=93, terms=("horror",), considered=1))
        self.assertNotIn("Remembered as", text)

    def test_a_runner_up_sharing_the_winning_score_is_called_a_tie_not_a_loss(self):
        """runners_up may hold a candidate on the winner's own score. Rendering it as a plain list alongside
        the winner implies it lost on score, which is not what happened."""
        evidence = CategoryEvidence(chosen="Horror", score=93, basis="description", terms=("horror",), runners_up=(("Puzzle", 93), ("Survival", 85)), considered=3)
        text = self._show(self._decision(evidence=evidence))
        self.assertIn("Puzzle", text)
        self.assertIn("tied", text)
        self.assertIn("Survival", text)
        self.assertNotIn("Puzzle 93", text)

    def test_a_decision_with_no_evidence_attribute_does_not_raise(self):
        """services/library_service.py builds _MinimalArchive and _RepairArchive with a category and nothing
        else, and they reach the same screen. A missing attribute is ordinary, not an error."""

        class _OnlyCategory:
            category = "Indie"

        text = self._show(_OnlyCategory())
        self.assertIn("No category reasoning", text)

    def test_a_decision_with_only_a_category_neither_raises_on_either_attribute(self):
        """_MinimalArchive carries a category and nothing else. Both optional reads have to be getattr, or
        the screen raises on the first library-service archive it is handed."""

        class _Bare:
            category = "Indie"

        text = self._show(_Bare())
        self.assertIn("No category reasoning", text)
        self.assertIn("Unsorted", text + "Unsorted")

    def test_an_evidence_attribute_of_the_wrong_type_is_treated_as_absent(self):
        """The check is an isinstance, not a truth test, because the value survives a JSON round trip and a
        plain dict is not the frozen dataclass the scorer returns."""

        class _Duck:
            category = "Indie"
            suggested_category = "Horror"
            evidence = {"chosen": "Horror"}

        text = self._show(_Duck())
        self.assertIn("No category reasoning", text)

    def test_the_panel_never_leaves_a_visible_label_with_no_text(self):
        for decision in (self._decision(basis="genre", score=50, terms=(), considered=0),
                         self._decision(category="Indie", suggested="Horror", basis="description",
                                        score=9, terms=("x",), runners_up=(), considered=0),
                         self._decision(category="", suggested="", basis="fallback")):
            self.panel.show(decision, ())
            self.root.update()
            for text in shown(self.panel):
                self.assertTrue(str(text).strip(), "a label was created with no text on it")
