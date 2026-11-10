import ast
import unittest

import pytest
from pathlib import Path

import core.constants
import core.exceptions
from app import jobs
from services import extract_service, organizer_service
from ui import organize_view, scan_view

ROOT = Path(__file__).resolve().parents[1]

# Names that exist, are never called, and look like the live implementation of something that was already fixed.
# Each entry says what replaced it, because "this is unused" is the finding that gets deleted along with the
# comment explaining why it was safe to delete.
REMOVED = [
    (jobs.JobContext, "wait_for_cancel",
     "JobContext.cancelled is what the tool watcher polls. The watcher waits on its own local Event so it can "
     "time out and release the thread, which is the opposite of what this method did."),
    (core.constants, "CATEGORY_GENRES", "canonical_category() plus CATEGORY_ALIASES and the scoring pass in suggest_category() replaced this lookup table."),
    (core.exceptions, "ConfigurationError", "Config.load() reports a bad settings file by returning defaults, not by raising."),
    (core.exceptions, "ServiceError", "No service raises or catches it; each reports its own failure through the event stream."),
    (organizer_service.OrganizerService, "_steam_link", "The move path calls write_steam_links() with the same two arguments inline."),
    (organize_view, "STAGE_COST", "STAGE_SPAN carries the same weights as (start, end) ranges and is the table the bar reads."),
    (scan_view.ScanView, "_activity_wheel", "The activity panel is bound through bind_wheel(self.activity, ...) instead."),
]


@pytest.mark.notkinter
class TestRemovedDeadCode(unittest.TestCase):
    """A helper that was superseded but left in place is a helper the next reader will call."""

    def test_the_superseded_names_are_gone(self):
        for owner, name, why in REMOVED:
            with self.subTest(name=f"{owner.__name__}.{name}"):
                self.assertFalse(
                    hasattr(owner, name),
                    f"{owner.__name__}.{name} still exists but nothing calls it. {why}",
                )

    def test_the_live_cancel_protocol_survived_the_removal(self):
        """wait_for_cancel went; the flag the watcher actually reads must not go with it."""
        ctx = jobs.JobContext("abc123")
        self.assertFalse(ctx.cancelled)
        self.assertIsNone(ctx.checkpoint())
        ctx.cancel()
        self.assertTrue(ctx.cancelled)
        with self.assertRaises(core.exceptions.CancellationError):
            ctx.checkpoint()

    def test_the_progress_regexes_are_not_mistaken_for_one_another(self):
        """The two progress parsers read different streams, so they are named apart.

        They were both called TOOL_PROGRESS_RE with different patterns, which reads as one shared rule. The
        extract side matches '42% name'; the organize side additionally has to skip the leading counter that
        -bsp1 appends and must not match the digit group inside a longer number.
        """
        self.assertNotEqual(
            extract_service.EXTRACT_PROGRESS_RE.pattern,
            organizer_service.STAGE_PROGRESS_RE.pattern,
            "the two progress patterns have been made identical; one of them has been changed by accident",
        )


class TestNoStaleDuplicateConstants(unittest.TestCase):
    """One name, one value.

    Two modules that each define the same constant with different values is a silent trap: the reader has no
    way to tell which one is current, and editing the stale copy changes nothing. STAGE_SPAN and
    TOOL_PROGRESS_RE both reached this state - two copies of a tuning table that had drifted apart.
    """

    APP_DIRS = ("app", "core", "services", "ui")

    def _app_constants(self):
        found = {}
        for directory in self.APP_DIRS:
            for path in sorted((ROOT / directory).rglob("*.py")):
                if "__pycache__" in path.parts:
                    continue
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in tree.body:
                    if not isinstance(node, ast.Assign):
                        continue
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id.isupper():
                            found.setdefault(target.id, []).append((path.relative_to(ROOT).as_posix(), node.lineno, ast.unparse(node.value)))
        return found

    def test_no_name_is_defined_twice_with_different_values(self):
        conflicts = {}
        for name, sites in self._app_constants().items():
            files = {site[0] for site in sites}
            if len(files) > 1 and len({site[2] for site in sites}) > 1:
                conflicts[name] = sites
        report = "\n".join(f"  {name}: {sites}" for name, sites in sorted(conflicts.items()))
        self.assertEqual({}, conflicts, f"a constant is defined twice with different values:\n{report}")

    def test_the_two_stage_weight_tables_are_separately_named(self):
        """The scan bar and the organize bar weight stages differently on purpose, so the tables stay apart."""
        for module in (scan_view, organize_view):
            self.assertFalse(hasattr(module, "STAGE_SPAN"), "a bare STAGE_SPAN cannot say which bar it drives")
        self.assertTrue(hasattr(scan_view, "SCAN_STAGE_SPAN"))
        self.assertTrue(hasattr(organize_view, "ORGANIZE_STAGE_SPAN"))
