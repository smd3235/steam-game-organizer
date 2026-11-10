"""Opening a folder or a URL in whatever the desktop has been told to use for it.

Two call sites wanted the folder behaviour - Done's "Open Library Folder" and the Artwork screen's "OPEN GAME
FOLDER" - and both had their own copy of `shutil.which('xdg-open')`. xdg-open is the Linux opener, so on Windows
the lookup found nothing and the button did nothing at all: no file manager, no message, nothing logged.

The question either caller actually has is not "is any particular opener installed" but "did anything get
launched", so that is what these return. They never raise: a button that cannot do its job should say so, not
take the window down with it.

The xdg-open branch these used to fall through to is gone rather than left dormant. It was unreachable on this
platform, so it could never be exercised by a test, and dead platform code is how the next person ends up
maintaining two answers to one question.

Both refuse off Windows rather than half-working. Asking the shell to open a URL meant naming a browser binary,
which on Windows means naming one of five Linux package names or shelling out to Flatpak - none of which can
match, so the caller was told a browser was missing on a machine that had one. `os.startfile` asks the shell
association instead, which is the same answer a double-click would get.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def _windows_only() -> bool:
    return os.name == "nt"


def open_folder(path) -> bool:
    """Show `path` in the desktop's file manager. Returns whether anything was launched.

    A path that is not an existing folder is refused rather than handed to the shell, which would otherwise
    spawn a file manager pointed at something that is not there.
    """
    try:
        target = Path(path)
        if not target.is_dir():
            return False
    except (OSError, TypeError, ValueError):
        return False

    if not _windows_only():
        # This app runs on Windows. Refusing here is honest: the alternative was launching nothing and
        # reporting success, which is how the button was dead in the first place.
        return False

    # os.startfile is what Explorer is opened with, and it is in the standard library - no subprocess, no
    # console window flashing up for a fraction of a second. Path is passed as a string because startfile
    # does not accept a Path on every 3.x build.
    try:
        os.startfile(str(target))  # type: ignore[attr-defined]
        return True
    except (OSError, AttributeError):
        # A minimal Windows install has no shell association registered for directories. explorer.exe is
        # then the only route left, and it is always present.
        opener = shutil.which("explorer")
        if not opener:
            return False
        try:
            subprocess.Popen([opener, str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            return False


def open_url(url) -> bool:
    """Hand `url` to the default browser. Returns whether anything was launched.

    os.startfile is the shell association, so this opens whatever the user has actually chosen as their
    browser rather than insisting on Chrome - and it is the whole reason the caller stopped looking for a
    binary: on this machine none of `google-chrome-stable`, `google-chrome`, `chrome`, `chromium`,
    `chromium-browser` and `flatpak` is on PATH, so the search reported no browser on a Windows PC with one.

    A url is refused if it is not a string or does not look like one. A scheme this app never builds would
    otherwise be passed to the shell verbatim, and the shell will open whatever it is told to.
    """
    if not isinstance(url, str) or not url.strip():
        return False
    if not url.lower().startswith(("http://", "https://", "file://", "mailto:")):
        return False

    if not _windows_only():
        return False

    try:
        os.startfile(url)  # type: ignore[attr-defined]
        return True
    except (OSError, AttributeError):
        # A machine with no shell association registered for http has no default browser to ask. rundll32
        # is the handler Windows itself ships, so it is the last route rather than an assumption.
        handler = shutil.which("rundll32")
        if not handler:
            return False
        try:
            subprocess.Popen([handler, "url.dll,FileProtocolHandler", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            return False
