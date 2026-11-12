"""Path-safety guards for every destructive file operation in the app.

The app's rule is: nothing outside the folders the user configured may ever be
removed, moved, or overwritten by this code. Every deletion target is resolved
and checked against an allowed-root list before anything touches the disk. A
path that cannot be resolved, or that resolves outside every allowed root, is
refused rather than acted on.

This module exists because two rollback pruners used to fall back to
`shutil.rmtree(game_dir)` when `library_root` was None - with no containment
check at all. A misconfigured or missing library root meant `game_dir` could
resolve anywhere on the machine, and rmtree would delete it. The fix is to
refuse outright: never delete without a proven containment answer.
"""

from __future__ import annotations

import shutil
from pathlib import Path


class PathOutsideAllowedRoot(Exception):
    """Raised when a destructive operation targets a path outside every allowed root."""


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


class DeletionGuard:
    """Holds the roots this app is allowed to delete inside and validates targets.

    A guard is built once per run with the library root and the app's own
    project root. Every `rmtree` / `unlink` / `remove` call site routes through
    `refuse_outside()` first, so a journal row naming `library\\..\\Windows` or a
    misconfigured root cannot reach `shutil.rmtree` outside the library.
    """

    def __init__(self, roots):
        self._roots = [str(Path(r).expanduser().resolve()) for r in roots if r]
        if not self._roots:
            raise ValueError("DeletionGuard needs at least one allowed root")

    def allowed(self, path):
        """True when `path` resolves inside one of the allowed roots."""
        try:
            resolved = str(Path(path).expanduser().resolve())
        except OSError:
            return False
        return any(resolved == root or root in Path(resolved).parents for root in self._roots)

    def refuse_outside(self, path, operation="delete"):
        """Raise `PathOutsideAllowedRoot` when `path` is outside every allowed root."""
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
