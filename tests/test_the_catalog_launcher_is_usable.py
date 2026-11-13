"""Extracted from tests/test_ui_regressions.py.

    TestTheCatalogLauncherIsUsable was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import os
import shutil
import tempfile
import unittest
from core.logger import AppLogger
from services.catalog_service import CatalogService
from services.organizer_service import OrganizerService


class TestTheCatalogLauncherIsUsable(unittest.TestCase):
    """A launcher beside the catalog must be a file this machine can actually open.

    Found in the real library rather than reasoned about. `Open Game Library.desktop` was sitting in the library
    root on this PC, containing:

        Exec=google-chrome --new-tab file:///D:/Game%20Installers/...

    and it was dead twice over. Windows has no association for `.desktop`, so double-clicking it opened nothing;
    and `google-chrome` does not exist here (`shutil.which` returns None), because `chrome_command()` returned a
    hardcoded string whenever no browser was found rather than admitting it had none.

    It was written at all because `html_handler()` only ever read the Linux XDG mimeapps.list, which cannot exist
    on this platform - so it always answered "nothing here opens HTML", on a machine where `HKCR\\.html` says
    `htmlfile` and double-clicking the catalog works perfectly well. A launcher is only needed when the machine
    genuinely has no handler, and this one did not know how to tell.

    The suite passed throughout: the one test covering this passed an explicit `/usr/bin/chrome` command and then
    only asserted that the file had been created, which is the one thing that was never the problem.
    """

    def test_a_launcher_file_carries_a_url_and_no_command_at_all(self):
        """The command is not merely unused now - it never could have been used.

        A .url with a `URL=` line and nothing else is resolved by the shell association, so the catalog's launcher
        never had a way to honour a browser command even when it was handed one.       The machinery that searched for
        one is gone; this asserts the file cannot reintroduce the idea.
        """
        from pathlib import Path as _Path

        root = _Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        catalog = CatalogService(AppLogger(root / "x.log"))
        catalog._write_chrome_launcher(root, root / "Game Library.html")
        text = (root / "Open Game Library.url").read_text()
        self.assertNotIn("Exec=", text, "the launcher names a program again, which the format cannot act on")

    def test_no_launcher_is_written_when_the_machine_already_opens_html(self):
        from pathlib import Path as _Path
        from tests.test_ui_regressions import _tmp_dir

        service = OrganizerService(AppLogger(_Path(_tmp_dir(self)) / "x.log"))
        # The real registry, not a mock: the whole defect was that this question was answered from a file that does
        # not exist here rather than from the platform that does.
        handler = service.html_handler()
        self.assertTrue(
            handler,
            "html_handler() reports nothing on a machine whose HKCR\\.html is set; "
            "it is still only reading the Linux mimeapps.list",
        )
        self.assertFalse(
            service.needs_catalog_launcher(),
            "a launcher was deemed necessary on a machine that already opens .html with a browser",
        )

    def test_a_launcher_is_never_a_linux_desktop_file_on_windows(self):
        """The fallback still has to be a format Windows understands.

        Reaching this branch needs a machine with no HTML association at all, which is rare - so it is reached by
        patching rather than by waiting for one, and the format is asserted rather than the presence.
        """
        if os.name != "nt":
            self.fail("this app is Windows-only now")
        from pathlib import Path as _Path

        root = _Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        catalog = CatalogService(AppLogger(root / "x.log"))
        catalog._write_chrome_launcher(root, root / "Game Library.html")
        written = sorted(p.name for p in root.iterdir())
        self.assertEqual(
            [],
            [n for n in written if n.endswith(".desktop")],
            f"wrote a Linux desktop entry on Windows: {written}",
        )
        self.assertTrue(written, f"no launcher at all was written for a machine with no HTML handler: {written}")
