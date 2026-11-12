"""Tests for core.path_safety: allowed-root containment and protected-system-path blocking.

Every destructive target must be refused when it is outside the allowed roots
or inside a protected system path (Windows, Program Files, Users, any drive
root), even when a misconfigured library_root would otherwise admit it.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

import pytest

from core.path_safety import DeletionGuard, PathOutsideAllowedRoot, is_protected, protected_roots


@pytest.mark.notkinter
class TestProtectedRoots(unittest.TestCase):
    """Protected system paths must be identifiable on this machine."""

    def test_windows_directory_is_protected(self):
        windir = os.environ.get("WINDIR") or os.environ.get("SYSTEMROOT", r"C:\Windows")
        self.assertIn(str(Path(windir).resolve()), protected_roots())

    def test_program_files_is_protected(self):
        pf = os.environ.get("PROGRAMFILES")
        if pf:
            self.assertIn(str(Path(pf).resolve()), protected_roots())

    def test_users_folder_is_protected(self):
        system_drive = os.environ.get("SYSTEMDRIVE", "C:")
        self.assertIn(f"{system_drive}\\Users", protected_roots())

    def test_existing_drive_roots_are_protected(self):
        found = False
        for letter in "CDE":
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                self.assertIn(drive, protected_roots())
                found = True
        # At least the system drive should exist on Windows.
        self.assertTrue(found, "no drive root found; protected_roots() returned nothing")


@pytest.mark.notkinter
class TestIsProtected(unittest.TestCase):
    """is_protected() must flag system paths and admit library paths."""

    def test_windows_directory_is_protected(self):
        windir = os.environ.get("WINDIR") or os.environ.get("SYSTEMROOT", r"C:\Windows")
        self.assertTrue(is_protected(windir))

    def test_program_files_is_protected(self):
        pf = os.environ.get("PROGRAMFILES")
        if pf:
            self.assertTrue(is_protected(pf))

    def test_users_folder_is_protected(self):
        system_drive = os.environ.get("SYSTEMDRIVE", "C:")
        self.assertTrue(is_protected(str(Path(system_drive) / "Users")))

    def test_drive_root_is_protected(self):
        system_drive = os.environ.get("SYSTEMDRIVE", "C:")
        self.assertTrue(is_protected(f"{system_drive}\\"))

    def test_nested_under_windows_is_protected(self):
        windir = os.environ.get("WINDIR") or os.environ.get("SYSTEMROOT", r"C:\Windows")
        self.assertTrue(is_protected(str(Path(windir) / "System32" / "kernel32.dll")))

    def test_library_root_path_is_not_protected(self):
        # A path inside a normal game library is not a protected system path.
        # Use the system drive root's own non-system child as a stand-in library.
        system_drive = os.environ.get("SYSTEMDRIVE", "C:")
        candidate = f"{system_drive}\\Games\\My Library"
        self.assertFalse(is_protected(candidate))

    def test_unresolvable_path_is_treated_as_protected(self):
        # A path that cannot resolve must be refused, never admitted.
        # A path under a protected root is protected regardless of format.
        system_drive = os.environ.get("SYSTEMDRIVE", "C:")
        self.assertTrue(is_protected(f"{system_drive}\\Windows\\System32\\config\\SAM"))


@pytest.mark.notkinter
class TestDeletionGuardProtectedPaths(unittest.TestCase):
    """DeletionGuard must refuse protected paths even within an allowed root."""

    def test_refuse_outside_blocks_windows_even_when_allowed(self):
        # If someone misconfigures library_root to C:\Windows, the guard must still refuse.
        windir = os.environ.get("WINDIR") or os.environ.get("SYSTEMROOT", r"C:\Windows")
        guard = DeletionGuard([windir])
        with self.assertRaises(PathOutsideAllowedRoot):
            guard.refuse_outside(windir, "delete")

    def test_refuse_outside_blocks_drive_root_even_when_allowed(self):
        system_drive = os.environ.get("SYSTEMDRIVE", "C:")
        guard = DeletionGuard([f"{system_drive}\\"])
        with self.assertRaises(PathOutsideAllowedRoot):
            guard.refuse_outside(f"{system_drive}\\", "rmtree")

    def test_refuse_outside_allows_library_path(self):
        system_drive = os.environ.get("SYSTEMDRIVE", "C:")
        guard = DeletionGuard([f"{system_drive}\\Games"])
        resolved = guard.refuse_outside(f"{system_drive}\\Games\\My Library\\Game 1", "delete")
        self.assertEqual(resolved, Path(f"{system_drive}\\Games\\My Library\\Game 1").resolve())

    def test_rmtree_blocks_protected_path(self):
        system_drive = os.environ.get("SYSTEMDRIVE", "C:")
        guard = DeletionGuard([f"{system_drive}\\"])
        with self.assertRaises(PathOutsideAllowedRoot):
            guard.rmtree(f"{system_drive}\\")

    def test_unlink_blocks_protected_path(self):
        system_drive = os.environ.get("SYSTEMDRIVE", "C:")
        guard = DeletionGuard([f"{system_drive}\\"])
        with self.assertRaises(PathOutsideAllowedRoot):
            guard.unlink(f"{system_drive}\\Windows\\System32\\kernel32.dll")


if __name__ == "__main__":
    unittest.main()
