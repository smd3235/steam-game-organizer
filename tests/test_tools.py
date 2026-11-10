"""Tests for the helper scripts in tools/, which had none at all.

The protocol handler installer is the one that matters. It registers the steamgameorganizer:// scheme that the
catalog's Extract button depends on, and it shipped referencing a name it never defined and calling os without
importing it - so it raised NameError on its first line of real work, on both platforms, and the tests said
nothing because no test had ever imported this directory. A tool that cannot run is exactly what an unimported
directory hides, so it is imported and exercised here.

Nothing here touches the registry or the desktop session: the Windows write goes through winreg, which is
patched out, and the Linux write goes to a temporary folder.
"""
from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import unittest

import pytest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tools import install_protocol_handler as installer

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.notkinter
class ProtocolHandlerInstallerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.entry = self.root / "steam_game_organizer.py"
        self.entry.write_text("# entry point\n", encoding="utf-8")

    def test_the_module_imports_and_knows_its_scheme(self):
        """The whole bug in one test: SCHEME was used eight times and defined nowhere.

        Importing this module used to raise NameError before main() ever ran, so the scheme could not be
        registered on either platform and nothing said so."""
        self.assertEqual(installer.SCHEME, "steamgameorganizer")

    def test_the_scheme_matches_the_one_the_page_generates(self):
        """The installer and the parser must not drift: the handler is only reachable if both agree."""
        from core.uri_actions import SCHEME as parser_scheme
        self.assertIs(installer.SCHEME, parser_scheme)

    def test_the_registry_path_has_one_separator(self):
        """Written as a raw string with two backslashes it is not a path any registry API documents."""
        self.assertNotIn("\\\\", installer.REGISTRY_ROOT)
        self.assertTrue(installer.REGISTRY_ROOT.endswith("Classes"))

    def test_exported_reg_names_the_scheme_and_escapes_the_command(self):
        """A .reg value is not a Python string: quotes inside it are escaped and every backslash is doubled.

        Hand-writing that escaping is how the command came out reading as a stray shell quote in front of the
        interpreter path, which regedit would have stored verbatim and Windows would have failed to run."""
        destination = self.root / "handler.reg"
        installer.export_windows_reg(destination, r"C:\Python313\python.exe", self.entry)
        text = destination.read_text(encoding="utf-16")
        self.assertIn(f"[HKEY_CURRENT_USER\\{installer.REGISTRY_ROOT}\\{installer.SCHEME}]", text)
        self.assertIn('"URL Protocol"=""', text)
        command = next(line for line in text.splitlines() if line.startswith('"@"="\\"'))
        # Each quote around a path is escaped once, every backslash in the path is doubled, and %1 survives
        # for the shell to substitute. Written out: \"C:\\Python313\\python.exe\" --uri \"%1\"
        self.assertIn(r'\"C:\\Python313\\python.exe\"', command)
        self.assertIn(r'--uri \"%1\"', command)
        # Doubling the backslashes after escaping the quotes would have produced \\" here instead.
        self.assertNotIn('\\\\"', command)


    def test_windows_install_writes_the_two_keys_and_the_command(self):
        """HKCU, so it needs no elevation, and the command has to carry the interpreter and the entry point."""
        written = {}

        class _Key:
            def __init__(self, path): self.path = path
            def __enter__(self): return self
            def __exit__(self, *exc): return False

        class _Winreg:
            """The slice of the winreg API install_windows() uses, over one dict.

            It modelled CreateKey and SetValueEx and nothing else. install_windows() now reads its own value
            back to confirm the write landed, and the read hit `AttributeError: no attribute 'OpenKey'` - a
            double that offers less of the interface than the code calls is the same defect as a test module
            importing a module that does not exist: it reports the shape of a thing it never exercised.
            """

            HKEY_CURRENT_USER = "HKCU"
            REG_SZ = 1

            @staticmethod
            def CreateKey(root, path):
                key = _Key(path)
                written.setdefault(('key', path), key)
                written.setdefault(('values', path), {})
                return key

            @staticmethod
            def SetValueEx(key, name, reserved, value_type, value):
                written.setdefault(('values', key.path), {})[name] = value
                written[('value', key.path, name)] = value

            @staticmethod
            def OpenKey(root, path):
                if ('values', path) not in written:
                    raise OSError(f"no such key: {path}")
                return _Key(path)

            @staticmethod
            def QueryValueEx(key, name):
                return (written[('values', key.path)][name], 1)

        with patch.dict(sys.modules, {"winreg": _Winreg}):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                installer.install_windows(r"C:\Python313\python.exe", self.entry)
        base = f"{installer.REGISTRY_ROOT}\\{installer.SCHEME}"
        command_key = base + r"\shell\open\command"
        self.assertIn(('key', command_key), written, 'the open command key was never created')
        # An empty value under this name is what makes Windows treat the key as a protocol, not a file type.
        self.assertEqual(written[('value', base, 'URL Protocol')], "")
        command = written[('value', command_key, None)]
        self.assertIn("--uri", command)
        self.assertIn('"%1"', command)
        self.assertIn(str(self.entry), command)
        # Reported only because the value was read back and matched, which is the whole point of the read.
        self.assertIn("verified:", buffer.getvalue())

    def test_install_does_not_claim_success_when_the_key_reads_back_differently(self):
        """It used to print "verified" straight after the writes, having verified nothing.

        Registration is the one setup step the README calls mandatory, and its failure mode is a dead Extract
        button with nothing on the page to say why. A success line printed unconditionally is worse than no
        line at all, because it closes the question the reader was about to ask.
        """

        class _Key:
            def __init__(self, path): self.path = path
            def __enter__(self): return self
            def __exit__(self, *exc): return False

        class _StaleWinreg:
            """Accepts every write and reports a different value for the one that was just made."""

            HKEY_CURRENT_USER = "HKCU"
            REG_SZ = 1

            @staticmethod
            def CreateKey(root, path): return _Key(path)
            @staticmethod
            def SetValueEx(key, name, reserved, value_type, value): pass
            @staticmethod
            def OpenKey(root, path): return _Key(path)
            @staticmethod
            def QueryValueEx(key, name): return (r'"C:\other\python.exe" --uri "%1"', 1)

        with patch.dict(sys.modules, {"winreg": _StaleWinreg}):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                installer.install_windows(r"C:\Python313\python.exe", self.entry)
        printed = buffer.getvalue()
        self.assertNotIn("verified:", printed,
                         "a value that did not read back as written was reported as a working handler")
        self.assertIn("WARNING", printed, "the disagreement was not reported at all")

    def test_check_reports_nothing_registered_rather_than_raising(self):
        """--check runs before any install and is the first thing anyone tries when a link does not open."""
        fake = type("W", (), {"HKEY_CURRENT_USER": "HKCU", "OpenKey": staticmethod(lambda *a: (_ for _ in ()).throw(OSError()))})()
        with patch.dict(sys.modules, {"winreg": fake}):
            with patch.object(installer.os, "name", "nt"):
                installer.check()


