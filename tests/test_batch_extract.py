"""The catalog's batch Extract: a per-category Extract all and a whole-library Extract all.

The rule that shapes all of this is in core/uri_actions.py and is asserted here rather than assumed. A batch link
names a category and nothing else - no archive paths - so the app enumerates the library itself. If the link could
carry its own list, the registered handler would be a way for any web page the user visits to choose what gets
unpacked on their machine, and the "is this inside the library" check that makes the single extract safe would
have to hold once per entry instead of once.

The rest is about the two things a batch has that a single extract does not: it runs for hours, so it has to
report where it is and be stoppable; and it touches many archives, so one bad one must not cost the rest.
"""
from __future__ import annotations

import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from core.constants import LIBRARY_RESERVED_DIRS
from core.logger import AppLogger
from core.uri_actions import UriRefused, parse_batch_uri
from services import batch_extract_service
from services.batch_extract_service import CANCELLED, DONE, EXTRACTING, FAILED, BatchExtractJob, plan_batch
from services.catalog_service import CatalogService
from services.extract_service import ExtractResult, ExtractService
from tests.test_services import _write_stub


def _game(root: Path, category: str, name: str, payload: int = 2048) -> Path:
    """A real zip on disk, with the metadata sidecar the catalog reads."""
    folder = root / category / f"{name} - 2024-01-01"
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / f"{name}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as handle:
        handle.writestr(f"{name}/game.bin", b"a" * payload)
    (folder / ".game-info.json").write_text(f'{{"appid":"1","name":"{name}","genres":["Idle"]}}', encoding="utf-8")
    return archive


