"""The whole workflow through real Tk and the real MainWindow: Scan -> Verify -> Review -> Organize -> Done.

Not a stub and not a unit test. It opens an actual Tk root, builds the actual Application, and drives the
buttons the user presses. What it covers is the seam the unit tests deliberately avoid: the screens, the
scan button's enable/disable, and the state handed from one screen to the next all have to work together in
one process, on a real event loop, with real worker threads reporting through the dispatch queue.

Two things make that safe to run unattended:

- The whole project root is redirected to a temporary tree before anything scans, by
  `tests.tk_support.sandbox_app`. The Application derives every path it writes from that root, and on this
  machine the project's own settings point at a real library on D:. A workflow test that organized into that
  would move a person's game folders, and one that saved its settings would rewrite the developer's.
- Mock mode. Archives are generated rather than discovered, so no real library is read and the archive
  toolchain is exercised for real only by the conversion tests, not by this file.

Every wait is bounded and its failure names the phase it was stuck in, because a hang is the interesting
outcome and must not read as a slow test.
"""

from __future__ import annotations

import pytest

import json
import random
import shutil
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.tk_support import require_tk, close_root, sandbox_app
from tests.test_artwork_render import _jpeg_bytes
from tests.test_ui_geometry import _measured_window

# TestRealWorkflow extracted to tests\test_real_workflow.py — see that module for its definition.
# wait_for_organize extracted to tests\wait_for_organize.py — see that module for its definition.
from tests.wait_for_organize import wait_for_organize
# wait_until extracted to tests\wait_until.py — see that module for its definition.
from tests.wait_until import wait_until
# ROOT and MOCK_APPIDS moved to test_helpers.py. They were defined here and imported back by
# test_real_workflow.py, which made the pair order-dependent: importing test_real_workflow first (unittest's
# alphabetical order) failed with a partially-initialised module. A constant belongs in the module with no
# dependencies, so both live there now and are imported here to keep this module's public names working.
from tests.test_helpers import MOCK_APPIDS, ROOT

# One-directional now: test_real_workflow imports its constants from test_helpers, not from this module.
from tests.test_real_workflow import TestRealWorkflow


if __name__ == "__main__":
    unittest.main()
