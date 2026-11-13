"""Extracted from tests/test_catalog_status.py.

    TheBannerIsWiredToTheFileThatFeedsIt was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

from services.catalog_status import STATUS_GLOBAL
from tests.test_catalog_status import AStatusFileTestCase
from tests.test_catalog_status import _assert_has
from services.catalog_status import STATUS_NAME


class TheBannerIsWiredToTheFileThatFeedsIt(AStatusFileTestCase):
    """The contract between three places that cannot see each other at runtime.

    The app writes the name, the generator writes the tag that loads it, and the script reads a global off it.
    Nothing connects them at import time, so a rename is silent until somebody opens a browser.
    """

    def setUp(self):
        super().setUp()
        self.text = self._page()

    def test_the_page_has_a_banner_to_fill(self):
        _assert_has(self, self.text, 'id="run-status"', "there is nowhere to show the result of the last run")
        _assert_has(self, self.text, ".run-status{", "the banner has no styling, so it would render as bare text")

    def test_the_page_loads_the_status_file_before_its_own_script(self):
        """Order is the whole mechanism: the data must be on window before the script looks for it.

        A plain object assignment rather than a call into a hook, so the two cannot race - but that only helps
        if this tag comes first.
        """
        tag = f'<script src="{STATUS_NAME}"></script>'
        _assert_has(self, self.text, tag, f"the page never loads {STATUS_NAME}, so no run can reach it")
        self.assertLess(self.text.index(tag), self.text.index("function apply("), "the status file loads after the script that reads it, so the first read sees nothing")

    def test_the_script_reads_the_global_the_status_file_publishes(self):
        _assert_has(self, self.text, f"window.{STATUS_GLOBAL}", "the page does not read the global the status file publishes")

    def test_the_banner_stays_hidden_until_a_run_has_been_reported(self):
        """A freshly scanned library has no run to report, and must not claim otherwise.

        This is the difference between a page that says nothing and one that opens with a confident, false
        summary of a night's extracting.
        """
        element = self.text.split('<div id="run-status"', 1)[1].split(">", 1)[0]
        self.assertIn("hidden", element, "the banner starts visible, empty and unexplained")
        _assert_has(self, self.text, "!run.ran_at", "the banner is not gated on a run having happened, so a fresh catalog reports one")

    def test_a_run_with_failures_is_marked_as_a_warning(self):
        """A green banner over three failures is worse than no banner.

        It reads as the whole run having worked, and the reader has gone to the shelf to look for three games
        that are not there.
        """
        _assert_has(self, self.text, "run-status-warn", "a run with failures is not distinguished from a clean one")
        _assert_has(self, self.text.replace(" ", ""), "run.failed||run.cancelled", "the warning covers neither failures nor a run that was cancelled")

    def test_the_footer_says_a_button_needs_the_handler_installed(self):
        """The one failure a reader cannot diagnose from the page.

        A page cannot detect that a protocol handler was never registered, so an Extract click can do nothing
        at all, silently. The footer is the only place the reader will look.
        """
        _assert_has(self, self.text, "foot-note", "the footer says nothing about the handler")
        _assert_has(self, self.text, "steamgameorganizer://", "the note does not name what has to be registered")
        _assert_has(self, self.text, "Copy folder path", "the note does not say what still works without it")

    def test_the_badges_are_checked_against_the_destination_box_on_load(self):
        """Not only when the box is touched.

        A destination is remembered between visits, so a page reopened with a different one restored would
        show badges decided against the folder it no longer names, and would keep showing them until the
        reader happened to edit the box.
        """
        _assert_has(self, self.text, "syncUnpackedBadges();", "the badges are never re-checked after the page loads")
        _assert_has(self, self.text, "destBox.addEventListener('input',syncUnpackedBadges)", "typing another destination leaves the badges claiming a folder that was never checked")
