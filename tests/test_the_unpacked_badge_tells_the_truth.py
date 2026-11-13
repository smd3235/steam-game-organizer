"""Extracted from tests/test_catalog_status.py.

    TheUnpackedBadgeTellsTheTruth was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

from pathlib import Path
from unittest import mock
from services import batch_extract_service
from services import catalog_service
from tests.test_catalog_status import AStatusFileTestCase
from tests.test_catalog_status import _unpacked_card
from services.catalog_status import already_extracted


class TheUnpackedBadgeTellsTheTruth(AStatusFileTestCase):
    def test_a_game_already_unpacked_is_marked(self):
        self._unpack("Loop Miner", self.dest)
        self.assertEqual(_unpacked_card(self._page()), 1, "a game already unpacked into the default destination is not marked, so Extract all reads as work that has not been done")

    def test_a_game_that_is_not_unpacked_is_not_marked(self):
        self.assertEqual(_unpacked_card(self._page()), 0, "a game with nothing unpacked is marked as done, which is the one claim this badge must never make")

    def test_an_empty_folder_is_not_treated_as_unpacked(self):
        """The planner's own rule, and for the same reason.

        An interrupted run leaves the folder behind. Calling that finished would mean Extract all silently
        skips the one game the reader most wants finished - and a badge that agreed with it would make the bug
        look like the page working.
        """
        (self.dest / "Loop Miner").mkdir()
        self.assertEqual(_unpacked_card(self._page()), 0, "an empty folder was read as an unpacked game")

    def test_a_game_unpacked_somewhere_else_is_not_marked(self):
        """The page cannot look at any folder but the one it was written against.

        It has no way to check a second destination, so it must not claim to. The badge's title names the
        folder it means, which is what stops a reader who extracted elsewhere from being misled.
        """
        self._unpack("Loop Miner", self.base / "Somewhere Else")
        self.assertEqual(_unpacked_card(self._page()), 0, "a game unpacked into a folder the page never checked is marked as unpacked")

    def test_a_game_unpacked_as_an_installer_is_marked_needs_install(self):
        """An installer repack unpacked to the default destination is unpacked but not ready.

        It must not get the green "Unpacked" mark - that reads as "playable" - so it earns its own amber badge
        and the green one is withheld.
        """
        self._unpack_installer("Loop Miner", self.dest)
        page = self._page()
        self.assertEqual(_unpacked_card(page), 0, "an installer layout was given the green Unpacked badge: " + "the two states cannot be read as the same thing")
        self.assertEqual(page.count('class="badge badge-warn"'), 1, "no 'Needs install' badge was drawn for an installer folder")
        self.assertIn("Needs install", page, "the badge text does not say what is still owed")

    def test_a_ready_game_keeps_the_unpacked_badge_in_front_of_the_installer_one(self):
        """A game that is genuinely unpacked and ready must still read green, not be downgraded to amber."""
        self._unpack("Loop Miner", self.dest)
        self.assertEqual(_unpacked_card(self._page()), 1, "a ready-to-play unpacked game was not marked unpacked")

    def test_two_cards_sharing_one_archive_name_are_neither_marked(self):
        """Two games can hold identically named archives, and the batch suffixes the second folder.

        The page cannot know which of the two would own the unsuffixed folder, so it has to say nothing.
        Marking both would claim two games are done when one folder exists, and marking one would be a coin
        flip that is wrong half the time.
        """
        for folder in ("Twin A", "Twin B"):
            where = self.root / "RPG" / f"{folder} - 2024-01-01"
            where.mkdir(parents=True)
            (where / "Shared Title.zip").write_bytes(b"x")
            (where / ".game-info.json").write_text('{"appid":"1","name":"Shared Title","genres":["Idle"]}', encoding="utf-8")
        self._unpack("Shared Title", self.dest)
        self.assertEqual(_unpacked_card(self._page()), 0, "one of two cards sharing an archive name was marked, and the page cannot know which")

    def test_the_badge_uses_the_planners_own_predicate(self):
        """One rule, one definition.

        Two implementations of "already unpacked" would agree right up until they did not, and the page would
        be the one that is wrong: it is generated from a snapshot, while the planner decides at the moment of
        the click. Asserting the identity is what stops a second copy being introduced later.
        """
        self.assertIs(catalog_service.already_extracted, batch_extract_service.already_extracted, "the catalog and the batch planner no longer share one definition of 'already unpacked'")
        self.assertIs(batch_extract_service.already_extracted, already_extracted, "the batch planner grew a second copy of the predicate")

    def test_a_destination_that_cannot_be_read_is_not_an_unpacked_game(self):
        """An unreadable folder must answer 'not unpacked' rather than raise out of a generator.

        Patched rather than provoked with permissions, because on Windows the owner can read a directory
        whatever its mode says - which would leave this test passing without ever reaching the handler.
        """
        self._unpack("Loop Miner", self.dest)
        with mock.patch.object(Path, "iterdir", side_effect=OSError("access denied")):
            self.assertFalse(already_extracted(self.dest / "Loop Miner"), "an unreadable destination was reported as an unpacked game")
        self.assertEqual(_unpacked_card(self._page()), 1, "the page disagrees with the planner when reading fails")
