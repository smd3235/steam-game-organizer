"""Extracted from tests/test_library_summary.py.

    TestUndoInvalidation was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import json
import unittest
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from tests.test_library_summary import service
from core.logger import AppLogger


class TestUndoInvalidation(unittest.TestCase):
    def test_undo_drops_the_index_because_it_does_not_regenerate_the_catalog(self):
        """Undo is the one path that changes the library without generating the catalog, so the retained numbers
        go on describing a run that was just put back. Dropped rather than rebuilt: the walk is only worth
        paying for when something asks for the index."""
        from threading import Event
        from app.controller import AppController
        from app.events import EventBus
        from app.jobs import JobManager
        from core.state import StateStore
        from services.rollback_service import RollbackService
        from services.organizer_service import OrganizerService

        with TemporaryDirectory() as d:
            work = Path(d)
            library = work / "Games"
            # Incoming holds no archive: the run moved it out, which is the state undo_last() is called from. A
            # file left there makes `not restore.exists()` false and the undo a no-op - a fixture that proves
            # nothing, which is the one thing a test about Undo must not be.
            incoming = work / "Incoming"
            incoming.mkdir(parents=True)
            source = incoming / "Loop Miner.7z"
            game_dir = library / "Idle" / "Loop Miner - 2026-01-01"
            game_dir.mkdir(parents=True)
            (game_dir / "Loop Miner.7z").write_bytes(b"7z\xbc\xaf\x27\x1c")
            (game_dir / ".game-info.json").write_text(json.dumps({"appid": "1", "name": "Loop Miner"}), encoding="utf-8")
            logger = AppLogger(work / "x.log")
            catalog = service(work)
            catalog.generate(library)
            self.assertEqual(catalog.library_summary().total_games, 1)
            rollback = RollbackService(work, logger, organizer=OrganizerService(logger))
            self.assertTrue(rollback.record([(source, game_dir / "Loop Miner.7z")], [str(game_dir)]), "the row was not journalled, so this case would prove nothing")
            services = type("Services", (), {"catalog": catalog, "rollback": rollback})()
            jobs = JobManager()
            controller = AppController(StateStore(), EventBus(), logger, services, jobs)
            finished = Event()
            out = []
            controller.undo_last(library, lambda result: (out.append(result), finished.set()))
            self.assertTrue(finished.wait(15), "the undo never finished")
            jobs.shutdown()
            self.assertEqual(out, [{"moved": 1, "pruned": 1, "reason": "Rollback complete"}], out)
            self.assertIsNone(catalog._summary, "the index still describes the run that was undone")
            self.assertFalse(catalog.library_summary().indexed)
            # And the next read rebuilds rather than answering out of the dropped one: 0 games, because the
            # archive is back in Incoming and the folder the run created is gone.
            self.assertEqual(catalog.library_summary(library).total_games, 0)
            self.assertEqual(catalog.collects, 2, f"{catalog.collects} walks for one generate and one rebuild")
