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

import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from core.constants import ARCHIVE_EXTENSIONS, LIBRARY_RESERVED_DIRS

SCHEME = "steamgameorganizer"
UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Folders a typed destination may never be. The catalog page accepts a free-text path, and unpacking a 40 GB
# game into one of these is unrecoverable without root, so they are refused by name rather than left to the
# user to avoid.
def _system_paths():
    """Folders a typed destination may never sit inside.

    Read from the environment rather than spelled out, because Windows, Program Files and ProgramData are not
    reliably where a hard-coded list says they are. Folders are case-folded with the platform's own rule,
    because C:\\Windows and C:\\WINDOWS are the same folder here and only one of them is the spelling a user
    types.

    The POSIX half of this list is gone. Every one of those paths is absolute on Windows too, so they could
    never have matched a resolved destination - which begins with a drive letter - and a list that reads as
    though it covers two platforms is worse than one that says plainly which platform it does.
    """
    paths=set()
    for variable in ("SystemRoot","ProgramFiles","ProgramFiles(x86)","ProgramData","ProgramW6432"):
        value=os.environ.get(variable)
        if value: paths.add(value)
    return tuple(sorted(os.path.normcase(os.path.normpath(p)) for p in paths))

SYSTEM_PATHS=_system_paths()


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


def safe_folder_name(text: str, fallback: str = "Extracted") -> str:
    """A single path component that is safe on every filesystem this can land on.

    Windows reserved device names and a trailing dot or space are stripped too: the catalog that supplies
    these names may sit on a synced or shared folder, and a folder named "CON" is unusable
    the moment it reaches one.
    """
    cleaned = UNSAFE_CHARS.sub(" ", unicodedata.normalize("NFKC", str(text or "")))
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    reserved = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}
    if not cleaned or cleaned.casefold() in reserved:
        return fallback
    return cleaned[:120]


def _within(candidate: Path, root: Path) -> bool:
    """True when candidate is root itself or sits under it.

    Both sides are fully resolved first, because '..' segments and symlinks are exactly what this is guarding
    against; comparing the unresolved strings would let /library/../etc pass.
    """
    try:
        candidate = candidate.resolve()
        root = root.resolve()
    except OSError:
        return False
    return candidate == root or root in candidate.parents


def _setup_hint():
    """The pointer every fresh-PC refusal carries.

    The three folders the Extract links are checked against are set by the
    setup wizard, and the page that fired the link carries the button that
    opens it - so a refusal on a PC that has not been set up yet names the
    fix rather than only the rule.
    """
    return " The Set up on this PC button at the top of the catalog points this app at the library."


def _configured_bases(extract_base):
    """The folders the user has already chosen, as a list. None means nowhere is approved."""
    if not extract_base:
        return []
    entries = extract_base if isinstance(extract_base, (list, tuple)) else [extract_base]
    return [Path(p).expanduser() for p in entries]


def _destination_parent(raw_destination, bases, library_root):
    """The folder a game's own subfolder will be created inside, or refuse.

    Shared by the single and batch actions so the two cannot drift on what counts as an acceptable destination -
    the free-text case in particular is a security boundary, and a second copy of it would be a second thing to
    get wrong.
    """
    if not bases:
        raise UriRefused("No extract folder is configured, so there is nowhere to unpack to."
                         + _setup_hint())
    raw_destination = (raw_destination or "").strip()
    if not raw_destination:
        return bases[0]
    return _typed_destination(raw_destination, library_root)


