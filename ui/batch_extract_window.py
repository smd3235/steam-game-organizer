"""The window a batch extraction runs in, with a row per game.

A single Extract shows a small result dialog after it finishes: one archive, one outcome, one
click to dismiss. A batch is the opposite - twenty games in a category, a hundred and seventy-
six in the library, hours of 7z - so silence would leave no way to tell a working run from a
wedged one, and no way to stop it. Hence a window for the batch and a dialog for the single.

Every game gets a row before the first archive is touched, and the row is updated in place rather than being
rebuilt. That is the whole reason the queue is planned up front: a list that appears as games finish cannot tell
you what is still to come, and "how many are left" is the question this window exists to answer.

The window owns no work. It starts a BatchExtractJob on a thread, is handed every transition through a queue,
and drains that queue on the Tk thread - the same arrangement app/application.py uses for its own jobs, so the
app has one way of doing this rather than two.
"""
from __future__ import annotations

import queue
import shutil
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from ui.theme import (ACCENT_HI, BORDER, GREEN, MUTED, ORANGE, PANEL, PANEL2, RED, TEXT, Theme, human_duration, human_size,
                      pin_bottom)
from services.batch_extract_service import (CANCELLED, DONE, EXTRACTING, FAILED, QUEUED, SKIPPED, BatchExtractJob)

# The word shown for each state. The colour is not here: each state is a tag on the Text, configured once below,
# so a row cannot be written in a colour that was never declared in the palette.
STATE_WORD = {
    QUEUED: "Waiting",
    EXTRACTING: "Extracting",
    DONE: "Done",
    FAILED: "Failed",
    SKIPPED: "Already there",
    CANCELLED: "Not done",
}

# Every column is a fixed character offset so a row can be rewritten in place. Tk's Text has no columns, only
# lines, so the alignment is the tab stops configured in _table - without them the four fields run together into
# one unreadable line.
FIELD_STOPS = (34, 46, 58)


