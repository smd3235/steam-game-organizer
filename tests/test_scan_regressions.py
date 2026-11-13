"""Regression tests for scan and library behaviour.

These tests were extracted from tests/test_regressions.py to keep each test module
focused on one area of the app: known identity regressions, New Only scanning,
and Preview Only write protection.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.config import AppConfig
from ui.main_window import MainWindow
from utils.filename_utils import identity_key, normalize_name
from core.models import ArtworkResult

# TestPreviewOnlyDoesNotMoveAnything extracted to tests\test_preview_only_does_not_move_anything.py — see that module for its definition.
from tests.test_preview_only_does_not_move_anything import TestPreviewOnlyDoesNotMoveAnything
# TestKnownRegressionCases extracted to tests\test_known_regression_cases.py — see that module for its definition.
from tests.test_known_regression_cases import TestKnownRegressionCases
# TestNewOnlyWithNothingNewDoesNotBlockOnTheVerifyScreen extracted to tests\test_new_only_with_nothing_new_does_not_block_on_the_verify_screen.py — see that module for its definition.
from tests.test_new_only_with_nothing_new_does_not_block_on_the_verify_screen import TestNewOnlyWithNothingNewDoesNotBlockOnTheVerifyScreen
def _tmp_dir(test_case):
    """A temporary directory that is cleaned up when the test finishes."""
    tmp = Path(tempfile.mkdtemp())
    test_case.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    return tmp

