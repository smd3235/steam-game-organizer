"""Extracted from tests/test_archive_service.py.

    DiscoveryIncrementalCache was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import time
import unittest
from pathlib import Path
from tests.test_archive_service import _service
from tempfile import TemporaryDirectory


class DiscoveryIncrementalCache(unittest.TestCase):
    """Incremental discovery: _walk_changed_files() skips directories whose mtime matches the cache.

    discover(use_cache=True) loads config/scan-state.json, walks only directories whose mtime changed,
    and saves the updated cache. discover(use_cache=False) always walks everything.
    """

    def _make_library(self, tmp: Path) -> Path:
        library = tmp / "Games"
        (library / "Action" / "Game A").mkdir(parents=True)
        (library / "Action" / "Game A" / "Game A.zip").write_bytes(b"PK\x03\x04" + b"0" * 64)
        (library / "RPG" / "Game C").mkdir(parents=True)
        (library / "RPG" / "Game C" / "Game C.zip").write_bytes(b"PK\x03\x04" + b"0" * 64)
        return library

    def test_walk_changed_files_returns_all_on_empty_cache(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            library = self._make_library(tmp)
            service = _service(tmp)
            files, updated = service._walk_changed_files(library, {})
            names = sorted(f.name for f in files)
            self.assertEqual(names, ["Game A.zip", "Game C.zip"])
            # Every directory walked gets a cache entry: root, Action, Game A, RPG, Game C
            self.assertEqual(len(updated), 5)

    def test_walk_changed_files_skips_all_when_cache_matches(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            library = self._make_library(tmp)
            service = _service(tmp)
            files1, cache1 = service._walk_changed_files(library, {})
            self.assertEqual(len(files1), 2)
            # Same cache, nothing changed: all directory mtimes match, no files returned.
            # updated only contains the root entry (the only directory actually visited).
            files2, cache2 = service._walk_changed_files(library, cache1)
            self.assertEqual(files2, [])
            root_key = str(library.resolve())
            self.assertEqual(cache2, {root_key: cache1[root_key]})

    def test_walk_changed_files_returns_new_category_only(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            library = self._make_library(tmp)
            service = _service(tmp)
            files1, cache1 = service._walk_changed_files(library, {})
            self.assertEqual(len(files1), 2)
            # Add a brand-new top-level category: root's mtime changes, so root is re-walked.
            # Action and RPG match the cache and are skipped; Simulation is new and its files are returned.
            time.sleep(0.01)
            sim = library / "Simulation"
            sim.mkdir()
            (sim / "Game B").mkdir()
            (sim / "Game B" / "Game B.zip").write_bytes(b"PK\x03\x04" + b"0" * 64)
            files2, cache2 = service._walk_changed_files(library, cache1)
            names = sorted(f.name for f in files2)
            self.assertEqual(names, ["Game B.zip"])

    def test_discover_use_cache_false_ignores_cache(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            library = self._make_library(tmp)
            service = _service(tmp)
            # First scan with cache populates scan-state.json
            archives1 = service.discover(library, use_cache=True).archives
            names1 = sorted(a.path.name for a in archives1)
            self.assertEqual(names1, ["Game A.zip", "Game C.zip"])
            # Add a new file deep inside an existing category: root's mtime does NOT change,
            # so use_cache=True would miss it, but use_cache=False walks everything.
            time.sleep(0.01)
            (library / "Action" / "Game D").mkdir(parents=True)
            (library / "Action" / "Game D" / "Game D.zip").write_bytes(b"PK\x03\x04" + b"0" * 64)
            archives2 = service.discover(library, use_cache=False).archives
            names2 = sorted(a.path.name for a in archives2)
            self.assertEqual(names2, ["Game A.zip", "Game C.zip", "Game D.zip"])

    def test_discover_use_cache_true_saves_and_reuses_cache(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            library = self._make_library(tmp)
            service = _service(tmp)
            # First scan finds everything and saves the cache
            archives1 = service.discover(library, use_cache=True).archives
            names1 = sorted(a.path.name for a in archives1)
            self.assertEqual(names1, ["Game A.zip", "Game C.zip"])
            # Second scan on unchanged library: all directory mtimes match, nothing new found.
            # Note: the cache is rewritten with only root's entry (subdirectories are not visited),
            # so the next scan with any root-level change re-walks everything beneath root.
            archives2 = service.discover(library, use_cache=True).archives
            self.assertEqual(archives2, [])
            # Adding a new top-level category changes root's mtime, so everything beneath root is re-walked
            time.sleep(0.01)
            sim = library / "Simulation"
            sim.mkdir()
            (sim / "Game B").mkdir()
            (sim / "Game B" / "Game B.zip").write_bytes(b"PK\x03\x04" + b"0" * 64)
            archives3 = service.discover(library, use_cache=True).archives
            names3 = sorted(a.path.name for a in archives3)
            self.assertEqual(names3, ["Game A.zip", "Game B.zip", "Game C.zip"])
