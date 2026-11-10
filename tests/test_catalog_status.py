"""The catalog's status file and its "already unpacked" badge.

Two claims the page now makes about the machine it was written on, and both have to be true: a card marked
Unpacked is a game Extract all would skip, and the banner at the top reports the run that actually happened.

Neither can be checked from the page. A document opened from `file://` has an opaque origin and cannot read
anything beside it - `fetch` and XHR are both refused - so the badge is decided when the page is written and
the banner arrives later through a sibling script. That is why these tests are about the generator and the
app rather than about JavaScript, and why the badge's predicate is asserted to be the planner's own rather
than a second implementation of it.

The one thing none of this can prove is that a browser honours a `<script src>` from `file://`. That is
verified by hand against a real headless browser, because the whole design rests on it and a string in a
generated page does not demonstrate it.
"""
from __future__ import annotations

import json
import tempfile
import unittest

import pytest
from pathlib import Path
from unittest import mock

from core.logger import AppLogger
from services import batch_extract_service, catalog_service
from services.catalog_service import CatalogService
from services.catalog_status import (STATUS_GLOBAL, STATUS_NAME, already_extracted, empty_status,
                                       archive_has_changed_since_extraction, elapsed_text,
                                       status_from_run, write_status)
from services.installer_detect import NEEDS_INSTALL_DIRNAME
from tests.test_batch_extract import _game


def _unpacked_card(text: str) -> int:
    """How many cards on the page carry the badge.

    Counted on the rendered class rather than on 'badge-done', which also appears in the stylesheet and in the
    script - a substring count would pass with the badge never drawn at all.
    """
    return text.count('class="badge badge-done"')


def _payload_of(path: Path) -> dict:
    """Read the status file back the way the browser would see it.

    Nothing in Python can execute the file, so the assignment is stripped and the remainder parsed. That
    checks two things at once: that the file really is a valid JavaScript object literal, and that what comes
    out is what went in - including for a category whose name is trying to be code, which is the case a
    hand-built string gets wrong.
    """
    text = path.read_text(encoding="utf-8")
    marker = f"window.{STATUS_GLOBAL} = "
    assert marker in text, f"the status file does not assign window.{STATUS_GLOBAL}: {text!r}"
    raw = text.split(marker, 1)[1].strip()
    return json.loads(raw[:-1] if raw.endswith(";") else raw)


def _assert_has(case, text: str, needle: str, message: str):
    """assertIn against a whole generated page, without printing the page when it fails.

    The container here is a 600 KB document, so an ordinary assertIn failure buries the one line that says what
    is missing under the entire catalogue. A failure should name the thing, not restate the thing.
    """
    case.assertTrue(needle in text, f"{message} (nothing on the page contains {needle!r})")


@pytest.mark.notkinter
class AStatusFileTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "Games"
        self.dest = self.base / "Out"
        self.dest.mkdir(parents=True)
        self.logger = AppLogger(self.base / "x.log")
        _game(self.root, "Idle", "Loop Miner")
        _game(self.root, "Idle", "Fellwood")
        _game(self.root, "RPG", "Deep Signal")

    def _generate(self, destination=None):
        folders = [destination] if destination else [self.dest]
        return CatalogService(self.logger, extract_folders=folders).generate(self.root, "")[0]

    def _page(self, destination=None) -> str:
        return self._generate(destination).read_text(encoding="utf-8")

    def _unpack(self, name: str, destination: Path):
        folder = destination / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "game.bin").write_bytes(b"x")

    def _unpack_installer(self, name: str, destination: Path):
        """A folder this version extracted as an installer: payload in the Needs Install folder at the
        destination root (the current layout)."""
        mark = destination / NEEDS_INSTALL_DIRNAME / name
        mark.mkdir(parents=True, exist_ok=True)
        (mark / "setup.exe").write_bytes(b"MZ")
        (mark / "setup-1.bin").write_bytes(b"x" * 1000)


