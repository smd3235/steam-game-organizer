"""The library index the catalog already paid for, kept instead of thrown away.

`CatalogService.generate()` walks every game folder and parses every `.game-info.json` on every scan and
again after every organize run, and until the index was added the result went out of scope the moment the
method returned.
These tests pin the retention, the shape of what is retained, and - the one that matters most - that reading
the index costs no further walk of the library. Every one of them is written to be able to fail: each asserts
a value a wrong implementation could not produce, and each was proved by reverting the fix and watching it go
red, with the failure count recorded in the change log below.

Nothing here touches the real library on the D: volume. Every library in this module is a TemporaryDirectory.
"""

import json
import shutil
import unittest

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from core.logger import AppLogger
from services.catalog_service import CatalogService, LibrarySummary


class CountingCatalog(CatalogService):
    """A catalog that counts its own disk access, so "no second walk" is a measurement rather than a claim."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.collects = 0
        self.reads = 0

    def _collect(self, library_root):
        self.collects += 1
        return super()._collect(library_root)

    def _read_game(self, game_dir, category_name, library_root):
        self.reads += 1
        return super()._read_game(game_dir, category_name, library_root)


def game(root, category, name, **metadata):
    """One game folder with a sidecar carrying the fields the index reads."""
    folder = root / category / f"{name} - 2024-01-01"
    folder.mkdir(parents=True)
    payload = {"appid": "1", "name": name, "description": "desc", "release_date": "1 Jan, 2024", "genres": ["Indie", "Simulation"], "developer": "Some Studio"}
    payload.update(metadata)
    (folder / ".game-info.json").write_text(json.dumps(payload), encoding="utf-8")
    return folder


def archive(folder, name, size):
    (folder / name).write_bytes(b"0" * size)
    return size


def service(root, **kwargs):
    return CountingCatalog(AppLogger(root / "x.log"), **kwargs)


@pytest.mark.notkinter
class TestRetention(unittest.TestCase):
    def test_the_walk_generate_already_does_is_kept(self):
        """generate() reads every sidecar today and returns [path]. The dict is now also left on the service.

        Asserted on the retained object rather than on a log line: a log line could be written by something
        that retained nothing, and the whole feature is that this value survives the return.
        """
        with TemporaryDirectory() as d:
            root = Path(d)
            folder = game(root, "Simulation", "Alpha Forge")
            archive(folder, "c.zip", 2048)
            catalog = service(root)
            catalog.generate(root)
            summary = catalog.library_summary()
            self.assertEqual(summary.total_games, 1)
            self.assertEqual(summary.categories, (("Simulation", 1, 2048),))
            self.assertEqual(summary.developer_placement, {})
            self.assertTrue(summary.indexed, "the index is not marked as built after a generate")

    def test_reading_the_index_walks_the_library_again_exactly_zero_more_times(self):
        """The reason this change is worth making at all.

        Before: generate() walks once, drops the dict, and the first read walks a second time - and a screen
        would ask again on every repaint. After: one walk, ever. `_collect` and `_read_game` are counted on
        the service itself, so this measures real disk access instead of an intention to avoid it.
        """
        with TemporaryDirectory() as d:
            root = Path(d)
            for index in range(4):
                archive(game(root, f"Cat{index}", f"Game {index}"), "a.zip", 512)
            catalog = service(root)
            catalog.generate(root)
            self.assertEqual((catalog.collects, catalog.reads), (1, 4), "the fixture did not walk exactly once")
            for _ in range(25):
                catalog.library_summary()
            catalog.library_summary(root)
            self.assertEqual((catalog.collects, catalog.reads), (1, 4), f"the index cost {catalog.collects} walks and {catalog.reads} sidecar reads")

    def test_a_cold_call_builds_once_and_caches(self):
        """Reaching a screen before any catalog pass has run in this process is ordinary, so the first read
        builds it. Answering with an empty index instead would read as "your library has no categories",
        which is the one wrong answer this feature exists to prevent.

        `assertIs` carries the caching claim: a rebuild per call returns equal-but-distinct objects and would
        pass a value comparison alone.
        """
        with TemporaryDirectory() as d:
            root = Path(d)
            archive(game(root, "RPG", "Fell & Sell"), "f.zip", 300)
            catalog = service(root)
            first = catalog.library_summary(root)
            second = catalog.library_summary(root)
            self.assertTrue(first.indexed, "a cold call answered without building anything")
            self.assertEqual(first.total_games, 1)
            self.assertEqual(first.categories, (("RPG", 1, 300),))
            self.assertIs(first, second, "the second read rebuilt the index instead of using the one it had")
            self.assertEqual(catalog.collects, 1, f"{catalog.collects} walks for one build")

    def test_an_empty_library_is_still_a_built_index(self):
        """`built_at == 0.0` means "not looked yet", and that is only honest if a library that was looked at and
        found empty comes back marked as built. Otherwise the two are indistinguishable and a display has to
        guess which one it is looking at."""
        with TemporaryDirectory() as d:
            catalog = service(Path(d))
            summary = catalog.library_summary(Path(d))
            self.assertTrue(summary.indexed)
            self.assertEqual((summary.total_games, summary.categories, summary.genre_placement, summary.developer_placement), (0, (), {}, {}))
            self.assertFalse(LibrarySummary().indexed, "a default summary claims to have been built")

    def test_a_failed_page_write_still_leaves_the_index_behind(self):
        """The render and the write come after the walk, so retention has to happen before them or the one
        pass that did succeed is thrown away by a full disk.

        A directory named `Game Library.html` makes write_text raise OSError on this platform, which is a
        reproducible stand-in for the disk-full case and needs no permission fiddling to arrange.
        """
        with TemporaryDirectory() as d:
            root = Path(d)
            archive(game(root, "Idle", "Loop Miner"), "a.zip", 77)
            (root / CatalogService.CATALOG_NAME).mkdir()
            catalog = service(root)
            self.assertEqual(catalog.generate(root), [], "the write was supposed to fail, so this proves nothing")
            self.assertEqual(catalog.library_summary().categories, (("Idle", 1, 77),))

    def test_regenerating_picks_up_a_game_that_moved_category(self):
        """Organize changes categories and then regenerates the catalog, so the index follows the moves with no
        invalidation call anywhere. Modelled here as the two generate() calls organize makes."""
        with TemporaryDirectory() as d:
            root = Path(d)
            archive(game(root, "Unsorted", "Deep Signal"), "a.zip", 900)
            catalog = service(root)
            catalog.generate(root)
            self.assertEqual(catalog.library_summary().categories, (("Unsorted", 1, 900),))
            (root / "RPG").mkdir()
            shutil.move(str(root / "Unsorted" / "Deep Signal - 2024-01-01"), str(root / "RPG" / "Deep Signal - 2024-01-01"))
            catalog.generate(root)
            self.assertEqual(catalog.library_summary().categories, (("RPG", 1, 900),))

    def test_a_root_that_is_not_a_readable_library_yields_an_empty_summary_not_an_exception(self):
        """The caller is a screen drawing a panel. A folder that was never there, a file where a folder should
        be, and a path that cannot be listed all have to draw something rather than take the screen down.

        Nothing is retained for any of them, so `indexed` is False and the next read tries again: caching the
        failure would report a drive that is not plugged in as a library with no categories, with no way back.
        """
        with TemporaryDirectory() as d:
            root = Path(d)
            catalog = service(root)
            missing = root / "nothing here"
            plain = root / "a file.txt"
            plain.write_text("not a library")
            for label, target in (("missing", missing), ("a file", plain)):
                summary = catalog.library_summary(target)
                self.assertIsInstance(summary, LibrarySummary)
                self.assertFalse(summary.indexed, f"{label} claimed to have been indexed")
                self.assertEqual(summary.total_games, 0)
                self.assertEqual(summary.categories_for_genres(["Indie"]), ())
            self.assertIsNone(catalog._summary, "a failed build was retained as if it had succeeded")

    def test_no_root_and_nothing_retained_is_empty_but_valid(self):
        """Without a root there is nothing to build from, and saying so by raising would be worse than saying
        so by answering. This is the state a screen sees before it has been told where the library is."""
        with TemporaryDirectory() as d:
            summary = service(Path(d)).library_summary()
            self.assertIsInstance(summary, LibrarySummary)
            self.assertFalse(summary.indexed)
            self.assertEqual(summary.total_games, 0)
            self.assertEqual(summary.precedent_for("Bewolba Studios"), ())


class TestShape(unittest.TestCase):
    def _summary(self, build):
        with TemporaryDirectory() as d:
            root = Path(d)
            build(root)
            catalog = service(root)
            catalog.generate(root)
            return catalog.library_summary()

    def test_categories_are_ranked_by_game_count_then_name(self):
        """Both halves of the sort key are asserted, with a deliberate tie: `Zeta` and `Alpha` hold five each,
        and a sort on the count alone leaves them in whatever order the directory walk happened to produce."""

        def build(root):
            for name in ("Delta", "Gamma", "Beta"):
                archive(game(root, name, f"{name} Game"), "a.zip", 10)
            for index in range(5):
                archive(game(root, "Zeta", f"Z {index}"), "a.zip", 10)
            for index in range(5):
                archive(game(root, "Alpha", f"A {index}"), "a.zip", 10)

        summary = self._summary(build)
        self.assertEqual([row[0] for row in summary.categories], ["Alpha", "Zeta", "Beta", "Delta", "Gamma"])
        self.assertEqual(summary.total_games, 13)

    def test_archive_bytes_are_summed_per_category_and_not_invented(self):
        """Exact byte totals, not a rounded human_size: 1024+2048+4096 is 7168, which no plausible wrong
        implementation lands on by accident. The fourth game has no archive and is not in the catalog at
        all - it is the folder left behind when the game was re-categorised, carrying the sidecar and
        the artwork the organizer wrote. It contributes nothing to the bytes and nothing to the count."""

        def build(root):
            archive(game(root, "Simulation", "One"), "a.zip", 1024)
            archive(game(root, "Simulation", "Two"), "b.zip", 2048)
            archive(game(root, "Strategy", "Three"), "c.zip", 4096)
            game(root, "Strategy", "Four")

        summary = self._summary(build)
        self.assertEqual(summary.categories, (("Simulation", 2, 3072), ("Strategy", 1, 4096)))
        self.assertEqual(summary.total_games, 3)

    def test_genre_placement_counts_only_genres_a_game_actually_carries(self):
        """The two games with no genres at all must add no keys, so `Indie` counts two in Simulation and one in
        Strategy rather than five in total."""

        def build(root):
            archive(game(root, "Simulation", "One", genres=["Indie", "Simulation"]), "a.zip", 1)
            archive(game(root, "Simulation", "Two", genres=["Indie"]), "a.zip", 1)
            archive(game(root, "Strategy", "Three", genres=["Indie"]), "a.zip", 1)
            archive(game(root, "Strategy", "Four", genres=[]), "a.zip", 1)
            archive(game(root, "Strategy", "Five", genres=None), "a.zip", 1)

        summary = self._summary(build)
        self.assertEqual(summary.genre_placement, {"Indie": {"Simulation": 2, "Strategy": 1}, "Simulation": {"Simulation": 1}})

    def test_the_genre_helper_ranks_by_most_games_first(self):
        def build(root):
            for index in range(3):
                archive(game(root, "Puzzle", f"P {index}", genres=["Casual"]), "a.zip", 1)
            archive(game(root, "RPG", "R", genres=["Casual", "RPG"]), "a.zip", 1)
            archive(game(root, "Strategy", "S", genres=["RPG"]), "a.zip", 1)

        summary = self._summary(build)
        self.assertEqual(summary.categories_for_genres(["Casual"]), (("Puzzle", 3), ("RPG", 1)))
        self.assertEqual(summary.categories_for_genres(["No Such Genre"]), (), "a genre nobody has is an answer, not an error")
        self.assertEqual(summary.categories_for_genres(["RPG"]), (("RPG", 1), ("Strategy", 1)))
        self.assertEqual(summary.categories_for_genres(["Casual", "RPG"]),
                         (("Puzzle", 3), ("RPG", 2), ("Strategy", 1)),
                         "RPG scores 2 not 1: its one game carries both genres asked about, which is the "
                         "documented sum. A display wanting per-genre numbers reads genre_placement.")
        self.assertEqual(summary.categories_for_genres(None), ())
        self.assertEqual(summary.categories_for_genres(["  rpg  "]), (("RPG", 1), ("Strategy", 1)), "a Steam genre string arrives padded and must still match")

    def test_a_developer_needs_two_games_to_be_a_precedent(self):
        """One game is not a precedent. Asserted both ways on one library: Bewolba is in, Allerton (a single
        game) is not, and the pair that is in is listed under its casefolded key in game-name order."""

        def build(root):
            for name, folder in (("Tower of Babel", "Puzzle"), ("Crying Suns", "Strategy"), ("Stoneshard", "RPG")):
                archive(game(root, folder, name, developer="Bewolba Studios"), "a.zip", 1)
            archive(game(root, "Idle", "Airborne Kingdom", developer="Allerton Apps"), "a.zip", 1)

        summary = self._summary(build)
        self.assertEqual(sorted(summary.developer_placement), ["bewolba studios"], "a single-game developer must not appear, and the key must be casefolded")
        self.assertEqual(summary.precedent_for("Bewolba Studios"),
                         (("Crying Suns", "Strategy"), ("Stoneshard", "RPG"), ("Tower of Babel", "Puzzle")),
                         "listed by game name, not by the order the categories were walked")
        self.assertEqual(summary.precedent_for("  bewolba studios "), summary.precedent_for("BEWOLBA STUDIOS"), "a Steam developer string arrives padded and inconsistently cased")
        for single in ("Allerton Apps", "", "Nobody At All"):
            self.assertEqual(summary.precedent_for(single), (), f"{single!r} produced a precedent")

    def test_a_folder_of_loose_archives_is_not_a_category(self):
        """`Larage Games` on the real library is a directory of .rar/.zip files, not a category of game folders.

        `_collect`'s `if games:` guard is what keeps it out, and the index is built from that dict rather than
        from the directory listing - so a tally that walked the root itself would list a phantom category
        holding zero games while the game count went on quietly ignoring them.
        """
        with TemporaryDirectory() as d:
            root = Path(d)
            archive(game(root, "Simulation", "Alpha Forge"), "a.zip", 100)
            loose = root / "Larage Games"
            loose.mkdir()
            (loose / "Some Pack v1.rar").write_bytes(b"Rar!" + b"0" * 50)
            (loose / "Another Pack.zip").write_bytes(b"PK" + b"0" * 50)
            catalog = service(root)
            catalog.generate(root)
            summary = catalog.library_summary()
            self.assertEqual([row[0] for row in summary.categories], ["Simulation"])
            self.assertEqual(summary.total_games, 1)
            self.assertNotIn("Larage Games", repr(summary))


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
