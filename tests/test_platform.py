"""Platform-specificity guard: this project runs on Windows and nowhere else.

Approach: parse each source file with `ast` and inspect string constants and call arguments.
Comments and docstrings are skipped, which matters because this repository documents its own removals at length
- the legacy filenames it still deletes and the v8 change-log notes are Linux references that must stay.

The second guard below covers `tests/` and `tools/` as well, which the first deliberately does not: production
code is easier to review, whereas a POSIX path in a test is handed straight to a constructor that creates the
directory it is given.

Deliberately NOT banned: `.desktop`, `unrar`, and the Steam Deck / POSIX path spellings used inside cleanup
lists. `LEGACY_LINK_NAMES` and `LEGACY_CATALOGS` are the names of files older releases *wrote*; the code's
job is to delete them, and a guard that forbade the strings would forbid the cleanup itself.
"""
import ast
import re
import sys
import unittest

import pytest
from pathlib import Path

# Derived from this file's own location, not written out: the project has moved
# (to the games disk, beside the library it organizes) and a test that only
# passes at one hard-coded path is a test that fails the day the folder moves.
ROOT = Path(__file__).resolve().parents[1]
APP_DIRS = ("app", "core", "services", "ui", "utils")

# (name, matching function, why it cannot be reintroduced)
BANNED = (
    ("xdg-open", lambda text: "xdg-open" in text,
     "the Linux file opener. No launcher here calls it: utils/desktop.py uses os.startfile."),
    ("xdg-mime / mimeapps.list", lambda text: "xdg-mime" in text or "mimeapps.list" in text,
     "the XDG association mechanism, replaced by HKCR in html_handler()."),
    ("flatpak", lambda text: "flatpak" in text,
     "the Flatpak sandbox. v9.19 removed the host re-exec and this pass removed the remaining "
     "flatpak run/info browser fallback in the review view."),
    ("/proc/meminfo", lambda text: "/proc/meminfo" in text,
     "the Linux memory source. Windows asks GlobalMemoryStatusEx; keeping a second reading "
     "meant a second answer to one question."),
    ("/home/<user> paths", lambda text: any(p in text for p in ("/home/", "/root/", "/usr/bin")),
     "POSIX home and binary paths. They cannot resolve on this platform, and a catalog that "
     "shows one tells the reader to look somewhere that does not exist."),
    ("Linux browser package names",
     lambda text: any(n in text for n in ("google-chrome-stable", "chromium-browser",
                                           "com.google.ChromeDev", "org.chromium.Chromium")),
     "Debian package names and Flatpak app ids. Chrome installs into Program Files without "
     "putting itself on PATH, so every one of these lookups returned None on this machine."),
)