class TheStatusFileIsWrittenBesideTheCatalog(AStatusFileTestCase):
    def test_a_new_catalog_arrives_with_a_status_file(self):
        """The page loads the status as a sibling script, so the two have to be written together.

        Without this the page still works - a missing script tag is a no-op - but it silently reports nothing
        about any run until one happens to be started from the app. A first catalog that cannot report is a
        catalog that looks like the feature was never built.
        """
        self._generate()
        self.assertTrue((self.root / STATUS_NAME).is_file(),
                        f"the catalog was written without {STATUS_NAME} beside it")

    def test_the_status_file_carries_every_key_the_page_reads(self):
        """The page indexes the payload without checking the keys are there.

        A key added to the writer and forgotten on the reading side is an `undefined` in the middle of a
        banner rather than a visible absence, so the shape is pinned here instead of discovered in a browser.
        """
        status = empty_status()
        for key in ("ran_at", "category", "destination", "total", "extracted", "skipped",
                    "failed", "cancelled", "already_done", "needs_install", "elapsed"):
            self.assertIn(key, status, f"{key} is missing, so the banner would show 'undefined'")
        self.assertEqual(status["ran_at"], "", "a status that claims a run happened when none did")

    def test_a_scan_does_not_erase_the_last_run(self):
        """The reason the status file is written only when it is absent.

        Every scan regenerates the catalog, so writing the empty status unconditionally would replace the last
        run's outcome with "no runs yet" the next time anything at all was scanned - which is the one piece of
        information the banner exists to carry, gone because the page was refreshed by an unrelated action.
        """
        self._generate()
        write_status(self.root, dict(empty_status(), ran_at="2026-10-04 05:12", total=3,
                                    extracted=2, failed=1, elapsed="1h 4m"), self.logger)
        self._generate()
        again = _payload_of(self.root / STATUS_NAME)
        self.assertEqual(again["ran_at"], "2026-10-04 05:12",
                         "regenerating the catalog threw away the record of the run that just finished")
        self.assertEqual(again["failed"], 1, "the failures went with it")

    def test_a_finished_run_is_reported_with_the_numbers_the_window_showed(self):
        """The banner and the window must not disagree about what happened.

        Both are readouts of one run, from one source. If the banner counted only successes while the window
        counted attempts, the page would report a clean run over three failures - the exact case the warning
        styling exists to prevent.
        """
        from services.batch_extract_service import BatchExtractJob, BatchPlan

        plan = BatchPlan(destination=self.dest, category="Idle")
        plan.items = [object(), object(), object()]
        plan.already_done = 4
        job = BatchExtractJob(plan, self.logger)
        job.succeeded, job.skipped, job.failed, job.cancelled = 2, 1, 0, 0
        job.started_at, job.finished_at = 1000.0, 1000.0 + 3844.0

        write_status(self.root, status_from_run(plan, job), self.logger)
        status = _payload_of(self.root / STATUS_NAME)
        self.assertEqual(status["total"], 3, "the banner counts different games than the window ran")
        self.assertEqual(status["extracted"], 2)
        self.assertEqual(status["skipped"], 1)
        self.assertEqual(status["already_done"], 4, "the games left alone before the run are not counted")
        self.assertEqual(status["elapsed"], "1h 4m")
        self.assertEqual(status["category"], "Idle")
        self.assertEqual(status["destination"], str(self.dest))
        self.assertTrue(status["ran_at"], "a finished run with no timestamp is not a report of anything")

    def test_a_run_that_was_cancelled_says_so(self):
        """Cancelled is neither success nor failure, and averaging it into either misleads.

        A run stopped halfway has unpacked some games and not started others. Reporting it as the successes
        alone would read as a clean finish.
        """
        from services.batch_extract_service import BatchExtractJob, BatchPlan

        plan = BatchPlan(destination=self.dest, category="Idle")
        plan.items = [object(), object()]
        job = BatchExtractJob(plan, self.logger)
        job.succeeded, job.failed, job.cancelled = 1, 0, 1
        job.started_at, job.finished_at = 10.0, 70.0
        status = status_from_run(plan, job)
        self.assertEqual(status["cancelled"], 1, "a cancelled run is reported as though nothing was left out")
        self.assertEqual(status["extracted"], 1)

    def test_a_category_naming_javascript_is_written_as_data(self):
        """A category name is a folder name, and folder names are not constrained to be polite.

        Built by string formatting rather than by a serialiser, this would be a script injection into a page
        the reader opens from disk. It is also part of why the status lives in its own file: a JSON string in an
        external script has no `</script>` to break out of, which it would have to if this were inlined.
        """
        hostile = '"; alert(1); "'
        write_status(self.root, dict(empty_status(), ran_at="now", category=hostile), self.logger)
        self.assertEqual(_payload_of(self.root / STATUS_NAME)["category"], hostile,
                         "the name was mangled or executed on the way through")

    def test_a_status_that_cannot_be_written_does_not_take_the_run_down(self):
        """The game folders are already unpacked by the time this runs.

        A browser that cannot be told about a finished run is not a reason to report the run as failed, so this
        must return None and log rather than raise. A directory is put where the file goes, which fails the
        same way on every platform - permissions would not, since Windows lets the owner write regardless.
        """
        blocker = self.root / STATUS_NAME
        blocker.mkdir()
        self.assertIsNone(write_status(self.root, empty_status(), self.logger),
                          "a status that could not be written reported success")


