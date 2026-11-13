"""Extracted from tests/test_release_structure.py.

    declared_versions was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""


from tests.test_release_structure import CHANGE_LOG_NOTE
from tests.test_release_structure import DECLARED_NEXT_TO_NAME
from tests.test_release_structure import FENCE
from tests.test_release_structure import LABELLED_VERSION
from tests.test_release_structure import VERSION_IN_HEADING
from tests.test_release_structure import code_before_comment
def declared_versions(text, markdown=False):
    """Yield (line number, version found, the line) for every version this text declares.

    Prose may quote history; code may not. A markdown document outside a fenced block is prose, so a release
    note can say what the User-Agent used to be, while a fenced code sample is a specimen of something that is
    meant to be current and is checked like code. A comment in a source file is likewise prose, which is what
    lets a `# v9.11 change log:` note keep its own date.

    Split out from the test that uses it so the rule can be pinned by synthetic input. A check that has never
    been made to fail is not a check - this repo has shipped one of those twice.
    """
    inside_fence = False
    for number, line in enumerate(text.splitlines(), 1):
        if markdown and FENCE.match(line):
            inside_fence = not inside_fence
            continue
        if markdown and not inside_fence:
            if CHANGE_LOG_NOTE.match(line):
                continue
            match = VERSION_IN_HEADING.match(line)
            if match:
                yield number, match.group(1), line
            continue
        for pattern in (DECLARED_NEXT_TO_NAME, LABELLED_VERSION):
            for match in pattern.finditer(code_before_comment(line) if not markdown else line):
                yield number, match.group(1), line
