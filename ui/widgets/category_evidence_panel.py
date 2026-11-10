import tkinter as tk
from ui.theme import ACCENT_HI, MUTED, ORANGE, PANEL, TEXT
from core.constants import CategoryEvidence


class CategoryEvidencePanel(tk.Frame):
    """Why the suggested category is what it is, in words the evidence can actually support.

    Rendered against `decision.suggested_category`, never `decision.category`: a remembered decision replaces
    `category` while `suggested_category` keeps the freshly computed value, and the whole point of the panel
    is that a person can see the two disagree. Labelling the winner "(suggested: <the same name>)" made the
    disagreement invisible, which is the one thing this panel exists to prevent.
    """

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=PANEL, **kw)
        self.heading = tk.Label(self, text="WHY THIS CATEGORY", bg=PANEL, fg=ACCENT_HI, font=("TkDefaultFont", 9, "bold"))
        self.heading.pack(anchor="w", padx=14, pady=(10, 4))
        self.body = tk.Frame(self, bg=PANEL)
        self.body.pack(fill="x", padx=14, pady=(0, 6))

    def _line(self, text, fg=TEXT, bold=False, pady=0):
        tk.Label(self.body, text=text, bg=PANEL, fg=fg, font=("TkDefaultFont", 8, "bold" if bold else "normal"), justify="left", anchor="w").pack(fill="x", pady=pady)

    def show(self, decision, genres=()):
        for w in self.body.winfo_children():
            w.destroy()
        evidence = getattr(decision, "evidence", None)
        remembered = getattr(decision, "category", "") or ""
        suggested = getattr(decision, "suggested_category", "") or ""
        if not isinstance(evidence, CategoryEvidence):
            self._line("No category reasoning was recorded for this game.", fg=MUTED)
            return
        self._line(f"{suggested or evidence.chosen}  ·  {self._reason(evidence, genres)}", bold=True)
        if suggested and remembered and remembered != suggested:
            self._line(f"Remembered as {remembered} instead. The suggestion is recomputed from this game, and the remembered value is what an earlier decision stored.", fg=ORANGE, pady=(2, 0))
        if evidence.runners_up:
            tied = {name for name, points in evidence.runners_up if points == evidence.score}
            self._line("Also considered: " + ", ".join(f"{name} (tied)" if name in tied else name for name, _ in evidence.runners_up), fg=MUTED, pady=(2, 0))
        if not evidence.considered:
            self._line("No other category scored at all.", fg=MUTED, pady=(2, 0))

    @staticmethod
    def _reason(evidence, genres):
        """One phrase naming the rule that won, and for a description or tag win the terms that fired.

        A `genre` win has no terms by design - the genre is the reason - so it is not rendered as missing data.
        A runner-up holding the winner's score is a tie, and is labelled as one rather than shown as a loss.
        """
        if evidence.basis == "fallback":
            return "nothing matched, so this is the fallback"
        if evidence.basis == "genre":
            listed = ", ".join(str(value).strip() for value in (genres or ()) if str(value or "").strip())
            return f"decided by the Steam genres: {listed}" if listed else "decided by the Steam genre list"
        if not evidence.terms:
            return f"won on {evidence.basis}"
        where = "in the description" if evidence.basis == "description" else "in the tags or Steam categories"
        return "matched " + ", ".join(f'"{term}"' for term in evidence.terms) + " " + where
