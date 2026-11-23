"""Tests using pytest-mock's `mocker` fixture.

Demonstrates the newly installed pytest-mock package:
- pytest-mock's `mocker` fixture patches and auto-cleans up after the test.
- Replaces `unittest.mock.patch` with a cleaner, context-manager-free API.
"""

from __future__ import annotations

import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.config import AppConfig, ROTATED_LOGS


def _make_log_file(log_dir: Path, name: str, mtime_seconds: float) -> Path:
    """Create a log file in log_dir with the given name and mtime."""
    path = log_dir / name
    path.write_text("log content\n", encoding="utf-8")
    ts = datetime.fromtimestamp(mtime_seconds, tz=timezone.utc)
    path.touch((ts.timestamp(), ts.timestamp()))
    return path


def test_pytest_mock_mocker_fixture(mocker):
    """pytest-mock's `mocker` fixture patches and auto-cleans up after the test.

    Replaces `unittest.mock.patch` with a context-manager-free fixture that
    is automatically restored when the test ends.
    """
    from core.config import AppConfig as AC

    # Patch AppConfig.default_library_root to return a controlled path
    fake_root = Path("/mock/library")
    mocker.patch.object(AC, "default_library_root", return_value=fake_root)

    config = AC.__new__(AC)
    config.library_root = fake_root
    assert config.default_library_root() == fake_root
    # mocker auto-restores the original after the test; no manual cleanup needed


def test_log_rotation_keeps_last_ten(tmp_path):
    """Creates 12 log files with staggered mtimes, then verifies that
    AppConfig._rotate_logs() keeps only the last ROTATED_LOGS (10).
    """
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    now = datetime.now(tz=timezone.utc).timestamp()

    # Create 12 log files, oldest first. Small sleep between creations so each
    # file gets a distinct mtime on the filesystem (Windows mtime resolution
    # can be coarse, so distinct offsets alone are not always enough).
    for i in range(12):
        mtime = now - (12 - i) * 60  # each file 1 minute newer than the last
        name = f"organizer-9.33-20260115-{120000 + i:06d}.log"
        _make_log_file(log_dir, name, mtime)
        time.sleep(0.01)

    # Create config pointing at our temp log dir
    config = AppConfig.__new__(AppConfig)
    config.log_dir = log_dir
    config._rotate_logs()

    remaining = sorted(p.name for p in log_dir.glob("organizer-*.log"))
    assert len(remaining) == ROTATED_LOGS, f"Expected {ROTATED_LOGS} logs, got {len(remaining)}: {remaining}"

    # The 2 oldest should have been deleted
    assert "organizer-9.33-20260115-120000.log" not in remaining
    assert "organizer-9.33-20260115-120001.log" not in remaining

    # The 10 newest should remain
    for i in range(2, 12):
        name = f"organizer-9.33-20260115-{120000 + i:06d}.log"
        assert name in remaining, f"Expected {name} to remain after rotation"


def test_log_rotation_under_ten_keeps_all(tmp_path):
    """When there are fewer than ROTATED_LOGS files, nothing is deleted."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    now = datetime.now(tz=timezone.utc).timestamp()
    for i in range(5):
        mtime = now - (5 - i) * 60
        name = f"organizer-9.33-20260115-{130000 + i:06d}.log"
        _make_log_file(log_dir, name, mtime)
        time.sleep(0.01)

    config = AppConfig.__new__(AppConfig)
    config.log_dir = log_dir
    config._rotate_logs()

    remaining = sorted(p.name for p in log_dir.glob("organizer-*.log"))
    assert len(remaining) == 5


def test_pytest_mock_patches_os_unlink(mocker):
    """pytest-mock can patch functions used by code under test."""
    import os

    fake_unlink = mocker.patch("os.unlink")

    # Simulate code that calls os.unlink
    os.unlink("/some/path")

    fake_unlink.assert_called_once_with("/some/path")