class BatchLinkNamesACategoryAndNothingElse(unittest.TestCase):
    """The security property. Everything else about the feature is convenience; this is the part that matters."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "Games"
        self.dest = Path(temporary.name) / "Out"
        self.dest.mkdir(parents=True)
        _game(self.root, "Idle", "Loop Miner")
        _game(self.root, "Idle", "Fellwood")
        _game(self.root, "RPG", "Deep Signal")

    def _parse(self, uri):
        return parse_batch_uri(uri, self.root, [self.dest])

    def test_a_category_link_resolves_to_that_folder(self):
        request = self._parse("steamgameorganizer://extract-all?category=Idle")
        self.assertEqual(request.category, "Idle")
        self.assertEqual(request.destination, self.dest)

    def test_the_link_carries_no_archive_paths_at_all(self):
        """The point of the design, asserted on the parsed request: there is nowhere for a page to put a source.

        A BatchExtractRequest has no field a path could be smuggled into, so this cannot regress into accepting
        one without the dataclass changing - a visible change rather than a silent one.
        """
        request = self._parse("steamgameorganizer://extract-all?category=Idle")
        extra = [name for name in request.__dataclass_fields__ if name not in ("category", "destination")]
        self.assertEqual(extra, [], f"BatchExtractRequest grew a field, so it can now be told what to unpack: {extra}")

    def test_a_src_parameter_in_the_link_is_ignored_rather_than_obeyed(self):
        """A page trying the single-extract trick anyway gets a category request, not a chosen file."""
        request = self._parse("steamgameorganizer://extract-all?category=Idle&src=C:/Windows/System32/config/SAM")
        self.assertEqual(request.category, "Idle")
        self.assertNotIn("archive", request.__dataclass_fields__)

    def test_a_bare_link_names_the_whole_library(self):
        """An extract-all link with no category selects every archive in the library.
        The category folder check is skipped for the empty case, which _handle_batch_uri
        treats as "whole library" rather than a refusal."""
        request = self._parse("steamgameorganizer://extract-all")
        self.assertEqual(request.category, "")
        self.assertEqual(request.destination, self.dest)

    def test_a_category_that_is_not_a_real_folder_is_refused(self):
        with self.assertRaises(UriRefused):
            self._parse("steamgameorganizer://extract-all?category=Nope")

    def test_a_category_cannot_walk_out_of_the_library(self):
        for hostile in ("..", "..%2F..", "Idle/../../Windows", "C:/Windows", "Idle\\..\\..", "Idle/"):
            with self.subTest(category=hostile):
                with self.assertRaises(UriRefused):
                    self._parse(f"steamgameorganizer://extract-all?category={hostile}")

    def test_the_apps_own_folders_are_not_categories(self):
        """Archive/ holds duplicates set aside on purpose and Processing/ holds a build in flight. Unpacking
        either would re-do work the app deliberately did not do."""
        for reserved in sorted(LIBRARY_RESERVED_DIRS):
            with self.subTest(folder=reserved):
                (self.root / reserved).mkdir(exist_ok=True)
                with self.assertRaises(UriRefused):
                    self._parse(f"steamgameorganizer://extract-all?category={reserved}")

    def test_a_hidden_folder_is_not_a_category(self):
        (self.root / ".stversions").mkdir()
        with self.assertRaises(UriRefused):
            self._parse("steamgameorganizer://extract-all?category=.stversions")

    def test_the_destination_follows_the_same_rules_as_a_single_extract(self):
        """The free-text case is a security boundary, and a second copy of it would be a second thing to get
        wrong. Proving the batch path refuses what the single path refuses is what keeps the two in step."""
        with self.assertRaises(UriRefused):
            self._parse("steamgameorganizer://extract-all?category=Idle&dest=not-a-full-path")
        with self.assertRaises(UriRefused):
            self._parse(f"steamgameorganizer://extract-all?category=Idle&dest={self.root}/Inside")
        request = self._parse(f"steamgameorganizer://extract-all?category=Idle&dest={self.dest}/Somewhere")
        self.assertEqual(request.destination, self.dest / "Somewhere")

    def test_a_single_extract_link_is_not_a_batch(self):
        with self.assertRaises(UriRefused):
            self._parse("steamgameorganizer://extract?src=x")


class PlanningABatchKnowsWhatItWouldDo(unittest.TestCase):
    """plan_batch runs before anything is unpacked, so the window can state the real count and size first."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "Games"
        self.dest = Path(temporary.name) / "Out"
        self.dest.mkdir(parents=True)
        self.logger = AppLogger(Path(temporary.name) / "x.log")
        _game(self.root, "Idle", "Loop Miner", 4096)
        _game(self.root, "Idle", "Fellwood", 4096)
        _game(self.root, "RPG", "Deep Signal", 4096)

    def _plan(self, category="", **kwargs):
        return plan_batch(self.root, self.dest, category, self.logger, **kwargs)

    def test_a_category_plan_covers_that_category_only(self):
        plan = self._plan("Idle")
        self.assertEqual(sorted(item.name for item in plan.items), ["Fellwood", "Loop Miner"])
        self.assertEqual(plan.category, "Idle")

    def test_a_whole_library_plan_covers_every_category(self):
        plan = self._plan()
        self.assertEqual(sorted(item.name for item in plan.items), ["Deep Signal", "Fellwood", "Loop Miner"])

    def test_the_plan_states_a_total_size_rather_than_leaving_the_window_to_add_it_up(self):
        plan = self._plan()
        self.assertGreater(plan.total_bytes, 0)
        self.assertEqual(plan.total_bytes, sum(item.size for item in plan.items))

    def test_two_games_with_one_name_do_not_land_in_one_folder(self):
        """A .7z and a .zip of the same title in different categories normalise to the same stem, and would
        otherwise unpack into one folder and interleave. The folder comes from the stem, so the collision has to
        be broken there."""
        _game(self.root, "RPG", "Loop Miner", 4096)
        folders = [item.destination for item in self._plan().items]
        self.assertEqual(len(folders), len(set(folders)), f"two games share a destination: {folders}")

    def test_an_already_unpacked_game_is_skipped_and_counted(self):
        """Otherwise Extract all on a shelf of 176 re-unpacks everything already unpacked on every click, and
        the button stops being usable after the first hour."""
        first = self._plan("Idle").items[0]
        first.destination.mkdir(parents=True)
        (first.destination / "already here.bin").write_bytes(b"x" * 10)
        second = self._plan("Idle")
        self.assertEqual(len(second.items), 1)
        self.assertEqual(second.already_done, 1)

    def test_an_empty_folder_is_not_treated_as_finished(self):
        """An interrupted run leaves the folder behind. Treating that as done would silently skip the one game
        the user most wants finished - the one it died on."""
        self._plan("Idle").items[0].destination.mkdir(parents=True)
        self.assertEqual(len(self._plan("Idle").items), 2, "an empty folder counted as already extracted")

    def test_the_destination_is_the_parent_and_each_game_gets_a_folder_inside_it(self):
        plan = self._plan("Idle")
        for item in plan.items:
            self.assertEqual(item.destination.parent, self.dest,
                             "a game's folder is not inside the requested destination")

    def test_an_installer_archive_gets_a_needs_install_destination(self):
        """An installer archive (setup.exe + .bin) must land in <dest>/Needs Install/, not crash plan_batch.

        NEEDS_INSTALL_DIRNAME was a bare str, so `NEEDS_INSTALL_DIRNAME / leaf` raised TypeError whenever any
        archive in the batch was detected as an installer. That crashed plan_batch before the window opened,
        which is why Extract all on a library with repacks silently produced no UI at all.
        """
        from services.installer_detect import NEEDS_INSTALL_DIRNAME
        folder = self.root / "Idle" / "Repack Game - 2024-01-01"
        folder.mkdir(parents=True, exist_ok=True)
        archive = folder / "Repack Game.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as handle:
            handle.writestr("setup.exe", b"x" * 100)
            handle.writestr("game.bin", b"y" * 4096)
        (folder / ".game-info.json").write_text('{"appid":"1","name":"Repack Game","genres":["RPG"]}',
                                                  encoding="utf-8")
        plan = self._plan("Idle")
        installers = [item for item in plan.items if NEEDS_INSTALL_DIRNAME in item.destination.parts]
        self.assertTrue(installers, "no item placed under Needs Install/")
        self.assertEqual(len(plan.items), 3)
        for item in installers:
            self.assertIn(NEEDS_INSTALL_DIRNAME, item.destination.parts)


