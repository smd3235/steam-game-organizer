import unittest

import pytest

from tests.tk_support import TK_AVAILABLE, close_root, sandbox_app

try:
    import tkinter as tk
except ModuleNotFoundError:
    tk = None
from pathlib import Path
from tempfile import TemporaryDirectory

from core.models import GameArchive, SteamMatch
from utils.filename_utils import identity_key


def setUpModule():
    """Fails the module outright if the toolkit is missing, rather than skipping its tests.

    Every test in here builds a real window, so tkinter is not optional. Each one used to carry its own
    skipUnless, which meant a machine that could not run the application at all still reported the suite
    green while twenty-nine UI assertions quietly did not run - the tests that would have caught a window
    that renders as a flat block, or a control clipped off the bottom, are exactly the ones that were
    being stepped over. On the platform this is run on, a missing tkinter is a broken install worth being
    told about, so it is raised instead of skipped."""
    if not TK_AVAILABLE:
        raise RuntimeError("tkinter could not be imported, so the window tests cannot run. The application needs it too - this install is missing the Tk bindings.")


def _measured_window(root, size="1280x800"):
    """Puts the root at a size a test can actually measure.

    MainWindow maximizes itself on start, which is what the app should do on a Deck. The trouble is that on
    Windows the zoomed state sticks: geometry() is ignored until the window is unzoomed, so a test that set a
    size anyway went on measuring a 2560x1440 window instead of the 1280x800 it asked for. That is how a panel
    written to need scrolling reported that it did not need to - the assertions were right and the window was
    wrong. Unzooming first makes every size in this module mean the same thing on a PC and on the Deck.
    """
    try:
        root.state("normal")
    except tk.TclError:
        pass
    if size:
        root.geometry(size)
    root.update()
    return root