class LayoutAuditToolTests(unittest.TestCase):
    """The layout audit is the geometric half of the visual checks, and it was reporting fiction.

    Two faults, both of which this file exists to prevent. It imported `app.application` without putting the
    project root on sys.path, so the documented `python3 tools/layout_audit.py` died with
    ModuleNotFoundError before it measured anything - and `tools/analyze_screenshot.py`, next to it, has
    always done that insert. Then, once it did run, it set the window size after Application() had already
    maximized itself; on Windows the zoomed state sticks and geometry() is ignored, so it measured a
    2532x1353 window while comparing every widget against a 1280x800 limit and printed 254 "off-window"
    issues, every one of them false.

    That second one is the more dangerous of the pair. A diagnostic that always reports problems is not
    obviously broken, and it buries a real clipping bug in two hundred and fifty lines of noise.
    """

    def _run(self, width=None, height=None):
        """Runs the tool the way the notes say to, from the project root."""
        env = dict(os.environ)
        if width: env["AUDIT_W"] = str(width)
        if height: env["AUDIT_H"] = str(height)
        return subprocess.run(
            [sys.executable, os.path.join("tools", "layout_audit.py")],
            capture_output=True, text=True, errors="replace", cwd=str(PROJECT_ROOT), env=env, timeout=300)

    def test_it_runs_as_a_script_the_way_the_notes_say_to(self):
        """Running a script puts tools/ on sys.path, not the project root, so the app import used to fail."""
        result = self._run()
        self.assertNotIn("ModuleNotFoundError", result.stderr,
                         "the layout audit cannot import the app when run as documented")
        self.assertEqual(result.returncode, 0, f"the layout audit exited {result.returncode}:\n{result.stderr}")

    def test_it_measures_the_window_size_it_asked_for(self):
        """The comparison limit is the requested size, so measuring a different size invalidates every result.

        Asserted on the size it reports rather than on the issues it finds: a genuine clipping bug should
        fail the geometry tests, not this one, and a test that pins "CLEAN" would keep failing for a reason
        that has nothing to do with the tool working.
        """
        result = self._run(1280, 800)
        self.assertRegex(result.stdout, r"measured 1280x800",
                         f"the tool did not measure the size it was asked for:\n{result.stdout}")
        self.assertNotIn("WARNING:", result.stdout,
                         f"the tool warned that its measurements do not match its limits:\n{result.stdout}")

    def test_it_actually_looks_at_the_widgets_rather_than_reporting_nothing(self):
        """"CLEAN" from a walk that examined nothing is the failure this project has been bitten by before.

        A safety net that is reported as present but was never run is worse than none, so the audit prints how
        many widgets it checked. Five pages of window is several hundred; a near-zero number means the walk
        stopped early and its clean bill of health is worth nothing.

        This cannot be pinned by shrinking the window, because the app's minsize(1100,680) means no reachable
        size overflows anything - which is the app behaving correctly, and is why the count is the honest
        thing to assert on.
        """
        result = self._run(1280, 800)
        match = re.search(r"checked (\d+) widgets", result.stdout)
        self.assertIsNotNone(match, f"the audit does not report how many widgets it checked:\n{result.stdout}")
        self.assertGreaterEqual(int(match.group(1)), 100,
                                "the audit reported a clean bill of health after examining almost nothing")

    def test_it_warns_when_the_window_would_not_take_the_size_it_asked_for(self):
        """The off-window check compares against the requested size, so a mismatch invalidates every result.

        Requesting a size below the window's minimum is the reliable way to produce that mismatch: Tk clamps
        to minsize, the tool keeps comparing against what was asked for, and it has to say so rather than
        quietly printing issues that mean nothing.
        """
        result = self._run(400, 300)
        self.assertIn("WARNING:", result.stdout,
                      f"the tool did not notice that the window refused the requested size:\n{result.stdout}")


if __name__ == "__main__":
    unittest.main()