class AFinishedRunIsWrittenOutForSomebodyToRead(unittest.TestCase):
    def test_a_duration_is_written_out_rather_than_counted_in_seconds(self):
        """The reader is deciding whether the run they just sat through was worth it.

        '7944' does not answer that; '2h 12m' does. Zero and sub-minute are checked too, because a run that
        failed immediately is exactly the one whose elapsed time matters most.
        """
        for seconds, expected in ((0, "0s"), (45, "45s"), (59, "59s"), (60, "1m"), (3599, "59m"),
                                  (3600, "1h 0m"), (7944, "2h 12m"), (86399, "23h 59m")):
            self.assertEqual(elapsed_text(seconds), expected, f"{seconds}s is not written as {expected}")

    def test_an_unusable_duration_does_not_raise(self):
        """These arrive off a job that may never have started, and a readout is not what may take down Tk."""
        for value in (None, "", "abc", object()):
            self.assertEqual(elapsed_text(value), "", f"{value!r} should format as nothing rather than raise")


class TheUnpackedBadgeTellsTheTruth(AStatusFileTestCase):
    def test_a_game_already_unpacked_is_marked(self):
        self._unpack("Loop Miner", self.dest)
        self.assertEqual(_unpacked_card(self._page()), 1,
                         "a game already unpacked into the default destination is not marked, so Extract all "
                         "reads as work that has not been done")

    def test_a_game_that_is_not_unpacked_is_not_marked(self):
        self.assertEqual(_unpacked_card(self._page()), 0,
                         "a game with nothing unpacked is marked as done, which is the one claim this badge "
                         "must never make")

    def test_an_empty_folder_is_not_treated_as_unpacked(self):
        """The planner's own rule, and for the same reason.

        An interrupted run leaves the folder behind. Calling that finished would mean Extract all silently
        skips the one game the reader most wants finished - and a badge that agreed with it would make the bug
        look like the page working.
        """
        (self.dest / "Loop Miner").mkdir()
        self.assertEqual(_unpacked_card(self._page()), 0, "an empty folder was read as an unpacked game")

    def test_a_game_unpacked_somewhere_else_is_not_marked(self):
        """The page cannot look at any folder but the one it was written against.

        It has no way to check a second destination, so it must not claim to. The badge's title names the
        folder it means, which is what stops a reader who extracted elsewhere from being misled.
        """
        self._unpack("Loop Miner", self.base / "Somewhere Else")
        self.assertEqual(_unpacked_card(self._page()), 0,
                         "a game unpacked into a folder the page never checked is marked as unpacked")

    def test_a_game_unpacked_as_an_installer_is_marked_needs_install(self):
        """An installer repack unpacked to the default destination is unpacked but not ready.

        It must not get the green "Unpacked" mark - that reads as "playable" - so it earns its own amber badge
        and the green one is withheld.
        """
        self._unpack_installer("Loop Miner", self.dest)
        page = self._page()
        self.assertEqual(_unpacked_card(page), 0,
                         "an installer layout was given the green Unpacked badge: " +
                         "the two states cannot be read as the same thing")
        self.assertEqual(page.count('class="badge badge-warn"'), 1,
                         "no 'Needs install' badge was drawn for an installer folder")
        self.assertIn("Needs install", page, "the badge text does not say what is still owed")

    def test_a_ready_game_keeps_the_unpacked_badge_in_front_of_the_installer_one(self):
        """A game that is genuinely unpacked and ready must still read green, not be downgraded to amber."""
        self._unpack("Loop Miner", self.dest)
        self.assertEqual(_unpacked_card(self._page()), 1,
                         "a ready-to-play unpacked game was not marked unpacked")

    def test_two_cards_sharing_one_archive_name_are_neither_marked(self):
        """Two games can hold identically named archives, and the batch suffixes the second folder.

        The page cannot know which of the two would own the unsuffixed folder, so it has to say nothing.
        Marking both would claim two games are done when one folder exists, and marking one would be a coin
        flip that is wrong half the time.
        """
        for folder in ("Twin A", "Twin B"):
            where = self.root / "RPG" / f"{folder} - 2024-01-01"
            where.mkdir(parents=True)
            (where / "Shared Title.zip").write_bytes(b"x")
            (where / ".game-info.json").write_text('{"appid":"1","name":"Shared Title","genres":["Idle"]}',
                                                   encoding="utf-8")
        self._unpack("Shared Title", self.dest)
        self.assertEqual(_unpacked_card(self._page()), 0,
                         "one of two cards sharing an archive name was marked, and the page cannot know which")

    def test_the_badge_uses_the_planners_own_predicate(self):
        """One rule, one definition.

        Two implementations of "already unpacked" would agree right up until they did not, and the page would
        be the one that is wrong: it is generated from a snapshot, while the planner decides at the moment of
        the click. Asserting the identity is what stops a second copy being introduced later.
        """
        self.assertIs(catalog_service.already_extracted, batch_extract_service.already_extracted,
                      "the catalog and the batch planner no longer share one definition of 'already unpacked'")
        self.assertIs(batch_extract_service.already_extracted, already_extracted,
                      "the batch planner grew a second copy of the predicate")

    def test_a_destination_that_cannot_be_read_is_not_an_unpacked_game(self):
        """An unreadable folder must answer 'not unpacked' rather than raise out of a generator.

        Patched rather than provoked with permissions, because on Windows the owner can read a directory
        whatever its mode says - which would leave this test passing without ever reaching the handler.
        """
        self._unpack("Loop Miner", self.dest)
        with mock.patch.object(Path, "iterdir", side_effect=OSError("access denied")):
            self.assertFalse(already_extracted(self.dest / "Loop Miner"),
                             "an unreadable destination was reported as an unpacked game")
        self.assertEqual(_unpacked_card(self._page()), 1, "the page disagrees with the planner when reading fails")


