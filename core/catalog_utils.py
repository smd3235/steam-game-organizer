"""Pure utility functions extracted from CatalogService.

These functions have no dependency on CatalogService instance state and can be
imported and tested independently. They were previously methods on CatalogService
that took all their inputs as parameters.
"""

from __future__ import annotations

import re
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from core.uri_actions import SCHEME
from utils.formatting import human_size


BANNER_PRIORITY = ("header_image", "library_hero", "capsule_imagev5", "capsule_image", "library_capsule", "grid")


def safe_name(value: str) -> str:
    """Sanitise a Steam game name into a filesystem-safe folder prefix.

    Strips illegal Windows characters, collapses whitespace, and falls back to
    "Unnamed Game" for empty input. Previously CatalogService._safe_name.
    """
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(value or "")).strip().rstrip(".")
    return re.sub(r"\s+", " ", value) or "Unnamed Game"


def clean_tags(raw) -> list[str]:
    """Steam's tag list, as a list of non-empty, de-duplicated strings.

    Defensive about the type because this is read out of a JSON sidecar the app
    wrote but a person can also edit. Previously CatalogService._clean_tags.
    """
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    seen: list[str] = []
    for value in raw:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.append(text)
    return seen


def archive_size(game_dir) -> int:
    """Size in bytes of the first archive found in a game folder."""
    try:
        for path in game_dir.iterdir():
            if path.is_file() and path.suffix.lower() in (".zip", ".rar", ".7z"):
                return path.stat().st_size
    except OSError:
        pass
    return 0


def archive_created(game_dir) -> str:
    """Archive file creation timestamp as an ISO string, or empty string."""
    try:
        for path in game_dir.iterdir():
            if path.is_file() and path.suffix.lower() in (".zip", ".rar", ".7z"):
                st = path.stat()
                from datetime import datetime

                return datetime.fromtimestamp(st.st_ctime).strftime("%Y-%m-%d %H:%M")
    except OSError:
        pass
    return ""


def find_banner(game_dir, prefix):
    """The best banner image for a game folder, by priority then any image file."""
    marker = prefix + "_"
    files = {}
    for f in game_dir.glob("*"):
        if f.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            continue
        if f.stem.startswith(marker):
            files[f.stem[len(marker) :]] = f
    for key in BANNER_PRIORITY:
        if key in files:
            return files[key]
    for f in sorted(game_dir.glob("*")):
        if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            return f
    return None


def store_url(appid: str) -> str:
    """Steam store page URL for an appid."""
    return f"https://store.steampowered.com/app/{appid}/"


def steam_protocol_url(appid: str) -> str:
    """steam:// protocol link for an appid."""
    return f"steam://store/{appid}"


def anchor(name: str) -> str:
    """URL-safe anchor/fragment from a category or game name."""
    return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or "category"


def path_within(candidate, root) -> bool:
    """True when candidate resolves to root or lives somewhere beneath it."""
    try:
        candidate = Path(candidate).resolve()
        root = Path(root).resolve()
    except OSError:
        return False
    return candidate == root or root in candidate.parents


def asset_prefix(game_dir, metadata=None) -> str:
    """Filesystem-safe asset prefix for a game folder.

    Prefers the metadata Steam name when available, otherwise derives it from the
    folder name by stripping a trailing date stamp. Previously CatalogService._asset_prefix.
    """
    name = (metadata or {}).get("name")
    if name:
        return safe_name(name)
    return re.sub(r"\s*-\s*(?:\d{4}-\d{2}-\d{2}|Unknown Release Date)$", "", game_dir.name).strip() or game_dir.name


def batch_uri(category: str) -> str:
    """steamgameorganizer:// link that unpacks a category, or the whole library when empty."""
    query = urlencode({"category": category}) if category else ""
    return f"{SCHEME}://extract-all?{query}" if query else f"{SCHEME}://extract-all"


def remaining_uri() -> str:
    """steamgameorganizer:// link that unpacks only games not already extracted."""
    return f"{SCHEME}://extract-remaining"


def setup_uri() -> str:
    """steamgameorganizer:// link that opens the setup wizard."""
    return f"{SCHEME}://setup"


def refresh_uri() -> str:
    """steamgameorganizer:// link that asks the app to regenerate the catalog."""
    return f"{SCHEME}://refresh-catalog"


def extract_uri(game) -> str:
    """steamgameorganizer:// link for a game's archive, percent-encoded."""
    name = game.get("archive") or ""
    if not name:
        return ""
    source = Path(game["folder"]) / name
    return f"{SCHEME}://extract?{urlencode({'src': str(source)})}"


def open_folder_uri(game) -> str:
    """steamgameorganizer://open-folder link for a game's folder."""
    folder_rel = game.get("folder_rel") or ""
    return f"{SCHEME}://open-folder?{urlencode({'path': folder_rel})}"


def batch_button(category, count, total_bytes, label, title, scope=""):
    """HTML for a batch Extract link carrying a category name."""
    if not count:
        return ""
    detail = f"{count} game{'' if count == 1 else 's'}"
    if total_bytes:
        detail += f", {human_size(total_bytes)}"
    shown = scope or category
    return (
        f'<a class="btn btn-batch" href="{batch_uri(category)}" data-batch="{batch_uri(category)}" '
        f'data-batch-count="{count}" data-batch-size="{int(total_bytes or 0)}" '
        f'data-batch-name="{escape(shown)}" data-batch-confirm="{escape(title)} ({escape(detail)})">'
        f"{label} {count}</a>"
    )


def remaining_button(count, label, title) -> str:
    """HTML for a batch Extract link that unpacks only not-yet-extracted games."""
    if not count:
        return ""
    detail = f"{count} game{'' if count == 1 else 's'}"
    shown = "the remaining games"
    return (
        f'<a class="btn btn-batch" href="{remaining_uri()}" data-batch="{remaining_uri()}" '
        f'data-batch-count="{count}" data-batch-size="0" data-batch-name="{escape(shown)}" '
        f'data-batch-confirm="{escape(title)} ({escape(detail)})">{label} {count}</a>'
    )
