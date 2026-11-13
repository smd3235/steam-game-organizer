"""Extracted from tests/test_category_evidence.py.

    TestControllerRecordsEvidence was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from core.constants import CategoryEvidence
from core.constants import UNSORTED_EVIDENCE
from core.models import ArtworkResult
from core.models import GameArchive
from core.models import SteamMatch
from core.state import StateStore


class TestControllerRecordsEvidence(unittest.TestCase):
    """Both call sites have to attach the evidence to the decision, and the evidence has
    to describe the computed suggestion even when a remembered category replaces it."""

    class _Steam:
        def __init__(self, found=True):
            self.found = found

        def lookup(self, title, ctx, archive_path=None, refresh=False):
            if not self.found:
                return SteamMatch(found=False)
            return SteamMatch(found=True, appid="1", name="Factory Game", description="Automate production", genres=["Indie", "Simulation"], tags=["Automation", "Factory"], categories=["Automation"])

        def remember(self, title, steam_match):
            pass

    class _Artwork:
        def download_assets(self, *args, **kwargs):
            return ArtworkResult(status="not_requested")

        def lookup(self, appid):
            return ArtworkResult(status="not_requested")

    def _controller(self, logger, jobs, steam):
        from app.controller import AppController
        from app.events import EventBus

        services = type("Services", (), {"steam": steam, "artwork": self._Artwork()})()
        return AppController(StateStore(), EventBus(), logger, services, jobs)

    def _archive(self):
        return GameArchive(Path("/tmp/Factory.zip"), "Factory Game", "Factory Game", "factory", ".zip")

    def _run(self, method, *args):
        # _submit() hands back only the JobContext, not the future, so the
        # result is captured through the done callback the job invokes.
        finished = threading.Event()
        captured = {}

        def done(result):
            captured["result"] = result
            finished.set()

        method(*args, done)
        self.assertTrue(finished.wait(timeout=30), "the verify job never finished")
        return captured["result"]

    def test_verify_all_attaches_the_evidence_to_the_decision(self):
        from app.jobs import JobManager
        from core.logger import AppLogger

        with TemporaryDirectory() as d:
            logger = AppLogger(Path(d) / "x.log")
            jobs = JobManager()
            controller = self._controller(logger, jobs, self._Steam())
            results = self._run(controller.verify_all, [self._archive()], lambda *a: None)
            self.assertEqual(results[0].decision.category, "Automation")
            self.assertEqual(results[0].decision.suggested_category, "Automation")
            self.assertEqual(results[0].decision.evidence,
                             CategoryEvidence(chosen="Automation", score=101,
                                              basis="description",
                                              terms=("automate", "factory"),
                                              runners_up=(("Simulation", 53),),
                                              considered=2))
            jobs.shutdown()

    def test_verify_one_attaches_the_evidence_to_the_decision(self):
        from app.jobs import JobManager
        from core.logger import AppLogger

        with TemporaryDirectory() as d:
            logger = AppLogger(Path(d) / "x.log")
            jobs = JobManager()
            controller = self._controller(logger, jobs, self._Steam())
            result = self._run(controller.verify_one, self._archive(), "Factory Game")
            self.assertEqual(result.decision.category, "Automation")
            self.assertEqual(result.decision.suggested_category, "Automation")
            self.assertEqual(result.decision.evidence,
                             CategoryEvidence(chosen="Automation", score=101,
                                              basis="description",
                                              terms=("automate", "factory"),
                                              runners_up=(("Simulation", 53),),
                                              considered=2))
            self.assertEqual(result.decision.accepted, False)
            jobs.shutdown()

    def test_a_remembered_category_replaces_the_category_but_not_the_evidence(self):
        from app.jobs import JobManager
        from core.logger import AppLogger

        with TemporaryDirectory() as d:
            logger = AppLogger(Path(d) / "x.log")
            jobs = JobManager()
            controller = self._controller(logger, jobs, self._Steam())
            controller.config = type("Config", (), {"config_dir": Path(d), "sync_to_appdata": lambda self: None})()
            controller.remember_category("factory", "Adventure")
            results = self._run(controller.verify_all, [self._archive()], lambda *a: None)
            # The combobox shows the remembered folder...
            self.assertEqual(results[0].decision.category, "Adventure")
            # ...while the suggestion, and the evidence beside it, still describe the
            # computed answer.
            self.assertEqual(results[0].decision.suggested_category, "Automation")
            self.assertEqual(results[0].decision.evidence.chosen, "Automation")
            self.assertEqual(results[0].decision.evidence.basis, "description")
            jobs.shutdown()

    def test_a_game_the_steam_lookup_misses_gets_fallback_evidence(self):
        from app.jobs import JobManager
        from core.logger import AppLogger

        with TemporaryDirectory() as d:
            logger = AppLogger(Path(d) / "x.log")
            jobs = JobManager()
            controller = self._controller(logger, jobs, self._Steam(found=False))
            results = self._run(controller.verify_all, [self._archive()], lambda *a: None)
            self.assertEqual(results[0].decision.category, "Unsorted")
            self.assertEqual(results[0].decision.evidence, UNSORTED_EVIDENCE)
            jobs.shutdown()

    def test_the_debug_log_reports_the_rule_that_won(self):
        from app.jobs import JobManager
        from core.logger import AppLogger

        with TemporaryDirectory() as d:
            logger = AppLogger(Path(d) / "x.log")
            jobs = JobManager()
            controller = self._controller(logger, jobs, self._Steam())
            with patch.object(logger, "debug") as debug:
                self._run(controller.verify_all, [self._archive()], lambda *a: None)
            messages = [call.args[1] for call in debug.call_args_list
                        if call.args and call.args[0] == "CATEGORY"]
            self.assertTrue(any("basis=[description]" in m and "terms=[automate|factory]" in m
                                 and "runners_up=[Simulation:53]" in m for m in messages),
                            "the debug log no longer says which rule won and what it matched: %r"
                            % (messages,))
            jobs.shutdown()