class TheBannerIsWiredToTheFileThatFeedsIt(AStatusFileTestCase):
    """The contract between three places that cannot see each other at runtime.

    The app writes the name, the generator writes the tag that loads it, and the script reads a global off it.
    Nothing connects them at import time, so a rename is silent until somebody opens a browser.
    """

    def setUp(self):
        super().setUp()
        self.text = self._page()

    def test_the_page_has_a_banner_to_fill(self):
        _assert_has(self, self.text, 'id="run-status"', "there is nowhere to show the result of the last run")
        _assert_has(self, self.text, ".run-status{", "the banner has no styling, so it would render as bare text")

    def test_the_page_loads_the_status_file_before_its_own_script(self):
        """Order is the whole mechanism: the data must be on window before the script looks for it.

        A plain object assignment rather than a call into a hook, so the two cannot race - but that only helps
        if this tag comes first.
        """
        tag = f'<script src="{STATUS_NAME}"></script>'
        _assert_has(self, self.text, tag, f"the page never loads {STATUS_NAME}, so no run can reach it")
        self.assertLess(self.text.index(tag), self.text.index("function apply("),
                        "the status file loads after the script that reads it, so the first read sees nothing")

    def test_the_script_reads_the_global_the_status_file_publishes(self):
        _assert_has(self, self.text, f"window.{STATUS_GLOBAL}",
                    "the page does not read the global the status file publishes")

    def test_the_banner_stays_hidden_until_a_run_has_been_reported(self):
        """A freshly scanned library has no run to report, and must not claim otherwise.

        This is the difference between a page that says nothing and one that opens with a confident, false
        summary of a night's extracting.
        """
        element = self.text.split('<div id="run-status"', 1)[1].split(">", 1)[0]
        self.assertIn("hidden", element, "the banner starts visible, empty and unexplained")
        _assert_has(self, self.text, "!run.ran_at",
                    "the banner is not gated on a run having happened, so a fresh catalog reports one")

    def test_a_run_with_failures_is_marked_as_a_warning(self):
        """A green banner over three failures is worse than no banner.

        It reads as the whole run having worked, and the reader has gone to the shelf to look for three games
        that are not there.
        """
        _assert_has(self, self.text, "run-status-warn", "a run with failures is not distinguished from a clean one")
        _assert_has(self, self.text.replace(" ", ""), "run.failed||run.cancelled",
                    "the warning covers neither failures nor a run that was cancelled")

    def test_the_footer_says_a_button_needs_the_handler_installed(self):
        """The one failure a reader cannot diagnose from the page.

        A page cannot detect that a protocol handler was never registered, so an Extract click can do nothing
        at all, silently. The footer is the only place the reader will look.
        """
        _assert_has(self, self.text, "foot-note", "the footer says nothing about the handler")
        _assert_has(self, self.text, "steamgameorganizer://", "the note does not name what has to be registered")
        _assert_has(self, self.text, "Copy folder path", "the note does not say what still works without it")

    def test_the_badges_are_checked_against_the_destination_box_on_load(self):
        """Not only when the box is touched.

        A destination is remembered between visits, so a page reopened with a different one restored would
        show badges decided against the folder it no longer names, and would keep showing them until the
        reader happened to edit the box.
        """
        _assert_has(self, self.text, "syncUnpackedBadges();",
                    "the badges are never re-checked after the page loads")
        _assert_has(self, self.text, "destBox.addEventListener('input',syncUnpackedBadges)",
                    "typing another destination leaves the badges claiming a folder that was never checked")