def _category_folder(raw_category, library_root):
    """The category directory named by a batch link, or refuse.

    The name arrives from a web page, so it is treated as a path fragment rather than a label: it has to be a
    single component with no separators, it may not walk upwards, and the folder it names has to actually be a
    directory inside the library. Checking the resolved folder rather than the string is what makes the last two
    rules hold for '..', for a symlink, and for a drive letter.
    """
    name = (raw_category or "").strip()
    if not name:
        raise UriRefused("The link did not say which category to extract.")
    # A separator, a drive, or a walk upwards all mean the name was never a category.
    if name in (".", "..") or "/" in name or "\\" in name or ":" in name:
        raise UriRefused(f"That is not a category name: {name}")
    if name.startswith("."):
        raise UriRefused(f"Refused: {name} is a hidden folder, not a category.")
    if name in LIBRARY_RESERVED_DIRS:
        raise UriRefused(f"Refused: {name} is a folder the app keeps for itself, not a category.")
    folder = library_root / name
    if not _within(folder, library_root):
        raise UriRefused(f"Refused: {name} is outside the game library.")
    if not folder.is_dir():
        raise UriRefused(f"There is no category called {name} in this library.")
    return folder


def parse_batch_uri(uri: str, library_root: Path, extract_base):
    """Returns a BatchExtractRequest naming a category, or raises UriRefused with a message for the user.

    The same three rules as a single extract, with the source rule inverted: because no source is named, the
    category is the only thing that needs checking, and the caller enumerates the library rather than trusting
    anything the page said. An empty category means the whole library and skips the folder check.
    """
    parts = urlsplit(str(uri))
    if parts.scheme.casefold() != SCHEME:
        raise UriRefused(f"Unsupported link type: {parts.scheme or 'none'}")
    action = (parts.netloc or parts.path.lstrip("/")).strip().casefold()
    if action not in ("extract-all","extract-remaining"):
        raise UriRefused(f"Unknown action: {action or 'none'}")
    if library_root is None:
        raise UriRefused("No game library is configured, so there is nothing to extract from."
                         + _setup_hint())
    bases = _configured_bases(extract_base)
    query = parse_qs(parts.query)
    parent = _destination_parent((query.get("dest") or [""])[0], bases, library_root)
    category = (query.get("category") or [""])[0].strip()
    if category:
        _category_folder(category, library_root)
    return BatchExtractRequest(category=category, destination=parent)


def parse_multi_uri(uri: str, library_root: Path, extract_base):
    """Returns a MultiBatchRequest of individually-validated archive paths, or raises.

    Each src parameter is validated exactly as parse_uri validates a single extract:
    it must resolve inside the library root, exist on disk, and carry an archive extension.
    A hostile page can only ask for files the user already owns, the same boundary a
    single Extract link has. The destination is shared and subject to the same typing rules.
    """
    parts = urlsplit(str(uri))
    if parts.scheme.casefold() != SCHEME:
        raise UriRefused(f"Unsupported link type: {parts.scheme or 'none'}")
    action = (parts.netloc or parts.path.lstrip("/")).strip().casefold()
    if action != "extract-multi":
        raise UriRefused(f"Unknown action: {action or 'none'}")
    if library_root is None:
        raise UriRefused("No game library is configured, so there is nothing to extract from."
                         + _setup_hint())
    bases = _configured_bases(extract_base)
    query = parse_qs(parts.query)
    parent = _destination_parent((query.get("dest") or [""])[0], bases, library_root)
    raw_sources = query.get("src") or []
    if len(raw_sources) < 2:
        raise UriRefused("Select at least two games to multi-extract.")
    archives: list[tuple[Path, Path]] = []
    for raw in raw_sources:
        archive = Path(raw).expanduser()
        if not _within(archive, library_root):
            raise UriRefused(f"Refused: {raw} is outside the game library." + _setup_hint())
        if not archive.is_file():
            raise UriRefused(f"That archive is not there any more: {archive.name}")
        if archive.suffix.lower() not in ARCHIVE_EXTENSIONS:
            raise UriRefused(f"Not an archive this can unpack: {archive.name}")
        leaf = safe_folder_name(archive.stem)
        archives.append((archive, parent / leaf))
    if not archives:
        raise UriRefused("No valid archives were selected.")
    return MultiBatchRequest(archives=archives, destination=parent)


