"""Pure utility functions extracted from LibraryService.

These functions have no dependency on LibraryService instance state and can be
imported and tested independently.
"""

from __future__ import annotations

from pathlib import Path

from core.constants import ENTRY_POINT


def is_app_folder(folder) -> bool:
    """True when this folder is the app's own project folder rather than a game category.

    The library root is the app's own project folder when the app is installed there, which is the
    default: the project folder sits inside the library root, and every scan picked it up as a
    category of one game - the app itself. The entry-point filename is the one thing that identifies
    the project regardless of what the folder is called, so the check looks for it rather than for a
    folder name: renaming the project folder no longer re-adds it to the catalog.

    Direct children of the project folder are the app's runtime and tooling, not game content.
    The bundled `runtime` folder is the one that mattered: it holds no archives, but it holds
    `python.exe`, `pythonw.exe`, the stdlib under `Lib`, the Tcl interpreter under `tcl`, and the
    vcruntime DLLs, so discovery walked it as a category of one game and listed its `.py`,
    `.pyc`, `.dll`, `.msg`, `.enc` and `.tm` files as archives. Checking for the interpreter
    rather than naming the folder keeps the rule anchored to what the app actually ships.
    """
    folder = Path(folder)
    if (folder / ENTRY_POINT).is_file():
        return True
    return (folder / "python.exe").is_file() and (folder.parent / ENTRY_POINT).is_file()


def game_folder_is_prunable(folder) -> bool:
    """Whether a game subfolder holds only things this app wrote there.

    A game folder is the player's too - a screenshot or a downloaded manual ends up beside the game -
    and there is nothing in a suffix that separates that from the artwork the app wrote. So the artwork
    accepted here has to carry the shape the organizer writes, `<title>_grid.jpg` and
    `<title>_<asset>.<ext>`, and an underscore in the stem is what that looks like once the name is a
    path. Anything else - a save file, a mod, a second archive - keeps the folder, because the sweep
    is for the game that left, not for the player's own files.
    """
    try:
        entries = list(Path(folder).iterdir())
    except OSError:
        return False
    for item in entries:
        if item.is_symlink() or not item.is_file():
            return False
        if item.name in RECOGNISED_FOLDER_FILES:
            continue
        if item.name in IGNORED_FILES_IN_SWEEP:
            continue
        if item.suffix.lower() in RECOGNISED_IMAGE_SUFFIXES and "_" in item.stem:
            continue
        return False
    return True


# Files this app writes into an organized game folder, by exact name. A folder holding only these and
# app-shaped artwork is the app's to remove when the game leaves. Kept here rather than in
# OrganizerService so the leftover sweep and the undo can agree on what counts as ours.
RECOGNISED_FOLDER_FILES = frozenset({
    ".game-info.json",
    "Open Steam Page.html",
    "Open Steam Page.desktop",
    "Open Steam Page in Chrome.desktop",
    "Open Steam Page (Steam Deck).desktop",
})
# Artwork, by suffix rather than by the exact name it was written under. move() copies the primary in as
# `<title>_grid.jpg` and each asset as `<title>_<asset>.<ext>`, so the title and the asset name both vary
# per game; the suffix is the part that says what the file is, and the underscore in the stem is what
# separates it from player files.
RECOGNISED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
# Syncthing leftovers, matched by name. Only the documented Syncthing naming is listed here - earlier drafts
# included ".~lock.*", which is a LibreOffice/KDE convention and has nothing to do with Syncthing.
IGNORED_FILES_IN_SWEEP = frozenset(
    {
        "Thumbs.db",
        "ehthumbs_vista.db",
        ".DS_Store",
        "desktop.ini",
        "Thumbs",
        "folder.jpg",
        "folder.jpeg",
        "folder.png",
        "folder.webp",
        "folder.gif",
        "folder.bmp",
        "folder.tif",
        "folder.tiff",
        "Folder.jpg",
        "Folder.jpeg",
        "Folder.png",
        "Folder.webp",
        "Folder.gif",
        "Folder.bmp",
        "Folder.tif",
        "Folder.tiff",
        "cover.jpg",
        "cover.jpeg",
        "cover.png",
        "cover.webp",
        "cover.gif",
        "cover.bmp",
        "cover.tif",
        "cover.tiff",
        "Cover.jpg",
        "Cover.jpeg",
        "Cover.png",
        "Cover.webp",
        "Cover.gif",
        "Cover.bmp",
        "Cover.tif",
        "Cover.tiff",
        "label.jpg",
        "label.jpeg",
        "label.png",
        "label.webp",
        "label.gif",
        "label.bmp",
        "label.tif",
        "label.tiff",
        "Label.jpg",
        "Label.jpeg",
        "Label.png",
        "Label.webp",
        "Label.gif",
        "Label.bmp",
        "Label.tif",
        "Label.tiff",
        "banner.jpg",
        "banner.jpeg",
        "banner.png",
        "banner.webp",
        "banner.gif",
        "banner.bmp",
        "banner.tif",
        "banner.tiff",
        "Banner.jpg",
        "Banner.jpeg",
        "Banner.png",
        "Banner.webp",
        "Banner.gif",
        "Banner.bmp",
        "Banner.tif",
        "Banner.tiff",
        "thumb.jpg",
        "thumb.jpeg",
        "thumb.png",
        "thumb.webp",
        "thumb.gif",
        "thumb.bmp",
        "thumb.tif",
        "thumb.tiff",
        "Thumb.jpg",
        "Thumb.jpeg",
        "Thumb.png",
        "Thumb.webp",
        "Thumb.gif",
        "Thumb.bmp",
        "Thumb.tif",
        "Thumb.tiff",
        "thumbnail.jpg",
        "thumbnail.jpeg",
        "thumbnail.png",
        "thumbnail.webp",
        "thumbnail.gif",
        "thumbnail.bmp",
        "thumbnail.tif",
        "thumbnail.tiff",
        "Thumbnail.jpg",
        "Thumbnail.jpeg",
        "Thumbnail.png",
        "Thumbnail.webp",
        "Thumbnail.gif",
        "Thumbnail.bmp",
        "Thumbnail.tif",
        "Thumbnail.tiff",
        "art.jpg",
        "art.jpeg",
        "art.png",
        "art.webp",
        "art.gif",
        "art.bmp",
        "art.tif",
        "art.tiff",
        "Art.jpg",
        "Art.jpeg",
        "Art.png",
        "Art.webp",
        "Art.gif",
        "Art.bmp",
        "Art.tif",
        "Art.tiff",
        "poster.jpg",
        "poster.jpeg",
        "poster.png",
        "poster.webp",
        "poster.gif",
        "poster.bmp",
        "poster.tif",
        "poster.tiff",
        "Poster.jpg",
        "Poster.jpeg",
        "Poster.png",
        "Poster.webp",
        "Poster.gif",
        "Poster.bmp",
        "Poster.tif",
        "Poster.tiff",
    }
)
