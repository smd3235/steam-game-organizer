import unittest

import pytest
import json
import re
import shutil
import subprocess
import urllib.parse
import zipfile
from tempfile import TemporaryDirectory
from pathlib import Path
from core.logger import AppLogger
from services.catalog_service import CatalogService, sort_date
from services.banner_art import banner_svg, banner_data_uri
from core.constants import DEFAULT_CATEGORIES

# TestCatalogPresentation extracted to tests\test_catalog_presentation.py — see that module for its definition.
from tests.test_catalog_presentation import TestCatalogPresentation
# TestCatalogService extracted to tests\test_catalog_service.py — see that module for its definition.
from tests.test_catalog_service import TestCatalogService
# TestCatalogFiltering extracted to tests\test_catalog_filtering.py — see that module for its definition.
from tests.test_catalog_filtering import TestCatalogFiltering
# TestCatalogBanners extracted to tests\test_catalog_banners.py — see that module for its definition.
from tests.test_catalog_banners import TestCatalogBanners
# TestSetupButtonAndFallback extracted to tests\test_setup_button_and_fallback.py — see that module for its definition.
from tests.test_setup_button_and_fallback import TestSetupButtonAndFallback
# TestReleaseDateSorting extracted to tests\test_release_date_sorting.py — see that module for its definition.
from tests.test_release_date_sorting import TestReleaseDateSorting
# TestExtractDestinationBox extracted to tests\test_extract_destination_box.py — see that module for its definition.
from tests.test_extract_destination_box import TestExtractDestinationBox
# TestGameFolderBox extracted to tests\test_game_folder_box.py — see that module for its definition.
from tests.test_game_folder_box import TestGameFolderBox
# TestGamesWithoutASteamMatch extracted to tests\test_games_without_a_steam_match.py — see that module for its definition.
from tests.test_games_without_a_steam_match import TestGamesWithoutASteamMatch
def make_game(root, **metadata):
    game = root / "Simulation" / "Alpha Forge - 2024-01-01"
    game.mkdir(parents=True)
    (game / "Alpha Forge.zip").write_text("x")
    for name in ("header_image", "library_hero"):
        (game / f"Alpha Forge_{name}.jpg").write_bytes(b"\xff\xd8\xff\xdb" + b"0" * 2000)
    payload = {"appid": "100001", "name": "Alpha Forge", "description": "desc", "release_date": "1 Jan, 2024", "genres": ["Simulation"]}
    payload.update(metadata)
    (game / ".game-info.json").write_text(json.dumps(payload))
    return game

@pytest.mark.notkinter

def _script_encoded_path(path):
    """The path the page's script would build, mirrored in Python.

    joinPath puts the library-relative folder under whatever is in the game folder box, and encodePath then
    escapes everything that would split the query string while leaving the separators and a Windows drive
    letter alone - which is exactly quote() with those two characters marked safe. No browser runs the suite,
    so this is how a link built in the page is handed to the handler that has to accept it.
    """
    return urllib.parse.quote(str(path), safe="/:")

def _rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))

def _contrast_ratio():
    """Reuse the app's own WCAG implementation so both palettes are judged by one formula."""
    import importlib.util

    path = Path(__file__).with_name("test_contrast.py")
    spec = importlib.util.spec_from_file_location("_app_contrast", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return lambda foreground, background: module.contrast(foreground, background)

if __name__ == "__main__":
    unittest.main()