def parse_setup_uri(uri: str) -> SetupRequest:
    """Returns the setup prefills a steamgameorganizer://setup link carries, or refuses.

    No source or destination is named, so there is nothing to check against the library
    root: the three values only ever seed text boxes, and the wizard that reads them
    validates everything before saving.
    """
    parts = urlsplit(str(uri))
    if parts.scheme.casefold() != SCHEME:
        raise UriRefused(f"Unsupported link type: {parts.scheme or 'none'}")
    action = (parts.netloc or parts.path.lstrip("/")).strip().casefold()
    if action != "setup":
        raise UriRefused(f"Unknown action: {action or 'none'}")
    query = parse_qs(parts.query)
    return SetupRequest(
        library=_prefill(query.get("library")),
        extract=_prefill(query.get("extract")),
        app=_prefill(query.get("app")),
    )


def _prefill(values):
    """One query value, cleaned for a text box: control characters dropped, length capped.

    A path box holds a path, and a path is neither a megabyte long nor full of newlines;
    the cap is what keeps a hostile link from stuffing something enormous into the
    wizard's fields.
    """
    text = (values or [""])[0]
    text = "".join(ch for ch in text if ch >= " ")
    return text.strip()[:1000]


def _parse_extract_root_action(uri: str, extract_folders, expected_action: str, *, must_have_marker: bool = False) -> Path:
    parts = urlsplit(str(uri))
    if parts.scheme.casefold() != SCHEME:
        raise UriRefused(f"Unsupported link type: {parts.scheme or 'none'}")
    action = (parts.netloc or parts.path.lstrip("/")).strip().casefold()
    if action != expected_action:
        raise UriRefused(f"Unknown action: {action or 'none'}")
    bases = _configured_bases(extract_folders)
    if not bases:
        raise UriRefused("No extract folder is configured." + _setup_hint())
    raw = (parse_qs(parts.query).get("path") or [""])[0]
    if not raw:
        raise UriRefused("The link did not say which folder to use.")
    folder = Path(raw).expanduser()
    if not any(_within(folder, b) for b in bases):
        raise UriRefused(f"Refused: {raw} is outside the configured extract folders.")
    try:
        folder = folder.resolve(strict=True)
    except OSError as exc:
        raise UriRefused(f"That folder cannot be opened: {exc}") from exc
    if not folder.is_dir():
        raise UriRefused(f"That folder is not there any more: {folder.name}")
    if must_have_marker and not (folder / '.sgo-extract-info').is_file():
        raise UriRefused(f"That extracted folder has no marker information: {folder.name}")
    return folder


def parse_pick_launcher_uri(uri: str, extract_folders) -> Path:
    """Returns the extracted marker/root directory for a pick-launcher action."""
    return _parse_extract_root_action(uri, extract_folders, 'pick-launcher', must_have_marker=True)


def parse_mark_installed_uri(uri: str, extract_folders) -> Path:
    """Returns the extracted marker/root directory for a mark-installed action."""
    return _parse_extract_root_action(uri, extract_folders, 'mark-installed', must_have_marker=True)


def parse_play_uri(uri: str, extract_folders) -> PlayRequest:
    """Returns a validated PlayRequest for a steamgameorganizer://play link.

    `exe` may point directly at an executable, or `path` may point at a marker/root
    directory whose persisted `launch_target` should be used. The target must be a
    `.exe` file under configured extract folders.
    """
    parts = urlsplit(str(uri))
    if parts.scheme.casefold() != SCHEME:
        raise UriRefused(f"Unsupported link type: {parts.scheme or 'none'}")
    action = (parts.netloc or parts.path.lstrip("/")).strip().casefold()
    if action != 'play':
        raise UriRefused(f"Unknown action: {action or 'none'}")
    bases = _configured_bases(extract_folders)
    if not bases:
        raise UriRefused("No extract folder is configured." + _setup_hint())
    query = parse_qs(parts.query)
    raw_exe = (query.get('exe') or [''])[0]
    raw_marker = (query.get('path') or query.get('marker') or [''])[0]
    marker_dir = None
    if raw_marker:
        marker_dir = _parse_extract_root_action(
            f"{SCHEME}://pick-launcher?path={raw_marker}", extract_folders, 'pick-launcher', must_have_marker=False)
    exe_path = None
    if raw_exe:
        exe = Path(raw_exe).expanduser()
        if not any(_within(exe, b) for b in bases):
            raise UriRefused(f"Refused: {raw_exe} is outside the configured extract folders.")
        try:
            exe_path = exe.resolve(strict=True)
        except OSError as exc:
            raise UriRefused(f"That launcher cannot be opened: {exc}") from exc
        if not exe_path.is_file() or exe_path.suffix.lower() != '.exe':
            raise UriRefused("Play links may only launch .exe files inside extract folders.")
    elif marker_dir is not None:
        from services.catalog_status import get_launch_target
        exe_path = get_launch_target(marker_dir, bases)
        if exe_path is None:
            raise UriRefused("No saved launcher is set for this game. Use Pick launcher first.")
    else:
        raise UriRefused("The link did not say what to launch.")
    return PlayRequest(exe=exe_path, marker_dir=marker_dir)


