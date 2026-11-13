import os
import re
import sys
import unittest

import pytest
from pathlib import Path
from core.constants import APP_NAME, ENTRY_POINT, USER_AGENT, VERSION

ROOT = Path(__file__).resolve().parents[1]

# Directories that hold generated data, a person's library, or someone else's
# product rather than anything this project ships. `runtime` is the vendored
# Python and 7-Zip the bundler copies in: its files declare Python's and
# 7-Zip's versions, which are not this app's version and were never written
# by this project, so the version gate has nothing to say about them.
# `build` and `dist` are PyInstaller's own working and output folders: a fresh
# build writes an EXE-00.toc whose XML declaration reads `<?xml version="1.0"`,
# which the version scanner picked up as a declared version and reported as a
# release-structure failure. They hold nothing a reviewer reads.
NOT_SOURCE = {"cache", "logs", "config", "__pycache__", ".git", "Processing", "runtime", "build", "dist"}
PROSE_SUFFIXES = {".md"}

# A version beside the product's name - the User-Agent case, which is the one that actually happened. The name is
# taken from the constant rather than spelled out, so renaming the app cannot quietly stop the rule matching.
# Casing and separator both vary in real strings: "SteamDeckGameOrganizer/9.0" is the conventional token style,
# and a browser-style User-Agent prefixes the product name, so the match ignores case and tolerates any run of
# spaces, slashes, dashes or underscores before the number. A case-sensitive `Steam Game Organizer/9.0`
# pattern missed the lowercase and unspaced forms entirely.
def app_name_pattern():
    """A pattern for the product name that tolerates how it is actually written.

    Whitespace inside the name is optional, so the unspaced token form that is conventional for a User-Agent -
    and the form most likely to be typed by whoever writes the next one - matches as readily as the spaced name.
    Built from APP_NAME rather than spelled out, so renaming the app cannot leave the rule matching a string
    nothing sends any more. Described rather than quoted: this rule forbids the literal anywhere in the tree.
    """
    return r"[\s_-]*".join(re.escape(part) for part in APP_NAME.split())

DECLARED_NEXT_TO_NAME = re.compile(rf"{app_name_pattern()}[\s/_-]*v?(\d+\.\d+(?:\.\d+)?)", re.I)
# A literal explicitly labelled as a version: APP_VERSION = "9.0", 'X-App-Version': '9.0'. Two details matter.
# The label must end at "version", or "conversion" matches - one word contains the other, and every
# `conversion=` in this codebase would fire. And the character before the label must not be a word character,
# which is what stops the optional "APP_" prefix from being reached by starting the match inside a longer word.
LABELLED_VERSION = re.compile(r"""(?<![\w-])(?:[\w-]*[-_])?version["']?\s*[:=]\s*["']?v?(\d+\.\d+(?:\.\d+)?)""", re.I)
VERSION_IN_HEADING = re.compile(r"^\#\s+\S.*?\bv(\d+\.\d+)\b")
CHANGELOG_HEADING = re.compile(r"^## (\d+\.\d+)\s*$", re.M)
# The `# vX.Y change log:` convention is used in markdown as well as in source, where it reads as a heading. It
# records the release a change belongs to, so it keeps that date rather than tracking the current one.
CHANGE_LOG_NOTE = re.compile(r"^\s*\#+\s*v(\d[\d.]*)\s+change log:")
# The version a change-log note claims its change belongs to. Split out from CHANGE_LOG_NOTE because the two
# are used for opposite things: the pattern above exempts the line from the version scan, and this one is what
# the note is then held to. Keeping them together would mean the exemption is the only thing ever read off a
# note, which is how six releases came to exist in the code with nothing in the changelog to show for them.
CHANGE_LOG_VERSION = re.compile(r"^\s*\#+\s*v(\d+\.\d+)\s+change log:")
FENCE = re.compile(r"^\s*(?:```|~~~)")
VERSION_SHAPE = re.compile(r"^\d+\.\d+$")
# Read past on sight rather than decoding to find out. Anything absent from this list is still safe: the
# UTF-8 decode below rejects actual binaries.
NOT_TEXT_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".icns", ".exe", ".dll", ".so", ".pyc", ".woff", ".woff2", ".ttf", ".mp3", ".wav", ".7z", ".zip", ".rar"}
MAX_SCANNED_BYTES = 2_000_000

