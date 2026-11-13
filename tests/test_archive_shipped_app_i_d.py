"""Extracted from tests/test_services.py.

    TestArchiveShippedAppID was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from unittest.mock import MagicMock
from app.jobs import JobContext
from core.exceptions import CancellationError
from core.logger import AppLogger
from core.models import SteamMatch
from services.extract_service import ExtractService
from services.steam_service import SteamService


class TestArchiveShippedAppID(unittest.TestCase):
    """An archive that states its own AppID answers the question the search engine would be asked.

    Before this, resolving a game meant searching a Steam Store index and scoring whatever came back, and a
    title whose punctuation had been flattened in the filename needed a hand-written alias to come back at all.
    Most releases ship `steam_settings/steam_appid.txt` or an `appmanifest_*.acf`, which is the answer already.
    Built from real archives here, because the reading is done by the real tool.
    """

    def setUp(self):
        # Nothing here needed a scratch folder: the fixtures are built under self.dir, which tearDown removes.
        # It used to be `Path(TemporaryDirectory().name)`, which threw the object away and so had its own
        # finalizer delete the folder the instant setUp returned - one ResourceWarning per test method, for a
        # path nothing ever read.
        self.dir = Path(tempfile.mkdtemp())
        self.service = SteamService(AppLogger(self.dir / "steam.log"))
        self.details = {}

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _zip(self, name, entries):
        """A real archive holding the given files, so the AppID is read by the real tool rather than a stub."""
        tool = ExtractService.find_tool()[0]
        if not tool:
            self.fail("7-Zip is required to build the fixture archive and was not found")
        source = self.dir / "tree" / name
        for relative, content in entries.items():
            item = source / relative
            item.parent.mkdir(parents=True, exist_ok=True)
            item.write_text(content, encoding="utf-8")
        archive = self.dir / name
        proc = subprocess.run([tool, "a", "-tzip", "-bso0", "-bsp0", str(archive), str(source)], stdin=subprocess.DEVNULL, capture_output=True)
        self.assertEqual(proc.returncode, 0, "could not build the fixture archive")
        return archive

    def _stub_details(self, appid, name):
        """Answer appdetails for one AppID out of a table, so the network is never involved.

        The name is passed separately rather than assumed to be the AppID: what appdetails returns is the
        game's *official* name, and that is the string the archive's AppID gets checked against. Answering
        with the AppID itself would make every score a mismatch.
        """
        self.details[appid] = {"name": name, "genres": [{"description": "Simulation"}], "release_date": {"date": "1 Jan, 2024"}}
        self.service._details = lambda wanted, ctx=None: self.details.get(wanted, {})
        return appid

    def test_a_shipped_appid_resolves_the_name_without_a_search(self):
        self._stub_details("55555", "Sir Beats Alot")
        archive = self._zip("Sir Beats Alot.zip", {"Sir Beats Alot/steam_settings/steam_appid.txt": "55555\n"})
        searched = []
        self.service._lookup_store = lambda title, ctx: searched.append(title) or SteamMatch(found=False)
        result = self.service.lookup("Sir Beats Alot", archive_path=archive)
        self.assertTrue(result.found)
        self.assertEqual(result.appid, "55555")
        self.assertEqual(result.name, "Sir Beats Alot")
        self.assertEqual(result.source, "steam_appid")
        self.assertEqual(result.confidence, "High")
        self.assertEqual(searched, [], "the AppID the archive shipped was not used, so a search ran anyway")

    def test_an_appmanifest_declares_the_appid_in_its_own_name(self):
        self._stub_details("66666", "Dancing Pickle")
        archive = self._zip("Dancing Pickle.zip", {"Dancing Pickle/steam_settings/appmanifest_66666.acf": '"AppState"\n{\n\t"appid"\t\t"66666"\n}\n'})
        self.service._lookup_store = lambda title, ctx: SteamMatch(found=False)
        result = self.service.lookup("Dancing Pickle", archive_path=archive)
        self.assertTrue(result.found)
        self.assertEqual(result.appid, "66666")
        self.assertEqual(result.name, "Dancing Pickle")

    def test_an_archive_that_declares_nothing_falls_back_to_searching(self):
        archive = self._zip("Some Game.zip", {"Some Game/readme.txt": "nothing useful here"})
        self.service._lookup_store = lambda title, ctx: SteamMatch(found=False)
        result = self.service.lookup("Some Game", archive_path=archive)
        self.assertFalse(result.found, "an archive with no AppID was still resolved")

    def test_an_archive_naming_several_appids_is_never_guessed_at(self):
        """A pack, or a shared steam_settings, is not one game. Picking one of them would be a coin flip that
        renames the game's folder to whichever title happened to win."""
        archive = self._zip("Pack.zip", {"Pack/steam_settings/appmanifest_1000.acf": '"AppState"{}', "Pack/steam_settings/appmanifest_2000.acf": '"AppState"{}'})
        self._stub_details("1000", "Pack")
        self._stub_details("2000", "Pack")
        self.service._lookup_store = lambda title, ctx: SteamMatch(found=False)
        result = self.service.lookup("Pack", archive_path=archive)
        self.assertFalse(result.found, "an ambiguous archive resolved to one of its AppIDs anyway")

    def test_a_stale_appid_is_rejected_rather_than_renaming_the_folder(self):
        """Some releases carry a copy-pasted AppID. Believing it would file the game under another game's name,
        which is the one outcome worse than not matching at all."""
        self._stub_details("900001", "Beta Voyager")
        archive = self._zip("AlphaForge.zip", {"AlphaForge/steam_settings/steam_appid.txt": "900001\n"})
        self.service._lookup_store = lambda title, ctx: SteamMatch(found=False)
        result = self.service.lookup("Alpha Forge", archive_path=archive)
        self.assertFalse(result.found, "a stale AppID was believed and the folder would have been renamed")

    def test_a_punctuation_different_filename_still_matches_its_own_appid(self):
        """The whole point: this title needed a hand-written alias before, because the search could not see it
        through the flattened punctuation."""
        self._stub_details("3062660", "Gamma Quest")
        archive = self._zip("GammaQuest-Chill-Electronics-Repairs.zip", {"GammaQuest/steam_settings/steam_appid.txt": "3062660\n"})
        self.service._lookup_store = lambda title, ctx: SteamMatch(found=False)
        result = self.service.lookup("Gamma Quest Chill Electronics Repairs", archive_path=archive)
        self.assertTrue(result.found)
        self.assertEqual(result.name, "Gamma Quest")

    def test_a_second_archive_with_the_same_title_is_read_for_its_own_appid(self):
        """The cache is keyed by title, so a title-keyed hit would hand the first archive's AppID to the second.

        An archive that states its own AppID is the authority on which game it is, and two archives can
        flatten onto one title while being different games. Whichever was scanned first would otherwise decide
        the name of the other, and the folder would be renamed to something it is not.
        """
        self._stub_details("200001", "Alpha Forge")
        self._stub_details("200002", "Alpha Forge II")
        first = self._zip("AlphaForge.zip", {"Game/steam_settings/steam_appid.txt": "200001\n"})
        second = self._zip("AlphaForgeII.rar", {"Game/steam_settings/steam_appid.txt": "200002\n"})
        self.service._lookup_store = lambda title, ctx: SteamMatch(found=False)
        one = self.service.lookup("Alpha Forge", archive_path=first)
        two = self.service.lookup("Alpha Forge", archive_path=second)
        self.assertEqual(one.appid, "200001")
        self.assertEqual(two.appid, "200002", "the second archive was given the first archive's AppID")
        self.assertEqual(two.name, "Alpha Forge II")

    def test_an_archive_still_wins_over_a_cached_match_for_its_title(self):
        """The cache is still consulted for an archive that states no AppID, and still never for one that does."""
        self._stub_details("200001", "Alpha Forge")
        archive = self._zip("AlphaForge.zip", {"Game/steam_settings/steam_appid.txt": "200001\n"})
        # A match cached under this title by an earlier scan, for a different game entirely.
        self.service.cache["alphaforge"] = SteamMatch(found=True, appid="999", name="Unrelated")
        self.service._lookup_store = lambda title, ctx: SteamMatch(found=False)
        result = self.service.lookup("Alpha Forge", archive_path=archive)
        self.assertEqual(result.appid, "200001", "a stale cached title entry outranked the archive")
        # With no archive to read, the cache is still what answers - it is the fallback, not the dead path.
        self.assertEqual(self.service.lookup("Alpha Forge").appid, "200001")

    def test_the_scan_hands_the_archive_path_to_the_lookup(self):
        """The AppID is inside the file; a lookup that only receives the title can never see it."""
        import inspect
        from app.controller import AppController

        source = inspect.getsource(AppController.verify_all)
        self.assertIn("archive_path=a.path", source, "verify_all no longer passes the archive, so the shipped AppID is unreachable")

    def test_appmanifest_appid_is_read_from_filename_without_extraction(self):
        """An appmanifest_*.acf names its AppID in its filename; the listing already carries the answer.

        The old code ran `7z e -so` to extract the file content before reading the AppID from the
        filename. For a large solid archive that extraction hangs for minutes while 7z decompresses
        the solid block to the file's offset - the Corsair.Cove case, where the steam_appid.txt is
        buried ~14 GB deep and the call ran for the full 60-second timeout. Since the AppID is in
        the path the listing returned, return it immediately and skip extraction entirely.
        """
        archive = self.dir / "Game.7z"
        archive.write_bytes(b"")
        listing = subprocess.CompletedProcess(args=["7z", "l", "-slt", "--", str(archive)], returncode=0, stdout="Path = Game/steam_settings/appmanifest_444444.acf\n Size = 100\n\n", stderr="")
        with patch.object(subprocess, "run", return_value=listing) as mock_run, patch.object(subprocess, "Popen") as mock_popen:
            result = self.service._appid_in_archive(archive, None)
            self.assertEqual(result, "444444", "the AppID from the appmanifest filename was not returned")
            self.assertEqual(mock_run.call_count, 1, "7z was called for extraction in addition to listing; the appmanifest branch should return from the filename without a second 7z call")
            mock_popen.assert_not_called()

    def test_steam_appid_extraction_is_cancelable(self):
        """A hung 7z extraction must respond to cancellation, not block for the full 60-second timeout.

        Before the fix, `subprocess.run(timeout=60)` blocked the job thread with no checkpoint, so
        closing the window froze until the timeout expired or the process finished. Now the process is
        polled via Popen and ctx.checkpoint() is checked between polls, so a cancel kills the 7z
        process at once instead of making the user wait.
        """
        archive = self.dir / "Game.7z"
        archive.write_bytes(b"")
        listing = subprocess.CompletedProcess(args=["7z", "l", "-slt", "--", str(archive)], returncode=0, stdout="Path = Game/steam_settings/steam_appid.txt\n Size = 7\n\n", stderr="")
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # process never finishes on its own
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.read.return_value = b""
        ctx = JobContext("cancel-test")
        calls = [0]
        original = ctx.checkpoint

        def checkpoint():
            calls[0] += 1
            if calls[0] > 1:
                ctx._cancel.set()
            original()

        ctx.checkpoint = checkpoint
        with patch.object(subprocess, "run", return_value=listing), patch.object(subprocess, "Popen", return_value=mock_proc):
            with self.assertRaises(CancellationError):
                self.service._appid_in_archive(archive, ctx)
        mock_proc.kill.assert_called_once()