def parse_open_extracted_uri(uri: str, extract_folders) -> Path:
    """Returns the folder path a steamgameorganizer://open-extracted link carries, or refuses.

    Opens the extracted game (or installer) folder. The path must be inside one of the configured
    extract folders (resolved/normalized so drive-letter/UNC case and symlinks do not cause false
    refusals on Windows).
    """
    parts = urlsplit(str(uri))
    if parts.scheme.casefold() != SCHEME:
        raise UriRefused(f"Unsupported link type: {parts.scheme or 'none'}")
    action = (parts.netloc or parts.path.lstrip("/")).strip().casefold()
    if action != "open-extracted":
        raise UriRefused(f"Unknown action: {action or 'none'}")
    bases = _configured_bases(extract_folders)
    if not bases:
        raise UriRefused("No extract folder is configured." + _setup_hint())
    raw = (parse_qs(parts.query).get("path") or [""])[0]
    if not raw:
        raise UriRefused("The link did not say which folder to open.")
    folder = Path(raw).expanduser()
    if not any(_within(folder, b) for b in bases):
        raise UriRefused(f"Refused: {raw} is outside the configured extract folders.")
    try:
        folder = folder.resolve(strict=True)
    except OSError as exc:
        raise UriRefused(f"That folder cannot be opened: {exc}") from exc
    if not folder.is_dir():
        raise UriRefused(f"That folder is not there any more: {folder.name}")
    return folder


def parse_uri(uri: str, library_root: Path, extract_base):
    """Returns an ExtractRequest, or raises UriRefused with a message for the user.

    extract_base may be one destination or an iterable of them, matching AppConfig.extract_folders. A page
    offers that same list, and every entry in it has already been chosen by the user, so each is trusted
    equally - but nothing outside the list is.
    """
    bases=_configured_bases(extract_base)
    if not uri:
        raise UriRefused("No action was given.")
    parts = urlsplit(str(uri))
    if parts.scheme.casefold() != SCHEME:
        raise UriRefused(f"Unsupported link type: {parts.scheme or 'none'}")
    # urlsplit puts the host in netloc, so extract://?x=1 arrives as path=''
    action = (parts.netloc or parts.path.lstrip("/")).strip().casefold()
    if action != "extract":
        raise UriRefused(f"Unknown action: {action or 'none'}")

    if library_root is None:
        raise UriRefused("No game library is configured, so there is nothing to extract from."
                         + _setup_hint())
    raw_source = (parse_qs(parts.query).get("src") or [""])[0]
    if not raw_source:
        raise UriRefused("The link did not say which archive to extract.")

    archive = Path(raw_source).expanduser()
    if not _within(archive, library_root):
        # The common fresh-PC case: the page names a folder this app has never
        # been set up to use, so the refusal says how to point it there.
        raise UriRefused(f"Refused: {raw_source} is outside the game library." + _setup_hint())
    if not archive.is_file():
        raise UriRefused(f"That archive is not there any more: {archive.name}")
    if archive.suffix.lower() not in ARCHIVE_EXTENSIONS:
        raise UriRefused(f"Not an archive this can unpack: {archive.name}")

    # Each game gets its own folder under the chosen parent, so extracting a second game does not mix it
    # with the first and a typo cannot scatter files next to unrelated ones.
    leaf = safe_folder_name(archive.stem)
    raw_destination = (parse_qs(parts.query).get("dest") or [""])[0]
    parent = _destination_parent(raw_destination, bases, library_root)
    return ExtractRequest(archive=archive, destination=parent / leaf)