@pytest.mark.geometry
@pytest.mark.ui
class TestUiGeometry(unittest.TestCase):
    def test_audit_progress_moves_the_bar_and_names_the_folder(self):
        # The audit fetches artwork for every game folder in the library, which is the slowest thing a scan
        # does. It used to announce itself once and then say nothing at all, so the run looked hung; the bar
        # and the stage row have to track the folder it is on, or the fix is only half a fix.
        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            _measured_window(root)
            view = app.window.views["scan"]
            app.window.show("scan")
            root.update()

            view.phase_update({"stage": "audit", "message": "Refreshing artwork and Steam links for the library"})
            root.update()
            self.assertEqual(float(view.progress["value"]), 0.0)

            view.phase_update({"stage": "audit", "message": "17 of 361: Brave New Wonders — artwork refreshed", "index": 17, "total": 361})
            root.update()
            self.assertAlmostEqual(float(view.progress["value"]), 17 / 361 * 100, places=1)
            self.assertIn("17 of 361", view.stage_row.cget("text"))

            view.phase_update({"stage": "audit", "message": "361 of 361: Sintopia — no Steam AppID", "index": 361, "total": 361})
            root.update()
            self.assertAlmostEqual(float(view.progress["value"]), 100.0, places=1)

            # Finishing must not leave the row claiming the audit is still on its last folder.
            view.phase_update({"stage": "audit_done", "message": "Checked 361 game folder(s) — refreshed 12"})
            root.update()
            self.assertIn("done", view.stage_row.cget("text"))
            self.assertNotIn("361 of", view.stage_row.cget("text"))
        finally:
            close_root(root)

    def test_both_conversion_paths_report_how_many_are_left(self):
        # There are two places a zip/rar is rebuilt: the repair pass at the tail of a scan, and the organize run.
        # Each owns a panel, and both have to say the same kind of thing - how many conversions are left - because
        # a run can work through twenty games and rebuild two of them, where "game 7 of 20" says nothing about
        # the rebuild that is the only slow part.
        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            _measured_window(root)
            window = app.window
            window.show("scan")
            window.show("organize")
            scan = window.views["scan"]
            organize = window.views["organize"]

            # Path 1: the scan's repair pass.
            scan.repair_done = 0
            scan.repair_free = 0
            scan.repair_total = 0
            scan.repair_update({"stage": "repair_plan", "index": 0, "total": 4})
            self.assertIn("4 left", scan.repair_count_label.cget("text"))
            scan.repair_update({"stage": "converted", "file": "a.zip", "index": 1, "total": 4})
            self.assertIn("1 of 4 converted", scan.repair_count_label.cget("text"))
            self.assertIn("3 left", scan.repair_count_label.cget("text"))

            # Path 2: the organize run.
            organize.progress_update({"stage": "organizing", "index": 1, "total": 6, "conversions": 2, "conversion": 1, "file": "a.zip", "game": "Game A"})
            self.assertIn("game 1 of 6", organize.counters.cget("text"))
            self.assertIn("0 of 2 converted", organize.counters.cget("text"))
            organize.progress_update({"stage": "converted", "file": "a.zip", "conversions": 2, "conversion": 1, "source_bytes": 100, "target_bytes": 50})
            self.assertIn("1 of 2 converted", organize.counters.cget("text"))
            self.assertIn("1 left", organize.counters.cget("text"))
            organize.progress_update({"stage": "converted", "file": "b.rar", "conversions": 2, "conversion": 2, "source_bytes": 100, "target_bytes": 50})
            self.assertIn("2 of 2 converted", organize.counters.cget("text"))
            # A game moved with no rebuild is not a conversion: it reports a terminal stage too, and counting
            # events instead of the run's ordinals would push the counter past the total.
            organize.progress_update({"stage": "skipped", "file": "c.7z", "conversions": 2, "conversion": 0})
            self.assertIn("2 of 2 converted", organize.counters.cget("text"))
        finally:
            close_root(root)

    def test_a_conversion_shows_the_file_size_while_it_works_and_not_only_when_it_is_done(self):
        # The size is what makes a quarter-hour rebuild bearable, and it was unreachable until the archive was
        # finished. Extraction reports the source size and compression the extracted total from the start, but
        # only the finished event was ever rendered, so the feed and the active panel showed a bare filename
        # for the entire run - which is exactly what a user watching an unattended conversion reports.
        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            _measured_window(root)
            window = app.window
            window.show("scan")
            scan = window.views["scan"]
            scan.begin_scan()
            scan.repair_update({"stage": "extracting", "file": "Mineral.Mining.Simulator.v0.9.78.rar", "source_bytes": 59652608, "source_suffix": ".rar", "index": 1, "total": 41})
            feed = scan.activity.get("1.0", "end")
            self.assertIn("56.9 MB", feed, f"the feed showed no source size while extracting:\n{feed}")
            self.assertIn("56.9 MB", scan.current.cget("text"), "the active panel showed no source size while extracting")
            scan.repair_update({"stage": "compressing", "file": "Mineral.Mining.Simulator.v0.9.78.rar", "source_bytes": 59652608, "extracted_bytes": 1440018, "level": 9, "index": 1, "total": 41})
            feed = scan.activity.get("1.0", "end")
            self.assertIn("56.9 MB", feed, f"the feed showed no source size while compressing:\n{feed}")
            self.assertIn("1.4 MB extracted", feed, "the feed never reported how much had been unpacked")
            self.assertIn("level 9", feed)
            self.assertIn("56.9 MB", scan.current.cget("text"))
            # A stage that has reported nothing yet is left alone rather than padded with a placeholder that
            # would read like a real measurement of a file the app has not looked at yet.
            scan.repair_update({"stage": "verifying", "file": "b.zip", "index": 2, "total": 41})
            self.assertNotIn("0 B", scan.current.cget("text"))
        finally:
            close_root(root)

    def test_the_repair_plan_and_start_records_reach_the_conversion_panel(self):
        # The panel was chosen by splitting the stage name on '_', so repair_plan and repair_start were taken
        # for pipeline phases - the pipeline really does have a phase called "repair" - and went to the phase
        # view. The conversion panel carries branches for both that could therefore never run, and the repair
        # row of the timeline sat idle until an archive was already being rebuilt.
        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            _measured_window(root)
            window = app.window
            window.show("scan")
            scan = window.views["scan"]
            scan.begin_scan()
            window._scan_progress({"stage": "repair", "message": "Checking organized folders for leftover ZIP/RAR archives"})
            self.assertEqual(scan.timeline.states["repair"], "active", "the repair phase never marked itself active")
            window._scan_progress({"stage": "repair_plan", "index": 0, "total": 41, "game": "X", "message": "41 archive(s) queued for conversion"})
            self.assertEqual(scan.repair_total, 41, "the repair plan never reached the conversion panel")
            window._scan_progress({"stage": "repair_start", "index": 1, "total": 41, "game": "X", "file": "a.zip", "message": "Converting 1 of 41: X"})
            self.assertEqual(scan.repair_index, 1, "the repair start never reached the conversion panel")
            self.assertIn("41 left", scan.repair_count_label.cget("text"))
            # The pipeline's own repair records still belong on the timeline, or the phase would never complete.
            window._scan_progress({"stage": "repair_done", "message": "Repair pass finished - 41 archive(s) converted"})
            self.assertEqual(scan.timeline.states["repair"], "done")
            self.assertIn("41 archive(s) converted", scan.activity.get("1.0", "end"))
        finally:
            close_root(root)

    def test_the_conversion_count_ignores_archives_that_are_already_7z(self):
        # The count is over rebuilds, not moves. A run of .7z archives is a run of zero conversions, and saying
        # otherwise would leave a permanent "3 left" on a run with nothing left to convert.
        from app.controller import AppController
        from app.events import EventBus
        from app.jobs import JobManager
        from core.logger import AppLogger
        from core.models import GameArchive
        from core.state import StateStore
        from services.organizer_service import OrganizerService
        from utils.filename_utils import identity_key

        with TemporaryDirectory() as d:
            root = Path(d)
            seven = root / "Already.7z"
            seven.write_bytes(b"\x37\x7a\xbc\xaf\x27\x1c")
            zipped = root / "Fresh.zip"
            zipped.write_bytes(b"PK\x03\x04")
            rared = root / "Old.rar"
            rared.write_bytes(b"Rar!\x1a\x07")
            logger = AppLogger(root / "x.log")
            controller = AppController(StateStore(), EventBus(), logger, type("S", (), {"organizer": OrganizerService(logger)})(), JobManager())

            def archive(path):
                return GameArchive(path, path.stem, path.stem, identity_key(path.stem), path.suffix)

            controller.config = type("C", (), {"convert_archives": True})()
            self.assertFalse(controller._needs_conversion(archive(seven)), "an archive that is already 7z was counted as a conversion")
            self.assertTrue(controller._needs_conversion(archive(zipped)))
            self.assertTrue(controller._needs_conversion(archive(rared)))
            controller.config = type("C", (), {"convert_archives": False})()
            self.assertFalse(controller._needs_conversion(archive(zipped)), "a conversion was counted with conversion switched off")
            self.assertFalse(controller._needs_conversion(archive(root / "Gone.zip")), "a missing file was counted as work to do")

    def test_workflow_screens_and_scroll_surfaces_exist(self):
        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            root.update_idletasks()
            self.assertEqual(set(app.window.views), {"scan", "review", "organize", "artwork", "done"})
            self.assertTrue(app.window.views["scan"].scan_btn.winfo_ismapped())
            for screen in ("review", "organize", "artwork", "done"):
                app.window.show(screen)
                root.update_idletasks()
                self.assertTrue(app.window.views[screen].winfo_ismapped())
            app.window.show("review")
            root.update_idletasks()
            review = app.window.views["review"]
            self.assertTrue(review.list.canvas.winfo_exists())
            self.assertTrue(review.detail_canvas.winfo_exists())
            app.window.show("artwork")
            root.update_idletasks()
            artwork = app.window.views["artwork"]
            self.assertTrue(artwork.canvas.winfo_exists())
        finally:
            close_root(root)

    def test_processing_panes_stay_pinned_to_the_bottom(self):
        # During a run the queue and the log panes must follow their newest content rather than holding an
        # older scroll offset, so a long run never leaves the view stranded partway up.
        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            root.update_idletasks()
            game_list = app.window.views["review"].list
            self.assertFalse(game_list.auto_scroll)
            game_list.set_auto_scroll(True)
            self.assertTrue(game_list.auto_scroll)
            game_list.set_auto_scroll(False)
            self.assertFalse(game_list.auto_scroll)
            scan = app.window.views["scan"]
            for i in range(40):
                scan._append_activity(f"line {i}\n")
            root.update_idletasks()
            self.assertAlmostEqual(scan.activity.yview()[1], 1.0, places=2)
        finally:
            close_root(root)

    def test_done_screen_reports_successes_and_failures(self):
        # The Done screen is the only place a user sees what a run actually did. Failures must appear with
        # their real reason and be listed before successes so a broken run is impossible to miss.
        from core.models import GameArchive, SteamMatch, ConversionResult

        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            root.update_idletasks()
            done = app.window.views["done"]

            def archive(name, status, message=""):
                item = GameArchive(Path(f"/tmp/{name}.rar"), name, name, status, ".rar")
                item.decision.accepted = True
                item.decision.category = "Simulation"
                item.steam = SteamMatch(found=True, appid="1", name=name)
                item.conversion = ConversionResult(status=status, message=message, source_format="RAR", target_format="7Z" if status in ("converted", "rebuilt") else "", final_name=f"{name}.7z", final_size=1_500_000_000, free_bytes_at_failure=2_000_000 if status == "failed" else 0)
                return item

            archives = [archive("Good Game", "converted"), archive("Bad Game", "failed", "7z build exited 255: Break signaled"), archive("Untouched", "skipped", "7z/7za not installed"), archive("Fine", "not_needed"), archive("Declined", "")]
            archives[-1].decision.accepted = False
            archives[-1].decision.skipped = True
            done.show(archives)
            root.update_idletasks()
            text = done.details.get("1.0", "end")
            self.assertIn("Break signaled", text)  # the reason, not just a red row
            self.assertIn("1.9 MB", text)  # free space at failure (2_000_000 bytes)
            self.assertIn("not converted", text)
            self.assertIn("Good Game", text)
            self.assertIn("FAILED", text)
            self.assertLess(text.index("FAILED"), text.index("CONVERTED TO 7Z"))
            self.assertEqual(done.tiles["failed"].cget("text"), "1")
            self.assertEqual(done.tiles["converted"].cget("text"), "1")
        finally:
            close_root(root)

    def test_done_screen_actually_receives_run_results(self):
        # Regression: the Done view's show() was never called, so it always displayed its empty placeholder.
        from core.models import GameArchive

        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            root.update_idletasks()
            window = app.window
            item = GameArchive(Path("/tmp/x.zip"), "x", "x", "x", ".zip")
            item.decision.accepted = True
            item.steam = type("S", (), {"found": True, "appid": "1", "name": "Visible Game"})()
            window.finish([item])
            root.update_idletasks()
            window.goto_done()
            root.update_idletasks()
            self.assertIn("Visible Game", window.views["done"].details.get("1.0", "end"))
        finally:
            close_root(root)

    def test_archived_duplicate_is_not_reported_as_pending_work(self):
        # Regression: archive_file() left the conversion note at its default status, so a duplicate that
        # had been successfully filed under Archive/ reached the Done screen indistinguishable from an
        # archive whose conversion never ran, and was reported as outstanding work.
        from core.models import GameArchive

        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            root.update_idletasks()
            done = app.window.views["done"]

            def item(name):
                archive = GameArchive(Path(f"/tmp/{name}.zip"), name, name, "k", ".zip")
                archive.decision.accepted = True
                archive.decision.category = "Adventure"
                archive.steam = SteamMatch(found=True, appid="1", name=name)
                return archive

            filed = item("Filed Game")
            filed.conversion.status = "archived"
            filed.conversion.source_format = "ZIP"
            filed.conversion.final_name = "Filed Game.zip"
            finished = item("Finished Game")
            finished.conversion.status = "converted"
            done.show([filed, finished])
            root.update_idletasks()
            text = done.details.get("1.0", "end")
            self.assertIn("ARCHIVED AS DUPLICATE", text)  # a completed outcome, named as such
            self.assertIn("Filed Game", text)
            self.assertNotIn("(pending)", text)  # never presented as unfinished work
            self.assertIn("duplicate(s) filed under Archive/", done.summary.cget("text"))
        finally:
            close_root(root)

    def test_scan_pipeline_shows_every_phase_not_just_discovery(self):
        # Only discovery used to report itself, so cleanup, dedupe, repair, audit and catalog each looked like
        # an unexplained wait. Every phase must now mark the timeline and state its real outcome.
        from ui.scan_view import SCAN_PHASES

        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            root.update_idletasks()
            window = app.window
            scan = window.views["scan"]
            scan.begin_scan()
            root.update_idletasks()
            for event in (
                {"stage": "cleanup", "message": "Reclaiming leftovers"},
                {"stage": "cleanup_done", "message": "Reclaimed 3 item(s), freed 1.2 GB"},
                {"stage": "dedupe_done", "message": "Kept one archive per game folder"},
                {"stage": "repair", "message": "Checking for leftover ZIP/RAR"},
                {"stage": "repair_done", "message": "Repair pass finished"},
                {"stage": "discover", "message": "Scanning for archives"},
                {"stage": "discover_done", "message": "Found 42 archive(s)"},
            ):
                window._scan_progress(event)
            root.update_idletasks()
            states = {key: scan.timeline.states[key] for key, _ in SCAN_PHASES}
            for finished in ("cleanup", "dedupe", "repair", "discover"):
                self.assertEqual(states[finished], "done", f"{finished} phase never reported completion")
            feed = scan.activity.get("1.0", "end")
            for phrase in ("Reclaiming leftovers", "freed 1.2 GB", "Found 42 archive(s)"):
                self.assertIn(phrase, feed)
            self.assertRegex(feed, r"\d\d:\d\d:\d\d")  # every line is timestamped
            self.assertIn("AUDIT", scan.timeline.chips and " ".join(c.cget("text") for c in scan.timeline.chips.values()).upper())
        finally:
            close_root(root)

    def test_done_screen_does_not_count_a_failed_game_as_organized(self):
        # The Done screen counts what a run achieved from the archives it is handed, and a game whose move
        # failed - a file open in Explorer, a permission the library does not grant - is handed over so that it
        # can be named. Counting it as organized would report a game the run never placed, so the headline and
        # the tile have to move to the games that actually landed.
        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            root.update_idletasks()
            done = app.window.views["done"]
            filed = GameArchive(Path("a.7z"), "Good Game", "Good Game", "good game", ".7z")
            filed.decision.accepted = True
            filed.organized_path = Path("Simulation/Good Game/Good Game.7z")
            refused = GameArchive(Path("b.7z"), "Locked Game", "Locked Game", "locked game", ".7z")
            refused.decision.accepted = True
            refused.conversion.status = "failed"
            refused.conversion.message = "[WinError 32] The process cannot access the file"
            done.show([filed, refused])
            root.update_idletasks()
            self.assertIn("1 game(s) organized", done.summary.cget("text"))
            self.assertEqual(done.tiles["organized"].cget("text"), "1")
            self.assertEqual(done.tiles["failed"].cget("text"), "1")
            self.assertEqual(done.summary_heading, "Completed with problems")
        finally:
            close_root(root)

    def test_organize_panel_marks_the_exact_stage_a_conversion_failed_in(self):
        # A failed conversion must not paint every stage as done, nor every stage as failed: the timeline has
        # to show which step actually died, because that is what the user has to act on.
        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            root.update_idletasks()
            window = app.window
            window.show("organize")
            root.update_idletasks()
            organize = window.views["organize"]
            organize.stage_counts = {}
            organize.current = None
            organize.work.grid()
            organize.timeline.reset()
            root.update_idletasks()
            for event in ({"stage": "organizing", "file": "Bad.rar", "game": "Bad", "index": 1, "total": 1}, {"stage": "extracting", "file": "Bad.rar", "source_bytes": 900}, {"stage": "compressing", "file": "Bad.rar", "extracted_bytes": 1800}, {"stage": "failed", "file": "Bad.rar", "message_text": "7z build exited 255: Break signaled"}):
                organize.progress_update(event)
            root.update_idletasks()
            states = dict(organize.timeline.states)
            self.assertEqual(states["compress"], "failed")  # died here
            self.assertEqual(states["move"], "done")  # these genuinely finished
            self.assertEqual(states["extract"], "done")
            self.assertEqual(states["verify"], "pending")  # never reached
            self.assertIn("7z build exited 255", organize.detail_label.cget("text"))
            self.assertIn("FAILED", organize.log.get("1.0", "end"))
        finally:
            close_root(root)

    def test_review_evidence_text_can_be_scrolled(self):
        # The wheel was routed to the detail canvas, but the long evidence lives in a Text nested inside that
        # canvas, so scrolling moved nothing and the bottom of every Steam description was unreachable.
        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            _measured_window(root)
            review = app.window.views["review"]
            app.window.show("review")
            root.update()
            review.detail.configure(state="normal")
            review.detail.insert("end", "\n".join(f"line {i} " + "x" * 90 for i in range(400)))
            review.detail.configure(state="disabled")
            root.update()
            self.assertGreater(int(review.detail.index("end-1c").split(".")[0]), 10)
            before = review.detail.yview()[0]
            # A real wheel event over the pane, delivered the way Tk delivers one: event.widget is the widget
            # under the pointer, not the toplevel the binding is installed on. Routing from that is what the
            # view does now, so the test does not depend on the window manager placing a window on a screen -
            # which is the only reason this test used to be able to fail on a machine that has a desktop.
            event = type("E", (), {})()
            event.widget = review.detail
            event.delta = -120
            event.num = 0
            for _ in range(15):
                review._route_wheel(event)
            root.update_idletasks()
            self.assertGreater(review.detail.yview()[0], before, "detail evidence still cannot be scrolled")
            # The canvas around the text still scrolls, so the padding above and below it is not dead space.
            # It has to be given something taller than its viewport first, or there is nothing to scroll and
            # the assertion would be measuring a canvas that was never going to move.
            tk.Label(review.detail_inner, text="\n".join(f"padding {i}" for i in range(200))).pack()
            root.update()
            canvas_before = review.detail_canvas.yview()[0]
            padding = type("E", (), {})()
            padding.widget = review.detail_canvas
            padding.delta = -120
            padding.num = 0
            for _ in range(3):
                review._route_wheel(padding)
            root.update_idletasks()
            self.assertGreater(review.detail_canvas.yview()[0], canvas_before, "the wheel over the detail padding moved nothing")
        finally:
            close_root(root)

    def test_artwork_progress_events_reach_the_review_status_line(self):
        # verify_all reports each artwork asset with a 6th callback argument, but _progress accepted 5, so the
        # first asset event raised TypeError on the Tk thread and artwork progress was never visible.
        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            _measured_window(root)
            review = app.window.views["review"]
            app.window.show("review")
            root.update_idletasks()
            archive = GameArchive(Path("/tmp/Alpha Quest v1.7z"), "Alpha Quest v1", "Alpha Quest", identity_key("alpha quest"), ".7z")
            archive.steam = SteamMatch(found=True, appid="1", name="Alpha Quest", confidence="High")
            review.archives = [archive]
            for event, expected in (({"asset": "cover", "state": "start", "detail": "Alpha Quest"}, "start"), ({"asset": "cover", "state": "downloaded", "detail": "3 of 5  •  412 KB"}, "412 KB"), ({"asset": "hero", "state": "failed", "detail": "TimeoutError"}, "failed")):
                review._progress(1, 1, archive, archive.steam, None, event)
                root.update_idletasks()
                text = review.progress.cget("text")
                self.assertIn(expected, text, f"artwork progress not shown: {text!r}")
            review._progress(1, 1, archive, archive.steam, None)
            self.assertIn("Verifying", review.progress.cget("text"), "per-game progress did not recover after assets")
        finally:
            close_root(root)

    def test_done_reports_run_facts_and_category_bars(self):
        # The run report was a narrow column of text in a very wide panel, so most of the screen stayed blank
        # and the run-level numbers (duration, space saved, rollback) were never shown at all.
        from core.logger import AppLogger
        from services.rollback_service import RollbackService

        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            root.update()
            done = app.window.views["done"]
            app.window.show("done")
            root.update_idletasks()
            archives = []
            for name, category in (("Alpha Quest", "Adventure"), ("Beta Raid", "Adventure"), ("Gamma Drift", "Strategy")):
                item = GameArchive(Path(f"/tmp/{name} v1.zip"), f"{name} v1", name, identity_key(name.lower()), ".zip")
                item.steam = SteamMatch(found=True, appid="1", name=name, confidence="High")
                item.decision.accepted = True
                item.decision.category = category
                item.conversion.status = "converted"
                item.conversion.source_format = "ZIP"
                item.conversion.target_format = "7Z"
                item.conversion.final_size = 1_000_000_000
                item.conversion.source_size = 1_400_000_000
                item.conversion.final_name = f"{name} v1.7z"
                archives.append(item)
            # A journal with one move in it, so the undo row's text is this test's to decide rather than whatever the
            # last real organize on this machine left behind. It used to inject `config=app.config` into the app
            # state and assert the row read 'nothing to undo' - but AppState has no config field and no
            # rollback_pending field, so the row rendered its placeholder no matter what was put there, and the
            # pre-fix code produced this very string. Asserting a count instead is what distinguishes the two:
            # '1 move(s)' is a string the old expression cannot reach. The empty case is kept as a second
            # assertion, where it belongs.
            with TemporaryDirectory() as scratch:
                done.rollback = RollbackService(scratch, AppLogger(Path(scratch) / "rollback.log"))
                moved = Path(scratch) / "Incoming" / "Alpha Quest v1.7z"
                organized = Path(scratch) / "Games" / "Adventure" / "Alpha Quest - 2020-01-01" / "Alpha Quest.7z"
                organized.parent.mkdir(parents=True)
                organized.write_bytes(b"7z")
                self.assertTrue(done.rollback.record([(moved, organized)], [str(organized.parent)]))
                app.state.update(run_seconds=125.4)
                done.show(archives)
                root.update_idletasks()
                self.assertEqual(done.facts["undo"].cget("text"), "1 move(s)", "a journalled move is invisible to the undo row")
                done.rollback.record([], [])
                done.show(archives)
                root.update_idletasks()
                self.assertEqual(done.facts["undo"].cget("text"), "nothing to undo", "an empty journal must not be reported as a move waiting to be undone")
            self.assertEqual(done.facts["compressed"].cget("text"), "2.8 GB")  # 3 x 1e9 bytes
            saved = done.facts["saved"].cget("text")
            self.assertIn("1.1 GB", saved, "combined space saved was never reported")  # 4.2e9 in, 3e9 out
            self.assertIn("29%", saved, "combined saving needs the saving share")
            # The combined total is not enough on its own: each game reports what it saved individually.
            report = done.details.get("1.0", "end")
            self.assertEqual(report.count("saved 381.5 MB (29%)"), 3, "per-game space saving is missing")
            self.assertNotEqual(done.facts["duration"].cget("text"), "—", "run duration was never reported")
            # One bar row per category, so the split is visible as a shape and not just a sentence.
            self.assertEqual(len(done.bars.winfo_children()), 2, "one bar row per category expected")
            rows = done.bars.winfo_children()
            labels = [c.winfo_children()[0].winfo_children()[0].cget("text") for c in rows]
            self.assertEqual(labels, ["Adventure", "Strategy"], "categories should be ordered by size")
            widths = [c.winfo_children()[1].winfo_children()[0].cget("width") for c in rows]
            self.assertNotEqual(widths[0], widths[1], "bar widths should scale with the counts")
            self.assertGreater(widths[0], widths[1], "the larger category should get the wider bar")
        finally:
            close_root(root)

    def test_nav_buttons_are_clickable_and_blocked_during_a_run(self):
        # The nav strip recoloured itself like a button but had no binding at all, so it was dead UI.
        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            root.update()
            window = app.window
            window.show("review")
            root.update_idletasks()
            window.nav_buttons["done"].invoke()
            root.update_idletasks()
            self.assertEqual(window.current, "done")
            # While a run is in flight, switching screens would reset live progress, so it must be refused.
            window._end("done")
            window._start("Organizing…")
            window.show("review")
            root.update_idletasks()
            window.nav_buttons["scan"].invoke()
            root.update_idletasks()
            self.assertEqual(window.current, "review")
            self.assertIn("run is in progress", window.status.cget("text"))
        finally:
            close_root(root)

    def test_organize_run_can_be_stopped_mid_flight(self):
        # The only cancel button lived in the pre-flight confirmation bar, so once work started there was no
        # way to stop a long LZMA2 repack from the screen being watched.
        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            root.update_idletasks()
            organize = app.window.views["organize"]
            stopped = []
            organize.on_cancel = lambda: stopped.append(True)
            organize.ctx = object()
            organize.work.grid()
            organize.stop_btn.configure(state="normal", text="STOP RUN")
            organize._stop()
            root.update_idletasks()
            self.assertEqual(stopped, [True])
            self.assertEqual(str(organize.stop_btn.cget("state")), "disabled")  # ttk returns a Tcl object
            self.assertIn("STOPPING", organize.stop_btn.cget("text"))
        finally:
            close_root(root)

    def test_no_rail_panel_silently_clips_its_own_content(self):
        # Both rail panels are fixed-height. The live data one needed 519px in a 271px slot once the
        # conversion rows were added, so everything below the first counts was clipped to zero height and
        # never drawn - which reads as dead space rather than as a bug. Anything that cannot fit must either
        # scroll or the panel must be given the room.
        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            _measured_window(root)
            window = app.window
            window.show("scan")
            window.show("organize")
            root.update_idletasks()
            scan = window.views["scan"]
            scan.begin_scan()
            root.update_idletasks()

            def clipped(panel):
                bottom = panel.winfo_rooty() + panel.winfo_height()
                out = []
                for child in panel.winfo_children():
                    if not child.winfo_ismapped() or child.winfo_class() == "Canvas":
                        continue
                    if child.winfo_rooty() + child.winfo_height() > bottom + 1:
                        out.append(child)
                return out

            self.assertEqual(clipped(scan.api), [], "the API panel clips its content")
            # The live data panel scrolls, so its content has to be taller than the viewport and fully
            # reachable rather than being cut off.
            canvas = scan._dash_canvas
            region = canvas.cget("scrollregion").split()
            self.assertGreater(int(region[3]), canvas.winfo_height(), "the live data content no longer needs scrolling - check it is not clipped instead")
            self.assertGreaterEqual(int(region[3]), scan.dash_body.winfo_height(), "the scroll region does not cover the whole content")
        finally:
            close_root(root)

    def test_conversion_toggle_is_present_and_follows_the_saved_setting(self):
        # The toggle is loaded from the saved setting on startup (ui/main_window.py), so its value depends on
        # the real config. Asserting it was "on" made this test fail whenever conversion had been switched off,
        # reporting a broken UI for a setting the test does not own. What matters here is that the control is
        # present in the panel and that it faithfully shows the stored value. The default-on behaviour and the
        # persistence of the choice are covered hermetically against a temporary config directory in the
        # service tests.
        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            _measured_window(root)
            window = app.window
            window.show("scan")
            root.update_idletasks()
            scan = window.views["scan"]
            self.assertEqual(scan.convert_var.get(), bool(window.config.convert_archives), "the conversion toggle does not reflect the saved setting")
            found = []

            def walk(widget):
                for child in widget.winfo_children():
                    if child.winfo_class() == "TCheckbutton":
                        found.append(str(child.cget("text")))
                    walk(child)

            walk(scan)
            self.assertIn("Convert ZIP/RAR to 7z", found, "the conversion toggle is missing from the panel")
        finally:
            close_root(root)

    def test_scan_bar_and_live_data_follow_the_conversion_pass(self):
        # The repair pass is the longest part of a scan, and it drove nothing: the bar belonged to discovery,
        # which had already finished, so an hour of converting looked frozen, and the rail beside it named the
        # current file without ever saying how big it was or how far along it was.
        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            _measured_window(root)
            window = app.window
            window.show("scan")
            root.update_idletasks()
            scan = window.views["scan"]
            scan.begin_scan()
            readings = []
            for percent in (0, 25, 50, 75, 100):
                scan.repair_update({"stage": "compressing", "file": "Big.zip", "source_bytes": 4 * 1024**3, "extracted_bytes": 9 * 1024**3, "progress": percent / 100, "tool_percent": percent, "tool_file": "data/pak.bin", "level": 9})
                readings.append(scan.progress["value"])
            self.assertTrue(all(v > 0 for v in readings), f"the bar sat at zero through the whole conversion: {readings}")
            self.assertEqual(readings, sorted(readings), f"the bar went backwards during one stage: {readings}")
            self.assertIn("Big.zip", scan.current.cget("text"))
            self.assertIn("4 GB", scan.repair_size_label.cget("text"))
            self.assertIn("9 GB", scan.repair_extracted_label.cget("text"))
            self.assertIn("100%", scan.repair_percent_label.cget("text"))
            self.assertIn("pak.bin", scan.current.cget("text"))
            scan.repair_update({"stage": "converted", "file": "Big.zip", "source_bytes": 4 * 1024**3, "target_bytes": 2 * 1024**3})
            self.assertIn("1 converted", scan.repair_count_label.cget("text"))
            # The saved total has its own row now. It used to be appended to the count label, where it shared
            # a line with "1 of 9 converted" and could not show a loss at all.
            self.assertIn("2 GB freed", scan.repair_saved_label.cget("text"))
        finally:
            close_root(root)

    def test_organize_bar_advances_through_a_long_compress(self):
        # The bar used to be set to a fixed position per stage, so a two-minute LZMA2 compress left it
        # parked at 72% with nothing moving. It has to advance while a single stage is still running.
        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            _measured_window(root)
            window = app.window
            window.show("organize")
            root.update_idletasks()
            organize = window.views["organize"]
            organize.stage_counts = {}
            organize.current = None
            organize.work.grid()
            organize.timeline.reset()
            organize.feed.clear()
            organize.total_bytes = 10 * 1024**3
            organize.done_bytes = 0
            organize.ctx = object()
            readings = []
            for percent in (0, 25, 50, 75, 100):
                organize.progress_update({"stage": "compressing", "file": "Big.7z", "source_bytes": 4 * 1024**3, "extracted_bytes": 9 * 1024**3, "progress": percent / 100, "tool_percent": percent, "tool_file": "setup-1.bin", "level": 9})
                readings.append(organize.bar["value"])
            self.assertEqual(readings, sorted(readings), f"the bar went backwards across one stage: {readings}")
            self.assertLess(readings[0], readings[-1], f"the bar never moved during the compress: {readings}")
            self.assertTrue(all(0 <= v <= 100 for v in readings), f"the bar left its 0-100 range: {readings}")
            # And the bar has to be a real fraction of the whole run, not just of this archive.
            self.assertLess(readings[-1], 100, "a single finished archive claimed the entire run")
            organize.ctx = None
        finally:
            close_root(root)

    def test_organize_live_panel_reports_the_level_memory_and_current_entry(self):
        # The live panel said only that a file was being converted. The level it settled on, the memory
        # headroom behind that choice, and the entry the compressor is writing are the numbers a user needs
        # to tell a healthy run from one about to fail.
        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            _measured_window(root)
            window = app.window
            window.show("organize")
            root.update_idletasks()
            organize = window.views["organize"]
            organize.stage_counts = {}
            organize.current = None
            organize.work.grid()
            organize.timeline.reset()
            organize.feed.clear()
            organize.total_bytes = 10 * 1024**3
            organize.done_bytes = 0
            organize.ctx = object()
            organize.started_at = __import__("time").monotonic()
            organize.progress_update({"stage": "compressing", "file": "Big.7z", "source_bytes": 4 * 1024**3, "progress": 0.42, "tool_percent": 42, "tool_file": "data/pak42.bin", "level": 9})
            organize._refresh_metrics()
            root.update_idletasks()
            pressure = organize.pressure.cget("text")
            self.assertIn("level 9", pressure)
            self.assertIn("pak42.bin", pressure)
            self.assertIn("7z level 9", pressure)
            # The memory reading has to be a real number. It was briefly formatted from a tuple rather than
            # from the two values the lookup returns, which rendered as a bare '-' and looked like no reading.
            # Both platforms now produce one - Linux from /proc/meminfo, Windows from the kernel - so the
            # figure is asserted unconditionally rather than excused where the reading was missing.
            self.assertRegex(pressure, r"RAM [\d.]+ [KMG]B free / swap [\d.]+ [KMG]B")
            self.assertIn("42%", organize.metrics.cget("text"), "stage progress was not shown")
            organize.ctx = None
        finally:
            close_root(root)

    def test_organize_feed_redraws_the_live_line_instead_of_repeating_it(self):
        # A stage reports about once a second for minutes, and every one of those was appended, so the feed
        # filled with identical "Converting: same-file" lines that buried the real transitions.
        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            _measured_window(root)
            window = app.window
            window.show("organize")
            root.update_idletasks()
            organize = window.views["organize"]
            organize.stage_counts = {}
            organize.current = None
            organize.work.grid()
            organize.timeline.reset()
            organize.feed.clear()
            for percent in (10, 20, 30, 40, 50):
                organize.progress_update({"stage": "compressing", "file": "Same.7z", "source_bytes": 1024, "progress": percent / 100, "tool_percent": percent})
            text = organize.log.get("1.0", "end")
            self.assertEqual(text.count("COMPRESSING: Same.7z"), 1, f"the live stage was appended repeatedly instead of redrawn:\n{text}")
            self.assertIn("50%", text, "the live line did not show the latest percentage")
            # A real transition must still be kept as its own line underneath the live one.
            organize.progress_update({"stage": "converted", "file": "Same.7z", "source_bytes": 1024, "target_bytes": 512})
            text = organize.log.get("1.0", "end")
            self.assertIn("CONVERTED: Same.7z", text)
        finally:
            close_root(root)

    def test_organize_shows_throughput_eta_and_free_space(self):
        # A single LZMA2 compress reports nothing between "compressing" and "converted", so without live
        # throughput, an estimate and a free-space reading the run reads as stalled rather than as working.
        import time as time_module

        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            _measured_window(root)
            window = app.window
            window.show("organize")
            root.update_idletasks()
            organize = window.views["organize"]
            organize.stage_counts = {}
            organize.current = None
            organize.work.grid()
            organize.timeline.reset()
            organize.feed.clear()
            organize.started_at = time_module.monotonic() - 60
            organize.total_bytes = 40 * 1024**3
            organize.done_bytes = 0
            organize.ctx = object()  # the metrics ticker only runs while a job is active
            organize.progress_update({"stage": "converted", "file": "A.7z", "source_bytes": 4 * 1024**3, "target_bytes": 2 * 1024**3})
            organize._refresh_metrics()
            root.update_idletasks()
            metrics = organize.metrics.cget("text")
            self.assertIn("running 01:00", metrics)
            self.assertIn("/s", metrics)  # throughput
            self.assertIn("left", metrics)  # estimate for the remainder
            space = organize.space_label.cget("text")
            self.assertIn("Free space on library volume", space)
            # The ratio is the concrete payoff of the repack.
            self.assertIn("% of original", organize.detail_label.cget("text"))
            organize.ctx = None  # stop the 1s ticker before the window is destroyed
        finally:
            close_root(root)

    def test_scan_phase_timeline_reports_real_counts_and_surfaces_errors(self):
        # audit() and catalog.generate() returned real counts that were discarded, so the feed could only say
        # "refreshed". ScanResult.errors was populated by the scanner and referenced nowhere in the UI at all.
        from core.models import ScanResult

        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            root.update()
            window = app.window
            scan = window.views["scan"]
            scan.begin_scan()
            root.update_idletasks()
            for event in ({"stage": "audit_done", "message": "Checked 40 game folder(s) — refreshed 12", "checked": 40, "refreshed": 12}, {"stage": "catalog_done", "message": "Catalog generated — 5 page(s) written", "written": 5}):
                window._scan_progress(event)
            root.update_idletasks()
            feed = scan.activity.get("1.0", "end")
            self.assertIn("refreshed 12", feed)
            self.assertIn("5 page(s) written", feed)
            result = ScanResult(archives=[], errors=["Library folder is unreadable: /mnt/broken"])
            scan.set_result(result)
            root.update_idletasks()
            after = scan.activity.get("1.0", "end")
            self.assertIn("Scan problem: Library folder is unreadable", after)
            self.assertIn("1 problem(s) during scan", scan.repair_note.cget("text"))
        finally:
            close_root(root)

    def test_done_report_can_be_saved_to_a_file(self):
        # The on-screen report vanishes with the window, so being able to keep it is the artifact worth having.
        import tempfile as tempfile_module
        from unittest.mock import patch

        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            root.update()
            from core.models import GameArchive, SteamMatch

            done = app.window.views["done"]
            item = GameArchive(Path("/tmp/x.zip"), "x", "x", "k", ".zip")
            item.decision.accepted = True
            item.steam = SteamMatch(found=True, appid="1", name="Saved Game")
            item.conversion.status = "converted"
            item.conversion.source_format = "ZIP"
            item.conversion.target_format = "7Z"
            item.conversion.final_size = 2_000_000_000
            item.conversion.final_name = "x.7z"
            done.show([item])
            root.update_idletasks()
            with tempfile_module.TemporaryDirectory() as folder:
                target = Path(folder) / "report.txt"
                with patch("ui.done_view.filedialog.asksaveasfilename", return_value=str(target)):
                    done._export_report()
                root.update_idletasks()
                self.assertTrue(target.is_file())
                self.assertIn("Saved Game", target.read_text())
                # And the user is told it happened; the details pane is read-only so this needs care.
                self.assertIn("Report saved to", done.details.get("1.0", "end"))
                self.assertEqual(str(done.details.cget("state")), "disabled")
        finally:
            close_root(root)

    def test_a_finished_conversion_shows_what_it_was_and_what_it_became(self):
        # "Converted: Big.zip" on its own cannot tell a user whether the run was worth an hour of CPU. The
        # original size, the 7z that replaced it and the difference are the three numbers that answer it, and
        # the completion event is the only place the finished count exists, so both sizes have to arrive with it.
        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            _measured_window(root)
            window = app.window
            window.show("scan")
            root.update_idletasks()
            scan = window.views["scan"]
            scan.begin_scan()
            scan.repair_update({"stage": "repair_plan", "index": 0, "total": 3})
            scan.repair_update({"stage": "converted", "index": 1, "file": "Big.zip", "source_bytes": 4 * 1024**3, "target_bytes": 3 * 1024**3, "source_format": "ZIP", "target_format": "7Z"})
            feed = scan.activity.get("1.0", "end")
            self.assertIn("4 GB", feed, "the original size never reached the activity feed")
            self.assertIn("3 GB", feed, "the new 7z size never reached the activity feed")
            self.assertIn("1 GB", feed, "the difference between them is not shown")
            self.assertEqual(len(scan.conversion_rows), 1, "the per-archive conversion list is empty")
            # The same three numbers are on the panel, for someone watching the run rather than reading it back.
            row_text = " ".join(child.cget("text") for row in scan.conversion_rows for child in row.winfo_children())
            self.assertIn("Big.zip", row_text)
            self.assertIn("1 GB", row_text)
        finally:
            close_root(root)

    def test_a_conversion_that_used_more_space_says_so_instead_of_reporting_zero(self):
        # Converting an already-compressed .zip to .7z routinely produces a larger file. Clamping the running
        # total at zero reported those conversions as having freed nothing, which is indistinguishable from a
        # total that cannot be computed - and both looked like a run that was quietly costing disk space.
        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            _measured_window(root)
            window = app.window
            window.show("scan")
            root.update_idletasks()
            scan = window.views["scan"]
            scan.begin_scan()
            scan.repair_update({"stage": "repair_plan", "index": 0, "total": 2})
            scan.repair_update({"stage": "converted", "index": 1, "file": "Small.zip", "source_bytes": 1 * 1024**3, "target_bytes": 2 * 1024**3, "source_format": "ZIP", "target_format": "7Z"})
            self.assertIn("LOST", scan.repair_saved_label.cget("text"), "a conversion that grew the file reported nothing")
            self.assertEqual(scan.repair_grown_label.cget("text"), "1", "the count of conversions that used more space is not tracked")
            # A later saving archive nets against the loss rather than being hidden by it.
            scan.repair_update({"stage": "converted", "index": 2, "file": "Big.rar", "source_bytes": 4 * 1024**3, "target_bytes": 2 * 1024**3, "source_format": "RAR", "target_format": "7Z"})
            self.assertIn("1 GB freed", scan.repair_saved_label.cget("text"), "the running total does not net gains against losses")
        finally:
            close_root(root)

    def test_the_repair_bar_moves_within_one_archive_and_finishes_on_the_last(self):
        # Forty-five archives at fifteen minutes each is the real case. A bar driven by three fixed stage
        # weights sat still for the whole of each archive and then jumped, and because the finished count was
        # read before it was incremented it could never reach 100% on the last one.
        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            _measured_window(root)
            window = app.window
            window.show("scan")
            root.update_idletasks()
            scan = window.views["scan"]
            scan.begin_scan()
            scan.repair_update({"stage": "repair_plan", "index": 0, "total": 4})
            scan.repair_update({"stage": "extracting", "file": "A.zip", "total": 4, "tool_percent": 0})
            early = scan.progress["value"]
            scan.repair_update({"stage": "extracting", "file": "A.zip", "total": 4, "tool_percent": 100})
            late = scan.progress["value"]
            self.assertGreater(late, early, "the bar did not move inside a single archive")
            self.assertLess(late, 25.0, "one archive of four filled the whole bar during its extraction")
            scan.repair_update({"stage": "compressing", "file": "A.zip", "total": 4, "tool_percent": 100})
            self.assertGreater(scan.progress["value"], late, "the bar did not move into compression")
            for index in range(1, 5):
                scan.repair_update({"stage": "converted", "index": index, "file": f"{index}.zip", "total": 4, "source_bytes": 2 * 1024**3, "target_bytes": 1024**3})
            self.assertEqual(scan.progress["value"], 100.0, "the bar never completed on the last archive")
            # And it is at 3/4 while the fourth is still being worked on, rather than reading full early.
            scan.begin_scan()
            scan.repair_update({"stage": "repair_plan", "index": 0, "total": 4})
            for index in range(1, 4):
                scan.repair_update({"stage": "converted", "index": index, "file": f"{index}.zip", "total": 4, "source_bytes": 2 * 1024**3, "target_bytes": 1024**3})
            self.assertEqual(scan.progress["value"], 75.0, "the bar reported the run as finished early")
        finally:
            close_root(root)

    def test_the_live_data_panel_scrolls_from_anywhere_over_its_contents(self):
        # The panel's rows are a frame on a scrolling canvas, so a wheel event over a label goes to that label
        # and Tk propagates only to ancestors - never to the canvas. Binding the canvas alone left the panel
        # scrollable only over bare canvas and the scrollbar.
        root = tk.Tk()
        try:
            app = sandbox_app(self, root)
            root.geometry("1100x680")
            root.update()
            window = app.window
            window.show("scan")
            root.update_idletasks()
            scan = window.views["scan"]
            unbound = []
            for widget in [scan.dash_body] + scan.dash_body.winfo_children():
                for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                    if not widget.bind(sequence):
                        unbound.append(f"{widget.winfo_class()}:{sequence}")
            self.assertEqual(unbound, [], "these panel widgets swallow the wheel instead of scrolling")
        finally:
            close_root(root)


if __name__ == "__main__":
    unittest.main()
