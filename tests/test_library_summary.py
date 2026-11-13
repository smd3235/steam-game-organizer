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
from core.library_summary import LibrarySummary
from services.catalog_service import CatalogService

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

# TestRetention extracted to tests\test_retention.py — see that module for its definition.
# Imported after archive and service are defined because test_retention imports them from here,
# which would otherwise be a circular import.
from tests.test_retention import TestRetention
# TestShape extracted to tests\test_shape.py — see that module for its definition.
from tests.test_shape import TestShape
# TestUndoInvalidation extracted to tests\test_undo_invalidation.py — see that module for its definition.
from tests.test_undo_invalidation import TestUndoInvalidation

