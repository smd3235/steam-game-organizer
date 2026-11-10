"""The three-path setup a fresh PC needs, and the one place those paths are saved.

A web page cannot write a file, so the Game folder and Extract to boxes in the catalog
are only remembered by the browser - they never reach this app. What the app itself has
to be told is what the protocol handler validates every Extract link against: the library
root (a source is refused if it is not inside it) and the extract folders (the
destination a link with no destination falls back to). Both live in config/settings.json
beside the app, and on a PC that has never run the setup they hold the defaults - which
is why an Extract button on a friend's machine refuses every link the page can build,
no matter what is typed into the page's own boxes.

The wizard this service backs is opened two ways: the "Set up on this PC" button at the
top of the catalog, and --setup on the command line for the first run on a machine where
the protocol handler is not registered yet, because a button that goes through that
handler cannot be the thing that installs it.
"""

from pathlib import Path
import os
import sys

from core.constants import ENTRY_POINT, LIBRARY_RESERVED_DIRS
from services.extract_service import ExtractService


def _default_register(python, entry):
    from tools.install_protocol_handler import install_windows

    install_windows(python, entry)


def _default_registered():
    from tools.install_protocol_handler import _registered_command

    return _registered_command()


def _library_has_games(root):
    """Whether the library holds at least one organized game folder.

    The same shape the scanner and the catalog walk: a category folder holding game
    folders. One level of each is enough to say "there are games here"; counting them
    is the scan's job, not the setup's.
    """
    try:
        for category in root.iterdir():
            if not category.is_dir() or category.name in LIBRARY_RESERVED_DIRS:
                continue
            if any(game.is_dir() for game in category.iterdir()):
                return True
    except OSError:
        return False
    return False


def _writable_or_creatable(path):
    """True when the folder exists and is writable, or can be created under a writable
    parent. The nearest existing ancestor is what answers the second case."""
    if path.exists():
        return path.is_dir() and os.access(path, os.W_OK)
    ancestor = path.parent
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    return ancestor.is_dir() and os.access(ancestor, os.W_OK)


class SetupService:
    """Answers the three setup questions and saves the answers.

    register_handler and registered_command are injected so a test can watch a
    registration without touching the registry; both default to the functions in
    tools/install_protocol_handler.py, which write HKCU\\Software\\Classes.
    """

    def __init__(self, logger, register_handler=None, registered_command=None):
        self.logger = logger
        self._register = register_handler or _default_register
        self._registered = registered_command or _default_registered

    def checks(self, library, app, extract):
        """What is wrong with these three paths, as (level, message) rows.

        level is 'error' (the save would be refused or nothing would work), 'warn'
        (it works, but badly) or 'ok'. These rows are what the wizard shows before
        anything is saved, so a user can see why a save would be refused rather than
        try and fail.
        """
        rows = []
        library = Path(library or "").expanduser()
        app = Path(app or "").expanduser()
        extract = Path(extract or "").expanduser()
        if not str(library).strip():
            rows.append(("error", "No game library folder was given."))
        elif not library.is_dir():
            rows.append(("warn", f"The game library does not exist yet: {library} - it will be created"))
        elif not _library_has_games(library):
            rows.append(("warn", f"The game library holds no organized games yet: {library} - run a scan once the setup is saved"))
        else:
            rows.append(("ok", f"Game library: {library}"))
        entry = app / ENTRY_POINT
        exe_entry = app / (ENTRY_POINT.replace(".py", ".exe"))
        if not str(app).strip():
            rows.append(("error", "No app folder was given."))
        elif not app.is_dir():
            rows.append(("error", f"The app folder is not a folder: {app}"))
        elif not entry.is_file() and not exe_entry.is_file():
            rows.append(("error", f"No {ENTRY_POINT} or {ENTRY_POINT.replace('.py', '.exe')} in {app} - this is not the app's folder"))
        else:
            rows.append(("ok", f"App folder: {app}"))
        if not str(extract).strip():
            rows.append(("error", "No extract folder was given."))
        elif extract.exists() and not extract.is_dir():
            rows.append(("error", f"The extract folder is a file, not a folder: {extract}"))
        elif not _writable_or_creatable(extract):
            rows.append(("error", f"The extract folder is not writable: {extract}"))
        elif library.is_dir() and _within(extract, library):
            # The same rule every typed destination is held to: an extracted game is a
            # folder of loose files, and the scanner treats every directory inside a
            # category as a game folder, so extracting into the library would hand the
            # next scan the unpacked files as games to reconsider.
            rows.append(("error", f"The extract folder is inside the game library. Choose a folder outside it: {extract}"))
        else:
            rows.append(("ok", f"Extract to: {extract}"))
        found, reason = ExtractService.find_tool()
        if not found:
            rows.append(("warn", f"No 7-Zip was found ({reason}), so Extract will not work until it is installed"))
        command = self._registered()
        if command:
            rows.append(("ok", f"The steamgameorganizer:// link is registered: {command}"))
        else:
            rows.append(("warn", "The steamgameorganizer:// link is not registered, so the catalog's Extract buttons do nothing. Saving this setup registers it."))
        return rows

    def apply(self, config, library, app, extract):
        """Save the three paths and register the handler. Returns (saved, rows).

        The checks run first and any error refuses the save: AppConfig.save() would
        silently drop a library root the disk does not have, and a registration
        pointing at a folder with no entry point would leave every Extract link dead
        with nothing on the page to say why.
        """
        rows = self.checks(library, app, extract)
        if any(level == "error" for level, _ in rows):
            return False, rows
        library = Path(library or "").expanduser()
        app = Path(app or "").expanduser()
        extract = Path(extract or "").expanduser()
        config.library_root = library
        library.mkdir(parents=True, exist_ok=True)
        config.save()
        config.extract_folders = [extract]
        entry = app / ENTRY_POINT
        if not entry.is_file():
            entry = app / ENTRY_POINT.replace(".py", ".exe")
        try:
            self._register(sys.executable, entry)
        except OSError as exc:
            # The paths are saved by now, so they stick; only the handler failed, and
            # the user can run the installer again. Reported, not raised: a wizard that
            # dies here would look like the save never happened.
            self.logger.warning("SETUP", f"HANDLER_REGISTER_FAILED error={type(exc).__name__}")
            rows.append(("warn", f"Paths saved, but the link could not be registered: {exc}"))
            return True, rows
        rows.append(("ok", "Saved. The catalog's Extract buttons now work from this PC."))
        return True, rows


def _within(candidate, root):
    """True when candidate sits under root. Resolved first, so '..' and a symlink or
    junction cannot walk out of the comparison."""
    try:
        candidate = candidate.resolve()
        root = root.resolve()
    except OSError:
        return False
    return candidate == root or root in candidate.parents
