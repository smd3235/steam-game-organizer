"""The setup wizard: the three folders a fresh PC has to be told.

The catalog's "Set up on this PC" button and the --setup command line both open
this. A Toplevel rather than the Application's own window, for the same reason
the batch window is one: the protocol handler runs with no main window, and
this is the only thing that has to appear.

The three boxes are the three things that decide whether an Extract button
works at all - where the games are (the handler refuses a source outside it),
where this app lives (the handler is registered to open it), and where games
are unpacked to. Each has a Browse button, because a path this important is
not one to type, and the checks below the boxes say what is wrong before
anything is saved.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from core.constants import APP_NAME
from core.uri_actions import SetupRequest
from services.setup_service import SetupService
from ui.theme import ACCENT_HI, BG, BORDER, ENTRY_BG, GREEN, MUTED, ORANGE, PANEL, PANEL2, RED, TEXT, Theme


class SetupWindow(tk.Toplevel):
    """Sets the game library, the app folder and the extract folder, and saves them.

    service is injectable so a test can watch a save without touching settings
    or the registry; it defaults to the real SetupService.
    """

    def __init__(self, master, config, logger, prefill=None, service=None):
        super().__init__(master)
        Theme(master)
        self.config = config
        self.logger = logger
        self.prefill = prefill or SetupRequest()
        self.service = service or SetupService(logger)
        # A box the link did not fill starts on the app's own answer, not empty:
        # an empty box is an error row on open, and the common case - the app's
        # first run on this PC, or --setup from the command line - has no link
        # at all. The app folder defaults to the copy that is running, because
        # that is the one that knows where it lives.
        import sys

        self.library_var = tk.StringVar(value=self.prefill.library or str(config.library_root))
        # The app folder is where the app itself lives. In a frozen build, that's the folder containing the exe
        # (bundle root), not _internal. In source, it's the project root.
        app_default = (self.prefill.app or str(Path(sys.executable).resolve().parent)) if getattr(sys, "frozen", False) else (self.prefill.app or (str(Path(__file__).resolve().parents[1]) if not self.prefill.library else str(Path(self.prefill.library).expanduser().resolve())))
        self.app_var = tk.StringVar(value=app_default)
        self.extract_var = tk.StringVar(value=self.prefill.extract or str(config.extract_folder))

        self.title(f"Set up {APP_NAME} on this PC")
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        self._header()
        self._fields()
        self._checks()
        self._footer()

        self.geometry("680x540")
        self.minsize(560, 440)
        # The checks describe the machine as it is right now, before any save,
        # which is the state the reader needs to see to know what the save fixes.
        self.refresh_checks()
        self.deiconify()
        self.lift(aboveThis=master)

    # ------------------------------------------------------------------ layout

    def _header(self):
        head = tk.Frame(self, bg=PANEL)
        head.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 6))
        head.columnconfigure(0, weight=1)

        # Title and description
        title_label = tk.Label(head, text=f"Set up {APP_NAME} on this PC", bg=PANEL, fg=TEXT, font=("TkDefaultFont", 17, "bold"), anchor="w")
        title_label.grid(row=0, column=0, sticky="w")

        desc_label = tk.Label(head, text="Three folders decide whether the catalog's Extract buttons work here. Set them once; the choices are saved beside the app.", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 9), anchor="w", justify="left", wraplength=620)
        desc_label.grid(row=1, column=0, sticky="w", pady=(4, 12))

        # Visual separator
        separator = tk.Frame(head, bg=ACCENT_HI, height=1, relief="flat")
        separator.grid(row=2, column=0, sticky="ew", pady=(4, 0))

    def _fields(self):
        body = tk.Frame(self, bg=BG)
        body.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 8))
        body.columnconfigure(0, weight=1)

        rows = (
            ("Game library", self.library_var, "The folder the games are in - the whole library, categories and all"),
            ("App folder", self.app_var, f"Where {APP_NAME} itself lives. The Extract link is registered to open this copy"),
            ("Extract to", self.extract_var, "Where games are unpacked. Outside the game library: loose files there would be scanned as games"),
        )

        for index, (label, variable, hint) in enumerate(rows):
            # Field container for better visual grouping
            field_container = tk.Frame(body, bg=BG)
            field_container.grid(row=index, column=0, sticky="ew", pady=(0, 8))
            field_container.columnconfigure(0, weight=1)

            # Label
            label_widget = tk.Label(field_container, text=label, bg=BG, fg=ACCENT_HI, font=("TkDefaultFont", 10, "bold"), anchor="w")
            label_widget.grid(row=0, column=0, sticky="w")

            # Input frame
            input_frame = tk.Frame(field_container, bg=BG)
            input_frame.grid(row=1, column=0, sticky="ew", pady=(2, 0))
            input_frame.columnconfigure(0, weight=1)

            entry = tk.Entry(input_frame, textvariable=variable, bg=ENTRY_BG, fg=TEXT, insertbackground=TEXT, font=("TkDefaultFont", 10), relief="flat", highlightbackground=BORDER, highlightthickness=1, bd=0)
            entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))

            browse_btn = ttk.Button(input_frame, text="Browse…", command=self._browse_for(variable))
            browse_btn.grid(row=0, column=1, sticky="e")

            # Hint text
            hint_label = tk.Label(field_container, text=hint, bg=BG, fg=MUTED, font=("TkDefaultFont", 8), anchor="w", justify="left", wraplength=600)
            hint_label.grid(row=2, column=0, sticky="w", pady=(2, 0))

            # Visual separator between fields (except after the last one)
            if index < len(rows) - 1:
                separator = tk.Frame(body, bg=BORDER, height=1, relief="flat")
                separator.grid(row=index + 1, column=0, sticky="ew", pady=(0, 4))

    def _browse_for(self, variable):
        def browse():
            chosen = filedialog.askdirectory(parent=self, mustexist=True, title="Choose a folder")
            if chosen:
                variable.set(chosen)

        return browse

    def _checks(self):
        # Container for the checks section with visual framing
        check_container = tk.Frame(self, bg=PANEL2, highlightbackground=BORDER, highlightthickness=1)
        check_container.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 8))
        check_container.columnconfigure(0, weight=1)
        check_container.rowconfigure(1, weight=1)

        # Header
        header_frame = tk.Frame(check_container, bg=PANEL2)
        header_frame.grid(row=0, column=0, sticky="ew", pady=(8, 8))
        tk.Label(header_frame, text="Checks", bg=BG, fg=ACCENT_HI, font=("TkDefaultFont", 9, "bold"), anchor="w").grid(row=0, column=0, sticky="w")

        # Report area
        self.report = tk.Text(check_container, height=10, bg=ENTRY_BG, fg=TEXT, wrap="word", font=("TkDefaultFont", 9), relief="flat", highlightthickness=1, highlightbackground=BORDER, state="disabled")
        self.report.grid(row=1, column=0, sticky="nsew", padx=(8, 0), pady=(0, 8))
        # The three levels, each in its own colour so a problem is visible before
        # the message is read. The palette names the colours; nothing here invents one.
        self.report.tag_configure("error", foreground=RED)
        self.report.tag_configure("warn", foreground=ORANGE)
        self.report.tag_configure("ok", foreground=GREEN)

    def _footer(self):
        # Container for the footer with better visual grouping
        footer_container = tk.Frame(self, bg=BG)
        footer_container.grid(row=3, column=0, sticky="ew", padx=18, pady=(18, 16))
        footer_container.columnconfigure(0, weight=1)

        # Separator
        separator = tk.Frame(footer_container, bg=BORDER, height=1, relief="flat")
        separator.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))

        # Status and button section
        action_frame = tk.Frame(footer_container, bg=BG)
        action_frame.grid(row=1, column=0, sticky="ew")
        action_frame.columnconfigure(0, weight=1)

        self.status = tk.Label(action_frame, text="", bg=BG, fg=MUTED, font=("TkDefaultFont", 9), anchor="w")
        self.status.grid(row=0, column=0, sticky="w")

        # Button container for better grouping
        button_frame = tk.Frame(action_frame, bg=BG)
        button_frame.grid(row=0, column=1, sticky="e")

        ttk.Button(button_frame, text="Save setup", style="Primary.TButton", command=self.save).grid(row=0, column=0, sticky="e")

    # ------------------------------------------------------------------ behaviour

    def refresh_checks(self):
        """Run the checks against the boxes as they stand and show the rows."""
        rows = self.service.checks(self.library_var.get(), self.app_var.get(), self.extract_var.get())
        bullets = {"ok": "\u2022", "warn": "\u2022", "error": "\u2022"}
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        for level, message in rows:
            self.report.insert("end", f"{bullets.get(level, ' ')} ", level)
            self.report.insert("end", message + "\n", level)
        self.report.configure(state="disabled")

    def save(self):
        """Save the three folders and register the link, then show what happened."""
        saved, rows = self.service.apply(self.config, self.library_var.get(), self.app_var.get(), self.extract_var.get())
        errors = [message for level, message in rows if level == "error"]
        if errors:
            self.status.configure(text="Not saved: " + errors[0], fg=RED)
        elif saved:
            self.status.configure(text="Saved. The catalog's Extract buttons now work from this PC.", fg=GREEN)
            self._show_launch_button()
        else:
            self.status.configure(text="Not saved.", fg=RED)
        # The registration row flips from "not registered" to the command that was
        # written, so the reader sees the button was not the only thing that changed.
        self.refresh_checks()

    def _show_launch_button(self):
        """Show a button to close the wizard and launch the main application."""
        if not hasattr(self, "_launch_btn"):
            self._launch_btn = ttk.Button(self, text="Launch Steam Game Organizer", style="Primary.TButton", command=self._launch_app)
            self._launch_btn.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 16))
        else:
            self._launch_btn.grid()

    def _launch_app(self):
        """Close the wizard and start the main application window."""
        import subprocess
        import sys

        entry = Path(self.app_var.get()) / "steam_game_organizer.exe"
        if not entry.is_file():
            entry = Path(self.app_var.get()) / "steam_game_organizer.py"
        try:
            if entry.suffix == ".exe":
                subprocess.Popen([str(entry)], start_new_session=True)
            else:
                subprocess.Popen([sys.executable, str(entry)], start_new_session=True)
        except OSError as exc:
            self.logger.warning("SETUP", f"LAUNCH_FAILED entry=[{entry}] error={exc}")
        self.destroy()
