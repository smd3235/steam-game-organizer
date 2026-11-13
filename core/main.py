"""Extracted from steam_game_organizer.py.

    main was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

from pathlib import Path
import argparse
from core.constants import APP_NAME
from core.constants import VERSION
from core.config import AppConfig
from core.logger import AppLogger
from core.state import StateStore
from debug.diagnostics import Diagnostics
from steam_game_organizer import _extract_to_disk
from steam_game_organizer import _needs_setup
from steam_game_organizer import _open_setup
from core.handle_uri import _handle_uri


def main():
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--mock", action="store_true", help="Run deterministic mock data; no real library changes")
    parser.add_argument("--diagnostics", action="store_true")
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--version", action="store_true")
    parser.add_argument(
        "--uri", nargs="?", const="", default=None,
        help="Handle a steamgameorganizer:// link. Empty means launch the GUI, so one desktop "
             "entry can serve both the menu and the protocol handler")
    parser.add_argument("--extract", help="Extract an archive to the extract folder, then exit")
    parser.add_argument("--setup", action="store_true", help="Open the setup wizard: set the game library, app folder and extract folder for this PC, then exit")
    parser.add_argument("--dest", help="Destination folder for --extract (default: the extract folder)")
    parser.add_argument("--zip-password", default="", help="Password for an encrypted .zip or .rar")
    args = parser.parse_args()
    if args.version:
        print(VERSION)
        return 0
    # Resolve the project root so logs, config and cache always land in the same
    # place whether running from source or the frozen exe. Always search upward
    # from the entry point's directory for steam_game_organizer.py itself: that
    # directory is the project root, and every path the app writes (config/,
    # cache/, logs/, debug/) goes beneath it. On a borrowed HD the drive letter
    # changes but the directory layout does not.
    exe_dir = Path(__file__).resolve().parent
    root_path = exe_dir
    for candidate in [exe_dir] + list(exe_dir.parents):
        if (candidate / "steam_game_organizer.py").is_file():
            root_path = candidate
            break
    else:
        # steam_game_organizer.py was not found anywhere up the tree — fall back
        # to the entry point's own directory rather than silently writing state
        # to an unrelated drive root.
        root_path = exe_dir
    headless = args.version or args.diagnostics or args.health or args.uri is not None or args.extract
    # For headless invocations (URI handlers, diagnostics, etc.), reuse the most recent log file
    # instead of creating a new timestamped one, so all logs from a session go to the same file.
    log_file = None
    if headless:
        log_dir = root_path / "logs"
        if log_dir.is_dir():
            recent = sorted(log_dir.glob("organizer-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
            if recent:
                log_file = recent[0]
    config = AppConfig(root_path, log_file=log_file)
    config.mock_mode = args.mock
    config.ensure_directories()
    logger_kwargs = {"console": True} if headless else {}
    logger = AppLogger(config.log_file, **logger_kwargs)
    logger.install_excepthook()
    if args.diagnostics:
        print(Diagnostics(config, StateStore(), logger).report())
        return 0
    if args.health:
        print(Diagnostics(config, StateStore(), logger).health_text())
        return 0
    # The URI handler opens a result dialog for single extracts and the batch window for batch
    # extracts, so it needs Tk. It is kept before the main GUI launch so a protocol-handler click
    # from the catalog shows feedback without first drawing the full application window.
    if args.uri is not None and args.uri:
        return _handle_uri(args.uri, config, logger)
    if args.extract:
        return _extract_to_disk(args, config, logger)
    # The setup wizard is the one path that opens a window without a main window, and it is
    # the first-run path on a PC where the protocol handler is not registered yet - which is
    # exactly when the catalog's own setup button cannot be clicked.
    if args.setup:
        return _open_setup(config, logger)
    # A copied folder has never been configured: settings.json does not exist, and the default
    # library root is a path that is not there. Opening the GUI on that would put the reader in
    # the Scan screen looking at an empty folder with no indication of what to do, so the
    # wizard opens first. It is a Toplevel-free window of its own and exits when closed; the
    # reader then relaunches and the app opens normally.
    # wizard opens first. When the save succeeds the app hands off to the main
    # window without an extra launch; if the reader dismissed it without saving,
    # the wizard's 0 return keeps the app in setup mode until a save succeeds.
    needed_setup = _needs_setup(config)
    setup_result = _open_setup(config, logger) if needed_setup else None
    if setup_result is not None:
        return setup_result
    if needed_setup:
        try:
            from services.catalog_service import CatalogService

            CatalogService(logger, extract_folders=config.extract_folders).generate(config.library_root)
        except Exception as exc:
            logger.warning("SETUP", f"CATALOG_REGEN_FAILED error={type(exc).__name__}: {exc}")
    try:
        import tkinter as tk
        from app.application import Application
    except ModuleNotFoundError as exc:
        if exc.name == "tkinter":
            # The message names Windows because that is the only platform this runs on. It used to suggest
            # the Debian package python3-tk and re-exec through flatpak-spawn, neither of which exists here,
            # so a missing tkinter produced instructions for a different operating system.
            parser.error("Tkinter is required for the GUI. Re-run the Python installer and tick 'tcl/tk and IDLE'.")
        raise
    root = tk.Tk()
    return Application(root, args.mock, config=config).run()