class RunningABatchReportsEveryGame(unittest.TestCase):
    """The queue's contract with the window, exercised without Tk and without a real 7-Zip.

    What is under test is the shape of what comes back - one verdict per game, a transition attributed to the
    right game, and a run that continues past a failure - because those are what the window is built on and none
    of them is visible from the catalog page.
    """

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "Games"
        self.dest = Path(temporary.name) / "Out"
        self.dest.mkdir(parents=True)
        self.logger = AppLogger(Path(temporary.name) / "x.log")
        self.seen = []
        self._fake_tool(fail_for=())

    def _fake_tool(self, fail_for=()):
        """Replace the 7z call with something that reports progress and obeys cancel.

        Written as a real class taking the constructor the job actually calls, so on_progress stays bound rather
        than being bypassed - a stub that ignored the callback would pass a test about progress attribution.
        """
        class _Fake:
            def __init__(self, logger, on_progress=None):
                self.on_progress = on_progress

            def extract(self, archive, destination, password="", cancel=None):
                for percent in (10, 50, 90):
                    if cancel and cancel():
                        return ExtractResult(archive, destination, False, "stopped part-way")
                    if self.on_progress:
                        self.on_progress(stage="extracting", percent=percent, name=archive.stem)
                if any(word in archive.stem for word in fail_for):
                    return ExtractResult(archive, destination, False, "Extraction failed (exit 2)", code=2)
                destination.mkdir(parents=True, exist_ok=True)
                (destination / "game.bin").write_bytes(b"a" * 1000)
                return ExtractResult(archive, destination, True, "Extracted 1 file(s)",
                                     extracted_bytes=1000, file_count=1, code=0)

        self.addCleanup(setattr, batch_extract_service, "ExtractService", batch_extract_service.ExtractService)
        batch_extract_service.ExtractService = _Fake

    def _games(self, *names):
        for name in names:
            _game(self.root, "Idle", name, 4096)

    def _run(self, category="", cancel_after=None, fail_for=()):
        if fail_for:
            self._fake_tool(fail_for=fail_for)
        plan = plan_batch(self.root, self.dest, category, self.logger)
        job = BatchExtractJob(plan, self.logger)
        started = []

        def record(stage="", item=None, detail=""):
            if item is not None:
                self.seen.append((stage, item.name, item.state))
                if cancel_after and item.state == "extracting":
                    started.append(item.name)
                    if len(started) >= cancel_after:
                        job.cancel()

        job.on_progress = record
        job.run()
        return job

    def test_every_game_gets_a_verdict(self):
        self._games("Alpha", "Beta", "Gamma")
        job = self._run()
        self.assertEqual([item.state for item in job.plan.items], [DONE, DONE, DONE])
        self.assertEqual(job.succeeded, 3)

    def test_each_game_reports_its_own_transitions(self):
        """Progress attributed to the wrong row is worse than no progress: it makes the window look stuck on one
        game while a different one is actually being unpacked."""
        self._games("Alpha", "Beta")
        self._run()
        self.assertEqual({name for _, name, _ in self.seen}, {"Alpha", "Beta"})
        for name in ("Alpha", "Beta"):
            with self.subTest(game=name):
                # On the row's state, not the event name. The job reports "progress" for every tick of a running
                # extraction and "item" when the verdict lands, so a test keyed on the stage would read a game that
                # was being unpacked continuously as one that never reported itself - which is the assertion
                # reading the wrong field rather than the window being wrong.
                self.assertTrue(any(n == name and state == EXTRACTING for _, n, state in self.seen),
                                f"{name} never reported itself as extracting; saw "
                                f"{sorted({(n, state) for _, n, state in self.seen})}")

    def test_one_failing_game_does_not_stop_the_rest(self):
        """The same rule the organize run was given after one unmovable archive aborted a whole library."""
        self._games("Alpha", "Broken", "Gamma")
        job = self._run(fail_for=("Broken",))
        states = {item.name: item.state for item in job.plan.items}
        self.assertEqual(states, {"Alpha": DONE, "Broken": FAILED, "Gamma": DONE})
        self.assertEqual((job.succeeded, job.failed), (2, 1))

    def test_a_failure_names_its_reason(self):
        """"Failed" with no reason is an outcome nobody can act on."""
        self._games("Broken")
        job = self._run(fail_for=("Broken",))
        self.assertIn("exit 2", job.plan.items[0].detail)

    def test_a_cancelled_run_marks_the_games_it_never_reached(self):
        """Anything still queued when the run ends was never started, and a row that stays 'Waiting' forever is
        how a stopped run comes to look like a hung one."""
        self._games("Alpha", "Beta", "Gamma")
        job = self._run(cancel_after=1)
        states = [item.state for item in job.plan.items]
        self.assertNotIn("queued", states, f"a game was left queued after the run ended: {states}")
        self.assertTrue(any(state == CANCELLED for state in states), f"nothing was marked cancelled: {states}")

    def test_a_cancel_stops_the_tool_rather_than_only_the_next_game(self):
        """Cancelling between games would still leave the current archive running to completion, which for a 4 GB
        unpack is most of the wait the user asked to stop."""
        self._games("Alpha", "Beta")
        job = self._run(cancel_after=1)
        self.assertEqual(job.cancelled, 2)
        self.assertEqual(job.succeeded, 0, "the run finished games after being asked to stop")

    def test_the_summary_counts_what_happened(self):
        self._games("Alpha", "Broken", "Gamma")
        job = self._run(fail_for=("Broken",))
        text = job.summary()
        self.assertIn("2 extracted", text)
        self.assertIn("1 failed", text)

    def test_an_installer_game_is_flagged_in_the_row_and_the_run(self):
        """An installer repack is unpacked, not installed, and that has to read on both the row and the summary."""
        from services.extract_service import ExtractResult

        class _InstallerFake:
            def __init__(self, logger, on_progress=None):
                self.on_progress = on_progress

            def extract(self, archive, destination, password="", cancel=None):
                destination.mkdir(parents=True, exist_ok=True)
                (destination / "setup.exe").write_bytes(b"MZ")
                (destination / "setup-1.bin").write_bytes(b"a" * 1000)
                return ExtractResult(archive, destination, True, "Extracted 2 files",
                                     extracted_bytes=2000, file_count=2, code=0, needs_install=True)

        self._games("Repack")
        batch_extract_service.ExtractService = _InstallerFake
        job = self._run()
        item = job.plan.items[0]
        self.assertEqual(item.state, DONE)
        self.assertIn("needs install", item.detail.lower(),
                      f"the row's detail did not flag the installer: {item.detail!r}")
        self.assertEqual(job.needs_install, 1, "the run did not count the installer")
        self.assertIn("need install", job.summary().lower(),
                      "the summary did not surface installers at the run level")

    def test_remaining_drains_to_zero(self):
        self._games("Alpha", "Beta")
        job = self._run()
        self.assertEqual(job.remaining(), 0, "the window's remaining count would never reach zero")

    def test_an_empty_plan_finishes_cleanly_rather_than_hanging(self):
        """Every game already unpacked is the state the button is in on its second click, and it must report
        itself finished rather than waiting for an archive that will never come."""
        self._games("Alpha")
        destination = self._plan_and_fill()
        job = BatchExtractJob(destination, self.logger)
        job.run()
        self.assertTrue(job.done.is_set())
        self.assertEqual(job.summary().split()[0], "0")

    def _plan_and_fill(self):
        plan = plan_batch(self.root, self.dest, "Idle", self.logger)
        for item in plan.items:
            item.destination.mkdir(parents=True, exist_ok=True)
            (item.destination / "done.bin").write_bytes(b"x")
        return plan_batch(self.root, self.dest, "Idle", self.logger)


