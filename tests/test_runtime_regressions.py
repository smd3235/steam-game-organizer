"""Regression tests for the bundled runtime.

These tests were extracted from tests/test_regressions.py to keep each test module
focused on one area of the app: ensuring the bundled Python + 7-Zip runtime travels
with the app so it works on a bare PC.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.bundle_runtime import build_plan


class TestTheBundledRuntimeTravelsWithTheApp(unittest.TestCase):
  """The runtime folder is what makes a copied app folder work on a bare PC."""

  def _tmp_dir(self):
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    self.addCleanup(__import__("shutil").rmtree, tmp, ignore_errors=True)
    return tmp

  def test_find_tool_answers_with_the_bundled_copy_before_path(self):
    import services.extract_service as module
    from services.extract_service import ExtractService, clear_tool_cache

    root = self._tmp_dir()
    bundled = root / "app" / "runtime"
    bundled.mkdir(parents=True)
    shipped = bundled / "7z.exe"
    shipped.write_bytes(b"bundled")
    on_path = root / "bin"
    on_path.mkdir()
    stub = on_path / "7z.bat"
    stub.write_text("@echo stub")
    old_path = os.environ["PATH"]
    os.environ["PATH"] = str(on_path) + os.pathsep + old_path
    self.addCleanup(setattr, os.environ, "PATH", old_path)
    original = module.APP_ROOT
    module.APP_ROOT = root / "app"
    self.addCleanup(setattr, module, "APP_ROOT", original)
    clear_tool_cache()
    found, reason = ExtractService.find_tool()
    self.assertEqual(found, str(shipped), f"the bundled copy was not the answer ({found}, {reason})")
    shipped.unlink()
    clear_tool_cache()
    found, reason = ExtractService.find_tool()
    self.assertEqual(
      str(found).casefold(), str(stub).casefold(), f"with no bundle the PATH answer was not kept ({found}, {reason})"
    )

  def test_the_plan_builds_the_layout_the_bundled_interpreter_needs(self):
    version = getattr(sys, "version_info", None)
    version = f"python{version.major}{version.minor}" if version else "python313"
    root = self._tmp_dir()
    source = root / "install"
    destination = root / "runtime"
    source.mkdir()
    for name in ("python.exe", "pythonw.exe", "python3.dll", "vcruntime140.dll"):
      (source / name).write_bytes(b"x")
    (source / f"{version}.dll").write_bytes(b"x")
    for folder in ("DLLs", "tcl", "tk"):
      (source / folder).mkdir()
      if folder == "DLLs":
        (source / folder / "a.pyd").write_bytes(b"x")
      else:
        (source / folder / "a").write_bytes(b"x")
    (source / "Lib").mkdir()
    (source / "Lib" / "os.py").write_text("pass")
    (source / "Lib" / "test").mkdir()
    (source / "Lib" / "test" / "test_os.py").write_text("pass")
    (source / "LICENSE.txt").write_text("PSF")
    plan = build_plan(source, destination, sevenzip=root / "7z.exe")
    files = {
      str(step.destination.relative_to(destination)) for step in plan if step.kind == "file"
    }
    for expected in (
      "python.exe",
      "pythonw.exe",
      "python3.dll",
      "vcruntime140.dll",
      f"{version}.dll",
      "LICENSE.txt",
      "7z.exe",
    ):
      self.assertIn(expected, files, f"the plan does not copy {expected}")
    trees = {
      str(step.destination.relative_to(destination)) for step in plan if step.kind == "tree"
    }
    for expected in ("Lib", "DLLs", "tcl", "tk"):
      self.assertIn(expected, trees, f"the plan does not copy {expected}/")
    lib = next(step for step in plan if step.kind == "tree" and str(step.destination.relative_to(destination)) == "Lib")
    self.assertIn("test", lib.exclude, "the standard library test suite would travel with the runtime")
    pyth = [step for step in plan if step.kind == "write" and step.destination.suffix == "._pth"]
    self.assertEqual(1, len(pyth), "the interpreter needs exactly one _pth")
    self.assertEqual(pyth[0].content, ".\nLib\nDLLs\n", "the _pth is the whole path search on a machine with no registry entry for Python")
  # Pillow must be included: Steam artwork is JPEG and tk.PhotoImage cannot decode it
    pil_steps = [
      step for step in plan if step.destination.relative_to(destination).parts == ("Lib", "PIL")
    ]
    has_pillow = any(
      step.kind == "tree" and step.source and step.source.is_dir() for step in pil_steps
    )
    self.assertTrue(has_pillow, "the build plan does not include Pillow, so JPEG artwork cannot render")

  def test_a_bundled_runtime_is_reported_by_the_check(self):
    """--check has to say what is actually there, because a folder a friend copied
    is the one place nobody will run a build in - a silent empty runtime/ would
    otherwise look like the answer to "nothing needs installed"."""
    from tools import bundle_runtime

    root = self._tmp_dir()
    (root / "python.exe").write_bytes(b"x")
    original = bundle_runtime.RUNTIME
    bundle_runtime.RUNTIME = root
    self.addCleanup(setattr, bundle_runtime, "RUNTIME", original)
    with patch("subprocess.run") as probe:
      probe.return_value = SimpleNamespace(returncode=0, stdout="3.13.15\n", stderr="")
      with patch("builtins.print") as report:
        self.assertEqual(0, bundle_runtime.check())
    said = " ".join(str(call.args[0]) for call in report.call_args_list)
    self.assertIn("3.13.15", said, "the check did not report the bundled version")
    self.assertIn("NOT bundled", said, "the check did not name a missing 7z.exe")
