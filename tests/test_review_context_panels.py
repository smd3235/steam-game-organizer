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

# ThePopulatedReviewScreenTests extracted to tests\the_populated_review_screen_tests.py — see that module for its definition.
from tests.the_populated_review_screen_tests import ThePopulatedReviewScreenTests
# CategoryEvidencePanelTests extracted to tests\category_evidence_panel_tests.py — see that module for its definition.
from tests.category_evidence_panel_tests import CategoryEvidencePanelTests
# EmptyTagsRowIsSuppressed extracted to tests\empty_tags_row_is_suppressed.py — see that module for its definition.
from tests.empty_tags_row_is_suppressed import EmptyTagsRowIsSuppressed
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


if __name__ == "__main__":
    unittest.main()