# A stub archiver that ignores the real 7z argument list and just prints progress lines, so extract() can be
# driven end to end - real Popen, real pipe, real cancel check - without a real 7-Zip. Written through the
# project's own _write_stub so it is a form this platform can actually execute.
_STUB_PROGRESS = '''#!/usr/bin/env python3
import sys
for line in ("10% 1 - a", "50% 2 - b", "90% 3 - c"):
    print(line)
    sys.stdout.flush()
sys.exit(0)
'''


class CancelReachesTheArchiveTool(unittest.TestCase):
    """extract() accepted a cancel callable and never called it.

    A Cancel button wired to a parameter nothing reads looks real and does nothing: 7z runs to the end of the
    archive. Asserted against the real extract() driving a real child process, because asserting it against a
    stub would only prove the stub is cancellable.
    """

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.logger = AppLogger(self.root / "x.log")
        self.archive = self.root / "Game.zip"
        with zipfile.ZipFile(self.archive, "w") as handle:
            handle.writestr("game/data.bin", b"a" * 5000)
        bin_dir = self.root / "bin"
        _write_stub(bin_dir, "7z", _STUB_PROGRESS)
        self.tool = bin_dir / ("7z.bat" if os.name == "nt" else "7z")
        self.assertTrue(self.tool.is_file(), f"the stub archiver was not written where it can be run: {self.tool}")

    def _service(self):
        service = ExtractService(self.logger)
        service.find_tool = lambda: (str(self.tool), None)
        # The real check needs a writable destination and enough room; neither is what this is testing.
        service.check_space = lambda archive, destination: ""
        return service

    def test_a_cancel_stops_the_run_instead_of_being_ignored(self):
        result = self._service().extract(self.archive, self.root / "out", cancel=lambda: True)
        self.assertFalse(result.ok, "a cancelled extraction reported success")
        self.assertIn("part-way", result.message,
                      f"a cancelled extraction did not say where its files are: {result.message!r}")

    def test_a_cancel_that_never_arrives_still_completes(self):
        """The other half: the fix cannot simply refuse to run, or every extraction would report cancelled."""
        result = self._service().extract(self.archive, self.root / "out", cancel=lambda: False)
        self.assertTrue(result.ok, f"an uncancelled extraction failed: {result.message}")

    def test_no_cancel_callable_behaves_as_before(self):
        result = self._service().extract(self.archive, self.root / "out")
        self.assertTrue(result.ok, f"extraction without a cancel callable failed: {result.message}")


