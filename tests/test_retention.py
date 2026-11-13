"""Extracted from tests/test_library_summary.py.

    TestRetention was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import shutil
import unittest
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from core.library_summary import LibrarySummary
from tests.test_helpers import archive
from tests.test_helpers import game
from tests.test_helpers import service
from services.catalog_service import CatalogService


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
            archive(game(root, "RPG", "Trampoline Tornado"), "f.zip", 300)
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
