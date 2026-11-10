import unittest


import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from core.config import AppConfig
from core.logger import AppLogger
from core.state import StateStore
from debug.diagnostics import Diagnostics
@pytest.mark.notkinter
class TestDiagnostics(unittest.TestCase):
 def test_health_and_report(self):
  with TemporaryDirectory() as d:
   c=AppConfig(Path(d)); c.ensure_directories(); l=AppLogger(c.log_file); r=Diagnostics(c,StateStore(),l).report(); self.assertIn("DIAGNOSTIC REPORT",r); self.assertTrue(Diagnostics(c,StateStore(),l).health()["project_root"])
