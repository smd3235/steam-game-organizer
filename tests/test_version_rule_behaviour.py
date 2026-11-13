"""Extracted from tests/test_release_structure.py.

    VersionRuleBehaviour was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import re
import sys
import unittest
from pathlib import Path
from core.constants import APP_NAME
from tests.test_helpers import DOUBLE_ENCODED
from tests.test_helpers import MAX_SCANNED_BYTES
from tests.test_helpers import _mojibake
from tests.test_release_structure import ROOT
from tests.test_release_structure import app_name_pattern
from tests.test_release_structure import change_log_versions
from tests.test_release_structure import read_shipped
from tests.test_release_structure import shipped_texts
from tests.test_release_structure import version_violations
from core.constants import VERSION


class VersionRuleBehaviour(unittest.TestCase):
    """The rule itself, on synthetic input, so that weakening it later is visible rather than silent.

    The stale values are assembled from APP_NAME and STALE rather than written out, because this file is itself
    scanned: a fixture spelled out in full would be a real stale declaration sitting in the repository, and the
    gate would rightly fail on its own test.
    """

    STALE = "9.0"

    def _violations(self, text, markdown=False):
        return [found for _, found, _ in version_violations(text, markdown)]

    def test_a_stale_version_in_a_string_is_a_violation(self):
        self.assertEqual(self._violations(f'req=Request(u,headers={{"User-Agent":"{APP_NAME}/{self.STALE}"}})'), [self.STALE])

    def test_a_stale_version_quoted_in_a_comment_is_not(self):
        self.assertEqual(self._violations(f'# it was hardcoded as "{APP_NAME}/{self.STALE}" everywhere'), [])

    def test_a_change_log_note_keeps_its_own_date(self):
        self.assertEqual(self._violations(f'# v9.11 change log: was "{APP_NAME}/9.11"'), [])

    def test_a_change_log_note_is_read_for_the_release_it_claims(self):
        """The exemption and the check that replaced it are two different reads of the same line.

        A note used to be only ever skipped. It is now also held to the version it names, which is the half that
        was missing - so the reader itself needs a test, or a later change could quietly turn it back into a skip
        and the gate would report clean while six undocumented releases sat in the tree.
        """
        self.assertEqual([found for _, found, _ in change_log_versions("# v9.11 change log: a fix")], ["9.11"])

    def test_only_a_real_change_log_note_is_read(self):
        """The marker is what makes a line a note.

        Otherwise any sentence mentioning a version beside the words "change log" would be read as a release
        claim - including the ones explaining the convention, and this one.
        """
        self.assertEqual(list(change_log_versions("the v9.11 change log convention records a release")), [])
        self.assertEqual(list(change_log_versions("# v9.11 was a release")), [])

    def test_a_note_naming_the_current_version_is_read(self):
        """A note for the release being worked on is the normal case, and the gate has to leave it alone."""
        self.assertEqual([found for _, found, _ in change_log_versions(f"# v{VERSION} change log: current")], [VERSION])

    def test_the_note_reader_ignores_a_version_without_a_minor_part(self):
        """`v9` is not a release this project ships - VERSION is asserted to be major.minor - so it is not a note.

        Read loosely it would become a version to compare, and comparing '9' against '9.16' is not a comparison.
        """
        self.assertEqual(list(change_log_versions("# v9 change log: no minor part")), [])

    def test_ordinary_floats_are_not_versions(self):
        self.assertEqual(self._violations("report(msg,progress=1.0,factor=2.5,ratio=0.5)"), [])

    def test_the_word_conversion_is_not_a_version_label(self):
        """ "conversion" contains "version", so a label match that did not stop at the end of a word would fire
        on every `conversion=` in the codebase rather than on anything to do with a release."""
        self.assertEqual(self._violations(f'conversion_ratio=1.0; stage_conversion=1.0; conversion_x="{self.STALE}"'), [])

    def test_a_labelled_version_literal_is_a_violation(self):
        label = "APP_VERSION"
        self.assertEqual(self._violations(f'{label} = "{self.STALE}"'), [self.STALE])
        header = "X-App-Version"
        self.assertEqual(self._violations(f"req=Request(u,headers={{'{header}': '{self.STALE}'}})"), [self.STALE])

    def test_markdown_prose_may_quote_the_version_it_fixed(self):
        self.assertEqual(self._violations(f"It identified itself as {APP_NAME}/{self.STALE}.", True), [])

    def test_a_markdown_code_sample_may_not(self):
        """The gap this rule was tightened to close: a sample is a specimen of what the code should say, so a
        stale version inside one is the same defect as a stale version in the code it documents."""
        self.assertEqual(self._violations(f"```\nUser-Agent: {APP_NAME}/{self.STALE}\n```\n", True), [self.STALE])

    def test_a_markdown_change_log_note_keeps_its_own_date(self):
        self.assertEqual(self._violations(f"# v9.9 change log: this described v{self.STALE}", True), [])

    def test_a_document_heading_is_a_declaration(self):
        self.assertEqual(self._violations(f"# {APP_NAME} v{self.STALE}", True), [self.STALE])

    def test_the_current_version_is_never_a_violation(self):
        self.assertEqual(self._violations(f'req=Request(u,headers={{"User-Agent":"{APP_NAME}/{VERSION}"}})'), [])
        self.assertEqual(self._violations(f"# {APP_NAME}/{VERSION} is current"), [])
        self.assertEqual(self._violations(f"# {APP_NAME} v{VERSION}", True), [])

    def test_the_user_agent_pattern_survives_how_it_is_actually_written(self):
        """The pattern was case-sensitive and allowed only a slash or space after the name, so it missed a
        lowercased product name, an unspaced token, and a dash separator. Each is pinned below."""
        for written in (f"{APP_NAME}/{self.STALE}", f"{APP_NAME.lower()}/{self.STALE}", f"{APP_NAME.replace(' ', '')}/{self.STALE}", f"{APP_NAME} - {self.STALE}", f"{APP_NAME} v{self.STALE}", f"Mozilla/5.0 {APP_NAME}/{self.STALE}"):
            self.assertEqual(self._violations(f'H={{"User-Agent":"{written}"}}'), [self.STALE], f"the rule missed a User-Agent written as {written!r}")

    def test_it_still_follows_a_renamed_application(self):
        """The name comes from the constant, so a rename cannot leave the rule matching a string nothing
        sends any more."""
        pattern = app_name_pattern()
        self.assertIn(re.escape(APP_NAME.split()[0]), pattern)
        self.assertNotIn(re.escape(APP_NAME), pattern, "the product name is matched with its spaces, so an unspaced User-Agent token misses")

    def test_a_binary_or_oversized_file_is_skipped_rather_than_decoded(self):
        import tempfile

        with tempfile.TemporaryDirectory() as scratch:
            binary = Path(scratch) / "logo.png"
            binary.write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe\x00binary")
            self.assertIsNone(read_shipped(binary), "a binary file was read as text")
            huge = Path(scratch) / "big.md"
            huge.write_text("x" * (MAX_SCANNED_BYTES + 1), encoding="utf-8")
            self.assertIsNone(read_shipped(huge), "an oversized file was read as text")
            plain = Path(scratch) / "notes.md"
            plain.write_text("a note\n", encoding="utf-8")
            self.assertEqual(read_shipped(plain), "a note\n")

    def test_files_are_found_by_content_not_by_extension(self):
        """An extension allowlist made a newly added file type invisible until someone remembered to list it,
        and `.gitignore` was already being skipped for having no extension."""
        self.assertFalse(hasattr(sys.modules[__name__], "SOURCE_SUFFIXES"), "the extension allowlist is back; files are meant to be found by content")
        scanned = {path.name for path, _ in shipped_texts()}
        self.assertIn(".gitignore", scanned, "a shipped file with no extension is not being scanned")

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
        offenders = [f"{path.relative_to(ROOT)}:{number}" for path, text in shipped_texts() for number, line in enumerate(text.splitlines(), 1) if DOUBLE_ENCODED.search(line)]
        self.assertEqual(offenders, [], "double-encoded punctuation, which renders as mojibake: " + ", ".join(offenders[:5]))

    def test_the_detector_itself_recognises_both_shapes(self):
        """A guard that cannot fail is not a guard, and this one is built out of the bytes it looks for.

        Asserted against what cp1252 actually produces for those byte sequences, so a later edit to the
        pattern cannot quietly stop matching and leave the rule above passing over real occurrences. The
        correctly encoded characters are checked too: the tree is full of real dashes on purpose, and a rule
        that flagged those would be unusable rather than strict.
        """
        self.assertTrue(DOUBLE_ENCODED.search(_mojibake("\u2014")), "an em dash round-tripped through cp1252")
        self.assertTrue(DOUBLE_ENCODED.search(_mojibake("\u2026")), "an ellipsis round-tripped through cp1252")
        self.assertTrue(DOUBLE_ENCODED.search(_mojibake("\u2019")), "a curly apostrophe round-tripped through cp1252")
        self.assertIsNone(DOUBLE_ENCODED.search("Celeste — Steam"), "a correctly encoded em dash was flagged")
        self.assertIsNone(DOUBLE_ENCODED.search("Ready – steady"), "a correctly encoded en dash was flagged")
        self.assertIsNone(DOUBLE_ENCODED.search("plain ascii text"), "ordinary text was flagged")
