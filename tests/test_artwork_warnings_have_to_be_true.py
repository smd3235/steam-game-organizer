"""Extracted from tests/test_services.py.

    ArtworkWarningsHaveToBeTrue was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from core.logger import AppLogger


class ArtworkWarningsHaveToBeTrue(unittest.TestCase):
    """A run that obtained artwork must not log that artwork was unavailable.

    download_assets() calls download() for the primary image and only then fetches the per-asset URLs. Those are
    different URL families on different hosts, so a game whose library capsule 404s can still have working asset
    URLs.     A live run of Mystery Archive.7z did exactly that: five images downloaded into the game folder, and one
    WARN reading UNAVAILABLE appid="888888" reason=[all_steam_sources_failed]. It was the only artwork warning in
    the log and it contradicted the run's own result.

    A warning that is wrong is worse than no warning, because it is the thing a person opens the log to find.
    So the honest severity depends on the whole attempt, which is only known after the asset pass - one warning
    for a game that genuinely has no artwork, and silence for one that does.
    """

    ASSETS = {"header_image": "https://cdn.example/header.jpg", "capsule_image": "https://cdn.example/capsule.jpg"}
    PAYLOAD = b"\xff\xd8\xff\xe0" + b"0" * 4000

    def _download(self, root, assets_succeed=True, preferred_url=""):
        """Fetch with the network faked: the asset URLs behave as asked, every other host 404s.

        The primary image is deliberately not among the URLs that succeed, because that is the situation being
        covered - a missing library capsule with working asset URLs behind it.
        """
        from urllib.error import HTTPError
        from services.artwork_service import ArtworkService

        cache = root / "cache"
        log = root / "x.log"
        working = {self.ASSETS["header_image"]} if assets_succeed else set()
        if preferred_url:
            working.add(preferred_url)

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return self.__class__.payload

        _Response.payload = self.PAYLOAD

        def fake_urlopen(request, timeout=None):
            url = getattr(request, "full_url", None) or str(request)
            if url in working:
                return _Response()
            raise HTTPError(url, 404, "Not Found", {}, None)

        with patch("services.artwork_service.urlopen", side_effect=fake_urlopen):
            result = ArtworkService(cache, AppLogger(log)).download_assets("888888", dict(self.ASSETS), preferred_url=preferred_url)
        return result, log.read_text(encoding="utf-8", errors="replace")

    def test_assets_downloaded_while_the_primary_404s_logs_no_warning(self):
        with TemporaryDirectory() as d:
            result, text = self._download(Path(d))
            self.assertTrue(result.assets, "the fixture did not download any asset, so it proves nothing")
            self.assertNotIn("[WARN", text, f"a run that downloaded artwork logged a warning about artwork being unavailable:\n{text}")

    def test_a_game_with_no_artwork_anywhere_is_still_warned_about(self):
        """The other half. Silence has to mean artwork arrived, not that the warning was simply removed."""
        with TemporaryDirectory() as d:
            result, text = self._download(Path(d), assets_succeed=False)
            self.assertFalse(result.assets, "the fixture downloaded an asset, so it is not the no-artwork case")
            self.assertIn("888888", text, "a game with no artwork at all was not recorded in the log")

    def test_a_primary_image_that_downloads_logs_no_warning(self):
        with TemporaryDirectory() as d:
            self._download(Path(d), preferred_url=self.ASSETS["header_image"])
            _, text = self._download(Path(d), preferred_url=self.ASSETS["header_image"])
            self.assertNotIn("[WARN", text, f"the ordinary successful path logged a warning:\n{text}")
