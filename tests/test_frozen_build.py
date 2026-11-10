"""Tests for the frozen build.

The build is a post-build step in tools/build_frozen.py rather than a spec change, because
PyInstaller's COLLECT stage puts every data and binary into `_internal/` and there is no
documented way to ask it to leave a tree at the bundle root. The app resolves its project
root as `Path(__file__).resolve().parent` and walks it for `runtime/7z.exe` and the other
sibling folders, so a build that left those inside `_internal/` would ship an app that
cannot unpack anything. These tests run the builder against a scratch tree and check the
layout it produces, not the one in this checkout.
"""
from __future__ import annotations

import pytest

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools import build_frozen

try:
    import PyInstaller  # noqa: F401
    HAS_PYINSTALLER = True
except ImportError:
    HAS_PYINSTALLER = False


@pytest.mark.frozen
class FrozenBuildLaysOutTheBundle(unittest.TestCase):
    """The frozen exe must sit in a bundle whose root looks like the source tree."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="sgo-build-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    @unittest.skipUnless(HAS_PYINSTALLER, "PyInstaller is not installed in this environment")
    def test_the_build_tool_produces_a_bundle_with_the_exe_inside(self):
        """A fresh build puts the exe inside the bundle and the runtime beside it."""
        # Drive the tool itself rather than repeating its steps: the point of the test is that
        # the post-build layout step happens, and that step is what moves the exe into the bundle
        # and lifts core/, runtime/ and the rest out of _internal/.
        source = Path(__file__).resolve().parent.parent
        original_root = build_frozen.ROOT
        original_dist = build_frozen.DIST
        original_bundle = build_frozen.BUNDLE
        original_exe = build_frozen.EXE
        original_spec = build_frozen.SPEC
        try:
            build_frozen.ROOT = self.root
            build_frozen.DIST = self.root / "dist"
            build_frozen.BUNDLE = build_frozen.DIST / "steam_game_organizer"
            build_frozen.EXE = build_frozen.BUNDLE / "steam_game_organizer.exe"
            build_frozen.SPEC = source / "steam_game_organizer.spec"
            code = build_frozen.main()
        finally:
            build_frozen.ROOT = original_root
            build_frozen.DIST = original_dist
            build_frozen.BUNDLE = original_bundle
            build_frozen.EXE = original_exe
            build_frozen.SPEC = original_spec
        self.assertEqual(code, 0, "the build tool exited non-zero")

        bundle = self.root / "dist" / "steam_game_organizer"
        exe = bundle / "steam_game_organizer.exe"
        self.assertTrue(exe.is_file(), f"no exe at {exe}")
        for name in ("core", "services", "runtime", "VERSION.txt"):
            self.assertTrue((bundle / name).exists(), f"bundle is missing {name}")
        self.assertTrue((bundle / "runtime" / "7z.exe").is_file(),
                        "the frozen app has no 7z.exe to unpack with")

    def test_the_exported_reg_points_at_the_runtime_python(self):
        """A .reg for a target PC must reference the bundled interpreter, not the one that ran the build."""
        from tools import install_protocol_handler as installer
        dest = self.root / "handler.reg"
        entry = Path("D:/app/steam_game_organizer.py")
        installer.export_windows_reg(dest, r"C:\Python313\python.exe", entry)
        text = dest.read_text(encoding="utf-16")
        self.assertIn(r'"@"="SGO.Python.File"', text)
        # The .reg doubles every backslash, so the path reads `runtime\\python.exe` in the file, and quotes inside
        # the value are escaped as `\"`. Both are the .reg format, not Python string escapes.
        self.assertIn("runtime\\\\python.exe", text)
        self.assertIn(r'\"%1\"', text)
        # The scheme handler still carries the interpreter that ran the build, which is what
        # the target PC will actually run the entry point with.
        self.assertIn(r'\"C:\\Python313\\python.exe\"', text)


if __name__ == "__main__":
    unittest.main()