"""Tests for the steamgameorganizer:// handler, which the catalog page's free-text destination box feeds.

The destination used to have to be one of the configured extract folders, which made the page a dropdown. A text
box is what was asked for, so these tests pin down what a typed path still has to satisfy - and, just as
importantly, that a typed path cannot be used to write outside the places it should be able to write.
"""

from __future__ import annotations

import tempfile
import unittest

import pytest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

from core.uri_actions import UriRefused, MultiBatchRequest
from core.parse_uri import parse_uri
from core.safe_folder_name import safe_folder_name
from core.parse_multi_uri import parse_multi_uri
from core.parse_open_folder_uri import parse_open_folder_uri

def make_archive(library: Path, name: str = "Some Game.7z") -> Path:
    path = library / name
    path.write_bytes(b"not really an archive")
    return path

def uri_for(archive: Path, dest: str | None = None) -> str:
    link = f"steamgameorganizer://extract?src={quote(str(archive), safe='')}"
    if dest is not None:
        link += f"&dest={quote(dest, safe='')}"
    return link

if __name__ == "__main__":
    unittest.main()
from core.parse_open_extracted_uri import parse_open_extracted_uri

from tests.typed_destination_tests import TypedDestinationTests
# TypedDestinationTests extracted to tests\typed_destination_tests.py — see that module for its definition.
from tests.test_fresh_pc_refusals_point_at_the_setup import FreshPcRefusalsPointAtTheSetup
# FreshPcRefusalsPointAtTheSetup extracted to tests\fresh_pc_refusals_point_at_the_setup.py — see that module for its definition.
from tests.multi_batch_tests import MultiBatchTests
# MultiBatchTests extracted to tests\multi_batch_tests.py — see that module for its definition.
from tests.test_open_folder_uri_tests import OpenFolderUriTests
# OpenFolderUriTests extracted to tests\open_folder_uri_tests.py — see that module for its definition.
from tests.test_open_extracted_uri_tests import OpenExtractedUriTests
# OpenExtractedUriTests extracted to tests\open_extracted_uri_tests.py — see that module for its definition.
from tests.test_play_and_marker_uri_tests import PlayAndMarkerUriTests
# PlayAndMarkerUriTests extracted to tests\play_and_marker_uri_tests.py — see that module for its definition.

