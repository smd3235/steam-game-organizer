"""Extracted from tests/test_cleanup_regressions.py.

    TestCleanupDoesNotLeaveTheLibraryThroughAJunction was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import os
import subprocess
import time
import unittest
from pathlib import Path
from core.logger import AppLogger
from services.library_service import LibraryService
from tests.test_helpers import _tmp_dir
from utils.treewalk import is_link


class TestCleanupDoesNotLeaveTheLibraryThroughAJunction(unittest.TestCase):
    """cleanup_leftovers() deleted a file that was never in the library.

    os.walk(followlinks=False) is documented not to follow symlinks, and the walk here relied on that. A Windows
    junction is not a symlink - Path.is_symlink() answers False for one, because the OS hands it back as an
    ordinary directory - so os.walk stepped straight through it. Everything reached that way is outside the
    folder the caller passed as the library root, and this is the one walk in the app that deletes what it finds.

    Confirmed live before the fix, in a temp directory:

        library/linked/  -> junction -> elsewhere/
        elsewhere/~syncthing~orphan.tmp   4096 bytes

    cleanup_leftovers() reported removed=1, and the file on the far side of the junction was gone. A file matched
    by name in a neighbouring folder, which a Syncthing setup makes routine, was destroyed by a routine scan.

    This is deliberately the opposite of the rule tests/test_services.py pins for scanning, where a junction to a
    sibling folder IS followed: reading a sibling folder through a link finds games the user meant to include, and
    refusing it would hide them. Deleting is not symmetric. The caller named one folder as the boundary, and a link
    is a way out of it, not a road inside.
    """

    def _link_directory(self, link, target):
        # Fails rather than skips: a skipped test here would report the library safe on the one platform where the
        # link is a junction rather than a symlink, which is the platform this defect needs.
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, timeout=30)
        if made.returncode == 0:
            return "junction"
        try:
            link.symlink_to(target, target_is_directory=True)
            return "symlink"
        except OSError as exc:
            self.fail(f"no way to make a directory link on this machine: {exc}")

    def _service(self, root):
        return LibraryService(AppLogger(Path(root) / "x.log"))

    def test_a_matching_file_behind_a_junction_survives(self):
        root = Path(_tmp_dir(self))
        library = root / "Games"
        library.mkdir()
        elsewhere = root / "Elsewhere"
        elsewhere.mkdir()
        victim = elsewhere / "~syncthing~orphan.tmp"
        victim.write_text("x" * 4096)
        old = time.time() - 30 * 24 * 3600
        os.utime(victim, (old, old))
        kind = self._link_directory(library / "linked", elsewhere)
        # A file the walk would find and the pattern would match, reached only by walking through the link.
        inside = library / "stale.7z.syncthing.abc.tmp"
        inside.write_text("x" * 4096)
        os.utime(inside, (old, old))
        self.assertTrue(
            any(p.name == victim.name for p in library.rglob("*")),
            f"the {kind} does not lead to the victim, so nothing would have been deleted",
        )
        self._service(root).cleanup_leftovers(library, grace_seconds=0)
        self.assertTrue(
            victim.exists(),
            f"cleanup deleted a {kind} and removed a file {victim} that was outside the library root",
        )
        self.assertFalse(inside.exists(), "the leftover actually inside the library was left behind by the fix")

    def test_a_junction_named_like_our_own_temp_folder_is_declined(self):
        """A link matching this app's own temp-folder names is declined, and the decline is visible.

        The content behind such a link was never actually at risk: shutil.rmtree() raises OSError on a Windows
        junction rather than descending it, so the folder survived by accident and cleanup logged
        LEFTOVER_REMOVE_FAILED while reporting a successful sweep. That is a warning about a folder the app did
        not create, on a scan the user reads as a routine clean-up - and it is the only warning in the pass that
        is not about something real.

        So what the fix changes is not the outcome but the intent: the link is recognised and counted, instead of
        attempted, failed, and reported as an error. Asserted on both halves, because either alone would pass
        against the old code - the content check alone passes there too.
        """
        root = Path(_tmp_dir(self))
        library = root / "Games"
        library.mkdir()
        precious = root / "Do Not Touch"
        precious.mkdir()
        (precious / "save.dat").write_text("x" * 4096)
        self._link_directory(library / ".organizer-repack-stale", precious)
        summary = self._service(root).cleanup_leftovers(library, grace_seconds=0)
        self.assertTrue(
            (precious / "save.dat").exists(), "cleanup reached through a link named as one of its own temp folders"
        )
        self.assertEqual(summary.get("skipped_links"), 1, f"the link was not counted as declined: {summary}")
        logged = (root / "x.log").read_text(encoding="utf-8", errors="replace")
        self.assertNotIn(
            "LEFTOVER_REMOVE_FAILED",
            logged,
            f"a link was attempted and then failed, instead of being declined up front: {logged[-400:]}",
        )

    def test_the_summary_reports_what_it_declined_to_walk(self):
        """A skipped junction is invisible otherwise - removed=0 and bytes_freed=0 read identically to 'nothing to
        do', which is how a library full of links could report a clean sweep for ever."""
        root = Path(_tmp_dir(self))
        library = root / "Games"
        library.mkdir()
        elsewhere = root / "Elsewhere"
        elsewhere.mkdir()
        (elsewhere / "~syncthing~orphan.tmp").write_text("x" * 4096)
        self._link_directory(library / "linked", elsewhere)
        summary = self._service(root).cleanup_leftovers(library, grace_seconds=0)
        self.assertEqual(summary.get("skipped_links"), 1, f"the junction was not reported as declined: {summary}")

    def test_is_link_says_no_to_a_plain_folder(self):
        """The fix must not turn cleanup into a no-op: a real temp folder, matched by name and old enough, still
        goes. is_link() is on the path of every deletion, so a false positive here would silently disable cleanup."""
        root = Path(_tmp_dir(self))
        junk = root / ".organizer-unzip-gone"
        junk.mkdir()
        (junk / "part.bin").write_text("x" * 4096)
        plain = root / "notes.txt"
        plain.write_text("x")
        self.assertFalse(is_link(junk), "an ordinary folder was reported as a link")
        self.assertFalse(is_link(plain), "an ordinary file was reported as a link")
        self._service(root).cleanup_leftovers(root, grace_seconds=0)
        self.assertFalse(junk.exists(), "a genuine leftover inside the library stopped being cleaned up")
