"""Extracted from tests/test_catalog_library.py.

    TestExtractDestinationBox was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
import pytest
import re
import urllib.parse
from tempfile import TemporaryDirectory
from pathlib import Path
from core.logger import AppLogger
from tests.test_catalog_library import make_game
from services.catalog_service import CatalogService


class TestExtractDestinationBox(unittest.TestCase):
    """The destination is a free-text box, not a dropdown.

    There is no browser on the test machine, so instead of driving the script these pin the contract the script
    and the handler share: the box exists, the configured folders are suggestions rather than the only choices,
    and the link shape the script builds is one the handler actually accepts.
    """

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        make_game(self.root)
        self.folders = [self.root / "extract one", self.root / "extract two"]
        for folder in self.folders:
            folder.mkdir()
        service = CatalogService(AppLogger(self.root / "x.log"), extract_folders=self.folders)
        self.text = service.generate(self.root)[0].read_text()

    def test_the_destination_is_a_text_box(self):
        self.assertIn('id="extract-dest" type="text"', self.text)
        self.assertNotIn('<select id="extract-dest"', self.text)

    def test_the_box_starts_on_the_first_configured_folder(self):
        box = re.search(r'id="extract-dest"[^>]*value="([^"]*)"', self.text)
        self.assertIsNotNone(box, "the box must come pre-filled so a click works with no typing")
        self.assertEqual(box.group(1), str(self.folders[0]))

    def test_configured_folders_are_offered_as_suggestions(self):
        """A datalist, so they are one click away without being the only thing that can be typed."""
        self.assertIn('list="dest-choices"', self.text)
        choices = re.search(r'<datalist id="dest-choices">(.*?)</datalist>', self.text, re.S)
        self.assertIsNotNone(choices)
        for folder in self.folders:
            self.assertIn(f'value="{folder}"', choices.group(1))

    def test_the_choice_is_remembered_between_opens(self):
        self.assertIn("store('catalog-dest'", self.text)
        self.assertIn("savedDest=store('catalog-dest')", self.text)
        self.assertIn("if(savedDest) destBox.value=savedDest", self.text)

    def test_every_extract_link_carries_a_rewriteable_base(self):
        """data-extract holds the src-only link the script appends to.

        The script rebuilds each href from this attribute on every keystroke, so it has to stay the pristine
        base - if the script wrote its own output back here the destination would accumulate across typing.
        """
        bases = re.findall(r'data-extract="([^"]*)"', self.text)
        self.assertTrue(bases, "the page produced no extract links at all")
        for base in bases:
            self.assertIn("src=", base)
            self.assertNotIn("dest=", base)

    def test_the_link_the_script_builds_is_accepted_by_the_handler(self):
        """Closes the loop the markup test cannot: build the URL the script would, hand it to the handler.

        The script's only job here is string building, so if the shape it produces parses and lands where the
        user typed, the two halves agree even though no browser ran.
        """
        from urllib.parse import parse_qs, urlsplit

        typed = str(self.root / "a folder with spaces")
        base = re.findall(r'data-extract="([^"]*)"', self.text)[0].replace("&amp;", "&")
        link = base + "&dest=" + typed.replace(" ", "%20")
        query = parse_qs(urlsplit(link).query)
        self.assertEqual(query["dest"], [typed])
        archive = Path(query["src"][0])
        self.assertTrue(archive.is_file(), f"the page built a link to a file that is not there: {archive}")

    def test_a_path_typed_into_the_box_survives_being_written_into_a_url(self):
        """The whole reason the box is text: a folder with spaces and an ampersand in it still works."""
        from urllib.parse import parse_qs, urlsplit

        awkward = "/data/RPG & Co/extracted games"
        encoded = urllib.parse.quote(awkward, safe="")
        query = parse_qs(urlsplit(f"steamgameorganizer://extract?src=%2Flib%2Fa.7z&dest={encoded}").query)
        self.assertEqual(query["dest"], [awkward], "an ampersand in a typed folder split the query")
