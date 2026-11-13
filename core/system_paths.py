"""Extracted from core/uri_actions.py.

    _system_paths was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import os


def _system_paths():
    """Folders a typed destination may never sit inside.

    Read from the environment rather than spelled out, because Windows, Program Files and ProgramData are not
    reliably where a hard-coded list says they are. Folders are case-folded with the platform's own rule,
    because C:\\Windows and C:\\WINDOWS are the same folder here and only one of them is the spelling a user
    types.

    The POSIX half of this list is gone. Every one of those paths is absolute on Windows too, so they could
    never have matched a resolved destination - which begins with a drive letter - and a list that reads as
    though it covers two platforms is worse than one that says plainly which platform it does.
    """
    paths = set()
    for variable in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData", "ProgramW6432"):
        value = os.environ.get(variable)
        if value:
            paths.add(value)
    return tuple(sorted(os.path.normcase(os.path.normpath(p)) for p in paths))
