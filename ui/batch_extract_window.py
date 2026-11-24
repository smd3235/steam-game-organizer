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

import customtkinter as ctk
import queue
import shutil
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from ui.custom_theme import ACCENT, ACCENT_HOVER, BG, GREEN, MUTED, ORANGE, PANEL, PANEL2, PANEL3, RED, TEXT, Theme, human_duration, human_size, pin_bottom, CTkFrame, CTkLabel, CTkButton, CTkProgressBar, CTkScrollbar
from services.batch_extract_service import CANCELLED, DONE, EXTRACTING, FAILED, QUEUED, SKIPPED, BatchExtractJob

# The word shown for each state. The colour is not here: each state is a tag on the Treeview row,
# configured once below, so a row cannot be written in a colour that was never declared in the palette.
STATE_WORD = {
    QUEUED: "Waiting",
    EXTRACTING: "Extracting",
    DONE: "Done",
    FAILED: "Failed",
    SKIPPED: "Already there",
    CANCELLED: "Not done",
}


class BatchExtractWindow(ctk.CTkToplevel):
    """Runs a BatchExtractJob and shows what every game in it is doing.

    A Toplevel rather than the Application's own window because the protocol handler runs with no main window:
    the batch is started from a link in a browser, and the only thing that has to appear is this.
    """

    def __init__(self, master, plan=None, logger=None, password="", on_finished=None, scanning=False):
        super().__init__(master)
        Theme(master)
        self.config = None  # Will be set by caller if needed
        self.logger = logger
        self.password = password
        self.on_finished = on_finished
        self.scanning = scanning
        self.plan = plan
        self.job = None
        self._pump = None
        self._closed = False
        self.rows = {}  # identity_key -> Treeview item id

        self.transient(master)

        self.title("Batch Extract")
        self.configure(fg_color=BG)
        self.resizable(True, True)
        self.grab_set()

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        self._header()
        self._table()
        self._footer()

        self.geometry("900x600")
        self.minsize(600, 400)

        if scanning:
            self._show_scanning()
        # start() is called explicitly by run_batch_window() / the caller, not here,
        # so items stay QUEUED until the caller starts the job.

        self._center_on_screen()
        self.after(50, lambda: self.lift())
        self.after_idle(lambda: self.attributes("-topmost", True))
        self.after_idle(lambda: self.attributes("-topmost", False))

        self.bind("<Escape>", lambda e: self._on_close())
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ layout

    def _header(self):
        head = CTkFrame(self, fg_color=PANEL, corner_radius=8)
        head.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 6))
        head.columnconfigure(0, weight=1)
        head.columnconfigure(1, weight=0)
        head.columnconfigure(2, weight=0)

        CTkLabel(head, text="Batch Extract", fg_color=PANEL, text_color=TEXT, font=("TkDefaultFont", 17, "bold"), anchor="w").grid(row=0, column=0, sticky="w")

        self.header_count = CTkLabel(head, text="", fg_color=PANEL, text_color=MUTED, font=("TkDefaultFont", 11, "bold"), anchor="e")
        self.header_count.grid(row=0, column=1, sticky="e", padx=(12, 0))

        CTkLabel(head,
            text="Each archive is extracted once. Accepted games are moved into their category folder; "
                 "skipped games are left untouched. Failed games stay where they are.",
            fg_color=PANEL, text_color=MUTED, font=("TkDefaultFont", 9), anchor="w", justify="left",
            wraplength=620).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 12))
        if self.plan:
            count = len(self.plan.items)
            already = getattr(self.plan, "already_done", 0)
            if already:
                self.header_count.configure(text=f"{already} already unpacked  •  Extracting {count} games")
            else:
                self.header_count.configure(text=f"Extracting {count} games")
            self.header_dest = CTkLabel(head, text=str(self.plan.destination), fg_color=PANEL, text_color=MUTED, font=("TkDefaultFont", 9), anchor="e")
            self.header_dest.grid(row=0, column=2, sticky="e")

    def _table(self):
        table_container = CTkFrame(self, fg_color=PANEL2, corner_radius=8)
        table_container.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 10))
        table_container.columnconfigure(0, weight=1)
        table_container.rowconfigure(0, weight=1)

        self.list = ttk.Treeview(table_container, columns=("size", "status", "detail"),
                                show="tree headings", height=12, selectmode="none")
        self.list.column("#0", width=300, minwidth=200, stretch=True)
        self.list.column("size", width=90, minwidth=70, stretch=False)
        self.list.column("status", width=100, minwidth=80, stretch=False)
        self.list.column("detail", width=260, minwidth=150, stretch=True)
        self.list.heading("#0", text="Game", anchor="w")
        self.list.heading("size", text="Size", anchor="w")
        self.list.heading("status", text="Status", anchor="w")
        self.list.heading("detail", text="Detail", anchor="w")
        self.list.grid(row=0, column=0, sticky="nsew", padx=(12, 0), pady=12)
        scroll = CTkScrollbar(table_container, orientation="vertical", command=self.list.yview)
        scroll.grid(row=0, column=1, sticky="ns", padx=(0, 12), pady=12)
        self.list.configure(yscrollcommand=scroll.set)

        for state, colour in ((QUEUED, MUTED), (EXTRACTING, ACCENT_HOVER), (DONE, GREEN), (FAILED, RED), (SKIPPED, MUTED), (CANCELLED, ORANGE)):
            self.list.tag_configure(state, foreground=colour)

    def _footer(self):
        footer_container = CTkFrame(self, fg_color=BG)
        footer_container.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 16))
        footer_container.columnconfigure(0, weight=1)
        footer_container.columnconfigure(1, weight=0)

        self.cancel_btn = CTkButton(footer_container, text="STOP RUN", command=self._stop,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=TEXT, font=("TkDefaultFont", 9, "bold"), height=32)
        self.cancel_btn.grid(row=0, column=0, sticky="w", padx=(12, 0))

        self.close_btn = CTkButton(footer_container, text="CLOSE", command=self._on_close,
            fg_color=PANEL3, hover_color=PANEL2, text_color=TEXT, font=("TkDefaultFont", 9, "bold"), height=32)
        self.close_btn.grid(row=0, column=1, sticky="e")

        self.progress_frame = CTkFrame(footer_container, fg_color=BG)
        self.progress_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.progress_frame.columnconfigure(0, weight=1)

        self.bar = CTkProgressBar(self.progress_frame, mode="determinate")
        self.bar.pack(fill="x", padx=0, pady=(0, 4))
        self.bar.set(0)

        self.remaining = CTkLabel(self.progress_frame, text="0 of 0 done - 0 remaining", fg_color=BG, text_color=MUTED, font=("TkDefaultFont", 9))
        self.remaining.pack(anchor="w", padx=0, pady=(0, 4))

        self.metrics = CTkLabel(self.progress_frame, text="", fg_color=BG, text_color=MUTED, font=("TkDefaultFont", 8))
        self.metrics.pack(anchor="w", padx=0, pady=(0, 0))

        self.summary = CTkLabel(self.progress_frame, text="", fg_color=BG, text_color=TEXT, font=("TkDefaultFont", 9), justify="left")
        self.summary.pack(anchor="w", padx=0, pady=(4, 0))

    # ------------------------------------------------------------------ behaviour

    def start(self):
        self.scanning = False
        self._render_all()
        self._start_job()

    def _start_job(self):
        self.job = BatchExtractJob(self.plan, self.logger, on_progress=self._on_progress, password=self.password)
        self._refresh_metrics()
        self._pump = self.after(150, self._tick)
        threading.Thread(target=self.job.run, daemon=True).start()

    def _on_progress(self, stage, item, detail=""):
        """Progress callback from BatchExtractJob (runs on the worker thread). Re-post to the Tk thread."""
        if item is not None:
            self.job.queue.put(("progress", item))

    def _tick(self):
        try:
            msg = self.job.queue.get_nowait()
        except queue.Empty:
            pass
        else:
            event, payload = msg
            if event == "progress":
                self._update_row(payload)
            elif event == "done":
                self._update_row(payload)
                self._refresh_metrics()
            elif event == "finished":
                self._finish()
                return
        if not self._closed:
            self._pump = self.after(150, self._tick)

    def _row_text(self, item):
        size = human_size(item.size) if item.size else "-"
        word = STATE_WORD.get(item.state, item.state)
        detail = item.detail
        if item.state == EXTRACTING and item.percent and not detail.startswith(f"{item.percent}%"):
            detail = f"{item.percent}%  {detail}".strip()
        return (item.name, size, word, detail)

    def _render_all(self):
        self.list.delete(*self.list.get_children())
        for item in self.plan.items:
            iid = self.list.insert("", "end", values=self._row_text(item), tags=(item.state, "detail"))
            self.rows[id(item)] = iid
        pin_bottom(self.list)

    def _update_row(self, item):
        iid = self.rows.get(id(item))
        if iid is None:
            return
        self.list.item(iid, values=self._row_text(item), tags=(item.state, "detail"))
        if item.state == EXTRACTING:
            self.list.see(iid)

    def _refresh_metrics(self):
        job = self.job
        if not job:
            return
        finished = sum(1 for item in job.plan.items if item.finished)
        total = len(job.plan.items)
        self.bar.set((finished / total * 100) if total else 100)
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
        probe = Path(self.plan.destination)
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        try:
            return shutil.disk_usage(probe).free
        except OSError:
            return None

    def _stop(self):
        if not self.job or self.job.done.is_set():
            return
        self.job.cancel()
        self.cancel_btn.configure(state="disabled", text="STOPPING...")

    def _finish(self):
        job = self.job
        self._pump = None
        self.bar.set(100)
        self.cancel_btn.configure(state="disabled", text="STOPPED" if job.cancel_requested else "FINISHED")
        self.remaining.configure(text=f"{job.plan.count} accounted for  -  0 remaining")
        self.summary.configure(text=job.summary(), text_color=RED if job.failed else TEXT)
        if job.failed:
            names = ", ".join(item.name for item in job.plan.items if item.state == FAILED)
            self.summary.configure(text=f"{job.summary()}\nFailed: {names}", text_color=RED)
        self.close_btn.focus_set()
        if self.on_finished:
            self.on_finished(job)

    def _on_close(self):
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

    def _center_on_screen(self):
        """Place the window near the centre of the screen once it has a size."""
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")


def run_batch_window(master, plan=None, logger=None, password="", on_finished=None, scanning=True):
    window = BatchExtractWindow(master, plan, logger=logger, password=password, on_finished=on_finished, scanning=scanning)
    if not scanning:
        window.start()
    return window