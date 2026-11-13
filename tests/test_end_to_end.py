"""End to end: a real library, real discovery, a real conversion, real moves.

Nothing here about the archive toolchain is stubbed - the thing worth testing is exactly what a stub cannot
show: that a conversion does not lose data, that the source is only ever removed once a verified replacement
exists, and that the numbers the run reports are the numbers on disk.

The fixture is built, not borrowed. An earlier version of this module used a real game from a real library,
which meant the whole suite skipped itself on every machine that did not have that one file on that one drive.
That is not a small gap: these are the tests that found 9.16's directory-counting and packed-lock-marker
defects, and they had been reported as passing while not running at all. A release-shaped tree built from a
seeded generator exercises the same paths on any machine, and the nesting is the part that matters - a flat
fixture cannot show a manifest that counts directories as files.

Conversion is expensive relative to a unit test, so each class performs one real run and the assertions then
read that one outcome rather than repeating the work.
"""

from __future__ import annotations

import unittest

# Shared fixtures live in tests\test_helpers.py to break circular imports between this module and the
# extracted end-to-end test modules that used to import build_game_tree / manifest / package_zip /
# package_seven_zip / run_organize / seven_zip from here.
from tests.test_helpers import build_game_tree
from tests.test_helpers import manifest
from tests.test_helpers import package_zip
from tests.test_helpers import package_seven_zip
from tests.test_helpers import run_organize
from tests.test_helpers import seven_zip

# ZipSourceConvertsToSevenZip extracted to tests\zip_source_converts_to_seven_zip.py — see that module for its definition.
from tests.test_zip_source_converts_to_seven_zip import ZipSourceConvertsToSevenZip
# SevenZipSourceIsRepackedAfterRenaming extracted to tests\seven_zip_source_is_repacked_after_renaming.py — see that module for its definition.
from tests.test_seven_zip_source_is_repacked_after_renaming import SevenZipSourceIsRepackedAfterRenaming
# CorruptSourceIsRefused extracted to tests\corrupt_source_is_refused.py — see that module for its definition.
from tests.test_corrupt_source_is_refused import CorruptSourceIsRefused


if __name__ == "__main__":
    unittest.main()