class TheExtractMarkerDetectsStaleArchives(unittest.TestCase):
    """Unit tests for archive_has_changed_since_extraction.

    The predicate has to be conservative: a missing marker is never stale (old extractions made
    before the marker existed must not be falsely flagged), and a present marker is stale only when
    the archive's size or mtime actually changed.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.base = Path(self.dir.name)
        self.archive = self.base / "Game.zip"
        self.archive.write_bytes(b"original content")
        self.dest_folder = self.base / "Extracted" / "Game"
        self.dest_folder.mkdir(parents=True)
        (self.dest_folder / "game.bin").write_bytes(b"unpacked")

    def _write_marker(self, dest, size=None, mtime_ns=None):
        from services.catalog_status import extract_marker_path
        import json as _json
        marker = extract_marker_path(dest)
        info = {
            'archive_size': size if size is not None else 0,
            'archive_mtime_ns': mtime_ns if mtime_ns is not None else 0,
        }
        marker.write_text(_json.dumps(info), encoding='utf-8')

    def test_a_missing_marker_is_never_stale(self):
        """A folder without a marker is treated as never having been checked - never falsely flagged."""
        self.assertFalse(archive_has_changed_since_extraction(self.dest_folder, self.archive))

    def test_an_unchanged_archive_is_not_stale(self):
        """The marker records the archive's size and mtime; if they match, nothing changed."""
        stat = self.archive.stat()
        self._write_marker(self.dest_folder, size=stat.st_size, mtime_ns=stat.st_mtime_ns)
        self.assertFalse(archive_has_changed_since_extraction(self.dest_folder, self.archive))

    def test_a_changed_size_is_stale(self):
        """A different archive size means the file on disk is a different version."""
        self._write_marker(self.dest_folder, size=self.archive.stat().st_size - 1000,
                           mtime_ns=self.archive.stat().st_mtime_ns)
        self.assertTrue(archive_has_changed_since_extraction(self.dest_folder, self.archive))

    def test_a_changed_mtime_is_stale(self):
        """Even with the same size, a different mtime means the archive was replaced."""
        self._write_marker(self.dest_folder, size=self.archive.stat().st_size,
                           mtime_ns=self.archive.stat().st_mtime_ns + 1)
        self.assertTrue(archive_has_changed_since_extraction(self.dest_folder, self.archive))

    def test_a_missing_archive_is_not_stale(self):
        """A deleted archive means the marker can't be compared, so report 'not changed'."""
        stat = self.archive.stat()
        self._write_marker(self.dest_folder, size=stat.st_size, mtime_ns=stat.st_mtime_ns)
        self.assertFalse(archive_has_changed_since_extraction(self.dest_folder, self.base / "missing.zip"))