def source_files(directories=APP_DIRS):
    for directory in directories:
        for path in sorted((ROOT / directory).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            yield path


def string_literals(tree):
    """Every string constant in the module except docstrings, as (text, line number)."""
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            yield node.value, node.lineno
        elif isinstance(node, ast.keyword) and node.arg is not None and \
                isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            yield node.value.value, node.value.lineno


@pytest.mark.notkinter
class TestNoNonWindowsPlatformCode(unittest.TestCase):
    """Windows is the only platform. A second implementation is not a fallback, it is an unanswered question."""

    def _offenders(self, predicate):
        found = []
        for path in source_files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for text, lineno in string_literals(tree):
                if predicate(text):
                    found.append(f"{path.relative_to(ROOT).as_posix()}:{lineno}: {text[:70]!r}")
        return found

    def test_no_linux_only_mechanism_is_called_anywhere(self):
        report = []
        for name, predicate, why in BANNED:
            hits = self._offenders(predicate)
            if hits:
                report.append(f"  {name} ({why}): {hits}")
        self.assertEqual([], report, "Linux-only code is back in the application:\n" + "\n".join(report))

    def test_the_legacy_filenames_this_app_deletes_are_still_deliberate(self):
        """The strings the guard must not touch, checked so the guard cannot be widened by accident.

        A rule that forbade the word `.desktop` everywhere would stop this app from deleting the desktop
        entries earlier releases scattered through a user's library - which is the one thing those lists are
        for. If these ever go, the cleanup went with them and the guard should be reconsidered at the same time.
        """
        from services.catalog_service import CatalogService
        from services.organizer_service import OrganizerService
        self.assertTrue(
            any(name.endswith('.desktop') for name in OrganizerService.LEGACY_LINK_NAMES),
            "the legacy .desktop link names are gone; check whether the guard above should change too")
        self.assertIn('.desktop', CatalogService.LEGACY_LAUNCHER,
                      "the legacy catalog launcher name is gone; check whether the guard above should change too")

    def test_the_ban_list_catches_what_it_claims_to(self):
        """A guard nobody has watched fail is a guard nobody knows is armed."""
        samples = {
            "xdg-open": "subprocess.Popen(['xdg-open', path])",
            "xdg-mime / mimeapps.list": "DEFAULT = '~/.local/share/applications/mimeapps.list'",
            "flatpak": "shutil.which('flatpak')",
            "/proc/meminfo": "text = Path('/proc/meminfo').read_text()",
            "/home/<user> paths": "fallback = '/home/you/Downloads/Games'",
            "Linux browser package names": "names = ('google-chrome-stable', 'chromium-browser')",
        }
        for name, predicate, _ in BANNED:
            caught = any(predicate(node.value) for node in ast.walk(ast.parse(samples[name]))
                         if isinstance(node, ast.Constant) and isinstance(node.value, str))
            self.assertTrue(caught, f"the pattern for {name!r} does not match the code it is meant to catch")

    def test_the_guard_ignores_comments_and_docstrings(self):
        """Otherwise it could not coexist with this repository's own record of what it removed."""
        source = ROOT / "services" / "organizer_service.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn("flatpak", text.lower(), "the removal note is gone; the tree should say why it is safe")
        tree = ast.parse(text)
        docstrings = [node.value for node in ast.walk(tree)
                      if isinstance(node, ast.Constant) and isinstance(node.value, str)]
        self.assertTrue(any("flatpak" in d.lower() for d in docstrings),
                        "the note naming flatpak should be a docstring, which the guard skips")
        self.assertEqual([], self._offenders(lambda value: "flatpak" in value.lower()),
                         "a docstring mentioning flatpak is being counted as code")


# The constructors that write into the directory they are handed. This is the whole reason a POSIX path in a
# test is not a label: each of these creates that directory. AppLogger creates the one holding its log, AppConfig
# derives config/, cache/, logs/ and debug/ from the project root and saves into them, ArtworkService creates the
# cache directory and then deletes from it, and RollbackService records the undo journal under the project root.
WRITING_CONSTRUCTORS = (
    ("AppConfig", "the root every runtime directory is derived from, and where save() writes settings.json"),
    ("AppLogger", "creates the directory holding the log it is given"),
    ("ArtworkService", "creates the cache directory and then deletes from it"),
    ("RollbackService", "records the undo journal under the project root it is given"),
)

# A string that opens a POSIX absolute path. Deliberately not "any string containing /tmp": that would flag
# 'https://cdn.example/header.jpg', the '#!/usr/bin/env python3' shebang every archive-tool stub is written
# with, and "fallback = '/home/you/Downloads/Games'" - a URL, a script header, and a sample of the very text the
# ban list above is built from. This shape catches '/tmp', '/tmp/project-root', '/etc' and '/home/deck'.
POSIX_ABSOLUTE = re.compile(r"^/[A-Za-z0-9_.~-]+")


def writing_constructor_calls(tree):
    """(name, [string constants in its arguments], line) for every call that writes into a directory it is given.

    Every argument is scanned, positional and keyword alike, because AppConfig is written `AppConfig(tmp)` as
    often as `AppConfig(project_root=tmp)`. Constants are collected from anywhere inside an argument, so
    `AppLogger(Path('/tmp') / 'x.log')` reports the '/tmp' buried inside it rather than only the file name.
    """
    names = {name for name, _reason in WRITING_CONSTRUCTORS}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        else:
            continue
        if name not in names:
            continue
        arguments = list(node.args) + [keyword.value for keyword in node.keywords]
        yield name, [constant.value for argument in arguments
                     for constant in ast.walk(argument)
                     if isinstance(constant, ast.Constant) and isinstance(constant.value, str)], node.lineno


def posix_paths_aimed_at_a_writer():
    """Every offending `file:line: Constructor('literal')` in the application, the tests and the tools."""
    found = []
    for path in source_files(APP_DIRS + ("tests", "tools")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for name, literals, lineno in writing_constructor_calls(tree):
            for literal in literals:
                if POSIX_ABSOLUTE.match(literal):
                    found.append(f"{path.relative_to(ROOT).as_posix()}:{lineno}: {name}({literal!r})")
    return found


class TestNoWritingIsAimedOutsideATemporaryTree(unittest.TestCase):
    """The tests and the tools are not exempt from the guard above - they are where it is easiest to break.

    A POSIX absolute path in production code is inert often enough to survive review. In a test it reaches one
    of four constructors that create the directory they are handed. On Windows a leading slash is not absolute:
    pathlib resolves it against whatever drive is current, so Path('/tmp') is C:\\tmp. This suite therefore
    created C:\\tmp, appended a log into it, and handed ArtworkService - which removes every number-stemmed
    *.jpg, every non-portrait *_steam_v2.jpg over 1 KB, and everything in the tree older than max_age_days - a
    real folder to delete from. All of it outside this repository, none of it asserted by anything.
    """

    def test_no_writing_constructor_is_handed_a_posix_absolute_path(self):
        found = posix_paths_aimed_at_a_writer()
        self.assertEqual([], found,
                         "these constructors create the directory they are handed, and on Windows a leading "
                         "slash resolves against the current drive, so each of these writes outside the "
                         "repository:\n" + "\n".join(found))

    def test_the_guard_notices_a_posix_path_handed_to_every_writer(self):
        """The control, without which the test above could pass by matching nothing at all.

        Planted rather than read from the tree, so it stays a claim about the matcher instead of about whatever
        the suite happens to contain today - including the last line, which is the shape the fixes use and must
        stay unflagged.
        """
        planted = (
            "a = AppConfig(Path('/tmp/project-root'))\n"
            "b = AppLogger(Path('/tmp') / 'x.log')\n"
            "c = ArtworkService(Path('/tmp/artwork-cache'), logger)\n"
            "d = RollbackService(Path('/tmp/root'), logger)\n"
            "e = AppLogger(root / 'x.log')\n"
        )
        flagged = sorted(f"{name}({literal!r})" for name, literals, _line
                         in writing_constructor_calls(ast.parse(planted))
                         for literal in literals if POSIX_ABSOLUTE.match(literal))
        self.assertEqual(["AppConfig('/tmp/project-root')", "AppLogger('/tmp')",
                          "ArtworkService('/tmp/artwork-cache')", "RollbackService('/tmp/root')"], flagged,
                         'the matcher no longer catches a POSIX path for every constructor it claims to watch, '
                         'or now flags a temporary-directory path')

    def test_the_scan_really_reads_the_tree(self):
        """The named constructors it found, so a scan that stopped walking files cannot report a clean tree."""
        names = set()
        for path in source_files(APP_DIRS + ("tests", "tools")):
            for name, _literals, _line in writing_constructor_calls(ast.parse(path.read_text(encoding="utf-8"))):
                names.add(name)
        self.assertEqual(sorted(name for name, _reason in WRITING_CONSTRUCTORS), sorted(names),
                         f'the scan saw only {sorted(names)} of the constructors it is meant to watch')


if __name__ == "__main__":
    unittest.main()

