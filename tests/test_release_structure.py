import os
import re
import sys
import unittest

import pytest
from pathlib import Path
from core.constants import APP_NAME, ENTRY_POINT, USER_AGENT, VERSION

ROOT=Path(__file__).resolve().parents[1]

# Directories that hold generated data, a person's library, or someone else's
# product rather than anything this project ships. `runtime` is the vendored
# Python and 7-Zip the bundler copies in: its files declare Python's and
# 7-Zip's versions, which are not this app's version and were never written
# by this project, so the version gate has nothing to say about them.
# `build` and `dist` are PyInstaller's own working and output folders: a fresh
# build writes an EXE-00.toc whose XML declaration reads `<?xml version="1.0"`,
# which the version scanner picked up as a declared version and reported as a
# release-structure failure. They hold nothing a reviewer reads.
NOT_SOURCE={'cache','logs','config','__pycache__','.git','Processing','runtime','build','dist'}
PROSE_SUFFIXES={'.md'}
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
    return r'[\s_-]*'.join(re.escape(part) for part in APP_NAME.split())


DECLARED_NEXT_TO_NAME=re.compile(rf'{app_name_pattern()}[\s/_-]*v?(\d+\.\d+(?:\.\d+)?)',re.I)
# A literal explicitly labelled as a version: APP_VERSION = "9.0", 'X-App-Version': '9.0'. Two details matter.
# The label must end at "version", or "conversion" matches - one word contains the other, and every
# `conversion=` in this codebase would fire. And the character before the label must not be a word character,
# which is what stops the optional "APP_" prefix from being reached by starting the match inside a longer word.
LABELLED_VERSION=re.compile(r'''(?<![\w-])(?:[\w-]*[-_])?version["']?\s*[:=]\s*["']?v?(\d+\.\d+(?:\.\d+)?)''',re.I)
VERSION_IN_HEADING=re.compile(r'^\#\s+\S.*?\bv(\d+\.\d+)\b')
CHANGELOG_HEADING=re.compile(r'^## (\d+\.\d+)\s*$',re.M)
# The `# vX.Y change log:` convention is used in markdown as well as in source, where it reads as a heading. It
# records the release a change belongs to, so it keeps that date rather than tracking the current one.
CHANGE_LOG_NOTE=re.compile(r'^\s*\#+\s*v(\d[\d.]*)\s+change log:')
# The version a change-log note claims its change belongs to. Split out from CHANGE_LOG_NOTE because the two
# are used for opposite things: the pattern above exempts the line from the version scan, and this one is what
# the note is then held to. Keeping them together would mean the exemption is the only thing ever read off a
# note, which is how six releases came to exist in the code with nothing in the changelog to show for them.
CHANGE_LOG_VERSION=re.compile(r'^\s*\#+\s*v(\d+\.\d+)\s+change log:')
FENCE=re.compile(r'^\s*(?:```|~~~)')
VERSION_SHAPE=re.compile(r'^\d+\.\d+$')
# Read past on sight rather than decoding to find out. Anything absent from this list is still safe: the
# UTF-8 decode below rejects actual binaries.
NOT_TEXT_SUFFIXES={'.png','.jpg','.jpeg','.gif','.webp','.ico','.icns','.exe','.dll','.so','.pyc',
                   '.woff','.woff2','.ttf','.mp3','.wav','.7z','.zip','.rar'}
MAX_SCANNED_BYTES=2_000_000


def change_log_versions(text):
    """Yield (line number, version, the line) for every release a change-log note claims its change belongs to."""
    for number,line in enumerate(text.splitlines(),1):
        found=CHANGE_LOG_VERSION.match(line)
        if found: yield number,found.group(1),line


def code_before_comment(line):
    """The part of a code line that is code rather than comment.

    Without this, an explanatory comment naming the version it fixed reads as a declaration of that version,
    and the gate either has to be weakened until it misses real ones or it fails on its own documentation. The
    scan tracks quotes so a `#` inside a string - a colour, a URL fragment - is not mistaken for a comment.
    """
    quote=None
    for index,char in enumerate(line):
        if quote:
            if char==quote: quote=None
        elif char in '"\'': quote=char
        elif char=='#': return line[:index]
    return line


