"""Extracted from tests/test_catalog_library.py.

    TestReleaseDateSorting was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
import pytest
import json
import re
from tempfile import TemporaryDirectory
from pathlib import Path
from core.logger import AppLogger
from services.catalog_service import CatalogService
from tests.test_catalog_library import make_game
from services.catalog_service import sort_date


class TestReleaseDateSorting(unittest.TestCase):
    """Newest is meant to be newest release date, not newest added to the library.

    It was neither. The sort key came from stripping the non-digits off the date and taking the first four
    characters, so "Jun 24, 2026" became "6242" - the day - and the comparator was ascending, putting the
    oldest game first under a button labelled Newest.
    """

    def test_a_us_date_becomes_a_sortable_key(self):
        self.assertEqual(sort_date("Jun 24, 2026"), "20260624")

    def test_a_day_first_date_becomes_the_same_key_as_its_month_first_twin(self):
        self.assertEqual(sort_date("1 Jan, 2024"), sort_date("Jan 1, 2024"))

    def test_a_single_digit_day_is_padded_so_it_still_sorts(self):
        self.assertEqual(sort_date("May 5, 2026"), "20260505")
        self.assertLess(sort_date("May 5, 2026"), sort_date("May 6, 2026"))

    def test_the_day_is_not_mistaken_for_the_year(self):
        """The original bug, stated as a test: 24 comes first in the digits, not 2026."""
        self.assertTrue(sort_date("Jun 24, 2026").startswith("2026"))
        self.assertNotIn("24", sort_date("Jun 24, 2026")[:4])

    def test_a_year_only_date_lands_in_that_year(self):
        self.assertEqual(sort_date("2020"), "20200000")
        self.assertEqual(sort_date("Dec 2019"), "20191200")

    def test_a_missing_or_unreadable_date_sorts_last(self):
        self.assertEqual(sort_date(""), "00000000")
        self.assertEqual(sort_date(None), "00000000")
        self.assertEqual(sort_date("Unknown release date"), "00000000")

    def test_keys_sort_in_calendar_order(self):
        keys = [sort_date(d) for d in ("Jan 1, 2020", "Dec 31, 2020", "Feb 3, 2021", "Mar 15, 2019")]
        self.assertEqual(sorted(keys), ["20190315", "20200101", "20201231", "20210203"])

    def test_the_card_carries_the_parsed_date_not_the_raw_text(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            make_game(root, release_date="Jun 24, 2026")
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
        card = re.search(r'<article class="card"[^>]*>', text).group(0)
        self.assertIn('data-date="20260624"', card)
        self.assertNotIn("data-year", card)

    def test_the_year_banner_reports_a_real_range(self):
        """The same broken parser fed the year-range in the tagline, so it never rendered at all."""
        with TemporaryDirectory() as d:
            root = Path(d)
            make_game(root, release_date="Jun 24, 2019")
            # make_game always writes to one fixed folder, so a second game needs its own directory.
            other = root / "Simulation" / "Other Game - 2026-03-02"
            other.mkdir(parents=True)
            (other / "Other Game.zip").write_text("x")
            (other / ".game-info.json").write_text(json.dumps({"appid": "1", "name": "Other Game", "description": "d", "release_date": "Mar 2, 2026", "genres": ["Action"]}))
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
        self.assertIn("2019", text)
        self.assertIn("2026", text)

    def test_newest_and_largest_are_marked_descending(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            make_game(root)
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
        newest = re.search(r'<button[^>]*data-sort="date"[^>]*>', text).group(0)
        largest = re.search(r'<button[^>]*data-sort="size"[^>]*>', text).group(0)
        name = re.search(r'<button[^>]*data-sort="name"[^>]*>', text).group(0)
        self.assertIn('data-desc="1"', newest, "Newest sorted oldest first")
        self.assertIn('data-desc="1"', largest)
        self.assertNotIn("data-desc", name, "Name should stay alphabetical")

    def test_the_comparator_honours_the_descending_flag(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            make_game(root)
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
        self.assertIn("getAttribute('data-desc')==='1'", text, "the buttons must actually drive the comparator")
        self.assertIn("descending?-1:1", text)
