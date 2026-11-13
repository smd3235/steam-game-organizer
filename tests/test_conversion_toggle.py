"""Tests for the conversion toggle (convert_archives).

Extracted from tests/test_services.py to keep each test module focused on one area:
whether archives are converted to 7z during organization, controlled by a live setting.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from subprocess import DEVNULL, run
from unittest.mock import patch

from core.config import AppConfig
from core.logger import AppLogger
from core.models import GameArchive, RepairArchive, SteamMatch
from services.library_service import LibraryService
from services.organizer_service import OrganizerService

GB = 1024**3


class TestConversionToggle(unittest.TestCase):
    """Conversion is the expensive part of a scan - it can run for an hour and needs three times the archive
    size in free disk - so it has to be switchable without switching off the scan. It is on by default,
    because that is the behaviour every existing settings file and every existing user already had."""

    def config(self, **settings):
        with tempfile.TemporaryDirectory() as d:
            return AppConfig(Path(d), settings=dict(settings))

    def test_conversion_is_on_when_no_setting_has_been_saved(self):
        # A settings file written by an earlier version has no convert_archives key at all. Reading it as
        # False would silently stop converting for every existing user on upgrade.
        self.assertTrue(self.config().convert_archives)

    def test_the_toggle_survives_a_restart(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            first = AppConfig(root)
            first.convert_archives = False
            second = AppConfig(root)  # a fresh instance reads the same settings file
            self.assertFalse(second.convert_archives)
            second.convert_archives = True
            self.assertTrue(AppConfig(root).convert_archives)

    def test_an_unmatched_7z_is_not_extracted_only_to_be_thrown_away(self):
        """The expensive half of the conversion ran for archives that could not possibly be rebuilt.

        `_repack_with_official_name` extracts the whole archive because the one thing that can make a
        rebuild worthwhile is renaming the generic content folder inside it to the official Steam name - and
        that rename is guarded by `archive.steam.found`. An archive with no Steam match can never be renamed,
        so for those the extraction was guaranteed to be discarded: a full 7z integrity read, then a full
        multi-GB write of the extracted tree to staging, then `return path` and the staging folder wiped.

        On a library of games the app itself converted and never matched, that is hours of I/O per run for no
        change to any file. It is worse than slow when the volume is short of space: the extraction fails, and
        the game is filed under FAILED - "7z could not extract this archive" - for an archive that was never
        going to be touched.
        """
        from services.extract_service import ExtractService

        if not ExtractService.find_tool()[0]:
            self.fail("7-Zip is required to build the fixture archive and was not found")
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            library = root / "Games"
            game = library / "Adventure" / "Unmatched Game - 2024-01-01"
            game.mkdir(parents=True)
            payload = root / "_payload" / "Unmatched Game v1" / "game"
            payload.mkdir(parents=True)
            (payload / "main.exe").write_bytes(b"binary" * 500)
            source = game / "Unmatched Game v1.7z"
            sevenzip = ExtractService.find_tool()[0]
            built = run(
                [sevenzip, "a", "-t7z", "-bso0", "-bsp0", str(source), str(payload.parent)],
                stdin=DEVNULL,
                capture_output=True,
            )
            self.assertEqual(built.returncode, 0, f"could not build the fixture archive: {built.stderr!r}")
            before = source.stat().st_size
            events = []
            # No AppID, which is what "the scan could not match this game" looks like to this routine.
            service = OrganizerService(AppLogger(root / "log.log"), convert_archives=lambda: True)
            result = service._repack_with_official_name(
                RepairArchive(source, "", "Unmatched Game"), on_progress=events.append, library_root=library
            )
            stages = [event.get("stage") for event in events]
            self.assertNotIn("extracting", stages, f"an archive that cannot be rebuilt was extracted anyway; stages were {stages}")
            self.assertNotIn("compressing", stages, f"an archive that cannot be rebuilt was rebuilt anyway; stages were {stages}")
            self.assertEqual(result, source, "the archive should have been left exactly where it was")
            self.assertEqual(source.stat().st_size, before, "the untouched archive changed size")
            leftovers = [p.name for p in library.rglob(".organizer-*")]
            self.assertEqual(leftovers, [], f"the skipped conversion left staging folders behind: {leftovers}")

    def test_the_skipped_conversion_still_finishes_the_stage_it_started(self):
        """A conversion that decided to do nothing never said so, so the run's progress display never ended.

        `stage='converted'`, `'failed'` and `'skipped'` are the terminal stages the organize view acts on: it
        marks the timeline done and closes the conversion count on those and nothing else. The "already a .7z
        and the folder is named correctly" branch returned without emitting any of them, so the pill stayed on
        EXTRACTING and the feed had no line for that game. On the last game of a run that is a run that
        finishes looking stuck.
        """
        import zipfile

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            library = root / "Games"
            game = library / "Adventure" / "Settled Game - 2024-01-01"
            game.mkdir(parents=True)
            source = game / "Settled Game v1.7z"
            with zipfile.ZipFile(source, "w") as archive:  # contents are never read; only the suffix matters
                archive.writestr("Settled Game v1/game/main.exe", "binary")
            events = []
            service = OrganizerService(AppLogger(root / "log.log"), convert_archives=lambda: True)
            with patch.object(service, "_source_is_intact", return_value=True), patch.object(
                service, "_run_tool", return_value=(0, "")
            ) as run_tool:
                service._repack_with_official_name(
                    RepairArchive(source, "", "Settled Game"), on_progress=events.append, library_root=library
                )
            run_tool.assert_not_called()
            stages = [event.get("stage") for event in events]
            self.assertTrue(stages, "the conversion reported nothing at all")
            self.assertIn(
                stages[-1], ("converted", "failed", "skipped"),
                f"the last stage was {stages[-1]!r}, which the organize view does not treat "
                f"as finished, so the timeline stays on the stage it had reached",
            )

    def test_a_matched_7z_that_needs_no_rename_still_finishes_its_stage(self):
        """The other "nothing to do" branch: Steam matched, but the folder inside is already named right.

        Separate from the test above because that one is settled earlier, before any extraction. This branch is
        only reachable once the archive has been extracted and inspected, which is why removing its report
        alone leaves the other test green - and why this one has to exist for the behaviour to be covered.
        """
        import zipfile

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            library = root / "Games"
            game = library / "Adventure" / "Named Game - 2024-01-01"
            game.mkdir(parents=True)
            source = game / "Named Game v1.7z"
            with zipfile.ZipFile(source, "w") as archive:  # only the suffix is read; extraction is stubbed
                archive.writestr("Named Game/game/main.exe", "binary")
            events = []
            service = OrganizerService(AppLogger(root / "log.log"), convert_archives=lambda: True)
            with patch.object(service, "_source_is_intact", return_value=True), patch.object(
                service, "_extraction_is_short", return_value=False
            ), patch.object(service, "_run_tool", return_value=(0, "")), patch.object(
                service, "_find_generic_content_folder", return_value=None
            ):
                # found=True mirrors the old _RepairArchive behaviour, which derived found=bool(appid);
                # without it _repack_with_official_name short-circuits to "skipped" before extracting.
                result = service._repack_with_official_name(
                    RepairArchive(source, "999", "Named Game", found=True),
                    on_progress=events.append,
                    library_root=library,
                )
            stages = [event.get("stage") for event in events]
            self.assertIn("extracting", stages, "the archive should have been extracted before deciding")
            self.assertEqual(result, source)
            self.assertIn(
                stages[-1], ("converted", "failed", "skipped"),
                f"the last stage was {stages[-1]!r}, which the organize view does not treat "
                f"as finished, so the timeline stays on the stage it had reached",
            )

    def test_organizing_still_moves_the_archive_when_conversion_is_off(self):
        # Turning conversion off must never block organizing a game. The archive lands in its game folder
        # in its original format, which is the whole point of the toggle.
        import zipfile

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            game = root / "Adventure" / "Toggle Game - 2024-01-01"
            game.mkdir(parents=True)
            (game / ".game-info.json").write_text('{"appid":"321","name":"Toggle Game"}')
            source = game / "Toggle Game v1.zip"
            with zipfile.ZipFile(source, "w") as zf:
                zf.writestr("Toggle Game v1/game/main.exe", "binary")
            library = LibraryService(AppLogger(root / "log.log"))
            candidates = library.pending_candidates(root)
            self.assertEqual(len(candidates), 1)
            _game_dir, path, _size, appid, name = candidates[0]
            events = []
            service = OrganizerService(AppLogger(root / "log.log"), convert_archives=False)
            result = service._repack_with_official_name(
                RepairArchive(path, appid, name), on_progress=events.append
            )
            # The service-level toggle covers the repair pass; organizing itself is covered below because
            # move() owns a different code path.
            self.assertEqual(result, path)

    def test_moving_an_archive_with_conversion_off_keeps_its_format(self):
        import zipfile

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            library_root = root / "Games"
            library_root.mkdir()
            source = library_root / "Toggle Game v1.zip"
            with zipfile.ZipFile(source, "w") as zf:
                zf.writestr("Toggle Game v1/game/main.exe", "binary")
            item = GameArchive(source, "Toggle Game", "Toggle Game v1", "togglegame", ".zip")
            item.decision.accepted = True
            item.decision.category = "Adventure"
            item.steam = SteamMatch(found=True, appid="321", name="Toggle Game")
            events = []
            service = OrganizerService(AppLogger(root / "log.log"), convert_archives=False)
            target = service.move(item, library_root, on_progress=events.append)
            self.assertEqual(target.suffix, ".zip", f"the archive was converted anyway: {target.name}")
            self.assertTrue(target.is_file(), "the archive was not moved into its game folder")
            self.assertIn("skipped", [e.get("stage") for e in events], f"the skip was not reported to the user: {[e.get('stage') for e in events]}")
            # And with conversion on, the same move produces a 7z.
            other = library_root / "Other Game v1.zip"
            with zipfile.ZipFile(other, "w") as zf:
                zf.writestr("Other Game v1/game/main.exe", "binary")
            second = GameArchive(other, "Other Game", "Other Game v1", "othergame", ".zip")
            second.decision.accepted = True
            second.decision.category = "Adventure"
            second.steam = SteamMatch(found=True, appid="322", name="Other Game")
            enabled = OrganizerService(AppLogger(root / "log.log"), convert_archives=True)
            self.assertEqual(enabled.move(second, library_root).suffix, ".7z")

    def test_the_service_reads_the_setting_at_the_moment_of_use(self):
        # The service is built once at startup but the control is a live checkbox, so a stale snapshot taken
        # at construction would mean toggling it had no effect until the app was restarted.
        current = [True]
        with tempfile.TemporaryDirectory() as d:
            service = OrganizerService(AppLogger(Path(d) / "l.log"), convert_archives=lambda: current[0])
            self.assertTrue(service.convert_archives)
            current[0] = False
            self.assertFalse(service.convert_archives, "the service kept a stale copy of the setting")