def _typed_destination(raw: str, library_root: Path) -> Path:
    """Validates a destination the user typed into the catalog page.

    The page offers a free-text box, so this cannot be the 'must be inside a pre-approved folder' check the
    configured list uses. What still holds: the path has to be absolute (a relative one would land wherever the
    handler happens to be started from), it may not sit inside a system folder or be the home folder itself, and
    it may not sit inside the game library, where unpacking would be picked up as new game folders on the next
    scan. Refusing a few known-bad targets is weaker than a fixed allow-list and is honest about being so.
    """
    expanded = Path(raw).expanduser()
    if not expanded.is_absolute():
        raise UriRefused(f"That is not a full path, so it would unpack somewhere unknown: {raw}")
    try:
        expanded = expanded.resolve()
    except OSError as exc:
        raise UriRefused(f"Cannot use that destination: {exc}") from exc
    if expanded.parent == expanded:
        raise UriRefused(f"Refused: {expanded} is the filesystem root.")
    if expanded == Path.home().resolve():
        raise UriRefused(f"Refused: {expanded} is your home folder. Pick a folder inside it.")
# Every folder on the way up is checked, not just the destination itself, so C:\Windows\System32\games is
    # refused as readily as the destination that contains it. That is also what catches a junction, which
    # resolve() rewrites to its target and an exact-match list would then wave through.
    for parent in (expanded, *expanded.parents):
        if os.path.normcase(str(parent)) in SYSTEM_PATHS:
            raise UriRefused(f"Refused: {expanded} is inside a system folder.")
    if _within(expanded, library_root):
        raise UriRefused(f"Refused: {expanded} is inside the game library. Choose somewhere outside it.")
    if expanded.exists():
        if not expanded.is_dir():
            raise UriRefused(f"That destination is a file, not a folder: {expanded}")
    else:
        # Allow a folder that is not created yet, but only if the closest folder that does exist can be written.
        ancestor = expanded.parent
        while not ancestor.exists() and ancestor != ancestor.parent:
            ancestor = ancestor.parent
        if not ancestor.is_dir() or not os.access(ancestor, os.W_OK):
            raise UriRefused(f"Cannot create a folder there: {ancestor} is not writable.")
    return expanded
def parse_open_folder_uri(uri: str, library_root) -> Path:
    """Returns the library folder path a steamgameorganizer://open-folder link carries, or refuses."""
    parts = urlsplit(str(uri))
    if parts.scheme.casefold() != SCHEME:
        raise UriRefused(f"Unsupported link type: {parts.scheme or 'none'}")
    action = (parts.netloc or parts.path.lstrip('/')).strip().casefold()
    if action != 'open-folder':
        raise UriRefused(f"Unknown action: {action or 'none'}")
    if library_root is None:
        raise UriRefused('No game library is configured.' + _setup_hint())
    raw = (parse_qs(parts.query).get('path') or [''])[0]
    if not raw:
        raise UriRefused('The link did not say which folder to open.')
    folder = Path(raw).expanduser()
    if not _within(folder, library_root):
        raise UriRefused(f'Refused: {raw} is outside the game library.' + _setup_hint())
    try:
        folder = folder.resolve(strict=True)
    except OSError as exc:
        raise UriRefused(f'That folder cannot be opened: {exc}') from exc
    if not folder.is_dir():
        raise UriRefused(f'That folder is not there any more: {folder.name}')
    return folder