def declared_versions(text,markdown=False):
    """Yield (line number, version found, the line) for every version this text declares.

    Prose may quote history; code may not. A markdown document outside a fenced block is prose, so a release
    note can say what the User-Agent used to be, while a fenced code sample is a specimen of something that is
    meant to be current and is checked like code. A comment in a source file is likewise prose, which is what
    lets a `# v9.11 change log:` note keep its own date.

    Split out from the test that uses it so the rule can be pinned by synthetic input. A check that has never
    been made to fail is not a check - this repo has shipped one of those twice.
    """
    inside_fence=False
    for number,line in enumerate(text.splitlines(),1):
        if markdown and FENCE.match(line):
            inside_fence=not inside_fence
            continue
        if markdown and not inside_fence:
            if CHANGE_LOG_NOTE.match(line): continue
            match=VERSION_IN_HEADING.match(line)
            if match: yield number,match.group(1),line
            continue
        for pattern in (DECLARED_NEXT_TO_NAME,LABELLED_VERSION):
            for match in pattern.finditer(code_before_comment(line) if not markdown else line):
                yield number,match.group(1),line


def version_violations(text,markdown=False,expected=VERSION):
    """Just the declarations that disagree with `expected`, so a caller does not repeat the comparison."""
    for number,found,line in declared_versions(text,markdown):
        if found!=expected: yield number,found,line


def read_shipped(path):
    """A shipped file's text, or None when it is binary or too large to be a document."""
    try:
        if path.suffix.lower() in NOT_TEXT_SUFFIXES: return None
        if path.stat().st_size > MAX_SCANNED_BYTES: return None
        return path.read_text(encoding='utf-8')
    except (OSError,UnicodeDecodeError,ValueError):
        return None


def shipped_texts():
    """Every shipped file that is text, with its contents.

    Keyed on what a file contains rather than on a list of extensions. An allowlist meant a file type added
    later was invisible until someone remembered to add it here, and `.gitignore` was already being skipped
    for having no extension at all.
    """
    for path in sorted(ROOT.rglob('*')):
        if not path.is_file(): continue
        if set(path.relative_to(ROOT).parts) & NOT_SOURCE: continue
        text=read_shipped(path)
        if text is not None: yield path,text


# The punctuation a bad round trip produces, built rather than written out. Each entry is a real character -
# a dash, a curly quote, an ellipsis, a non-breaking space - whose UTF-8 bytes are then decoded as cp1252,
# which is the whole mechanism: a file saved as cp1252 and reopened as UTF-8 (or the reverse) leaves these
# three-character spellings where one character belongs.
#
# Derived rather than typed as literals on purpose. The rule below scans every shipped file, this one
# included, so a guard written out in the characters it forbids would report itself - and a rule that fires on
# its own source is one that gets deleted rather than fixed.
def _mojibake(character):
    """What one character becomes when its UTF-8 bytes are read as cp1252, or None when it cannot.

    cp1252 leaves five byte values undefined (0x81, 0x8D, 0x8F, 0x90 and 0x9D), so not every character has a
    mojibake spelling to look for: U+201D among them. Those are dropped rather than guessed at, because a
    pattern built from a byte value the codec does not define raises on import instead of matching.
    """
    try: return character.encode('utf-8').decode('cp1252')
    except UnicodeDecodeError: return None


MOJIBAKE_SEQUENCES=tuple(spelling for spelling in
                         (_mojibake(character) for character in '\u2014\u2013\u2018\u2019\u201c\u201d\u2026\u00a0')
                         if spelling)
DOUBLE_ENCODED=re.compile('|'.join(re.escape(spelling) for spelling in MOJIBAKE_SEQUENCES))


