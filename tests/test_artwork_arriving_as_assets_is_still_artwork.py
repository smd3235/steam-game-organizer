"""Extracted from tests/test_run_reporting.py.

    ArtworkArrivingAsAssetsIsStillArtwork was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import tkinter as tk
import unittest
import shutil
from pathlib import Path
from tempfile import mkdtemp
from core.models import ConversionResult
from core.models import GameArchive
from core.models import ScanResult
from core.models import SteamMatch
from core.state import StateStore
from tests.tk_support import require_tk
from tests.tk_support import close_root


class ArtworkArrivingAsAssetsIsStillArtwork(unittest.TestCase):
    """A game whose artwork arrived as assets rather than as one primary image has to be reported as having artwork.

    Found by running the real pipeline over a real archive - Glow Stick Samurai.7z, the smallest in a 176-archive,
    244 GB library. Steam's API serves this game's pictures as asset URLs (`header_image`, `capsule_image`,
    `background`, ...) and the primary image cache came back empty, so `ArtworkResult.path` was None while
    `ArtworkResult.assets` held five real files. OrganizerService.move() copies every one of them into the game
    folder, so the run had put five images on disk and DoneView reported "0 artwork copied".

    Both screens read only `.path`. A user reading either one concludes artwork failed for a game whose folder is
    full of artwork, which is the outcome that sends someone re-downloading images that are already there.
    """

    def setUp(self):
        require_tk(self)
        self.root = tk.Tk()
        self.addCleanup(close_root, self.root)
        self.assets_dir = Path(mkdtemp())
        self.addCleanup(shutil.rmtree, self.assets_dir, ignore_errors=True)

    def _asset(self, name: str) -> Path:
        path = self.assets_dir / name
        path.write_bytes(b"\xff\xd8\xff\xe0" + b"jpeg-ish")
        return path

    def _game(self, primary=None, assets=None):
        from core.models import ArtworkResult, OrganizationDecision

        return GameArchive(
            path=Path("Games/Idle/Glow Stick Samurai - 2026-09-03/Glow Stick Samurai.7z"),
            display_name="Glow Stick Samurai",
            normalized_title="Glow Stick Samurai",
            identity_key="glowsticksamurai",
            extension=".7z",
            steam=SteamMatch(found=True, appid="999999", name="Glow Stick Samurai"),
            artwork=ArtworkResult(status="ready", path=primary, assets=assets or {}),
            decision=OrganizationDecision(category="Idle", accepted=True),
            conversion=ConversionResult(status="converted"),
        )

    def test_the_done_summary_counts_assets_when_there_is_no_primary_image(self):
        from ui.done_view import DoneView

        view = DoneView(self.root, lambda: None)
        game = self._game(assets={"header_image": self._asset("header_image.jpg")})
        view.show([game])
        self.root.update()
        summary = str(view.summary.cget("text"))
        self.assertIn("1 artwork copied", summary, f"a game with a downloaded asset and no primary image is reported as having no artwork: {summary!r}")

    def test_a_game_with_no_artwork_at_all_is_still_reported_as_having_none(self):
        """The other half. Counting assets must not turn the total into a number that is simply always >= 1."""
        from ui.done_view import DoneView

        view = DoneView(self.root, lambda: None)
        view.show([self._game()])
        self.root.update()
        self.assertIn("0 artwork copied", str(view.summary.cget("text")))

    def test_an_asset_that_is_not_on_disk_is_not_counted(self):
        """OrganizerService only copies assets whose path is a real file, so a path left over from a pruned
        cache would be counted here as artwork the run never wrote."""
        from ui.done_view import DoneView

        view = DoneView(self.root, lambda: None)
        game = self._game(assets={"header_image": self.assets_dir / "gone.jpg"})
        view.show([game])
        self.root.update()
        self.assertIn("0 artwork copied", str(view.summary.cget("text")))

    def test_the_organize_plan_does_not_say_artwork_unavailable_when_assets_are_present(self):
        """The same wrong answer on the screen shown *before* the run, which is where a user decides whether to
        bother running it at all."""
        from ui.organize_view import OrganizeView

        state = StateStore()
        game = self._game(assets={"header_image": self._asset("header_image.jpg")})
        state.update(scan_result=ScanResult(archives=[game]))

        preview = type("P", (), {"preview": staticmethod(lambda archives, root: {})})
        controller = type("C", (), {})()
        controller.services = type("S", (), {"organizer": preview})()
        controller.config = type("Cfg", (), {"library_root": Path("Games"), "sync_to_appdata": lambda self: None})()

        view = OrganizeView(self.root, controller, state, lambda *a: None)
        view.refresh()
        self.root.update()
        text = str(view.list.get("1.0", "end"))
        self.assertIn("artwork included", text, f"the plan calls a game with downloaded artwork 'artwork unavailable': {text!r}")
