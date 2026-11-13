"""Turns a steamgameorganizer:// URI into an extraction request, or refuses it.

A registered protocol handler is the one supported way for a web page to ask the machine to do something, and
it is also the one way a web page can try to make a local program touch an arbitrary path. Anything can craft
the link, including another page the user happens to visit, so this module treats every field as hostile input.

Three rules, and each one exists because without it the link is a remote file-write:

  1. The source must resolve inside the configured library root. Otherwise the handler would be a way to ask
     the machine to unpack /etc or the user's home directory.
  2. The source must already exist and carry an archive extension, so the check above cannot be satisfied with
     a path that only looks like it points into the library.
  3. The destination must be a usable folder: either inside the configured extract folder, omitted so a safe
     default is derived, or a full path the user typed into the catalog page that is not a system folder and not
     inside the library. See _typed_destination for what the free-text case still rules out.

Nothing here runs a command or touches the disk beyond resolving paths; the caller does that.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from core.system_paths import _system_paths
SCHEME = "steamgameorganizer"
UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Folders a typed destination may never be. The catalog page accepts a free-text path, and unpacking a 40 GB
# game into one of these is unrecoverable without root, so they are refused by name rather than left to the
# user to avoid.

SYSTEM_PATHS = _system_paths()

@dataclass
class ExtractRequest:
    archive: Path
    destination: Path

@dataclass
class PlayRequest:
    """A request to launch a validated game executable under configured extract folders."""

    exe: Path
    marker_dir: Path | None = None

@dataclass
class ExtractRootRequest:
    """A request that targets an extracted root/marker directory under extract folders."""

    folder: Path

@dataclass
class SetupRequest:
    """The three paths a fresh PC has to be told, as the page offered them.

    Every field is a prefill for a box the user edits before anything is saved, not a
    command: the wizard that reads this re-validates each path against the disk before
    it touches a setting or the registry. A hostile page can put anything in here, and
    the worst that can happen is a nonsense string sitting in a text box.
    """

    library: str = ""
    extract: str = ""
    app: str = ""

@dataclass
class BatchExtractRequest:
    """A request to unpack many archives, named by category rather than by path.

    Deliberately carries no archive list. A single-extract link names one file and is checked against the
    library root, so a hostile page can at worst ask for a file the user already owns. A batch link that carried
    its own list would be the same handler pointed at an arbitrary set of sources, and the check would have to
    be repeated per entry - the kind of rule that is right until one entry is missed. So the link names a
    category and the app enumerates the library itself, which leaves the page able to say "Idle" and nothing
    more.
    """

    category: str
    destination: Path

@dataclass
class MultiBatchRequest:
    """A request to unpack a user-selected set of archives from the catalog.

    Each archive path is validated individually against the library root by parse_multi_uri(), using the same
    rules as parse_uri - so a hostile page can at worst ask for archives the user already owns. The destination
    is shared across all items, same as BatchExtractRequest.
    """

    archives: list[tuple[Path, Path]]
    destination: Path

class UriRefused(Exception):
    """Raised with a message meant for the user, not a traceback."""

