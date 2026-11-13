"""Tests for artwork image shape detection.

Extracted from tests/test_services.py to keep each test module focused on one area:
reading image shape from the file itself rather than shelling out to ffprobe.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.logger import AppLogger
from core.models import ArtworkResult
from services.artwork_service import ArtworkService, image_shape, shape_name


class TestArtworkImageShape(unittest.TestCase):
    """Artwork shape used to be read by shelling out to ffprobe, and a missing ffprobe came back as "wide" - the
    same answer as a genuinely wrong-shaped image. Every caller deletes what it is told is the wrong shape, so on a
    machine with no ffmpeg (any PC) the cache emptied itself at startup and every portrait download was deleted the
    moment it landed. The Deck has ffmpeg, which is why the same library had pictures there and not here. These pin
    the two halves of the fix: the shape is read from the file itself, and an unreadable file is never deleted."""

    def _jpeg(self, width, height):
        """A minimal JPEG carrying just enough structure for the frame header to be found."""
        return (b"\xff\xd8" + b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
                + b"\xff\xc0\x00\x10\x08" + height.to_bytes(2, "big") + width.to_bytes(2, "big")
                + b"\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01" + b"\xff\xd9")

    def test_the_shape_is_read_out_of_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            portrait = root / "portrait.jpg"
            portrait.write_bytes(self._jpeg(600, 900))
            wide = root / "wide.jpg"
            wide.write_bytes(self._jpeg(460, 215))
            self.assertIs(image_shape(portrait), True)
            self.assertIs(image_shape(wide), False)
            self.assertEqual([shape_name(image_shape(p)) for p in (portrait, wide)], ["portrait", "wide"])

    def test_an_unreadable_file_is_unknown_rather_than_wide(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            truncated = root / "truncated.jpg"
            truncated.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00truncated")
            empty = root / "empty.jpg"
            empty.write_bytes(b"")
            self.assertIsNone(image_shape(truncated))
            self.assertIsNone(image_shape(empty))
            self.assertIsNone(image_shape(root / "never-written.jpg"))
            self.assertEqual(shape_name(None), "unknown")

    def test_a_portrait_cache_file_survives_startup_and_a_download(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cache = root / "cache"
            service = ArtworkService(cache, AppLogger(root / "first.log"))
            keep = service.cached_path("123", steam=True)
            keep.parent.mkdir(parents=True, exist_ok=True)
            keep.write_bytes(self._jpeg(600, 900))
            # A second service is exactly what a second run of the app does: the startup sweep must leave this alone.
            ArtworkService(cache, AppLogger(root / "second.log"))
            self.assertTrue(keep.exists(), "a portrait primary was deleted as wrongly shaped")
            # And download() re-checks the same file before it will use it.
            ArtworkService(cache, AppLogger(root / "third.log")).download("123")
            self.assertTrue(keep.exists(), "download() deleted a portrait primary as wrongly shaped")

    def test_a_file_that_cannot_be_classified_is_kept(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cache = root / "cache"
            service = ArtworkService(cache, AppLogger(root / "first.log"))
            unreadable = service.cached_path("456", steam=True)
            unreadable.parent.mkdir(parents=True, exist_ok=True)
            unreadable.write_bytes(b"not a jpeg at all")
            ArtworkService(cache, AppLogger(root / "second.log"))
            self.assertTrue(unreadable.exists(), "an unreadable cache file was deleted instead of looked at again")

    def test_lookup_falls_back_to_a_game_folder_when_cache_is_empty(self):
        # The cache is pruned after max_age_days; a re-scan with downloads off must still find
        # artwork the organizer copied into the game folder as <prefix>_grid.jpg.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cache = root / "cache"
            game_dir = root / "games" / "Some Game - 2026-10-13"
            game_dir.mkdir(parents=True)
            # A minimal valid JPEG (portrait-shaped) so image_shape() passes the 1024-byte and
            # shape checks in lookup()'s game-folder fallback.
            grid = game_dir / "Some Game_grid.jpg"
            grid.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xc0\x00\x10\x08\x00\x01\x00\x10\x01\x00" + b"\x00" * 2048 + b"\xff\xd9")
            service = ArtworkService(cache, AppLogger(root / "artwork.log"))
            result = service.lookup("9999999", game_dir=game_dir)
            self.assertTrue(result.present(), "game-folder artwork was not found when cache was empty")
            empty_dir = root / "games" / "Empty Game"
            empty_dir.mkdir()
            result_empty = service.lookup("8888888", game_dir=empty_dir)
            self.assertFalse(result_empty.present(), "artwork was fabricated for a game with no files")
