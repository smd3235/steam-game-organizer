"""A polished dialog for single-archive extraction, with live progress and a result view.

The catalog's per-game Extract button launches a handler process. Without a visible UI the browser
console vanishes before the reader can see the outcome, so this dialog does two things: shows a
progress bar while 7z runs, then flips to a result view with the archive name, destination, and
action buttons so the reader always knows what happened.

The single-extract result is NOT written to the catalog's status file — that file feeds only the
batch "Last run" banner, and writing a single-archive outcome there would make the banner show
"Last run: 1 of 1 extracted" after every click, redundant with this dialog.

It is kept separate from the multi-game batch window so neither needs to know the other exists.
"""

from __future__ import annotations

import os
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from ui.theme import ACCENT, ACCENT_HOVER, BG, BORDER, GREEN, MUTED, ORANGE, PANEL2, PANEL3, RED, TEXT, Theme


class ExtractProgressDialog(tk.Toplevel):
    """Shows a progress bar during extraction, then hands off to the result view."""

    def __init__(self, master, archive: Path, destination: Path, logger, password: str = "", needs_install: bool = False, on_done=None):
        super().__init__(master)
        Theme(master)
        self._archive = archive
        self._destination = destination
        self._logger = logger
        self._password = password
        self._needs_install = needs_install
        self._on_done = on_done
        self._cancelled = threading.Event()
        self._result = None
        self.transient(master)

        self.title("Extracting installer…" if needs_install else "Extracting")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()

        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True, padx=0, pady=0)

        tk.Label(outer, text="Extracting installer" if needs_install else "Extracting", bg=BG, fg=MUTED, font=("TkDefaultFont", 8, "bold")).pack(anchor="w", padx=24, pady=(18, 8))
        tk.Label(outer, text=str(archive.name), bg=BG, fg=TEXT, font=("TkDefaultFont", 12, "bold")).pack(anchor="w", padx=24)

        self._file_label = tk.Label(outer, text="Starting...", bg=BG, fg=MUTED, font=("TkDefaultFont", 9))
        self._file_label.pack(anchor="w", padx=24, pady=(10, 4))

        self._bar = ttk.Progressbar(outer, style="Dark.Horizontal.TProgressbar", mode="determinate", maximum=100)
        self._bar.pack(fill="x", padx=24, pady=(0, 8))
        self._bar["value"] = 0

        self._elapsed = tk.Label(outer, text="", bg=BG, fg=MUTED, font=("TkDefaultFont", 8))
        self._elapsed.pack(anchor="w", padx=24, pady=(0, 16))

        self._footer = tk.Frame(outer, bg=BG, height=50)
        self._footer.pack(fill="x", padx=24, pady=(0, 22))
        self._footer.pack_propagate(False)

        self._cancel_btn = tk.Button(self._footer, text="Cancel", command=self._cancel, bg=PANEL3,
            fg=TEXT, font=("TkDefaultFont", 9, "bold"), activebackground=BG, bd=0, padx=12,
            pady=4, cursor="hand2")
        self._cancel_btn.pack(side="right")

        self._start_time = time.monotonic()

        self.bind("<Escape>", lambda e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self._center_on_screen()
        self.after(50, lambda: self.lift())
        self.after_idle(lambda: self.attributes("-topmost", True))
        self.after_idle(lambda: self.attributes("-topmost", False))

        self._thread = threading.Thread(target=self._run_extraction, daemon=True)
        self._thread.start()
        self._pump_stats()

    def _on_progress(self, stage, percent, name):
        if self._cancelled.is_set():
            return
        self.after(0, self._update_progress, percent, name)

    def _update_progress(self, percent, name):
        self._bar["value"] = percent
        if name:
            self._file_label.config(text=name)

    def _pump_stats(self):
        self._update_stats()
        if self._result is None:
            self.after(500, self._pump_stats)
        elif self._result is not None:
            return

    def _update_stats(self):
        elapsed = int(time.monotonic() - self._start_time)
        self._elapsed.config(text=f"{elapsed}s elapsed")

    def _cancel(self):
        self._cancelled.set()
        self._cancel_btn.config(text="Stopping...", state="disabled")

    def _center_on_screen(self):
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"+{x}+{y}")

    def _run_extraction(self):
        from services.extract_service import ExtractService

        service = ExtractService(self._logger, on_progress=self._on_progress)
        service.check_space = lambda archive, destination: ""
        result = service.extract(self._archive, self._destination, password=self._password, cancel=self._cancelled.is_set)
        self._result = result
        self.after(0, self._finish)

    def _finish(self):
        result = self._result
        if result is None:
            return
        if self._on_done:
            try:
                self._on_done(result)
            except Exception:
                pass
        self.withdraw()
        ExtractResultWindow(self.master, self._archive, result.destination, result.ok, result.message, needs_install=result.needs_install)
        self.destroy()
        self.master.quit()


