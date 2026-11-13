"""Extracted from tests/test_services.py.

    TestPartialArchiveSafety was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import os
import time
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from app.jobs import JobContext
from core.logger import AppLogger
from core.models import RepairArchive
from services.archive_service import ArchiveService
from services.library_service import LibraryService
from services.organizer_service import OrganizerService


class TestPartialArchiveSafety(unittest.TestCase):
    """An interrupted conversion used to leave a partial archive wearing its final name.

    Dedupe then preferred that partial file over the intact source - the promotion rule trusts .7z over
    .zip/.rar - and moved the good copy to Archive. Three games lost their archive this way, so these pin
    each of the three guards that now prevent it."""

    def game_folder(self, root, name="Atomic Game", stems=("Atomic.Game.v1",)):
        game = root / "Adventure" / name
        game.mkdir(parents=True)
        (game / ".game-info.json").write_text('{"appid":"606","name":"%s"}' % name)
        return game

    def make_zip(self, game, stem, payload=b"game-content" * 40):
        path = game / f"{stem}.zip"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr(f"{stem}/game/main.exe", payload)
        return path

    def candidate(self, library, path, name="Atomic Game"):

        return RepairArchive(path, "606", name)

    def test_a_partial_build_never_appears_under_the_final_name(self):
        # The whole failure started here: the .rar/.zip -> .7z build wrote straight to "Name.7z", so an
        # interrupted build was indistinguishable from a finished one by name alone.
        observed = []
        original = OrganizerService._run_tool

        def spy(self, args, stage, report, **kw):
            if stage == "compressing" and not observed:
                target = kw.get("cwd") and Path(kw["cwd"]).parent / Path(args[-2]).name
                observed.append(target.exists())
            return original(self, args, stage, report, **kw)

        with TemporaryDirectory() as d:
            root = Path(d)
            game = self.game_folder(root)
            self.make_zip(game, "Atomic.Game.v1")
            OrganizerService._run_tool = spy
            try:
                library = LibraryService(AppLogger(root / "log.log"))
                converted = library.convert_pending_archives(root, OrganizerService(AppLogger(root / "log.log")), JobContext("T"), unlocker=None)
            finally:
                OrganizerService._run_tool = original
            self.assertEqual(converted, 1, "the conversion did not run")
            self.assertEqual(
                observed, [False],
                "the final .7z name existed while the build was still running, so an "
                "interrupted build would look like a complete archive to anything scanning "
                "the folder")

    def test_the_replacement_is_built_outside_the_game_folder(self):
        # The staging folder exists so a game folder being converted holds only its source. Anything reading
        # the folder - dedupe, the catalog, Syncthing, the user in a file browser - then sees an untouched
        # folder instead of one containing a half-written archive competing with the good copy.
        seen = []
        original = OrganizerService._run_tool

        def spy(self, args, stage, report, **kw):
            if stage == "compressing" and not seen:
                processing = root / "Processing"
                seen.append(
                    {
                        # .game-info.json is the folder's own metadata, not something the build adds.
                        "archives": sorted(a.name for a in game.iterdir() if a.is_file() and not a.name.startswith(".")),
                        "processing": processing.is_dir(),
                        "staged": sorted(p.name for p in processing.iterdir()) if processing.is_dir() else [],
                        "extracted": any(p.is_dir() for p in processing.glob("*")) if processing.is_dir() else False,
                    }
                )
            return original(self, args, stage, report, **kw)

        with TemporaryDirectory() as d:
            root = Path(d)
            game = self.game_folder(root, "Stage Game")
            source = self.make_zip(game, "Stage.Game.v1")
            OrganizerService._run_tool = spy
            try:
                converted = LibraryService(AppLogger(root / "log.log")).convert_pending_archives(root, OrganizerService(AppLogger(root / "log.log")), JobContext("T"), unlocker=None)
            finally:
                OrganizerService._run_tool = original
            self.assertEqual(converted, 1)
            self.assertEqual(len(seen), 1, "the compressing stage was never observed")
            state = seen[0]
            self.assertEqual(state["archives"], [source.name], "the game folder held extra files while the replacement was being built")
            self.assertTrue(state["processing"], "no Processing folder was used for staging")
            self.assertEqual(len(state["staged"]), 1, "expected exactly one staging folder for this conversion")
            # The extraction lives in the staging folder too, so the game folder holds nothing of ours at any
            # point: not the multi-GB working set, not the build.
            self.assertTrue(state["extracted"], "the extracted files were written into the game folder")
            self.assertTrue((game / "Stage.Game.v1.7z").is_file(), "the converted archive was not published")

    def test_the_staging_folder_is_reclaimed_after_a_conversion(self):
        # A stranded staging folder holds a full extra copy of the archive, so it is disk the library cannot
        # afford to lose and must not be left behind on the success or the failure path.
        for label, break_it in (("success", False), ("failure", True)):
            with self.subTest(outcome=label), TemporaryDirectory() as d:
                root = Path(d)
                game = self.game_folder(root, "Reclaim Game")
                self.make_zip(game, "Reclaim.Game.v1")
                organizer = OrganizerService(AppLogger(root / "log.log"))
                original = OrganizerService._run_tool
                if break_it:

                    def failing(self, args, stage, report, _original=original, **kw):
                        if stage == "compressing":
                            raise OSError("simulated build failure")
                        return _original(self, args, stage, report, **kw)

                    OrganizerService._run_tool = failing
                try:
                    LibraryService(AppLogger(root / "log.log")).convert_pending_archives(root, organizer, JobContext("T"), unlocker=None)
                finally:
                    OrganizerService._run_tool = original
                processing = root / "Processing"
                leftovers = list(processing.iterdir()) if processing.is_dir() else []
                self.assertEqual(leftovers, [], "a staging folder survived the conversion")

    def test_the_processing_folder_is_removed_once_the_conversion_is_done(self):
        # The folder is the app's own scratch area, so an empty Processing/ left in the library root is litter
        # the user has to notice and delete by hand. It must be gone once the last conversion has finished.
        with TemporaryDirectory() as d:
            root = Path(d)
            game = self.game_folder(root, "Scratch Game")
            self.make_zip(game, "Scratch.Game.v1")
            organizer = OrganizerService(AppLogger(root / "log.log"))
            converted = LibraryService(AppLogger(root / "log.log")).convert_pending_archives(root, organizer, JobContext("T"), unlocker=None)
            self.assertEqual(converted, 1, "the conversion did not run")
            self.assertFalse((root / "Processing").exists(), "the Processing folder was left in the library root")

    def test_the_processing_folder_is_kept_while_a_build_is_still_staged_in_it(self):
        # Removal is rmdir, never rmtree. A staging folder abandoned by a killed run can hold the only copy of a
        # partially built archive, and a second instance of this app can be converting into the same folder right
        # now, so cleanup has to leave those alone and let the next scan reclaim them.
        with TemporaryDirectory() as d:
            root = Path(d)
            staged = root / "Processing" / ".organizer-repack-abandoned"
            staged.mkdir(parents=True)
            (staged / "Some Game v1.7z").write_bytes(b"x" * 100)
            organizer = OrganizerService(AppLogger(root / "log.log"))
            self.assertFalse(organizer.cleanup_processing_dir(root), "cleanup claimed to have removed a staged build")
            self.assertTrue((staged / "Some Game v1.7z").is_file(), "cleanup deleted a staged build")
            (staged / "Some Game v1.7z").unlink()
            staged.rmdir()
            self.assertTrue(organizer.cleanup_processing_dir(root), "cleanup did not remove the emptied folder")
            self.assertFalse((root / "Processing").exists(), "the emptied Processing folder survived")

    def test_the_processing_folder_is_not_treated_as_a_game_category(self):
        # It sits beside the categories, so every scan that walks the library root has to skip it or staged
        # builds show up as games.
        with TemporaryDirectory() as d:
            root = Path(d)
            staged = root / "Processing" / ".organizer-repack-j1"
            staged.mkdir(parents=True)
            (staged / "Some Game v1.7z").write_bytes(b"x" * 100)
            (staged / "Some Game v1.zip").write_bytes(b"y" * 100)
            (staged / "Game.7z").write_bytes(b"z" * 100)
            service = LibraryService(AppLogger(root / "log.log"))
            moved = service.enforce_single_archive(root, OrganizerService(AppLogger(root / "log.log")))
            self.assertEqual(moved, 0, "the Processing folder was scanned as a game category")
            self.assertTrue((staged / "Some Game v1.7z").is_file(), "a staged archive was moved out of staging")
            self.assertTrue((staged / "Some Game v1.zip").is_file(), "a staged archive was moved out of staging")

    def test_a_live_build_is_not_deleted_by_a_concurrent_scan(self):
        # The extraction folder was protected by its lock marker, but the half-built replacement was not: the
        # staleness test only ran on directories, so a scan beside a conversion deleted a build that had been
        # running for hours. The pid is in the file's name, which is all it takes to tell a live build from an
        # abandoned one.
        with TemporaryDirectory() as d:
            root = Path(d)
            game = self.game_folder(root, "Live Build Game")
            live = game / f"Live.Build.v1.organizer-temp.{os.getpid()}.7z"
            live.write_bytes(b"partial build" * 200)
            dead = game / "Dead.Build.v1.organizer-temp.999999.7z"
            dead.write_bytes(b"abandoned build" * 200)
            os.utime(dead, (0, 0))  # old enough that a dead owner really does mean abandoned
            LibraryService(AppLogger(root / "log.log")).cleanup_leftovers(root)
            self.assertTrue(live.is_file(), "a build that is still being written was deleted by a scan")
            self.assertFalse(dead.exists(), "an abandoned build was left behind")
            # Same rule as the extraction folder: a dead pid alone is not enough, because a recycled pid could
            # belong to a build that started seconds ago. The grace window is what separates the two.
            young = game / "Young.Build.v1.organizer-temp.999999.7z"
            young.write_bytes(b"recent" * 100)
            LibraryService(AppLogger(root / "log.log")).cleanup_leftovers(root)
            self.assertTrue(young.is_file(), "a build younger than the grace window was deleted on a dead pid alone")

    def test_a_scan_never_offers_in_flight_work_as_a_game(self):
        # The extraction folder lives inside the game folder, and a game archive can legitimately contain an
        # archive of its own. Offering that nested file - or the half-built replacement - as a game put temp
        # artefacts into the review queue under names of their own, and an Organize press would then file one
        # under a category as if it were a separate game.
        with TemporaryDirectory() as d:
            root = Path(d)
            game = self.game_folder(root, "Nested Game")
            source = self.make_zip(game, "Nested.Game.v1")
            extracting = game / ".organizer-repack-live"
            extracting.mkdir()
            with zipfile.ZipFile(extracting / "Inner Disk.zip", "w") as zf:
                zf.writestr("inner/data.bin", b"y" * 512)
            build = game / f"Nested.Game.v1.organizer-temp.{os.getpid()}.7z"
            build.write_bytes(b"partial" * 100)
            found = ArchiveService(AppLogger(root / "log.log")).discover(root).archives
            self.assertEqual([archive.path for archive in found], [source], "a scan offered the extraction folder contents or the in-flight build as games")

    def test_conversion_still_works_without_a_library_root(self):
        # Callers that cannot name the library root must not be left unable to convert; they stage beside the
        # source under the temp tag, which is the older, still-safe behaviour.
        with TemporaryDirectory() as d:
            root = Path(d)
            game = self.game_folder(root, "No Root Game")
            source = self.make_zip(game, "No.Root.Game.v1")
            organizer = OrganizerService(AppLogger(root / "log.log"))
            after = organizer._repack_with_official_name(self.candidate(None, source))
            self.assertEqual(after.name, "No.Root.Game.v1.7z")
            self.assertTrue(after.is_file(), "the archive was not published")
            self.assertFalse(source.exists(), "the source was not cleaned up")
            self.assertFalse((game / "Processing").exists(), "staging must not appear inside a game folder")

    def test_the_source_survives_if_publishing_the_result_fails(self):
        # The order matters. Unlinking the source first meant a failed replace destroyed the only copy.
        original_replace = os.replace

        def failing(src, dst, *a, **kw):
            raise OSError("simulated publish failure")

        with TemporaryDirectory() as d:
            root = Path(d)
            game = self.game_folder(root)
            source = self.make_zip(game, "Atomic.Game.v1")
            organizer = OrganizerService(AppLogger(root / "log.log"))
            os.replace = failing
            try:
                try:
                    organizer._repack_with_official_name(self.candidate(None, source))
                except OSError:
                    pass
            finally:
                os.replace = original_replace
            self.assertTrue(source.is_file(), "the source archive was destroyed when publishing the result failed")

    def test_dedupe_leaves_a_folder_alone_while_a_conversion_is_running(self):
        # Mid-repack the folder legitimately holds the source and the half-written replacement. Neither is an
        # extra copy, and archiving the source is what pulled a live archive out from under a running build.
        with TemporaryDirectory() as d:
            root = Path(d)
            game = self.game_folder(root, "Busy Game")
            source = game / "Busy.Game.v1.zip"
            source.write_bytes(b"source")
            other = game / "Busy.Game.v1.7z"
            other.write_bytes(b"partial build")
            busy = game / ".organizer-repack-live"
            busy.mkdir()
            (busy / ".organizer-lock").write_text(f"{os.getpid()} {time.time():.0f}\n")
            service = LibraryService(AppLogger(root / "log.log"))
            moved = service.enforce_single_archive(root, OrganizerService(AppLogger(root / "log.log")))
            self.assertEqual(moved, 0, "a folder with a conversion in progress was modified")
            self.assertTrue(source.is_file(), "the in-flight source archive was moved out from under the conversion")
            self.assertTrue(other.is_file(), "the in-flight build was moved")

    def test_dedupe_still_collapses_once_the_conversion_is_dead(self):
        # The guard must not become a permanent exemption, or two archives would sit in a folder forever.
        with TemporaryDirectory() as d:
            root = Path(d)
            game = self.game_folder(root, "Dead Game")
            source = game / "Dead.Game.v1.zip"
            source.write_bytes(b"source" * 100)
            other = game / "Dead.Game.v1.7z"
            other.write_bytes(b"x" * 100)
            stale = game / ".organizer-repack-dead"
            stale.mkdir()
            # A pid that cannot be running, and older than the grace window.
            (stale / ".organizer-lock").write_text(f"{999999999} 1\n")
            service = LibraryService(AppLogger(root / "log.log"))
            moved = service.enforce_single_archive(root, OrganizerService(AppLogger(root / "log.log")))
            self.assertEqual(moved, 1, "a folder abandoned by a dead conversion should still collapse")
            self.assertFalse(source.exists(), "the redundant archive should have been archived")

    def test_nothing_is_archived_when_the_newest_archive_is_an_empty_stub(self):
        # Promoting an empty or missing stub leaves the folder with no usable archive at all, which is how the
        # original bug emptied a game folder. Refusing to archive is the only safe answer.
        with TemporaryDirectory() as d:
            root = Path(d)
            game = self.game_folder(root, "Stub Game")
            source = game / "Stub.Game.v1.zip"
            source.write_bytes(b"real content" * 100)
            # Stamped newer explicitly: the shape an interrupted build leaves behind is the newest file in
            # the folder, and a zero-byte one at that. Left to natural mtimes the two can tie and the test
            # would pass or fail depending on which way the tie broke.
            stub = game / "Stub.Game.v1.7z"
            stub.write_bytes(b"")
            os.utime(stub, (time.time() + 60, time.time() + 60))
            self.assertEqual(
                max([source, stub],
                    key=OrganizerService(AppLogger(root / "log.log"))._path_promotion_key),
                stub,
                "this test only means something if the stub is the one that wins promotion")
            service = LibraryService(AppLogger(root / "log.log"))
            moved = service.enforce_single_archive(root, OrganizerService(AppLogger(root / "log.log")))
            self.assertEqual(moved, 0, "an archive was moved aside on the strength of an empty file")
            self.assertTrue(source.is_file(), "the only usable archive was archived")