@pytest.mark.notkinter
class TestReleaseStructure(unittest.TestCase):
    def test_no_legacy_backend(self):
        self.assertFalse((ROOT/"legacy_backend.sh").exists()); self.assertFalse((ROOT/"services"/"backend.py").exists())
    def test_one_entry_point_and_no_linux_launcher(self):
        # The repo root used to ship a .desktop launcher beside the entry point. It named /bin/bash and
        # python3, so it could not launch anything on this platform, and after the entry point was renamed it
        # pointed at a file that no longer existed - a stale launcher is worse than none, because it looks like
        # the job is still handled. The entry point is the only way in, and it is the one named in constants.
        entry=ROOT/ENTRY_POINT
        self.assertTrue(entry.is_file(),f'{ENTRY_POINT} is missing')
        self.assertFalse((ROOT/APP_NAME).exists(),'an extensionless bash wrapper is back')
        launchers=[p.name for p in ROOT.glob('*.desktop')]
        self.assertEqual([],launchers,f'Linux launcher(s) in the repo root: {launchers}')
        wrappers=[p.name for p in ROOT.glob('*.sh')]
        self.assertEqual([],wrappers,f'shell wrapper(s) in the repo root: {wrappers}')
    def test_version_consistency(self):
        """No file may declare a version other than the one in core/constants.py.

        The only thing that ever enforced this checked VERSION.txt, and everything else drifted: the README
        still titled itself 9.0, ARCHITECTURE.md 9.10, and every request to Steam's API carried a User-Agent
        hardcoded as `.../9.0` - so the app identified itself to Steam as 9.0 across nine releases without a
        single test objecting. Rather than list the places that have gone stale before, this scans every
shipped file for a declared version, so the next one added is caught without anyone remembering.
        """
        self.assertRegex(VERSION,VERSION_SHAPE,
                         f'VERSION is {VERSION!r}, which is not a major.minor version; every comparison below '
                         'would silently stop meaning anything')
        self.assertEqual((ROOT/"VERSION.txt").read_text(encoding="utf-8").strip(),VERSION)

        changelog=(ROOT/"CHANGELOG.md").read_text(encoding="utf-8")
        released=CHANGELOG_HEADING.search(changelog)
        self.assertIsNotNone(released,'the changelog has no release heading to compare against')
        self.assertEqual(released.group(1),VERSION,
                         'the newest CHANGELOG entry is not the current version, so a release was left unwritten')
        # The newest heading matching VERSION is only half the check: a release documented *below* the current
        # version would mean VERSION was never bumped, and reading the top of the file alone would not see it.
        for documented in CHANGELOG_HEADING.findall(changelog):
            self.assertLessEqual(tuple(int(p) for p in documented.split('.')),
                                 tuple(int(p) for p in VERSION.split('.')),
                                 f'the changelog documents {documented}, which is newer than VERSION {VERSION}; '
                                 'the constant was never bumped')

        for path,text in shipped_texts():
            markdown=path.suffix.lower() in PROSE_SUFFIXES
            for number,found,line in version_violations(text,markdown):
                self.assertEqual(found,VERSION,
                                 f'{path.relative_to(ROOT)}:{number} declares version {found}, not {VERSION}: '
                                 f'{line.strip()[:120]}')

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
        current=tuple(int(part) for part in VERSION.split('.'))
        for path,text in shipped_texts():
            for number,found,line in change_log_versions(text):
                self.assertLessEqual(tuple(int(part) for part in found.split('.')),current,
                                     f'{path.relative_to(ROOT)}:{number} records its change as belonging to '
                                     f'{found}, which is newer than VERSION {VERSION}: the release has no entry '
                                     f'in CHANGELOG.md and the constant was never bumped\n'
                                     f'    {line.strip()[:140]}')

    def test_the_user_agent_is_not_written_out_anywhere(self):
        """Steam's API sees this string on every request, and it said 9.0 through nine releases because five
        copies of it were typed into call sites instead of derived once. Markdown prose is exempt because a
        release note may quote it; a fenced sample is not, and declared_versions checks that."""
        self.assertEqual(USER_AGENT,f"{APP_NAME}/{VERSION}")
        hardcoded=re.compile(rf'{app_name_pattern()}/\d',re.I)
        for path,text in shipped_texts():
            if path.suffix.lower() in PROSE_SUFFIXES: continue
            for number,line in enumerate(text.splitlines(),1):
                if path.name=='constants.py': continue
                self.assertIsNone(hardcoded.search(code_before_comment(line)),
                                  f'{path.relative_to(ROOT)}:{number} hardcodes a versioned User-Agent: '
                                  f'{line.strip()[:120]}')

