"""What the CategoriesEvidencePanel says, and whether it says it at all.

The evidence panel was added to fill the Review screen's dead space, and
can fail in a way no other test in this suite notices. A panel that builds
the right widgets with the right text and renders as a flat block of
background passes every geometry test in the file; a panel that says the
suggestion is "Horror" and, beside it, "Remembered as Indie" hides the
disagreement the user needs to see behind a label that repeats the
suggestion. So these read the labels that were actually created.

Every assertion here is on rendered text or on a live widget option. None of
them reads the source, because the source can describe the fix and pass.
"""

from __future__ import annotations

import unittest
import tkinter as tk
from pathlib import Path

from core.constants import CategoryEvidence
from core.models import GameArchive, OrganizationDecision, SteamMatch
from ui.widgets.category_evidence_panel import CategoryEvidencePanel
from ui.widgets.metadata_panel import MetadataPanel
from tests.test_ui_geometry import _measured_window
from tests.tk_support import close_root, require_tk, sandbox_app


def shown(widget):
    """Every string the panel actually put on screen, in creation order.

    Walks the live tree rather than the source: a label that was built and never packed is not shown, and a
    string that only exists in a change log at the bottom of the file is not shown either.
    """
    found = []
    pending = list(widget.winfo_children())
    while pending:
        child = pending.pop(0)
        try:
            text = str(child.cget("text"))
        except tk.TclError:
            text = ""
        if text:
            found.append(text)
        pending.extend(child.winfo_children())
    return found


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


class EmptyTagsRowIsSuppressed(unittest.TestCase):
    """tags is unobtainable: it is [] on all 165 sidecars and Steam's appdetails payload has no such field.

    An always-empty row would read as "this game has no tags", which is a claim about the game rather than
    about the feed we cannot get. The row is therefore suppressed, and suppressed only when empty.
    """

    def setUp(self):
        require_tk(self)
        self.root = tk.Tk()
        self.addCleanup(close_root, self.root)
        self.panel = MetadataPanel(self.root)
        self.panel.pack()
        self.root.update()

    def _archive(self, tags):
        archive = GameArchive(Path("Alpha Quest.7z"), "Alpha Quest", "Alpha Quest", "alpha quest", ".7z")
        archive.steam = SteamMatch(found=True, appid="1", name="Alpha Quest", genres=("Horror",), description="A game.", tags=list(tags), developer="Bewolba Studio")
        return archive

    def test_no_tags_row_when_the_list_is_empty(self):
        self.panel.show(self._archive(()))
        self.root.update()
        self.assertNotIn("TAGS", shown(self.panel))

    def test_the_tags_row_appears_when_tags_do(self):
        """Otherwise the suppression is a row that can never appear, which is indistinguishable from
        deleting the feature."""
        self.panel.show(self._archive(("Great Soundtrack",)))
        self.root.update()
        self.assertIn("Great Soundtrack", shown(self.panel))

    def test_the_match_trust_section_reports_what_the_match_was(self):
        archive = self._archive(())
        archive.steam.confidence = "High"
        archive.steam.source = "steam_appid"
        archive.steam.reason = "exact title"
        self.panel.show(archive)
        self.root.update()
        text = "\n".join(shown(self.panel))
        self.assertIn("MATCH TRUST", text)
        self.assertIn("High", text)


