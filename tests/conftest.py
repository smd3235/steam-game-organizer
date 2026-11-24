"""Pytest configuration for the Steam Game Organizer test suite.

Isolated GUI tests (marked @pytest.mark.isolated) must never run in the same process
as other tests - Tkinter state on Windows corrupts when multiple tk.Tk() roots are
created and destroyed in sequence. These tests are deselected by default; use
`--run-isolated` to include them (and then run each test file alone).
"""

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-isolated",
        action="store_true",
        default=False,
        help="include @pytest.mark.isolated tests (run each file alone)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-isolated"):
        return
    skip_isolated = pytest.mark.skip(reason="isolated GUI test - run alone with --run-isolated")
    for item in items:
        if item.get_closest_marker("isolated"):
            item.add_marker(skip_isolated)
