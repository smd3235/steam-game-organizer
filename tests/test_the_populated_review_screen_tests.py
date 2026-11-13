"""Extracted from tests/test_review_context_panels.py.

    ThePopulatedReviewScreenTests was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
import tkinter as tk
from pathlib import Path
from core.constants import CategoryEvidence
from core.models import GameArchive
from core.models import OrganizationDecision
from core.models import SteamMatch
from tests.test_ui_geometry import _measured_window
from tests.tk_support import close_root
from tests.tk_support import require_tk
from tests.test_review_context_panels import shown
from tests.tk_support import sandbox_app


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
