"""Extracted from core/uri_actions.py.

    parse_play_uri was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

from pathlib import Path
from urllib.parse import parse_qs
from urllib.parse import urlsplit
from core.within import _within
from core.setup_hint import _setup_hint
from core.configured_bases import _configured_bases
from core.uri_actions import PlayRequest
from core.uri_actions import SCHEME
from core.uri_actions import UriRefused
from core.parse_extract_root_action import _parse_extract_root_action


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
    if action != "play":
        raise UriRefused(f"Unknown action: {action or 'none'}")
    bases = _configured_bases(extract_folders)
    if not bases:
        raise UriRefused("No extract folder is configured." + _setup_hint())
    query = parse_qs(parts.query)
    raw_exe = (query.get("exe") or [""])[0]
    raw_marker = (query.get("path") or query.get("marker") or [""])[0]
    marker_dir = None
    if raw_marker:
        marker_dir = _parse_extract_root_action(f"{SCHEME}://pick-launcher?path={raw_marker}", extract_folders, "pick-launcher", must_have_marker=False)
    exe_path = None
    if raw_exe:
        exe = Path(raw_exe).expanduser()
        if not any(_within(exe, b) for b in bases):
            raise UriRefused(f"Refused: {raw_exe} is outside the configured extract folders.")
        try:
            exe_path = exe.resolve(strict=True)
        except OSError as exc:
            raise UriRefused(f"That launcher cannot be opened: {exc}") from exc
        if not exe_path.is_file() or exe_path.suffix.lower() != ".exe":
            raise UriRefused("Play links may only launch .exe files inside extract folders.")
    elif marker_dir is not None:
        from services.catalog_status import get_launch_target

        exe_path = get_launch_target(marker_dir, bases)
        if exe_path is None:
            raise UriRefused("No saved launcher is set for this game. Use Pick launcher first.")
    else:
        raise UriRefused("The link did not say what to launch.")
    return PlayRequest(exe=exe_path, marker_dir=marker_dir)