def change_log_versions(text):
    """Yield (line number, version, the line) for every release a change-log note claims its change belongs to."""
    for number, line in enumerate(text.splitlines(), 1):
        found = CHANGE_LOG_VERSION.match(line)
        if found:
            yield number, found.group(1), line

def code_before_comment(line):
    """The part of a code line that is code rather than comment.

    Without this, an explanatory comment naming the version it fixed reads as a declaration of that version,
    and the gate either has to be weakened until it misses real ones or it fails on its own documentation. The
    scan tracks quotes so a `#` inside a string - a colour, a URL fragment - is not mistaken for a comment.
    """
    quote = None
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "#":
            return line[:index]
    return line

def version_violations(text, markdown=False, expected=VERSION):
    """Just the declarations that disagree with `expected`, so a caller does not repeat the comparison."""
    for number, found, line in declared_versions(text, markdown):
        if found != expected:
            yield number, found, line

def read_shipped(path):
    """A shipped file's text, or None when it is binary or too large to be a document."""
    try:
        if path.suffix.lower() in NOT_TEXT_SUFFIXES:
            return None
        if path.stat().st_size > MAX_SCANNED_BYTES:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        return None

def shipped_texts():
    """Every shipped file that is text, with its contents.

    Keyed on what a file contains rather than on a list of extensions. An allowlist meant a file type added
    later was invisible until someone remembered to add it here, and `.gitignore` was already being skipped
    for having no extension at all.
    """
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        if set(path.relative_to(ROOT).parts) & NOT_SOURCE:
            continue
        text = read_shipped(path)
        if text is not None:
            yield path, text

