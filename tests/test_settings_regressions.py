"""Regression tests for settings and lock behaviour.

These tests were extracted from tests/test_regressions.py to keep each test module
focused on one area of the app: config save retry under file locks, and category
decision persistence under OneDrive-style locking.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.config import AppConfig
from core.logger import AppLogger


def _tmp_dir(test_case):
    """A temporary directory that is cleaned up when the test finishes."""
    tmp = Path(tempfile.mkdtemp())
    test_case.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
    return tmp


class TestSettingsSurvivesASyncClientLock(unittest.TestCase):
    """Config.save() must not let a file lock stop the app working.

    Found in the real log rather than reasoned about: pressing Scan raised PermissionError from os.replace and
    the scan never started. The project lived in a OneDrive folder, and OneDrive opens the file it is syncing,
    so the target is briefly un-replaceable - WinError 5, "Access is denied". os.replace is atomic and that is
    exactly why it is used, but atomicity buys nothing if the one call can fail on a locked destination and the
    exception is allowed to reach the button handler that called it.

    Retrying is the fix, and the bound matters as much as the retry: a genuinely read-only settings directory
    must still report the failure rather than spin.
    """

    def _config(self, tmp):
        (tmp / "Incoming").mkdir(parents=True, exist_ok=True)
        return AppConfig(project_root=tmp, library_root=tmp / "Incoming")

    def _settings(self, tmp):
        """Where AppConfig puts settings.json: a config/ directory under the project root, not the root itself."""
        return tmp / "config" / "settings.json"

    def test_a_transient_lock_does_not_lose_the_settings(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            config = self._config(tmp)
            config.settings["steamgriddb_api_key"] = "abc123"
            real = os.replace
            calls = []

            def locked(source, target):
                calls.append(target)
                if len(calls) <= 2:
                    raise PermissionError(5, "Access is denied", str(target))
                return real(source, target)

            with patch("core.config.os.replace", side_effect=locked):
                config.save()
                self.assertEqual(
                    3,
                    len(calls),
                    f"save() gave up after {len(calls)} attempt(s) instead of retrying a locked file",
                )
                self.assertEqual(
                    "abc123",
                    json.loads(self._settings(tmp).read_text(encoding="utf-8"))["steamgriddb_api_key"],
                    "the settings did not reach the file once the lock cleared",
                )

    def test_a_permanent_failure_is_still_reported(self):
        """The opposite requirement, and the one a retry can quietly break.

        A settings directory that cannot be written has to say so. Retrying forever would turn a clear error into a
        hung button, and swallowing it would mean the app runs on settings it never saved.
        """
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            config = self._config(tmp)

            def always_locked(source, target):
                raise PermissionError(5, "Access is denied", str(target))

            with patch("core.config.os.replace", side_effect=always_locked):
                with self.assertRaises(PermissionError):
                    config.save()
                self.assertFalse(
                    self._settings(tmp).exists(), "a failed save left a settings file behind"
                )

    def test_the_temporary_file_is_removed_after_a_failed_save(self):
        """A leftover settings.XXXX.tmp is not harmless.

        ensure_directories() and the next mkstemp all work in this directory, so a temp file left by every failed
        save is how a config directory slowly fills with the debris of previous attempts.
        """
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            config = self._config(tmp)

            def always_locked(source, target):
                raise PermissionError(5, "Access is denied", str(target))

            with patch("core.config.os.replace", side_effect=always_locked):
                with self.assertRaises(PermissionError):
                    config.save()
            leftovers = list((tmp / "config").glob("settings.*.tmp"))
            self.assertEqual(
                [],
                leftovers,
                f"{len(leftovers)} temporary settings file(s) left behind: {[p.name for p in leftovers]}",
            )


class TestTheCategoryDecisionSurvivesALockedFolder(unittest.TestCase):
    """remember_category() writes the user's pick through the same folder OneDrive
    syncs. v9.19 absorbed that lock for settings.json; the category decisions were
    written with a fixed temp name and an unguarded replace, so the same brief lock
    raised out of the review screen's click handler and took the pick with it."""

    def _controller(self, d):
        from app.controller import AppController
        from app.events import EventBus
        from app.jobs import JobManager
        from core.state import StateStore

        self.warnings = []
        logger = SimpleNamespace(warning=lambda *a, **k: self.warnings.append((a, k)))
        jobs = JobManager()
        controller = AppController(StateStore(), EventBus(), logger, type("Services", (), {})(), jobs)
        controller.config = type(
            "Config", (), {"config_dir": Path(d), "sync_to_appdata": lambda self: None}
        )()
        self.addCleanup(jobs.shutdown)
        return controller

    def test_a_brief_lock_on_the_replace_is_retried(self):
        import os as os_module

        root = Path(_tmp_dir(self))
        controller = self._controller(root)
        real = os_module.replace
        calls = []

        def flaky(src, dst):
            calls.append(str(src))
            if len(calls) == 1:
                raise PermissionError("locked")
            return real(src, dst)

        with patch("os.replace", side_effect=flaky):
            controller.remember_category("example", "Simulation")
            self.assertEqual(
                controller._saved_categories()["identity"]["example"],
                "Simulation",
                "the pick was lost to a lock that a retry would have cleared",
            )

    def test_a_stale_temp_file_of_the_old_fixed_name_cannot_block_the_write(self):
        """The old writer used category-decisions.tmp for every write, so a leftover
        from a crashed run - read-only, or held by a second copy of the app - was in
        the way of the next one. mkstemp names are unique, so the stale file is
        simply never opened: the fixture is the old collision, and the write has to
        succeed around it."""
        root = Path(_tmp_dir(self))
        controller = self._controller(root)
        stale = root / "category-decisions.tmp"
        stale.write_text("{}")
        os.chmod(stale, 0o444)
        self.addCleanup(lambda: os.chmod(stale, 0o644))
        controller.remember_category("example", "Simulation")
        self.assertEqual(
            controller._saved_categories()["identity"]["example"],
            "Simulation",
            "a stale temp file of the old fixed name blocked the write",
        )
        self.assertEqual(
            stale.read_text(),
            "{}",
            "the write went through the stale file instead of around it",
        )

    def test_a_lock_that_outlives_the_retries_costs_a_warning_not_a_crash(self):
        """The decision is already held in memory when the write runs, so a folder
        that stays locked costs the on-disk copy of the pick - not the callback the
        click handler was mid-way through. The old code raised straight out of the
        review screen's handler."""
        root = Path(_tmp_dir(self))
        controller = self._controller(root)
        with patch("os.replace", side_effect=PermissionError("locked")):
            controller.remember_category("example", "Simulation")
            self.assertEqual(
                controller._category_cache["identity"].get("example"),
                "Simulation",
                "the in-memory decision was lost with the write",
            )
        self.assertTrue(
            self.warnings,
            "a pick that could not be saved was not reported anywhere",
        )
        self.assertEqual(
            list(root.glob("category-decisions.*.tmp")),
            [],
            f"the temp file was left behind: {list(root.glob('category-decisions.*'))}",
        )
