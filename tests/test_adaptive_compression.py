"""Extracted from tests/test_services.py.

    TestAdaptiveCompression was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
from core.constants import COMPRESSION_LEVEL
from core.constants import COMPRESSION_THREADS
from tests.test_helpers import GB
from services.organizer_service import OrganizerService


class TestAdaptiveCompression(unittest.TestCase):
    """The compressor must reach for maximum compression only when the machine can sustain it. Level 9
    needs ~2.5 GB of match finder; picking it regardless of headroom is what killed builds on a busy
    Steam Deck session, so both the headroom check and the step-down retry are pinned here."""

    def service(self):
        return OrganizerService.__new__(OrganizerService)

    def test_level_nine_is_used_when_memory_is_plentiful(self):
        service = self.service()
        service._available_ram = lambda: (12 * GB, 8 * GB)
        self.assertEqual(service._choose_compression_level(), 9)

    def test_level_steps_down_until_the_match_finder_fits(self):
        service = self.service()
        # 1.2 GB of RAM cannot hold the 1.4 GB a level 7 build needs, but a level 6 one is a comfortable fit.
        service._available_ram = lambda: (int(1.2 * GB), 8 * GB)
        self.assertEqual(service._choose_compression_level(), 6)

    def test_level_falls_to_the_floor_on_a_hopelessly_busy_machine(self):
        service = self.service()
        service._available_ram = lambda: (200 * 1024 * 1024, 0)
        self.assertGreaterEqual(service._choose_compression_level(), 5)

    def test_exhausted_swap_forces_a_step_down_even_with_free_ram(self):
        # MemAvailable can look healthy while the machine is already swapping hard. A compressor that
        # then asks for another 2.5 GB is what makes the desktop unusable, so swap pressure wins.
        service = self.service()
        service._available_ram = lambda: (12 * GB, 64 * 1024 * 1024)
        self.assertEqual(service._choose_compression_level(), 8)

    def test_unknown_memory_falls_back_to_the_configured_level(self):
        service = self.service()
        service._available_ram = lambda: (None, None)
        self.assertEqual(service._choose_compression_level(), COMPRESSION_LEVEL)

    def test_resource_failures_are_told_apart_from_real_errors(self):
        service = self.service()
        # 7z reports memory death as a bare "Break signaled" with no diagnosis, indistinguishable from a
        # genuine error by exit code, and only the text separates them.
        self.assertTrue(service._looks_like_resource_failure("Break signaled"))
        self.assertTrue(service._looks_like_resource_failure("ERROR: Not enough memory"))
        self.assertTrue(service._looks_like_resource_failure("Cannot allocate memory"))
        self.assertFalse(service._looks_like_resource_failure("Unexpected end of data"))
        self.assertFalse(service._looks_like_resource_failure(""))

    def test_compressor_threads_are_capped(self):
        # Every 7z thread carries its own match finder, so an uncapped thread count multiplies the cost
        # of whatever level was chosen.
        self.assertGreater(COMPRESSION_THREADS, 0)
        self.assertLessEqual(COMPRESSION_THREADS, 4)