class TheCatalogOffersTheBatchButtons(unittest.TestCase):
    """The page half. Every assertion is on the rendered text, because a button the reader cannot see is the
    whole failure and a helper that built one nobody renders would pass."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "Games"
        self.dest = Path(temporary.name) / "Out"
        self.dest.mkdir(parents=True)
        for category, name in (("Idle", "Loop Miner"), ("Idle", "Fellwood"), ("RPG", "Deep Signal")):
            _game(self.root, category, name)
        service = CatalogService(AppLogger(Path(temporary.name) / "x.log"), extract_folders=[self.dest])
        self.text = service.generate(self.root)[0].read_text(encoding="utf-8")

    def test_each_category_banner_offers_to_install_its_games(self):
        self.assertIn("Extract all 2", self.text, "the Idle category's two games are not offered as a batch")
        self.assertIn("Extract all 1", self.text, "the RPG category's single game is not offered as a batch")

    def test_the_toolbar_offers_the_whole_library(self):
        self.assertIn("Extract all 3", self.text, "there is no whole-library Extract all in the toolbar")

    def test_a_category_link_names_that_category(self):
        self.assertIn("steamgameorganizer://extract-all?category=Idle", self.text)

    def test_the_library_wide_link_names_no_category(self):
        """The library-wide button sends the action with no category, which the handler treats as the whole
        library rather than a named folder. The script on the page rebuilds this link the same way as the
        per-category ones, so it carries the same shape: steamgameorganizer://extract-all with no query."""
        import re
        library_links = re.findall(r'data-batch="(steamgameorganizer://extract-all[^"]*)"', self.text)
        self.assertTrue(library_links, "no batch link carries the data-batch the script rebuilds from")
        self.assertIn("steamgameorganizer://extract-all\"", self.text,
                      "the whole-library link does not end at the action with no query string")

    def test_the_buttons_state_how_many_games_they_cover(self):
        """A button reading 'Extract all' over a shelf of 176 games is not enough evidence to agree to hours of
        unpacking, so the count is on the button and the size is in the confirmation."""
        import re
        counts = re.findall(r'data-batch-count="(\d+)"', self.text)
        self.assertEqual(sorted(int(c) for c in counts), [1, 1, 2, 2, 3, 3],
                         f"the batch buttons do not carry the real counts: {counts}")

    def test_the_batch_links_rebuild_from_the_destination_box(self):
        """Rebuilt from the pristine data-batch on every keystroke, exactly like the single Extract links, so
        typing in the box cannot accumulate a second dest parameter onto a link that already has one."""
        self.assertIn("data-batch=", self.text)
        self.assertIn("document.querySelectorAll('[data-batch]')", self.text)
        self.assertIn("var bbase=batch[j].getAttribute('data-batch')", self.text)

    def test_a_batch_is_confirmed_before_the_browser_hands_it_over(self):
        """preventDefault() has to be in there. Without it the run starts on the click and any prompt appears
        over a window that is already unpacking."""
        self.assertIn("confirmBatch(link)", self.text)
        self.assertIn("event.preventDefault()", self.text)

    def test_the_confirmation_names_the_count_and_the_destination(self):
        self.assertIn("data-batch-confirm=", self.text)
        self.assertIn("To: '+dest", self.text)
        self.assertIn("free space", self.text,
                      "the prompt does not mention that a batch needs several times the archive size in room")

    def test_the_single_extract_links_are_left_alone(self):
        """One archive is small and reversible; a prompt on every card would make the button tiresome. So the
        confirmation is bound to the batch links only."""
        self.assertEqual(self.text.count("data-batch-count="), 6, "an unexpected number of batch buttons appeared")
        self.assertIn('class="btn btn-extract"', self.text, "the per-game Extract button is gone")
        self.assertIn("querySelectorAll('.btn-extract')", self.text,
                      "the single Extract links are no longer rebuilt from the destination box")

    def test_the_single_game_button_is_still_on_the_card(self):
        """The whole point of the three levels: this one game, this category, everything."""
        self.assertEqual(self.text.count('class="btn btn-extract"'), 3, "one Extract button per game is expected")