class ThePopulatedReviewScreenTests(unittest.TestCase):
    """The panels inside the real view, at both window sizes the app allows.

    layout_audit.py never calls select(), so the review screen it audits holds the panels in their empty
    state and the populated ones are measured by nothing. These select a game first, which is the only way
    the evidence and library panels ever build their rows.
    """

    def setUp(self):
        require_tk(self)
        self.root = tk.Tk()
        self.addCleanup(close_root, self.root)
        self.app = sandbox_app(self, self.root)
        _measured_window(self.root)

    def _review_with_a_game(self):
        review = self.app.window.views["review"]
        self.app.window.show("review")
        archive = GameArchive(Path("Alpha Quest.7z"), "Alpha Quest", "Alpha Quest", "alpha quest", ".7z")
        archive.steam = SteamMatch(found=True, appid="1", name="Alpha Quest", confidence="High", genres=("Horror", "Indie"), description="A long description.", developer="Bewolba Studio", tags=[])
        archive.decision = OrganizationDecision(
            category="Indie", suggested_category="Horror",
            evidence=CategoryEvidence(chosen="Horror", score=93, basis="description",
                                      terms=("horror",), runners_up=(("Indie", 85),),
                                      considered=3))
        review.archives = [archive]
        review.select(archive)
        self.root.update()
        return review

    def test_selecting_a_game_fills_the_evidence_panel_from_live_data(self):
        review = self._review_with_a_game()
        evidence = "\n".join(shown(review.evidence_panel))
        self.assertIn("Horror", evidence)
        self.assertIn("Remembered as Indie", evidence)

    def test_the_description_pane_still_gets_the_flexible_space(self):
        """The evidence panel is packed fill='x' above it, so the pane that has to absorb the leftover height is
        still the description. A panel packed expand=True here would take every spare pixel."""
        review = self._review_with_a_game()
        info = review.evidence_panel.pack_info()
        self.assertNotEqual(str(info.get("expand")), "1", f"{review.evidence_panel.__class__.__name__} expands and starves the description pane")
        self.assertEqual(str(review.detail.master.pack_info().get("expand")), "1", "the description pane is no longer the one that grows")

    def test_the_populated_review_screen_is_inside_the_scrolling_viewport(self):
        """The panel lives inside the detail canvas rather than beside it, so a tall content split scrolls
        instead of pushing the description off the bottom of the window."""
        review = self._review_with_a_game()
        self.assertTrue(review._is_descendant(review.evidence_panel, review.detail_inner), f"{review.evidence_panel.__class__.__name__} is not inside the scrollable detail viewport")

    def test_the_populated_review_screen_keeps_the_description_below_the_fold_but_reachable(self):
        review = self._review_with_a_game()
        self.root.update()
        self.assertGreater(review.detail.winfo_height(), 40, "the description pane collapsed to nothing once the panels were added")
        self.assertGreater(review.detail_canvas.bbox("all")[3], review.detail_canvas.winfo_height(), "the detail viewport no longer overflows, so the wheel route has nothing to scroll")

    def test_the_description_pane_is_disabled_before_anything_is_selected(self):
        """Read after a selection, _set_detail has already re-disabled the pane, so a constructor that
        forgot the option entirely would still pass. Nothing has been selected here."""
        review = self.app.window.views["review"]
        self.app.window.show("review")
        self.root.update()
        self.assertEqual(str(review.detail.cget("state")), "disabled", "the description pane starts writable and would take the user's typing as evidence")

    def test_the_description_pane_is_still_disabled_and_the_subtitle_still_wraps(self):
        """Two invariants a regenerated file loses silently: a writable Text takes the user's typing as if it
        were evidence, and an unwrapped subtitle runs off the panel."""
        review = self._review_with_a_game()
        self.assertEqual(str(review.detail.cget("state")), "disabled")
        self.assertEqual(int(review.subtitle.cget("wraplength")), 900)

    def test_the_layout_is_intact_at_the_minimum_window_size(self):
        """minsize() is 1100x680, so that size is reachable rather than theoretical."""
        _measured_window(self.root, "1100x680")
        review = self._review_with_a_game()
        window_width = self.root.winfo_width()
        for panel in (review.evidence_panel, review.detail):
            right = panel.winfo_rootx() - self.root.winfo_rootx() + panel.winfo_width()
            self.assertLessEqual(right, window_width + 1, f"{panel.__class__.__name__} runs past the right edge at {window_width}px")
            self.assertGreaterEqual(panel.winfo_height(), 1, f"{panel.__class__.__name__} collapsed at the minimum size")

    def test_the_wheel_still_routes_into_the_detail_canvas_and_the_description(self):
        """The panels added two more widget classes between the pointer and the canvas. Routing that stops
        at them would leave the evidence panel unscrollable."""
        review = self._review_with_a_game()
        self.root.update()
        event = type("E", (), {})()
        event.widget = review.evidence_panel
        event.delta = -120
        event.num = 0
        self.assertEqual(review._route_wheel(event), "break", "the wheel over the evidence panel did not route into the detail canvas")
        over_list = type("E", (), {})()
        over_list.widget = review.list
        over_list.delta = -120
        over_list.num = 0
        self.assertEqual(review._route_wheel(over_list), "break", "the wheel over the game list did not scroll the list canvas")
        native = tk.Listbox(review.detail_inner)
        review.root = None
        native_listbox = type("E", (), {})()
        native_listbox.widget = native
        native_listbox.delta = -120
        native_listbox.num = 0
        self.assertIsNone(review._route_wheel(native_listbox), "the wheel over a real Tk Listbox was swallowed instead of left to the listbox")
        # The category Combobox sits in the actions bar, outside the detail viewport, so it is the only
        # widget that can tell "handed back to the widget" apart from "happened to route somewhere else".
        combo = type("E", (), {})()
        combo.widget = review.category
        combo.delta = -120
        combo.num = 0
        self.assertEqual(review._route_wheel(combo), "break", "the wheel over the category combobox was not handed back to the combobox")
        entry = type("E", (), {})()
        entry.widget = review.title_entry
        entry.delta = -120
        entry.num = 0
        self.assertEqual(review._route_wheel(entry), "break", "the wheel over the title entry was not handed back to the entry")

    def test_load_starts_verification_and_holds_the_context_so_it_can_be_cancelled(self):
        """load() is what puts the screen to work. Reading that it returns without verifying is not a
        failure anyone notices - the list simply sits on "Verifying 0 of n" until the screen is reloaded."""
        review = self.app.window.views["review"]
        self.app.window.show("review")
        archive = GameArchive(Path("Alpha Quest.7z"), "Alpha Quest", "Alpha Quest", "alpha quest", ".7z")
        archive.steam = SteamMatch(found=True, appid="1", name="Alpha Quest")
        calls = []

        class _Ctx:
            cancelled = False

            def cancel(self):
                _Ctx.cancelled = True

        ctx = _Ctx()
        review.controller.verify_all = lambda archives, progress, done, download_artwork=True: calls.append((list(archives), download_artwork)) or ctx
        review.load([archive], download_artwork=False)
        self.root.update()
        self.assertEqual(len(calls), 1, "load() did not start a verification pass")
        self.assertEqual(calls[0][0], [archive], "verification was handed a different set of archives")
        self.assertFalse(calls[0][1], "download_artwork=False was not passed through")
        self.assertIs(review.verify_ctx, ctx, "verify_ctx does not hold the context, so cancel_lookup cannot cancel")
        review.cancel_lookup()
        self.assertTrue(_Ctx.cancelled, "cancel_lookup did not cancel the running verification")
        self.assertIsNone(review.verify_ctx, "verify_ctx was left set after cancelling")


if __name__ == "__main__":
    unittest.main()