class BatchExtractWindow(tk.Toplevel):
    """Runs a BatchExtractJob and shows what every game in it is doing.

    A Toplevel rather than the Application's own window because the protocol handler runs with no main window:
    the batch is started from a link in a browser, and the only thing that has to appear is this.
    """

    def __init__(self, master, plan=None, logger=None, password="", on_finished=None, scanning=False):
        super().__init__(master)
        Theme(master)
        self.plan = plan
        self.logger = logger
        self.password = password
        self.on_finished = on_finished
        self.rows = {}
        self.job = None
        self._events = queue.Queue()
        self._pump = None
        self._closed = False
        self.scanning = scanning

        self.title("Extracting games")
        self.configure(bg=PANEL)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        self._header()
        self._summary_row()
        self._table()
        self._footer()

        # Wide enough for a game name, a size, a status and a detail line. A library-sized run scrolls, which is
        # why every row carries its own state rather than relying on being seen.
        self.geometry("900x640")
        self.minsize(640, 400)
        self.deiconify()
        self.lift()
        self.after_idle(lambda: self.attributes("-topmost", True))
        self.after_idle(lambda: self.attributes("-topmost", False))
        if not self.scanning:
            self.cancel_btn.focus_set()

    # ------------------------------------------------------------------ layout

    def _header(self):
        head = tk.Frame(self, bg=PANEL)
        head.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 6))
        head.columnconfigure(0, weight=1)
        
        if self.scanning:
            # Scanning mode header
            title_label = tk.Label(head, text="Scanning library", bg=PANEL, fg=TEXT,
                          font=("TkDefaultFont", 17, "bold"), anchor="w")
            title_label.grid(row=0, column=0, sticky="w")
            subtitle_label = tk.Label(head, text="discovering archives and checking installer signatures",
                         bg=PANEL, fg=MUTED, font=("TkDefaultFont", 9), anchor="w")
            subtitle_label.grid(row=1, column=0, sticky="w")
            return
        
        # Extraction mode header
        main_title = tk.Label(head, text=f"Extracting {self.plan.count} game{'s' if self.plan.count != 1 else ''}", bg=PANEL, fg=TEXT,
                   font=("TkDefaultFont", 17, "bold"), anchor="w")
        main_title.grid(row=0, column=0, sticky="w")
        
        category_frame = tk.Frame(head, bg=PANEL)
        category_frame.grid(row=1, column=0, sticky="w", pady=(2, 0))
        category_label = tk.Label(category_frame, text=self.plan.category, bg=PANEL, fg=ACCENT_HI, font=("TkDefaultFont", 9, "bold"),
                   anchor="w")
        category_label.grid(row=0, column=0, sticky="w")
        
        destination_frame = tk.Frame(head, bg=PANEL)
        destination_frame.grid(row=2, column=0, sticky="w", pady=(4, 0))
        destination_label = tk.Label(destination_frame, text=f"To  {self.plan.destination}", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 8),
                  anchor="w", justify="left", wraplength=660)
        destination_label.grid(row=0, column=0, sticky="w")
        
        if self.plan.already_done:
            already_frame = tk.Frame(head, bg=PANEL)
            already_frame.grid(row=3, column=0, sticky="w", pady=(2, 0))
            already_label = tk.Label(already_frame, text=f"{self.plan.already_done} already unpacked, so left alone", bg=PANEL, fg=MUTED,
                      font=("TkDefaultFont", 8), anchor="w")
            already_label.grid(row=0, column=0, sticky="w")

    def _summary_row(self):
        bar_container = tk.Frame(self, bg=PANEL)
        bar_container.grid(row=1, column=0, sticky="ew", padx=18, pady=(4, 8))
        bar_container.columnconfigure(0, weight=1)
        
        # Progress bar section
        progress_frame = tk.Frame(bar_container, bg=PANEL)
        progress_frame.grid(row=0, column=0, sticky="ew")
        progress_frame.columnconfigure(0, weight=1)
        
        self.bar = ttk.Progressbar(progress_frame, style="Dark.Horizontal.TProgressbar", mode="determinate", maximum=100)
        self.bar.grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.bar["value"] = 0
        
        # Info section
        info_frame = tk.Frame(bar_container, bg=PANEL)
        info_frame.grid(row=0, column=1, sticky="ew", padx=(12, 0))
        info_frame.columnconfigure(0, weight=1)
        
        self.remaining = tk.Label(info_frame, text="Starting...", bg=PANEL, fg=TEXT, font=("TkDefaultFont", 9, "bold"),
                                   anchor="w")
        self.remaining.grid(row=0, column=0, sticky="ew")
        
        self.metrics = tk.Label(info_frame, text="", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 8), anchor="w")
        self.metrics.grid(row=1, column=0, sticky="ew", pady=(6, 0))

    def _table(self):
        # Container for the table with visual framing
        table_container = tk.Frame(self, bg=PANEL2, highlightbackground=BORDER, highlightthickness=1)
        table_container.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 10))
        table_container.columnconfigure(0, weight=1)
        table_container.rowconfigure(0, weight=1)
        
        self.list = tk.Text(table_container, bg=PANEL2, fg=TEXT, relief="flat", wrap="none", height=12, undo=False,
                            font=("TkDefaultFont", 9), padx=10, pady=8, state="disabled", tabs=FIELD_STOPS)
        self.list.grid(row=0, column=0, sticky="nsew", padx=(12, 0), pady=12)
        scroll = ttk.Scrollbar(table_container, orient="vertical", command=self.list.yview, style="Dark.Vertical.TScrollbar")
        scroll.grid(row=0, column=1, sticky="ns", padx=(0, 12), pady=12)
        self.list.configure(yscrollcommand=scroll.set)
        
        for state, colour in ((QUEUED, MUTED), (EXTRACTING, ACCENT_HI), (DONE, GREEN), (FAILED, RED),
                              (SKIPPED, MUTED), (CANCELLED, ORANGE)):
            self.list.tag_configure(state, foreground=colour)
        self.list.tag_configure("size", foreground=MUTED)
        self.list.tag_configure("detail", foreground=MUTED)
        self.list.tag_configure("failed-detail", foreground=RED)

    def _footer(self):
        foot = tk.Frame(self, bg=PANEL)
        foot.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 16))
        foot.columnconfigure(0, weight=1)
        
        # Summary section
        summary_frame = tk.Frame(foot, bg=PANEL)
        summary_frame.grid(row=0, column=0, sticky="ew")
        summary_frame.columnconfigure(0, weight=1)
        
        self.summary = tk.Label(summary_frame, text="", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 9), anchor="w",
                                justify="left", wraplength=620)
        self.summary.grid(row=0, column=0, sticky="w")
        
        # Button section
        button_frame = tk.Frame(foot, bg=PANEL)
        button_frame.grid(row=0, column=1, sticky="e")
        
        self.cancel_btn = ttk.Button(button_frame, text="STOP RUN", style="Danger.TButton", command=self._stop)
        self.cancel_btn.grid(row=0, column=0, sticky="e")
        
        self.close_btn = ttk.Button(button_frame, text="CLOSE", style="Secondary.TButton", command=self._on_close)
        self.close_btn.grid(row=0, column=1, sticky="e", padx=(8, 0))

    # ------------------------------------------------------------------ running

    def start(self):
        """Build every row, then start the job.

        The rows exist before the first archive is touched. A list that fills in as games finish cannot answer
        "how many are left", which is the question this window is for.
        """
        self.scanning = False
        self._render_all()
        self._start_job()

    def _start_job(self):
        self.job = BatchExtractJob(self.plan, self.logger, on_progress=self._queue, password=self.password)
        self._refresh_metrics()
        self._pump = self.after(150, self._tick)
        threading.Thread(target=self.job.run, name="batch-extract", daemon=True).start()

    def set_plan(self, plan):
        """Replace the header with the real plan and start extraction.

        Called from the Tk thread after plan_batch finishes on a background thread. If the plan is
        empty, the window reports "nothing to extract" and waits for the user to close it, which
        lets the handler return 0 without opening a headless console nobody reads.
        """
        self.plan = plan
        self.scanning = False
        for child in self.grid_slaves(row=0):
            child.destroy()
        self._header()
        self.remaining.configure(text=f"Preparing {plan.count} game{'s' if plan.count != 1 else ''}...")
        if plan.items:
            self._render_all()
            self._start_job()
        else:
            self.cancel_btn.configure(state="disabled")
            self.remaining.configure(text=f"Nothing to extract from {plan.category or 'the whole library'}.")
            if plan.already_done:
                self.remaining.configure(text=f"Nothing to extract from {plan.category or 'the whole library'}. "
                                             f"{plan.already_done} already unpacked, so left alone.")
        self.close_btn.focus_set()

    def _queue(self, stage="", item=None, detail=""):
        """Hand a transition to the Tk thread. Never touches a widget from here."""
        self._events.put((stage, item, detail))

    def _tick(self):
        """Drain the queue on the Tk thread. Scheduled by Tk, so it is the only place widgets are touched."""
        if self._closed:
            return
        finished = False
        try:
            while True:
                stage, item, detail = self._events.get_nowait()
                if stage == "finished":
                    finished = True
                    break
                if item is not None:
                    self._update_row(item)
        except queue.Empty:
            pass
        if finished:
            self._finish()
            return
        self._refresh_metrics()
        self._pump = self.after(150, self._tick)

    def _row_text(self, item):
        """The four fields of a row, in the order the tab stops are set for."""
        size = human_size(item.size) if item.size else "-"
        word = STATE_WORD.get(item.state, item.state)
        detail = item.detail
        if item.state == EXTRACTING and item.percent and not detail.startswith(f"{item.percent}%"):
            detail = f"{item.percent}%  {detail}".strip()
        return f"{item.name}\t{size}\t{word}\t{detail}"

    def _render_all(self):
        self.list.configure(state="normal")
        self.list.delete("1.0", "end")
        for item in self.plan.items:
            # The line number is remembered so the row can be rewritten in place. Deleting and reinserting would
            # shift every row below it, so the list would jump under the reader on every progress event.
            self.rows[id(item)] = self.list.index("end-1c")
            self.list.insert("end", self._row_text(item) + "\n", (item.state, "detail"))
        self.list.configure(state="disabled")
        pin_bottom(self.list)

    def _update_row(self, item):
        """Rewrite one row's text, keeping its tags, and follow it while it is the active game."""
        start = self.rows.get(id(item))
        if start is None:
            return
        self.list.configure(state="normal")
        # "lineend", not "+1c". The character index counts one character, so deleting "+1c" removed the
        # row's first letter and left the rest of it behind to be duplicated on every progress tick.
        # "lineend" stops before the newline, which is why the replacement carries no trailing newline of
        # its own: adding one would leave an extra blank line behind and the list would grow per tick.
        self.list.delete(start, f"{start} lineend")
        # The row's own state is re-applied as a tag, so a row turns green or red without a colour lookup here.
        self.list.insert(start, self._row_text(item), (item.state, "detail"))
        self.list.configure(state="disabled")
        if item.state == EXTRACTING:
            self.list.see(start)

    def _refresh_metrics(self):
        """The running totals. Cheap enough for every tick, which is what keeps them honest."""
        job = self.job
        if not job:
            return
        finished = sum(1 for item in job.plan.items if item.finished)
        total = len(job.plan.items)
        self.bar["value"] = (finished / total * 100) if total else 100
        self.remaining.configure(text=f"{finished} of {total} done  -  {total - finished} remaining")

        elapsed = (time.monotonic() - job.started_at) if job.started_at else 0
        parts = [f"{human_size(job.written)} unpacked", human_duration(elapsed)]
        if elapsed > 0 and job.written:
            parts.append(f"{human_size(int(job.written / elapsed))}/s")
        free = self._free_bytes()
        if free is not None:
            parts.append(f"{human_size(free)} free on the drive")
        self.metrics.configure(text="  -  ".join(parts))

    def _free_bytes(self):
        """Room left where the files are landing, or None when it cannot be read.

        None rather than 0 on purpose: an unreadable volume is not a full one, and "0 B free" would read as the
        run being about to fail for a reason it has not hit.
        """
        probe = Path(self.plan.destination)
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        try:
            return shutil.disk_usage(probe).free
        except OSError:
            return None

    # ------------------------------------------------------------------ finishing

    def _stop(self):
        """Ask the run to stop. Deliberately does not close the window.

        Closing on the request would report a stopped run as a finished one, and the games already unpacked would
        be indistinguishable from the ones that never started. The button says STOPPING and the run unwinds on its
        own, which is the arrangement the organize view already uses.
        """
        if not self.job or self.job.done.is_set():
            return
        self.job.cancel()
        self.cancel_btn.configure(state="disabled", text="STOPPING...")

    def _finish(self):
        """Stop the pump and report the outcome. The window stays open until closed."""
        job = self.job
        self._pump = None
        self.bar["value"] = 100
        self.cancel_btn.configure(state="disabled", text="STOPPED" if job.cancel_requested else "FINISHED")
        self.remaining.configure(text=f"{job.plan.count} accounted for  -  0 remaining")
        self.summary.configure(text=job.summary(), fg=RED if job.failed else TEXT)
        # The failed games are named in the summary rather than left only in their rows: a run of 176 with 3
        # failures is a success with caveats, and the caveats should not require scrolling to find.
        if job.failed:
            names = ", ".join(item.name for item in job.plan.items if item.state == FAILED)
            self.summary.configure(text=f"{job.summary()}\nFailed: {names}", fg=RED)
        self.close_btn.focus_set()
        if self.on_finished:
            self.on_finished(job)

    def _on_close(self):
        """Close the window, cancelling a live run first so closing cannot leave 7z writing unattended."""
        if self.job and not self.job.done.is_set():
            self.job.cancel()
            self.title("Stopping the current game, then closing...")
            self.cancel_btn.configure(state="disabled", text="STOPPING...")
            return
        self._closed = True
        if self._pump:
            try:
                self.after_cancel(self._pump)
            except (tk.TclError, ValueError):
                pass
            self._pump = None
        self.destroy()
        try:
            self.master.quit()
        except (tk.TclError, AttributeError):
            pass


def run_batch_window(master, plan=None, logger=None, password="", on_finished=None, scanning=True):
    """Build the window and start it. Returns the window, for a caller that wants to keep a handle on it.

    When scanning=True (the default), the window opens immediately showing "Scanning library" and does not
    start extraction. The caller must invoke window.set_plan(plan) once the background plan_batch completes.
    When scanning=False, plan must be provided and start() is called immediately.
    """
    window = BatchExtractWindow(master, plan, logger=logger, password=password,
                                on_finished=on_finished, scanning=scanning)
    if not scanning:
        window.start()
    return window


