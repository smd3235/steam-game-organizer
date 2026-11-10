"""Test package initialization — isolates test logging from real app logs.

Any `AppConfig` created during a test run writes to
`STEAM_GAME_ORGANIZER_TEST_LOG` instead of the real `logs/` directory, so a test
run never pollutes the user's log history and real runs are easy to tell apart.

Test logs live under `<project root>/logs/test/` with a timestamped name
(`organizer-<VERSION>-TEST-<YYYYMMDD>-<HHMMSS>.log`), so they are documented
alongside real logs but never confused with them. The env var is set with
`setdefault` so a caller who explicitly exports it keeps control.
"""
import os
from datetime import datetime, timezone
from pathlib import Path

# This file lives at <project root>/tests/__init__.py, so parents[1] is the
# project root even when the suite is run from a copy or a checkout.
_project_root = Path(__file__).resolve().parents[1]
_test_dir = _project_root / "logs" / "test"
_test_dir.mkdir(parents=True, exist_ok=True)

stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
_test_log = str(_test_dir / f"organizer-9.33-TEST-{stamp}.log")
os.environ.setdefault("STEAM_GAME_ORGANIZER_TEST_LOG", _test_log)
