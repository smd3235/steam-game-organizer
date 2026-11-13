"""Import-integrity test: every module in core/ and services/ must import cleanly.

This catches breakage from module splits before any behaviour test runs. If a
module fails to import, every test that depends on it fails with an opaque error;
this test reports the failing module by name.

steam_game_organizer is imported first because it is the entry point: importing
it resolves the circular import chain (core.constants <-> core.suggest_category_with_evidence
<-> core.canonical_category and steam_game_organizer <-> core.main <-> core.handle_uri
<-> core.handle_batch_uri) in the correct order, after which every other module
imports cleanly.
"""

import importlib
import unittest
from pathlib import Path

# Imported first to resolve circular import chains. Every other module import
# below relies on it having been loaded.
_ENTRY_POINT = "steam_game_organizer"

# Every source module that must import without raising. Kept as a list so a new
# module added to core/ or services/ is obvious here when it is missing.
_CORE_MODULES = [
    "core.canonical_category",
    "core.category_evidence",
    "core.category_folder",
    "core.config",
    "core.configured_bases",
    "core.connection_pool",
    "core.constants",
    "core.controller_utils",
    "core.catalog_utils",
    "core.destination_parent",
    "core.exceptions",
    "core.handle_batch_uri",
    "core.handle_multi_uri",
    "core.handle_open_folder_uri",
    "core.handle_pick_launcher_uri",
    "core.handle_uri",
    "core.library_summary",
    "core.library_utils",
    "core.logger",
    "core.main",
    "core.models",
    "core.naming_utils",
    "core.organizer_utils",
    "core.parse_batch_uri",
    "core.parse_extract_root_action",
    "core.parse_mark_installed_uri",
    "core.parse_multi_uri",
    "core.parse_open_extracted_uri",
    "core.parse_open_folder_uri",
    "core.parse_pick_launcher_uri",
    "core.parse_play_uri",
    "core.parse_setup_uri",
    "core.parse_uri",
    "core.path_safety",
    "core.prefill",
    "core.safe_folder_name",
    "core.scan_view_utils",
    "core.setup_hint",
    "core.suggest_category_with_evidence",
    "core.state",
    "core.steam_query_utils",
    "core.system_paths",
    "core.typed_destination",
    "core.uri_actions",
    "core.within",
]

_SERVICES_MODULES = [
    "services.archive_service",
    "services.artwork_service",
    "services.banner_art",
    "services.batch_extract_service",
    "services.batch_item",
    "services.catalog_service",
    "services.catalog_status",
    "services.clear_tool_cache",
    "services.discover_game_launchers",
    "services.extract_result",
    "services.extract_service",
    "services.image_shape",
    "services.installer_detect",
    "services.library_service",
    "services.organizer_service",
    "services.plan_batch",
    "services.rollback_service",
    "services.setup_service",
    "services.shape_name",
    "services.sort_date",
    "services.steam_service",
    "services.update_extract_marker",
    "services.write_extract_result",
]


class TestAllModulesImport(unittest.TestCase):
    """Every module in core/ and services/ imports without raising."""

    def test_core_modules_import(self):
        importlib.import_module(_ENTRY_POINT)
        for name in _CORE_MODULES:
            with self.subTest(module=name):
                importlib.import_module(name)

    def test_services_modules_import(self):
        importlib.import_module(_ENTRY_POINT)
        for name in _SERVICES_MODULES:
            with self.subTest(module=name):
                importlib.import_module(name)


class TestProjectModulesListed(unittest.TestCase):
    """The module lists above stay in sync with the actual files on disk."""

    def test_core_list_matches_disk(self):
        core_dir = Path(__file__).resolve().parents[1] / "core"
        on_disk = {
            p.stem for p in core_dir.glob("*.py") if p.name != "__init__.py"
        }
        listed = {name.split(".", 1)[1] for name in _CORE_MODULES}
        missing = on_disk - listed
        self.assertFalse(
            missing,
            f"core/ modules not listed in test_module_imports.py: {sorted(missing)}",
        )

    def test_services_list_matches_disk(self):
        services_dir = Path(__file__).resolve().parents[1] / "services"
        on_disk = {
            p.stem for p in services_dir.glob("*.py") if p.name != "__init__.py"
        }
        listed = {name.split(".", 1)[1] for name in _SERVICES_MODULES}
        missing = on_disk - listed
        self.assertFalse(
            missing,
            f"services/ modules not listed in test_module_imports.py: {sorted(missing)}",
        )


if __name__ == "__main__":
    unittest.main()
