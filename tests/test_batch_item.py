"""Tests for services.batch_item.BatchItem: one game in the extract queue.

BatchItem tracks one game through the batch extract pipeline: its archive,
destination, current state, and progress counters. It is a plain class (not a
dataclass), so attributes are set after construction.
"""

import unittest
from pathlib import Path

from services.batch_extract_service import CANCELLED, DONE, FAILED, QUEUED, SKIPPED
from services.batch_item import BatchItem


class TestBatchItemDefaults(unittest.TestCase):
    """A fresh BatchItem starts QUEUED with zeroed counters."""

    def test_default_state_is_queued(self):
        item = BatchItem()
        item.archive = Path("a.7z")
        item.destination = Path("out")
        self.assertEqual(item.state, QUEUED)

    def test_default_counters_are_zero(self):
        item = BatchItem()
        item.archive = Path("a.7z")
        item.destination = Path("out")
        self.assertEqual(item.percent, 0)
        self.assertEqual(item.written, 0)
        self.assertEqual(item.files, 0)
        self.assertEqual(item.size, 0)

    def test_default_name_and_detail_are_empty(self):
        item = BatchItem()
        item.archive = Path("a.7z")
        item.destination = Path("out")
        self.assertEqual(item.name, "")
        self.assertEqual(item.detail, "")


class TestBatchItemFinishedProperty(unittest.TestCase):
    """finished is True only when the item has reached a terminal state."""

    def _item(self, state):
        item = BatchItem()
        item.archive = Path("a.7z")
        item.destination = Path("out")
        item.state = state
        return item

    def test_queued_is_not_finished(self):
        self.assertFalse(self._item(QUEUED).finished)

    def test_done_is_finished(self):
        self.assertTrue(self._item(DONE).finished)

    def test_failed_is_finished(self):
        self.assertTrue(self._item(FAILED).finished)

    def test_skipped_is_finished(self):
        self.assertTrue(self._item(SKIPPED).finished)

    def test_cancelled_is_finished(self):
        self.assertTrue(self._item(CANCELLED).finished)


if __name__ == "__main__":
    unittest.main()