class TheStaleBadgeTellsTheTruth(AStatusFileTestCase):
    """The stale badge appears only when the archive changed since extraction, on an unpacked game."""

    def test_a_unchanged_archive_gets_no_stale_badge(self):
        """An unpacked game whose archive matches the marker is not flagged."""
        self._unpack("Loop Miner", self.dest)
        archive = self.root / "Idle" / "Loop Miner - 2024-01-01" / "Loop Miner.zip"
        stat = archive.stat()
        from services.catalog_status import extract_marker_path
        import json as _json
        marker = extract_marker_path(self.dest / "Loop Miner")
        marker.write_text(_json.dumps({'archive_size': stat.st_size,
                                       'archive_mtime_ns': stat.st_mtime_ns}), encoding='utf-8')
        page = self._page()
        self.assertNotIn('data-stale="1"', page, "an unchanged archive was flagged as stale")
        self.assertNotIn('class="badge badge-stale"', page,
                         "a stale badge was drawn for a current archive")

    def test_a_changed_archive_gets_a_stale_badge(self):
        """When the archive's size differs from the marker, the card gets a stale cue."""
        self._unpack("Loop Miner", self.dest)
        archive = self.root / "Idle" / "Loop Miner - 2024-01-01" / "Loop Miner.zip"
        from services.catalog_status import extract_marker_path
        import json as _json
        marker = extract_marker_path(self.dest / "Loop Miner")
        marker.write_text(_json.dumps({'archive_size': archive.stat().st_size - 500,
                                       'archive_mtime_ns': archive.stat().st_mtime_ns}), encoding='utf-8')
        page = self._page()
        self.assertIn('data-stale="1"', page, "the stale archive was not flagged on its card")
        self.assertIn('class="badge badge-stale"', page, "the stale badge class is missing from the card")

    def test_a_stale_unpacked_game_keeps_the_unpacked_badge(self):
        """Stale and unpacked are separate facts: the game is extracted but the archive moved on."""
        self._unpack("Loop Miner", self.dest)
        archive = self.root / "Idle" / "Loop Miner - 2024-01-01" / "Loop Miner.zip"
        from services.catalog_status import extract_marker_path
        import json as _json
        marker = extract_marker_path(self.dest / "Loop Miner")
        marker.write_text(_json.dumps({'archive_size': archive.stat().st_size - 500,
                                       'archive_mtime_ns': archive.stat().st_mtime_ns}), encoding='utf-8')
        page = self._page()
        self.assertEqual(_unpacked_card(page), 1, "the unpacked badge was lost when the archive went stale")
        self.assertIn('data-stale="1"', page, "the stale flag was not set alongside the unpacked badge")

    def test_a_hide_extracted_button_is_present(self):
        """The hide-extracted stat button exists when there are unpacked games to hide."""
        self._unpack("Loop Miner", self.dest)
        page = self._page()
        self.assertIn('data-filter="hide_extracted"', page,
                      "the hide-extracted filter button is missing from the page")


if __name__ == "__main__":
    unittest.main()