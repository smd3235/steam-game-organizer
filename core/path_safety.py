"""Path-safety guards for every destructive file operation in the app.

The app's rule is: nothing outside the folders the user configured may ever be
removed, moved, or overwritten by this code. Every deletion target is resolved
and checked against an allowed-root list before anything touches the disk. A
path that cannot be resolved, or that resolves outside every allowed root, is
refused rather than acted on.

A second, independent guard blocks protected system paths -- the Windows
directory, Program Files, Users, and every drive root -- even when they fall
within an allowed root. A misconfigured library_root (C:\\, C:\\Windows) must
never open the system to deletion.

This module exists because two rollback pruners used to fall back to
`shutil.rmtree(game_dir)` when `library_root` was None - with no containment
check at all. A misconfigured or missing library root meant `game_dir` could
resolve anywhere on the machine, and rmtree would delete it. The fix is to
refuse outright: never delete without a proven containment answer.
"""

from __future__ import annotations

import os
import shutil
import string
from pathlib import Path


class PathOutsideAllowedRoot(Exception):
    """Raised when a destructive operation targets a path outside every allowed root
    or a protected system path that must never be deleted."""


def is_within(path, root):
    """Whether `path` resolves to `root` or somewhere beneath it.

    Both sides are resolved so `..` segments, symlinks and junctions are settled.
    Returns False (never raises) on an unresolvable path, because the answer a
    delete needs is "no".
    """
    try:
        resolved = Path(path).resolve()
        base = Path(root).resolve()
    except OSError:
        return False
    return resolved == base or base in resolved.parents


def protected_roots():
    """Paths that must never be deleted, regardless of library-root config.

    Includes the Windows directory, Program Files folders, the Users folder,
    and every existing drive root. A misconfigured library_root (e.g. C:\\ or
    C:\\Windows) must not open these to deletion.
    """
    roots = []
    windir = os.environ.get("WINDIR") or os.environ.get("SYSTEMROOT", r"C:\Windows")
    roots.append(windir)
    program_files = os.environ.get("PROGRAMFILES")
    if program_files:
        roots.append(program_files)
    program_files_x86 = os.environ.get("PROGRAMFILES(X86)")
    if program_files_x86:
        roots.append(program_files_x86)
    system_drive = os.environ.get("SYSTEMDRIVE", "C:")
    roots.append(str(Path(system_drive) / "Users"))
    # Every existing drive root: C:\, D:\, E:\, ...
    for letter in string.ascii_uppercase:
        drive = f"{letter}:\\"
        if os.path.exists(drive):
            roots.append(drive)
    return [str(Path(r).expanduser().resolve()) for r in roots if r]


def is_protected(path):
    """True when `path` resolves inside a protected system path.

    Drive roots (C:\\, D:\\) protect only themselves - deleting the root is
    refused, but subdirectories are left to the allowed-root check. Windows,
    Program Files, and Users protect their entire subtree. Returns True
    (treat as protected) on an unresolvable path, because the answer a delete
    needs is "no".
    """
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        return True
    for root in protected_roots():
        root_path = Path(root)
        if resolved == root_path:
            return True
        # Drive roots protect only themselves; everything beneath them is left
        # to the allowed-root check. Other protected paths guard their subtree.
        if str(root_path) != root_path.anchor and root_path in resolved.parents:
            return True
    return False


class DeletionGuard:
    """Holds the roots this app is allowed to delete inside and validates targets.

    A guard is built once per run with the library root and the app's own
    project root. Every `rmtree` / `unlink` / `remove` call site routes through
    `refuse_outside()` first, so a journal row naming `library\\..\\Windows` or a
    misconfigured root cannot reach `shutil.rmtree` outside the library.

    Protected system paths are refused even when they fall within an allowed
    root, so a misconfigured library_root can never open the system to deletion.
    """

    def __init__(self, roots):
        self._root_paths = [Path(r).expanduser().resolve() for r in roots if r]
        self._roots = [str(p) for p in self._root_paths]
        if not self._root_paths:
            raise ValueError("DeletionGuard needs at least one allowed root")

    def allowed(self, path):
        """True when `path` resolves inside one of the allowed roots."""
        try:
            resolved = Path(path).expanduser().resolve()
        except OSError:
            return False
        return any(resolved == root or root in resolved.parents for root in self._root_paths)

    def refuse_outside(self, path, operation="delete"):
        """Raise `PathOutsideAllowedRoot` when `path` is unsafe to delete.

        A path is unsafe when it is a protected system path (Windows, Program
        Files, Users, any drive root) or when it is outside every allowed root.
        Protected paths are refused even if they fall within an allowed root,
        so a misconfigured library_root can never open the system to deletion.
        """
        if is_protected(path):
            raise PathOutsideAllowedRoot(
                f"{operation} refused: {path} is a protected system path"
            )
        if not self.allowed(path):
            raise PathOutsideAllowedRoot(
                f"{operation} refused: {path} is outside every allowed root ({', '.join(self._roots)})"
            )
        return Path(path).expanduser().resolve()

    def rmtree(self, directory, ignore_errors=False):
        """`shutil.rmtree` guarded by the allowed-root check."""
        resolved = self.refuse_outside(directory, "rmtree")
        try:
            shutil.rmtree(str(resolved), ignore_errors=ignore_errors)
        except OSError:
            if not ignore_errors:
                raise
            # Swallowed on the ignore path: a locked or already-deleted file must
            # not mask the error the caller actually cares about.

    def unlink(self, path, missing_ok=True):
        """`Path.unlink` guarded by the allowed-root check."""
        resolved = self.refuse_outside(path, "unlink")
        try:
            resolved.unlink()
        except FileNotFoundError:
            if not missing_ok:
                raise
        except OSError:
            if not missing_ok:
                raise


def safe_rmtree(directory, roots, ignore_errors=False):
    """One-shot guarded `shutil.rmtree` for call sites without a persistent guard."""
    guard = DeletionGuard(roots)
    guard.rmtree(directory, ignore_errors=ignore_errors)


def safe_unlink(path, roots, missing_ok=True):
    """One-shot guarded `Path.unlink` for call sites without a persistent guard."""
    guard = DeletionGuard(roots)
    guard.unlink(path, missing_ok=missing_ok)