class TheWindowShowsEveryGame(unittest.TestCase):
    """The window is the only place the run is visible, so the things it promises are asserted on the widgets.

    Driven without the job: the queue is filled by hand and the rows rendered, which is what isolates the display
    from the extraction. The run itself is covered by RunningABatchReportsEveryGame.
    """

    def setUp(self):
        from tests.tk_support import close_root, require_tk
        require_tk(self)
        import tkinter as tk

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root_dir = Path(temporary.name)
        self.logger = AppLogger(self.root_dir / "x.log")

        self.root = tk.Tk()
        self.addCleanup(close_root, self.root)

    def _plan(self, already_done=0):
        from services.batch_extract_service import BatchItem, BatchPlan
        plan = BatchPlan(destination=self.root_dir / "Out", category="Idle", already_done=already_done)
        for index, name in enumerate(("Alpha", "Beta", "Gamma"), 1):
            plan.items.append(BatchItem(archive=Path(f"C:/library/{name}.zip"), destination=Path(f"C:/out/{name}"),
                                        name=name, size=index * 1024 * 1024))
        plan.total_bytes = sum(item.size for item in plan.items)
        return plan

    def _window(self, already_done=0):
        from ui.batch_extract_window import BatchExtractWindow
        self.plan = self._plan(already_done)
        self.window = BatchExtractWindow(self.root, self.plan, self.logger)
        return self.window

    def _text(self):
        # "end-1c", not "end". A Tk text always ends in a newline, so reading to "end" counts a phantom
        # empty row past the last game and every row count here would be one too high.
        return self.window.list.get("1.0", "end-1c")

    def _labels(self, widget):
        found = []
        for child in widget.winfo_children():
            try:
                found.append(str(child.cget("text")))
            except Exception:
                pass
            found.extend(self._labels(child))
        return found

    def test_every_game_in_the_plan_has_a_row_before_anything_runs(self):
        window = self._window()
        window._render_all()
        self.root.update()
        text = self._text()
        for name in ("Alpha", "Beta", "Gamma"):
            self.assertIn(name, text, f"{name} has no row, so there is no way to see its status")
        self.assertEqual(len(window.rows), 3, "a game in the plan has no row to update")

    def test_a_row_shows_the_name_the_size_and_the_status(self):
        window = self._window()
        window._render_all()
        self.root.update()
        line = self._text().splitlines()[0]
        self.assertIn("Alpha", line)
        self.assertIn("1 MB", line, f"the row does not show how big the game is: {line!r}")
        self.assertIn("Waiting", line, "a game that has not started does not say so")

    def test_a_row_is_rewritten_in_place_rather_than_reinserted(self):
        """Deleting and reinserting would shift every row below it, so the list would jump under the reader on
        every progress event - a hundred and seventy-six games would be unreadable."""
        window = self._window()
        window._render_all()
        self.root.update()
        before_lines = self._text().splitlines()
        item = window.plan.items[1]
        item.state = EXTRACTING
        item.percent = 42
        item.detail = "42%  game/data.bin"
        window._update_row(item)
        self.root.update()
        self.assertEqual(len(self.window.rows), 3, "the row map was rebuilt instead of the rows being updated")
        self.assertEqual(len(self._text().splitlines()), 3, "updating a row changed the number of rows")
        self.assertEqual(self._text().splitlines()[0], before_lines[0], "an earlier row moved")
        self.assertIn("Extracting", self._text().splitlines()[1], "the row did not take its new status")
        self.assertIn("42%", self._text().splitlines()[1], "the row did not take its new detail")

    def test_the_header_states_the_count_and_the_destination(self):
        window = self._window()
        text = " ".join(self._labels(window))
        self.assertIn("Extracting 3 games", text)
        self.assertIn(str(window.plan.destination), text)

    def test_the_header_says_how_many_were_left_alone(self):
        """A user who clicks Extract All on 176 games and watches 12 run has to know the other 164 were left
        alone on purpose, or the button looks broken."""
        window = self._window(already_done=164)
        self.root.update()
        self.assertIn("164 already unpacked", " ".join(self._labels(window)))

    def test_the_metrics_carry_the_numbers_a_long_run_needs(self):
        """Done, remaining, bytes unpacked, elapsed, throughput and free space. The last is the one that turns a
        healthy run into a failing one, and a batch is the run that can fill a disk."""
        window = self._window()
        window._render_all()
        job = BatchExtractJob(window.plan, self.logger)
        job.started_at = time.monotonic() - 30
        job.written = 50 * 1024 * 1024
        window.job = job
        window._refresh_metrics()
        self.root.update()
        metrics = str(window.metrics.cget("text"))
        self.assertIn("unpacked", metrics)
        self.assertIn("free on the drive", metrics)
        self.assertIn("/s", metrics, "no throughput is reported")
        self.assertIn("3 remaining", str(window.remaining.cget("text")))

    def test_the_stop_button_asks_the_job_to_stop_and_says_so(self):
        window = self._window()
        job = BatchExtractJob(window.plan, self.logger)
        window.job = job
        window._stop()
        self.root.update()
        self.assertTrue(job.cancel_requested, "the Stop button did not reach the job")
        self.assertIn("STOPPING", str(window.cancel_btn.cget("text")))
        self.assertEqual(str(window.cancel_btn.cget("state")), "disabled",
                         "the Stop button stayed live while stopping, so it could be pressed twice")

    def test_closing_mid_run_cancels_first_rather_than_leaving_the_tool_writing(self):
        window = self._window()
        job = BatchExtractJob(window.plan, self.logger)
        window.job = job
        window._on_close()
        self.root.update()
        self.assertTrue(job.cancel_requested, "closing the window left a run going with no window to stop it")
        self.assertTrue(window.winfo_exists(), "the window closed while a run was still writing")

    def test_a_finished_run_names_the_games_that_failed(self):
        """A run of 176 with three failures is a success with caveats, and the caveats should not require
        scrolling through a hundred rows to find."""
        from services.batch_extract_service import FAILED as STATE_FAILED
        window = self._window()
        job = BatchExtractJob(window.plan, self.logger)
        window.job = job
        window.plan.items[1].state = STATE_FAILED
        window.plan.items[1].detail = "Extraction failed (exit 2)"
        job.failed = 1
        job.succeeded = 2
        window._finish()
        self.root.update()
        summary = str(window.summary.cget("text"))
        self.assertIn("Failed: Beta", summary)
        self.assertIn("2 extracted", summary)


if __name__ == "__main__":
    unittest.main()
