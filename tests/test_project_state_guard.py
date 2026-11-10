"""The suite must not write the state of the project it runs in.

`AppConfig` derives every path it writes from its project root, and `Application` builds one from
`Path(__file__).resolve().parents[1]` - this repository. A test that constructs either one the ordinary way
therefore inherits the developer's own `config/`, `cache/` and `logs/`, and ordinary code paths write to all
of them: `MainWindow.show()` appends a line to the log on every screen change, `MainWindow.scan()` saves
settings twice over, a finished scan records a summary, an organize run records into the undo journal, and
`ArtworkService.__init__` *deletes* from the artwork cache directory it was handed.

That was not theoretical. Two suite runs were started at once, they raced on the real `config/settings.json`,
and one of them left it holding `convert_archives: false` - which silently turns off zip/rar -> 7z conversion
on the next real run. It reads exactly like the OneDrive `WinError 5` lock that `AppConfig.save()` retries,
and that retry is real and is still there, so the symptom points at the wrong cause entirely.

These are the guard. Each snapshots every file under `config/`, exercises the writes that used to reach it,
and fails if any byte or mtime moved. The writes are aimed at a temporary tree - except when
`PROJECT_UNDER_TEST` says otherwise, which is how both were proved able to fail:

    PROJECT_UNDER_TEST = ROOT     # run this module, watch both tests fail, put it back

`tests/tk_support.sandbox_app` is how every other test in the suite builds its window and its config; the
second test here is what holds that mechanism to this same rule.
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.controller import AppController
from app.events import EventBus
from app.jobs import JobManager
from core.config import AppConfig
from core.logger import AppLogger
from core.models import ScanResult
from core.state import StateStore
from services.organizer_service import OrganizerService
from services.rollback_service import RollbackService
from tests.tk_support import close_root, require_tk, sandbox_app

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / 'config'

# The seam both tests are proved against. `None` aims their writes at a temporary tree; pointing this at ROOT
# reproduces the defect, and it has to be a one-line edit somebody can actually make.
PROJECT_UNDER_TEST = None

WRITTEN_FILES = ('settings.json', 'scan-state.json', 'category-decisions.json', 'last-organization.json')


def snapshot_config():
    """Every real file under `config/`, as bytes and mtime. A missing directory reads as an empty snapshot."""
    if not CONFIG_DIR.is_dir():
        return {}
    return {path: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in sorted(CONFIG_DIR.rglob('*')) if path.is_file()}


def write_like_the_offending_tests(root):
    """The four writers, aimed at `root`, in the order one run of the app hits them.

    The config is constructed and saved (`MainWindow.scan()` calls `save_api()` and assigns
    `convert_archives`, each of which saves), a finished scan records a summary through the controller, a
    review decision is remembered, and an organize run records into the undo journal. `root` is a parameter
    because pointing it at the real project is the only way to watch this fail.
    """
    library = root / 'Games'
    library.mkdir(parents=True, exist_ok=True)
    config = AppConfig(root, library_root=library)
    config.save()
    config.convert_archives = True
    logger = AppLogger(root / 'logs' / 'organizer.log')
    controller = AppController(StateStore(), EventBus(), logger, type('Services', (), {})(), JobManager())
    controller.config = config
    controller._scan_ok(ScanResult(archives=[]), lambda result: None)
    controller.remember_category('guard-game', 'Simulation')
    RollbackService(root, logger, organizer=OrganizerService(logger)).record(
        [(library / 'Guard Game.zip', library / 'Guard Game.7z')])
    return config


class TheSuiteDoesNotWriteThisProjectsOwnState(unittest.TestCase):
    """Two guards over the same snapshot: the config writers themselves, and a real window built the way the
    rest of the suite builds one. The second is the shape that actually caused the corruption, so testing only
    the first would leave the mechanism that reached the file uncovered."""

    def _assert_untouched(self, before, after):
        self.assertEqual(sorted(before), sorted(after),
                         f'a file appeared under {CONFIG_DIR.name}/ during the run: '
                         f'{sorted(set(after) - set(before))}')
        for path, (data, mtime) in sorted(before.items()):
            self.assertEqual(data, after[path][0], f'{path.name} was rewritten')
            self.assertEqual(mtime, after[path][1], f'{path.name} was touched without its bytes changing')

    def _assert_config_has_files_to_protect(self):
        before = snapshot_config()
        self.assertTrue(before, f'{CONFIG_DIR} holds no files, so this guard would pass without looking at '
                                f'anything - it has nothing to protect')
        return before

    def test_the_writes_that_reached_the_real_config_go_to_a_temporary_tree(self):
        before = self._assert_config_has_files_to_protect()

        with TemporaryDirectory() as raw:
            target = PROJECT_UNDER_TEST if PROJECT_UNDER_TEST is not None else Path(raw) / 'project'
            write_like_the_offending_tests(target)
            # The control, and it comes first on purpose: without it this test would be satisfied by the
            # exercised writes doing nothing at all, which is a different defect and an easier one to ship.
            for name in WRITTEN_FILES:
                self.assertTrue((target / 'config' / name).is_file(),
                                f'the exercised writes never produced {name}, so nothing was actually written '
                                f'and the assertions below prove nothing')

        self._assert_untouched(before, snapshot_config())

    def test_a_real_window_writes_nothing_into_this_projects_own_config(self):
        require_tk(self)
        import tkinter as tk

        before = self._assert_config_has_files_to_protect()
        root = tk.Tk()
        self.addCleanup(close_root, root)

        app = sandbox_app(self, root, project_root=PROJECT_UNDER_TEST)
        app.window.show('review')
        root.update()
        # The save every scan starts with, driven through the window rather than through AppConfig, so this
        # covers the composition as well: a MainWindow holding a config rooted at the project.
        app.window.views['scan'].api_var.set('sandbox-key')
        app.window.save_api()
        root.update()
        app.shutdown()

        # The controls, and they come first on purpose. Without the log the run never reached the code that
        # writes, and without the saved key it never reached the write either - and a guard that passes
        # because nothing happened is the failure mode this file exists to prevent.
        log = app.config.log_file
        self.assertTrue(log.is_file() and log.stat().st_size > 0,
                        f'the window logged nothing at all, so it never reached the code that writes: {log}')
        self.assertEqual('sandbox-key',
                         json.loads(app.config.settings_file.read_text(encoding='utf-8'))['steamgriddb_api_key'],
                         'the window saved no API key, so it never reached AppConfig.save()')

        self._assert_untouched(before, snapshot_config())
        self.assertNotEqual(CONFIG_DIR, app.config.config_dir,
                            'the window under test is pointed at the real config directory, so the run above '
                            'proved nothing about the redirect')