# The punctuation a bad round trip produces, built rather than written out. Each entry is a real character -
# a dash, a curly quote, an ellipsis, a non-breaking space - whose UTF-8 bytes are then decoded as cp1252,
# which is the whole mechanism: a file saved as cp1252 and reopened as UTF-8 (or the reverse) leaves these
# three-character spellings where one character belongs.
#
# Derived rather than typed as literals on purpose. The rule below scans every shipped file, this one
# included, so a guard written out in the characters it forbids would report itself - and a rule that fires on
# its own source is one that gets deleted rather than fixed.
@pytest.mark.notkinter
class TestReleaseStructure(unittest.TestCase):
    def test_no_legacy_backend(self):
        self.assertFalse((ROOT / "legacy_backend.sh").exists())
        self.assertFalse((ROOT / "services" / "backend.py").exists())

    def test_one_entry_point_and_no_linux_launcher(self):
        # The repo root used to ship a .desktop launcher beside the entry point. It named /bin/bash and
        # python3, so it could not launch anything on this platform, and after the entry point was renamed it
        # pointed at a file that no longer existed - a stale launcher is worse than none, because it looks like
        # the job is still handled. The entry point is the only way in, and it is the one named in constants.
        entry = ROOT / ENTRY_POINT
        self.assertTrue(entry.is_file(), f"{ENTRY_POINT} is missing")
        self.assertFalse((ROOT / APP_NAME).exists(), "an extensionless bash wrapper is back")
        launchers = [p.name for p in ROOT.glob("*.desktop")]
        self.assertEqual([], launchers, f"Linux launcher(s) in the repo root: {launchers}")
        wrappers = [p.name for p in ROOT.glob("*.sh")]
        self.assertEqual([], wrappers, f"shell wrapper(s) in the repo root: {wrappers}")

    def test_version_consistency(self):
        """No file may declare a version other than the one in core/constants.py.

                The only thing that ever enforced this checked VERSION.txt, and everything else drifted: the README
                still titled itself 9.0, ARCHITECTURE.md 9.10, and every request to Steam's API carried a User-Agent
                hardcoded as `.../9.0` - so the app identified itself to Steam as 9.0 across nine releases without a
                single test objecting. Rather than list the places that have gone stale before, this scans every
        shipped file for a declared version, so the next one added is caught without anyone remembering.
        """
        self.assertRegex(VERSION, VERSION_SHAPE, f"VERSION is {VERSION!r}, which is not a major.minor version; every comparison below would silently stop meaning anything")
        self.assertEqual((ROOT / "VERSION.txt").read_text(encoding="utf-8").strip(), VERSION)

        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        released = CHANGELOG_HEADING.search(changelog)
        self.assertIsNotNone(released, "the changelog has no release heading to compare against")
        self.assertEqual(released.group(1), VERSION, "the newest CHANGELOG entry is not the current version, so a release was left unwritten")
        # The newest heading matching VERSION is only half the check: a release documented *below* the current
        # version would mean VERSION was never bumped, and reading the top of the file alone would not see it.
        for documented in CHANGELOG_HEADING.findall(changelog):
            self.assertLessEqual(tuple(int(p) for p in documented.split(".")), tuple(int(p) for p in VERSION.split(".")), f"the changelog documents {documented}, which is newer than VERSION {VERSION}; the constant was never bumped")

        for path, text in shipped_texts():
            markdown = path.suffix.lower() in PROSE_SUFFIXES
            for number, found, line in version_violations(text, markdown):
                self.assertEqual(found, VERSION, f"{path.relative_to(ROOT)}:{number} declares version {found}, not {VERSION}: {line.strip()[:120]}")

    def test_no_note_claims_a_release_that_does_not_exist(self):
        """The other half of the exemption, and the half that was missing.

        A `# vX.Y change log:` note is deliberately exempt from the version scan, because it records the release
        a change belongs to rather than the one the file was written in. But nothing checked the version it
        named, so a note could claim any release at all and the gate stayed green: the tree reached notes for
        9.17 through 9.22 while VERSION, VERSION.txt and the whole changelog still said 9.16. Every release
        gate agreed with every other one and six releases of work were undocumented.

        The fix is to keep the exemption and check the note. A note may name the current release or an older
        one - that is what the exemption is for - but never a newer one, because a newer one is a release that
        has not been written up or bumped yet.
        """
        current = tuple(int(part) for part in VERSION.split("."))
        for path, text in shipped_texts():
            for number, found, line in change_log_versions(text):
                self.assertLessEqual(tuple(int(part) for part in found.split(".")), current, f"{path.relative_to(ROOT)}:{number} records its change as belonging to {found}, which is newer than VERSION {VERSION}: the release has no entry in CHANGELOG.md and the constant was never bumped\n    {line.strip()[:140]}")

    def test_the_user_agent_is_not_written_out_anywhere(self):
        """Steam's API sees this string on every request, and it said 9.0 through nine releases because five
        copies of it were typed into call sites instead of derived once. Markdown prose is exempt because a
        release note may quote it; a fenced sample is not, and declared_versions checks that."""
        self.assertEqual(USER_AGENT, f"{APP_NAME}/{VERSION}")
        hardcoded = re.compile(rf"{app_name_pattern()}/\d", re.I)
        for path, text in shipped_texts():
            if path.suffix.lower() in PROSE_SUFFIXES:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if path.name == "constants.py":
                    continue
                self.assertIsNone(hardcoded.search(code_before_comment(line)), f"{path.relative_to(ROOT)}:{number} hardcodes a versioned User-Agent: {line.strip()[:120]}")

# VersionRuleBehaviour extracted to tests\test_version_rule_behaviour.py — see that module for its definition.
from tests.test_version_rule_behaviour import VersionRuleBehaviour
# declared_versions extracted to tests\declared_versions.py — see that module for its definition.
from tests.declared_versions import declared_versions


