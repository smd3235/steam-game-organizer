"""Regression tests for platform paths and commands.

These tests were extracted from tests/test_regressions.py to keep each test module
focused on one area of the app: ensuring no POSIX paths or Linux-only commands
remain in the Windows-only application.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from core.config import AppConfig
from services.extract_service import ExtractService


class TestPlatformPathsAreNotHardCoded(unittest.TestCase):
  """A path or command from another platform survives long after the platform is dropped.

  Both of these were found by looking at the running app rather than by reading a test: the message was written
  when Steam Deck was the primary platform and told a Windows user to look in /home/deck, and the archive
  verification tool - the thing you run to check a library is intact - exited immediately on a normal PC
  because it looked for 7z only on PATH and 7-Zip installs to Program Files without adding itself there.

  Neither shows up in a test that supplies its own paths, which is why a suite can be entirely green while the
  app is telling the user to go somewhere that does not exist on their machine.
  """

  def _code_strings(self, relative):
    """Every string literal in a module's code, excluding its comments.

    Read from the parsed AST rather than the file text: both of these words appear in the change logs that
    explain why they were removed, and a grep over the raw source reports a Linux path that is only being
    described. That is the same mistake as asserting on a file's text to prove a call was removed.
    """
    path = Path(relative)
    if not path.is_file():
      path = Path(__file__).resolve().parents[1] / path
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return path, [
      node.value for node in ast.walk(tree)
      if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]

  def _code_calls(self, relative):
    """Every call expression in a module, as source. Comments cannot appear here."""
    path = Path(relative)
    if not path.is_file():
      path = Path(__file__).resolve().parents[1] / path
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return path, [ast.unparse(node) for node in ast.walk(tree) if isinstance(node, ast.Call)]

  def test_the_library_root_dialog_does_not_name_a_path_from_another_platform(self):
    source, literals = self._code_strings(Path("ui") / "main_window.py")
    for dead in ("/home/deck", "/home/jail", "xdg-open"):
      hits = [s for s in literals if dead in s]
      self.assertEqual(
        [],
        hits,
        f"{source.name} still builds a message or command from {dead!r}: {hits}",
      )
    self.assertTrue(AppConfig.default_library_root().is_absolute())

  def test_the_archive_verifier_finds_seven_zip_the_way_the_app_does(self):
    """It must reach the same verdict about this machine as the organizer does.

    Asserted against the real lookup rather than a mock: this is the question the tool exists to answer, and a
    patched shutil.which would only prove the tool calls the function it always called.
    """
    source, literals = self._code_strings(Path("tools") / "verify_archives.py")
    self.assertEqual(
      [],
      [s for s in literals if "/home/deck" in s],
      f"{source.name} still defaults to the Steam Deck library path",
    )
    source, calls = self._code_calls(Path("tools") / "verify_archives.py")
    self.assertEqual(
      [],
      [c for c in calls if "shutil.which" in c],
      f"{source.name} still resolves 7z with shutil.which, which cannot see a Windows install",
    )
    self.assertTrue(
      [c for c in calls if "find_tool" in c],
      f"{source.name} no longer asks ExtractService where the archive tool is",
    )
    found, reason = ExtractService.find_tool()
    self.assertIsNotNone(
      found, f"the verifier and the app would both report no archive tool here ({reason})"
    )