class VersionRuleBehaviour(unittest.TestCase):
    """The rule itself, on synthetic input, so that weakening it later is visible rather than silent.

    The stale values are assembled from APP_NAME and STALE rather than written out, because this file is itself
    scanned: a fixture spelled out in full would be a real stale declaration sitting in the repository, and the
    gate would rightly fail on its own test.
    """
    STALE='9.0'

    def _violations(self,text,markdown=False):
        return [found for _,found,_ in version_violations(text,markdown)]

    def test_a_stale_version_in_a_string_is_a_violation(self):
        self.assertEqual(self._violations(f'req=Request(u,headers={{"User-Agent":"{APP_NAME}/{self.STALE}"}})'),
                         [self.STALE])

    def test_a_stale_version_quoted_in_a_comment_is_not(self):
        self.assertEqual(self._violations(f'# it was hardcoded as "{APP_NAME}/{self.STALE}" everywhere'),[])

    def test_a_change_log_note_keeps_its_own_date(self):
        self.assertEqual(self._violations(f'# v9.11 change log: was "{APP_NAME}/9.11"'),[])

    def test_a_change_log_note_is_read_for_the_release_it_claims(self):
        """The exemption and the check that replaced it are two different reads of the same line.

        A note used to be only ever skipped. It is now also held to the version it names, which is the half that
        was missing - so the reader itself needs a test, or a later change could quietly turn it back into a skip
        and the gate would report clean while six undocumented releases sat in the tree.
        """
        self.assertEqual([found for _,found,_ in change_log_versions('# v9.11 change log: a fix')],['9.11'])

    def test_only_a_real_change_log_note_is_read(self):
        """The marker is what makes a line a note.

        Otherwise any sentence mentioning a version beside the words "change log" would be read as a release
        claim - including the ones explaining the convention, and this one.
        """
        self.assertEqual(list(change_log_versions('the v9.11 change log convention records a release')),[])
        self.assertEqual(list(change_log_versions('# v9.11 was a release')),[])

    def test_a_note_naming_the_current_version_is_read(self):
        """A note for the release being worked on is the normal case, and the gate has to leave it alone."""
        self.assertEqual([found for _,found,_ in change_log_versions(f'# v{VERSION} change log: current')],
                         [VERSION])

    def test_the_note_reader_ignores_a_version_without_a_minor_part(self):
        """`v9` is not a release this project ships - VERSION is asserted to be major.minor - so it is not a note.

        Read loosely it would become a version to compare, and comparing '9' against '9.16' is not a comparison.
        """
        self.assertEqual(list(change_log_versions('# v9 change log: no minor part')),[])

    def test_ordinary_floats_are_not_versions(self):
        self.assertEqual(self._violations('report(msg,progress=1.0,factor=2.5,ratio=0.5)'),[])

    def test_the_word_conversion_is_not_a_version_label(self):
        """"conversion" contains "version", so a label match that did not stop at the end of a word would fire
        on every `conversion=` in the codebase rather than on anything to do with a release."""
        self.assertEqual(self._violations(f'conversion_ratio=1.0; stage_conversion=1.0; conversion_x="{self.STALE}"'),[])

    def test_a_labelled_version_literal_is_a_violation(self):
        label='APP_VERSION'
        self.assertEqual(self._violations(f'{label} = "{self.STALE}"'),[self.STALE])
        header='X-App-Version'
        self.assertEqual(self._violations(f"req=Request(u,headers={{'{header}': '{self.STALE}'}})"),[self.STALE])

    def test_markdown_prose_may_quote_the_version_it_fixed(self):
        self.assertEqual(self._violations(f'It identified itself as {APP_NAME}/{self.STALE}.',True),[])

    def test_a_markdown_code_sample_may_not(self):
        """The gap this rule was tightened to close: a sample is a specimen of what the code should say, so a
        stale version inside one is the same defect as a stale version in the code it documents."""
        self.assertEqual(self._violations(f'```\nUser-Agent: {APP_NAME}/{self.STALE}\n```\n',True),[self.STALE])

    def test_a_markdown_change_log_note_keeps_its_own_date(self):
        self.assertEqual(self._violations(f'# v9.9 change log: this described v{self.STALE}',True),[])

    def test_a_document_heading_is_a_declaration(self):
        self.assertEqual(self._violations(f'# {APP_NAME} v{self.STALE}',True),[self.STALE])

    def test_the_current_version_is_never_a_violation(self):
        self.assertEqual(self._violations(f'req=Request(u,headers={{"User-Agent":"{APP_NAME}/{VERSION}"}})'),[])
        self.assertEqual(self._violations(f'# {APP_NAME}/{VERSION} is current'),[])
        self.assertEqual(self._violations(f'# {APP_NAME} v{VERSION}',True),[])

    def test_the_user_agent_pattern_survives_how_it_is_actually_written(self):
        """The pattern was case-sensitive and allowed only a slash or space after the name, so it missed a
        lowercased product name, an unspaced token, and a dash separator. Each is pinned below."""
        for written in (f'{APP_NAME}/{self.STALE}', f'{APP_NAME.lower()}/{self.STALE}',
                        f'{APP_NAME.replace(" ","")}/{self.STALE}', f'{APP_NAME} - {self.STALE}',
                        f'{APP_NAME} v{self.STALE}', f'Mozilla/5.0 {APP_NAME}/{self.STALE}'):
            self.assertEqual(self._violations(f'H={{"User-Agent":"{written}"}}'),[self.STALE],
                             f'the rule missed a User-Agent written as {written!r}')

    def test_it_still_follows_a_renamed_application(self):
        """The name comes from the constant, so a rename cannot leave the rule matching a string nothing
        sends any more."""
        pattern=app_name_pattern()
        self.assertIn(re.escape(APP_NAME.split()[0]),pattern)
        self.assertNotIn(re.escape(APP_NAME),pattern,
                         'the product name is matched with its spaces, so an unspaced User-Agent token misses')

    def test_a_binary_or_oversized_file_is_skipped_rather_than_decoded(self):
        import tempfile
        with tempfile.TemporaryDirectory() as scratch:
            binary=Path(scratch)/"logo.png"
            binary.write_bytes(b'\x89PNG\r\n\x1a\n\xff\xfe\x00binary')
            self.assertIsNone(read_shipped(binary),'a binary file was read as text')
            huge=Path(scratch)/"big.md"
            huge.write_text("x"*(MAX_SCANNED_BYTES+1),encoding="utf-8")
            self.assertIsNone(read_shipped(huge),'an oversized file was read as text')
            plain=Path(scratch)/"notes.md"
            plain.write_text("a note\n",encoding="utf-8")
            self.assertEqual(read_shipped(plain),"a note\n")

    def test_files_are_found_by_content_not_by_extension(self):
        """An extension allowlist made a newly added file type invisible until someone remembered to list it,
        and `.gitignore` was already being skipped for having no extension."""
        self.assertFalse(hasattr(sys.modules[__name__],'SOURCE_SUFFIXES'),
                         'the extension allowlist is back; files are meant to be found by content')
        scanned={path.name for path,_ in shipped_texts()}
        self.assertIn('.gitignore',scanned,'a shipped file with no extension is not being scanned')

    def test_no_shipped_file_carries_double_encoded_punctuation(self):
        """UTF-8 read as cp1252 and written back out as UTF-8, which is what a bad round trip produces.

        An em dash (U+2014) is the three bytes E2 80 94, and decoding those as cp1252 yields three characters
        which are then written as six bytes of their own. The result is valid UTF-8 and renders as three
        glyphs of nonsense, so nothing reports it: no decode fails, no linter objects, and the text reads
        correctly to every tool in the chain. It had reached the files this app writes for the user - the
        title of every Steam shortcut said three characters where a dash belonged - and the progress text in
        the organize view. No test caught it because the checks in this suite read markup and geometry, not
        glyphs.
        """
        offenders=[f'{path.relative_to(ROOT)}:{number}' for path,text in shipped_texts()
                   for number,line in enumerate(text.splitlines(),1) if DOUBLE_ENCODED.search(line)]
        self.assertEqual(offenders,[],
                         'double-encoded punctuation, which renders as mojibake: '+', '.join(offenders[:5]))

    def test_the_detector_itself_recognises_both_shapes(self):
        """A guard that cannot fail is not a guard, and this one is built out of the bytes it looks for.

        Asserted against what cp1252 actually produces for those byte sequences, so a later edit to the
        pattern cannot quietly stop matching and leave the rule above passing over real occurrences. The
        correctly encoded characters are checked too: the tree is full of real dashes on purpose, and a rule
        that flagged those would be unusable rather than strict.
        """
        self.assertTrue(DOUBLE_ENCODED.search(_mojibake('\u2014')),'an em dash round-tripped through cp1252')
        self.assertTrue(DOUBLE_ENCODED.search(_mojibake('\u2026')),'an ellipsis round-tripped through cp1252')
        self.assertTrue(DOUBLE_ENCODED.search(_mojibake('\u2019')),'a curly apostrophe round-tripped through cp1252')
        self.assertIsNone(DOUBLE_ENCODED.search('Celeste — Steam'),'a correctly encoded em dash was flagged')
        self.assertIsNone(DOUBLE_ENCODED.search('Ready – steady'),'a correctly encoded en dash was flagged')
        self.assertIsNone(DOUBLE_ENCODED.search('plain ascii text'),'ordinary text was flagged')

