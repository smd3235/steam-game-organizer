"""Extracted from ui/theme.py.

    PhaseTimeline was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

from __future__ import annotations

import customtkinter as ctk
import time
from customtkinter import CTkFrame  # CTkLabel imported earlier but never used (dropped to clear ruff F401)
from utils.formatting import human_duration
from ui.palette import BORDER, GREEN, MUTED, ORANGE, PANEL, PANEL3, RED, ACCENT_HI

# Pill colours mapping from group name to (bg, fg)
PILL_COLOURS = {
    "good": (GREEN, "#071b12"),
    "warn": (ORANGE, "#211505"),
    "bad": (RED, "#260a10"),
    "muted": (PANEL3, MUTED),
    "accent": (ACCENT_HI, "white"),
}


def pill(parent, text, kind="accent"):
    """Pill-shaped label matching the HTML catalog's data-tip callout."""
    bg, fg = PILL_COLOURS.get(kind, PILL_COLOURS["accent"])
    return ctk.CTkLabel(parent, text=text, fg_color=bg, text_color=fg, corner_radius=12,
                        font=("TkDefaultFont", 8, "bold"), padx=9, pady=4)


class PhaseTimeline(ctk.CTkFrame):
    """A row of stage chips showing every step of a run at once, so the current step is obvious and finished
    steps stay visible instead of being replaced by the newest line of text.
    This is what makes a long run legible: 'Converting 4 of 30' is a single overwritable sentence, while the
    timeline shows which of the six phases are done, which is running, and which were skipped entirely.
    Each chip also carries how long its stage took. A stage that always takes 30s reads very differently from
    one that suddenly takes eight minutes, which is usually the first sign of a problem worth stopping for.
    """

    STATE_KIND = {"pending": "muted", "active": "accent", "done": "good", "skipped": "muted", "failed": "bad", "skipped_soft": "muted"}

    def __init__(self, parent, phases, bg=PANEL, show_timing=True, **kw):
        super().__init__(parent, fg_color=bg, **kw)
        self.states = {}
        self.chips = {}
        self.labels = {}
        self.started = {}
        self.elapsed = {}
        self.show_timing = show_timing
        for column, (key, label) in enumerate(phases):
            cell = CTkFrame(self, fg_color=bg)
            cell.grid(row=0, column=column, sticky="w", padx=(0, 10))
            if column:
                divider = CTkFrame(cell, fg_color=BORDER, width=2, height=20)
                divider.pack(side="left", fill="y", padx=(0, 8))
            self.chips[key] = pill(cell, label, "muted")
            self.chips[key].pack(side="left")
            self.states[key] = "pending"
            self.labels[key] = label

    def _render(self, key):
        state = self.states[key]
        chip = self.chips[key]
        kind = self.STATE_KIND.get(state, "muted")
        kind_colors = {"muted": MUTED, "active": ACCENT_HI, "good": GREEN, "bad": RED, "skipped": MUTED, "skipped_soft": MUTED}
        color = kind_colors.get(kind, MUTED)
        chip.configure(text_color=color)
        mark = {"done": "✓ ", "failed": "✗ ", "active": "▸ ", "skipped": "– "}.get(state, "")
        timing = ""
        if self.show_timing and key in self.elapsed and state in ("done", "failed"):
            timing = f"  {human_duration(self.elapsed[key])}"
        chip.configure(text=f"{mark}{self.labels[key]}{timing}")

    def set_state(self, key, state, now=None):
        if key not in self.states:
            return
        now = time.monotonic() if now is None else now
        previous = self.states.get(key)
        if state == "active" and previous != "active":
            self.started[key] = now
        if state in ("done", "failed", "skipped") and key in self.started and key not in self.elapsed:
            self.elapsed[key] = now - self.started[key]
        self.states[key] = state
        self._render(key)

    def start(self, key):
        self.set_state(key, "active")

    def done(self, key):
        self.set_state(key, "done")

    def fail(self, key):
        self.set_state(key, "failed")

    def skip(self, key):
        self.set_state(key, "skipped")

    def reset(self):
        self.started = {}
        self.elapsed = {}
        for key in self.states:
            self.states[key] = "pending"
            self._render(key)