"""Extracted from ui/theme.py.

    PhaseTimeline was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import time
import tkinter as tk
from utils.formatting import human_duration
from ui.palette import BORDER
from ui.theme import pill
from ui.palette import PANEL


class PhaseTimeline(tk.Frame):
    """A row of stage chips showing every step of a run at once, so the current step is obvious and finished
    steps stay visible instead of being replaced by the newest line of text.
    This is what makes a long run legible: 'Converting 4 of 30' is a single overwritable sentence, while the
    timeline shows which of the six phases are done, which is running, and which were skipped entirely.
    Each chip also carries how long its stage took. A stage that always takes 30s reads very differently from
    one that suddenly takes eight minutes, which is usually the first sign of a problem worth stopping for.
    """

    STATE_KIND = {"pending": "muted", "active": "accent", "done": "good", "skipped": "muted", "failed": "bad", "skipped_soft": "muted"}

    def __init__(self, parent, phases, bg=PANEL, show_timing=True, **kw):
        super().__init__(parent, bg=bg, **kw)
        self.states = {}
        self.chips = {}
        self.labels = {}
        self.started = {}
        self.elapsed = {}
        self.show_timing = show_timing
        for column, (key, label) in enumerate(phases):
            cell = tk.Frame(self, bg=bg)
            cell.grid(row=0, column=column, sticky="w", padx=(0, 10))
            if column:
                tk.Frame(cell, bg=BORDER, width=2, height=20).pack(side="left", fill="y", padx=(0, 8))
            self.chips[key] = pill(cell, label, "muted")
            self.chips[key].pack(side="left")
            self.states[key] = "pending"
            self.labels[key] = label

    def _render(self, key):
        state = self.states[key]
        chip = self.chips[key]
        chip.restyle(self.STATE_KIND.get(state, "muted"))
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
