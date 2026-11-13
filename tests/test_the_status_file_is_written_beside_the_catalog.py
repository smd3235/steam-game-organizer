"""Extracted from tests/test_catalog_status.py.

    TheStatusFileIsWrittenBesideTheCatalog was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

from services.catalog_status import STATUS_NAME
from services.catalog_status import empty_status
from services.catalog_status import status_from_run
from tests.test_helpers import AStatusFileTestCase
from services.catalog_status import write_status


class TheStatusFileIsWrittenBesideTheCatalog(AStatusFileTestCase):
    def test_a_new_catalog_arrives_with_a_status_file(self):
        """The page loads the status as a sibling script, so the two have to be written together.

        Without this the page still works - a missing script tag is a no-op - but it silently reports nothing
        about any run until one happens to be started from the app. A first catalog that cannot report is a
        catalog that looks like the feature was never built.
        """
        self._generate()
        self.assertTrue((self.root / STATUS_NAME).is_file(), f"the catalog was written without {STATUS_NAME} beside it")

    def test_the_status_file_carries_every_key_the_page_reads(self):
        """The page indexes the payload without checking the keys are there.

        A key added to the writer and forgotten on the reading side is an `undefined` in the middle of a
        banner rather than a visible absence, so the shape is pinned here instead of discovered in a browser.
        """
        status = empty_status()
        for key in ("ran_at", "category", "destination", "total", "extracted", "skipped", "failed", "cancelled", "already_done", "needs_install", "elapsed"):
            self.assertIn(key, status, f"{key} is missing, so the banner would show 'undefined'")
        self.assertEqual(status["ran_at"], "", "a status that claims a run happened when none did")

    def test_a_scan_does_not_erase_the_last_run(self):
        """The reason the status file is written only when it is absent.

        Every scan regenerates the catalog, so writing the empty status unconditionally would replace the last
        run's outcome with "no runs yet" the next time anything at all was scanned - which is the one piece of
        information the banner exists to carry, gone because the page was refreshed by an unrelated action.
        """
        self._generate()
        write_status(self.root, dict(empty_status(), ran_at="2026-10-04 05:12", total=3, extracted=2, failed=1, elapsed="1h 4m"), self.logger)
        self._generate()
        again = self._payload_of(self.root / STATUS_NAME)
        self.assertEqual(again["ran_at"], "2026-10-04 05:12", "regenerating the catalog threw away the record of the run that just finished")
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
        status = self._payload_of(self.root / STATUS_NAME)
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
        self.assertEqual(self._payload_of(self.root / STATUS_NAME)["category"], hostile, "the name was mangled or executed on the way through")

    def test_a_status_that_cannot_be_written_does_not_take_the_run_down(self):
        """The game folders are already unpacked by the time this runs.

        A browser that cannot be told about a finished run is not a reason to report the run as failed, so this
        must return None and log rather than raise. A directory is put where the file goes, which fails the
        same way on every platform - permissions would not, since Windows lets the owner write regardless.
        """
        blocker = self.root / STATUS_NAME
        blocker.mkdir()
        self.assertIsNone(write_status(self.root, empty_status(), self.logger), "a status that could not be written reported success")
