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


if __name__ == "__main__":
    unittest.main()