class ExtractResultWindow(tk.Toplevel):
    """Shows the outcome of a single extraction with a status icon, archive info, and actions."""

    def __init__(self, master, archive: Path, destination: Path, ok: bool, message: str, needs_install: bool = False):
        super().__init__(master)
        Theme(master)
        self._destination = destination
        self._archive = archive
        self.ok = ok
        self.transient(master)

        self.title("Extraction complete")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()

        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True, padx=0, pady=0)

        self._draw_header(outer, ok, needs_install)
        self._draw_body(outer, archive, destination, message, needs_install)
        self._draw_footer(outer, ok)

        self.bind("<Escape>", lambda e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._center_on_screen()
        self.after(50, lambda: self.lift())
        self.after_idle(lambda: self.attributes("-topmost", True))
        self.after_idle(lambda: self.attributes("-topmost", False))
        self.wait_window(self)

    def _draw_header(self, parent, ok, needs_install):
        header = tk.Frame(parent, bg=BG, height=90)
        header.pack(fill="x", padx=24, pady=(22, 0))
        header.pack_propagate(False)

        status_color = GREEN if ok else RED
        icon = "\u2713" if ok else "\u2717"
        tk.Label(header, text=icon, bg=BG, fg=status_color, font=("TkDefaultFont", 32, "bold")).place(relx=0.5, rely=0.25, anchor="center")

        title = "Extraction Succeeded" if ok else "Extraction Failed"
        tk.Label(header, text=title, bg=BG, fg=TEXT, font=("TkDefaultFont", 14, "bold")).place(relx=0.5, rely=0.68, anchor="center")

        subtitle = (
            "Run the installer in the destination folder to finish installing this game"
            if needs_install and ok else
            "The game is ready to play" if ok else
            "The extraction did not complete. Check the log for details.")
        tk.Label(header, text=subtitle, bg=BG, fg=MUTED, font=("TkDefaultFont", 9)).place(relx=0.5, rely=0.84, anchor="center")

    def _draw_body(self, parent, archive, destination, message, needs_install):
        body = tk.Frame(parent, bg=BG)
        body.pack(fill="both", expand=True, padx=24, pady=(16, 22))

        tk.Label(body, text=str(archive.name), bg=BG, fg=TEXT, font=("TkDefaultFont", 11, "bold")).pack(anchor="w", pady=(0, 12))

        if needs_install and self.ok:
            note = tk.Frame(body, bg=PANEL2, relief="flat", bd=0)
            note.pack(fill="x", pady=(0, 12))
            note.columnconfigure(1, weight=1)
            tk.Label(note, text="\u26a0", bg=PANEL2, fg=ORANGE, font=("TkDefaultFont", 14)).grid(row=0, column=0, padx=(12, 8), pady=10)
            tk.Label(note, text="Installer archive detected. Run the setup program to install the game.",
                bg=PANEL2, fg=TEXT, font=("TkDefaultFont", 9, "bold"), wraplength=380,
                justify="left").grid(row=0, column=1, sticky="w")

        msg_frame = tk.LabelFrame(body, text="Details", bg=BG, fg=MUTED, font=("TkDefaultFont", 8), bd=1, highlightbackground=BORDER, highlightthickness=1)
        msg_frame.pack(fill="x", pady=(0, 12), padx=(0, 0))
        tk.Label(msg_frame, text=message, bg=BG, fg=MUTED, font=("TkDefaultFont", 9), wraplength=420, justify="left").pack(padx=12, pady=8)

        if self.ok:
            dest_frame = tk.LabelFrame(body, text="Extracted to", bg=BG, fg=MUTED, font=("TkDefaultFont", 8), bd=1, highlightbackground=BORDER, highlightthickness=1)
            dest_frame.pack(fill="x", pady=(0, 0))
            dest_label = tk.Label(dest_frame, text=str(destination), bg=BG, fg=TEXT, font=("TkDefaultFont", 8), wraplength=420, justify="left")
            dest_label.pack(padx=12, pady=8)

    def _draw_footer(self, parent, ok):
        footer = tk.Frame(parent, bg=BG, height=50)
        footer.pack(fill="x", padx=24, pady=(0, 22))
        footer.pack_propagate(False)

        if ok:
            btn_open = tk.Button(footer, text="\u00a0Show in Explorer\u00a0", command=self._open_folder, bg=ACCENT, fg=TEXT, font=("TkDefaultFont", 9, "bold"), activebackground=ACCENT_HOVER, activeforeground=TEXT, bd=0, padx=14, pady=5, cursor="hand2")
            btn_open.pack(side="left")

            btn_copy = tk.Button(footer, text="Copy path", command=self._copy_path, bg=PANEL3, fg=TEXT, font=("TkDefaultFont", 9), activebackground=PANEL2, bd=0, padx=14, pady=5, cursor="hand2")
            btn_copy.pack(side="left", padx=(12, 0))

        tk.Button(footer, text="Done", command=self.destroy, bg=ACCENT if ok else PANEL3, fg=TEXT, font=("TkDefaultFont", 9, "bold"), activebackground=ACCENT_HOVER if ok else PANEL2, activeforeground=TEXT, bd=0, padx=18, pady=5, cursor="hand2").pack(side="right")

    def _center_on_screen(self):
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"+{x}+{y}")

    def _open_folder(self):
        try:
            os.startfile(str(self._destination))
        except OSError:
            pass

    def _copy_path(self):
        try:
            self.clipboard_clear()
            self.clipboard_append(str(self._destination))
            self.update()
        except tk.TclError:
            pass


def show_extract_with_progress(master, archive: Path, destination: Path, logger, password: str = "", needs_install: bool = False, on_done=None) -> ExtractProgressDialog:
    """Show a progress dialog during extraction, then a result dialog. Blocks until both are done."""
    root = master if master else tk._default_root
    return ExtractProgressDialog(root, archive, destination, logger, password=password, needs_install=needs_install, on_done=on_done)
