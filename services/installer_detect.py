"""Recognises archives that unpack to a Windows installer rather than a ready-to-play game.

Two installer shapes show up in repack libraries and both have to be treated the same way - unpacked into a
"Needs Install" folder, not mistaken for a game that is already playable:

  - setup.exe + one or more .bin files (FitGirl, DODI, SteamRIP)
  - a .iso that has to be mounted before setup runs (TENOKE, PLAZA)

This module is the one place that shape is named, so the extract step that relocates an installer and any surface
that wants to flag one - the catalog badge, the run banner - stay in step. The same rule is applied to an extracted
folder and to a list of archive member names, so the badge the catalog draws before extraction and the move the
extract step performs afterwards cannot disagree.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from utils.treewalk import walk_files

# Executables a setup-based repack uses to install itself. The set is deliberately small and name-bound: a game's
# own .exe is never one of these, so a normal archive is never mistaken for an installer even though it ships an
# executable. Detection also requires a .bin alongside one, which closes the obvious false positive of a game that
# happens to be launched by a file called setup.exe.
INSTALLER_EXE_NAMES = frozenset(
    {
        "setup.exe",
        "setup_install.exe",
        "install.exe",
        "installer.exe",
        "autostart.exe",
        "run.exe",
        "run_installer.exe",
        "setup_game.exe",
    }
)

# Where an installer archive is parked after extraction, so it is obvious at a glance that it has not been run yet.
# Named in plain English because a person reads this label, not a machine.
NEEDS_INSTALL_DIRNAME = "Needs Install"


@dataclasses.dataclass(frozen=True)
class InstallSignature:
    """What marks an archive as an installer, and what the user has to do with it.

    kind is "iso" when an ISO to mount is present, "repack" when a named setup exe sits beside .bin data files.
    program is the file the user has to open - the iso to mount, or the exe to run - so a message can be specific
    instead of generic.
    """

    kind: str
    program: Path


def installer_from_names(names) -> InstallSignature | None:
    """An installer signature read from archive member names, or None if none match.

    Member names from a zip central directory or a `7z l`/`unrar l` listing are treated as relative paths; only their
    basename and suffix matter, which is what the repack/iso signature is built on. The same rule is used against a
    directory listing, so "this archive is an installer" and "this folder is an unpacked installer" are one opinion.
    """
    iso = None
    exe = None
    saw_bin = False
    for name in names:
        member = Path(name)
        suffix = member.suffix.lower()
        base = member.name.casefold()
        if suffix == ".iso":
            if iso is None:
                iso = member
        elif base in INSTALLER_EXE_NAMES:
            if exe is None:
                exe = member
        elif suffix == ".bin":
            saw_bin = True
        if iso is not None or (exe is not None and saw_bin):
            break
    if iso is not None:
        return InstallSignature(kind="iso", program=iso)
    if exe is not None and saw_bin:
        return InstallSignature(kind="repack", program=exe)
    return None


def find_installer(root, entries=None) -> InstallSignature | None:
    """The installer signature in an extracted folder, or None if it is not an installer layout.

    Returns the signature rather than a bare bool so a caller can name the exact program the reader has to run
    instead of leaving the message generic. The scan is junction-safe through walk_files: an archive that unpacks
    to a junction back into itself would otherwise be followed forever by rglob.

    `entries` optionally supplies pre-computed Path objects (e.g. from a single rglob the caller already did),
    avoiding a second walk of the same tree.
    """
    path = Path(root)
    if not path.is_dir():
        return None
    if entries is None:
        entries = walk_files(path)
    # Full paths, not basenames: `program` is the file the reader has to open, and on disk that is an absolute path
    # to setup.exe / the .iso. installer_from_names still only looks at basename and suffix, so this stays in step
    # with the archive-member variant where member names are archive-relative.
    return installer_from_names(str(entry) for entry in entries)


def looks_like_installer(root) -> bool:
    """True when an extracted folder holds a repack-style or ISO installer."""
    return find_installer(root) is not None


def has_needs_install_mark(root) -> bool:
    """True when `root` is an unpacked installer that has not been run yet.

    Checks two layouts:
      - New style: the folder itself sits inside a "Needs Install" directory at the extract root.
      - Old style: a "Needs Install" subfolder lives inside the game folder (pre-v9.31 relocations).

    A cheap directory-entry check rather than re-scanning for the setup.exe/.bin/.iso signature on every card.
    """
    root = Path(root)
    if root.parent and root.parent.name == NEEDS_INSTALL_DIRNAME:
        return True
    return (root / NEEDS_INSTALL_DIRNAME).is_dir()
