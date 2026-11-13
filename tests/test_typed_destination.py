"""Tests for core.typed_destination._typed_destination: user-typed destination validation.

_typed_destination() validates a path the user typed into the catalog page. It
refuses relative paths, the home folder, system folders, paths inside the game
library, files instead of folders, and unwritable locations.
"""

import os
import unittest
from pathlib import Path
from tempfile import mkdtemp

from core.typed_destination import _typed_destination
from core.uri_actions import UriRefused


class TestTypedDestinationRejectsInvalidInputs(unittest.TestCase):
    """Invalid destinations raise UriRefused."""

    def test_relative_path_is_refused(self):
        with self.assertRaises(UriRefused):
            _typed_destination("relative/path", Path("C:/Games"))

    def test_home_folder_is_refused(self):
        with self.assertRaises(UriRefused):
            _typed_destination(str(Path.home()), Path("C:/Games"))

    def test_filesystem_root_is_refused(self):
        system_drive = os.environ.get("SYSTEMDRIVE", "C:")
        root = f"{system_drive}\\"
        with self.assertRaises(UriRefused):
            _typed_destination(root, Path("C:/Games"))

    def test_system_folder_is_refused(self):
        windir = os.environ.get("WINDIR") or os.environ.get("SYSTEMROOT", r"C:\Windows")
        with self.assertRaises(UriRefused):
            _typed_destination(windir, Path("C:/Games"))

    def test_path_inside_library_root_is_refused(self):
        library = Path(mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(library, ignore_errors=True))
        inside = library / "Some Game"
        with self.assertRaises(UriRefused):
            _typed_destination(str(inside), library)

    def test_file_instead_of_folder_is_refused(self):
        tmp = Path(mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        a_file = tmp / "a_file.txt"
        a_file.write_text("x")
        with self.assertRaises(UriRefused):
            _typed_destination(str(a_file), Path("C:/Games"))


class TestTypedDestinationAcceptsValidInputs(unittest.TestCase):
    """Valid destinations are returned as resolved Path objects."""

    def test_absolute_path_outside_library_is_accepted(self):
        tmp = Path(mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        destination = tmp / "Extracted Games"
        result = _typed_destination(str(destination), Path("C:/Games"))
        self.assertEqual(result, destination.resolve())

    def test_nonexistent_parent_that_is_writable_is_accepted(self):
        tmp = Path(mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        destination = tmp / "new" / "folder"
        result = _typed_destination(str(destination), Path("C:/Games"))
        self.assertEqual(result, destination.resolve())


if __name__ == "__main__":
    unittest.main()
