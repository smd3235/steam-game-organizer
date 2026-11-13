"""Pure utility functions extracted from OrganizerService.

These functions have no dependency on OrganizerService instance state and can be
imported and tested independently. They were previously static methods on
OrganizerService that took all their inputs as parameters.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import subprocess
import time
import zipfile


def zip_is_encrypted(path) -> bool:
    """True when the zip's central directory marks any entry as encrypted.

    Python's zipfile reads the flag bits without decrypting, so this is a cheap check
    that needs no password. WinZip AES entries carry bit 0 of the general-purpose flags.
    """
    try:
        with zipfile.ZipFile(path) as source:
            return any(info.flag_bits & 0x1 for info in source.infolist() if not info.is_dir())
    except Exception:
        return False


def looks_like_resource_failure(detail: str) -> bool:
    """True when a build died from memory pressure or an interrupt rather than from bad input.

    7z reports these as exit 255 with 'Break signaled' and no useful explanation, which is
    indistinguishable from a genuine error by exit code alone. Retrying one level lower costs
    a minute; giving up costs the entire extraction.
    """
    text = (detail or "").lower()
    return any(marker in text for marker in ("break signaled", "not enough memory", "out of memory", "cannot allocate", "killed"))


def defender_flagged(detail) -> list[str]:
    """The filenames Windows Defender refused to scan during a 7z build, parsed from its error text.

    7z's content-intelligence integration asks Defender to scan every file as it packs. A file
    Defender flags is reported as "Operation did not complete successfully because the file contains
    a virus or potentially unwanted software", followed by the path on the next line and "The
    system cannot find the file specified" on the line after. The names are extracted from the
    first form, which is stable across 7-Zip versions; the second form is the same file reported
    again after the scan was refused.
    """
    if not detail:
        return []
    names: list[str] = []
    # The actual format is "path : message", not "message path": 7z prints the member path first,
    # then a colon, then the Defender refusal. The earlier version split on the message and took
    # what came after, which found nothing and returned an empty list - so every Defender refusal
    # was reported as a build failure with no exclusions to retry with.
    for line in detail.split("|"):
        line = line.strip()
        if "Operation did not complete successfully because the file contains a virus" not in line:
            continue
        path = line.split(" : ", 1)[0].strip()
        if not path:
            continue
        name = path.replace("\\", "/").lstrip("./").rsplit("/", 1)[-1]
        if name:
            names.append(name)
    return names


def still_running(process) -> bool:
    """Tolerant check whether a process is still alive.

    Runs from finally blocks, so a missing poll() or platform quirk must not turn a handled
    failure into an AttributeError that hides the real cause.
    """
    poll = getattr(process, "poll", None)
    if poll is None:
        return False
    try:
        return poll() is None
    except OSError:
        return False


def stop_tool(process, grace: float = 3.0) -> None:
    """Ends a running archive tool.

    terminate() asks first because 7z closes its output file on SIGTERM and the partial build
    can be reused as a retry candidate; kill() is the backstop for a tool wedged in a syscall.
    Both are needed: a level-9 LZMA2 build under memory pressure can ignore a polite signal
    for a long time.
    """
    if not still_running(process):
        return
    with contextlib.suppress(OSError, AttributeError):
        process.terminate()
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if not still_running(process):
            return
        time.sleep(0.05)
    with contextlib.suppress(OSError, AttributeError):
        process.kill()
    # subprocess.TimeoutExpired is a SubprocessError, not an OSError, so a suppress written for the
    # signals above lets it straight through. That is the one exception this wait can raise, and letting
    # it out of a `finally` replaces whatever was already failing - which is the masking of the real cause
    # that the tolerance above exists to prevent.
    with contextlib.suppress(OSError, AttributeError, subprocess.TimeoutExpired):
        process.wait(timeout=5)


def pid_is_alive(pid: int) -> bool:
    """Whether a process id still exists. Written per platform because the obvious check is wrong here.

    os.kill(pid, 0) is the portable idiom, but on Windows it raises a plain OSError for a pid
    that does not exist as well as for one that does, so treating any OSError as "alive" means
    a dead run's folder is never reclaimed - which is the whole case this sweep exists for.
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        # PROCESS_QUERY_LIMITED_INFORMATION is the least privilege that still answers "does this exist".
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
