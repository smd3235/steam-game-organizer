"""Shared, UI-independent formatting helpers.

These lived only in the view layer, which meant the controller had no way to report a real byte count to the
user without either importing UI code or growing another divergent copy of the same loop.
"""

import time


def human_size(value):
    """Formats a byte count for humans. Returns '-' for unusable input instead of raising, because these
    values arrive from background workers and a bad one must not take down the Tk main loop.

    Trailing '.0' is dropped but the space before the unit is kept: the old '.0 ' replace also ate the space
    and rendered 21 GB as '21GB'."""
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return "-"
    number = abs(number)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if number < 1024:
            text = f"{number:.1f}".removesuffix(".0")
            return f"{text} {unit}"
        number /= 1024
    return f"{number:.1f} PB"


def human_duration(seconds):
    """Formats an elapsed time as MM:SS, growing to H:MM:SS once a run passes the hour mark."""
    try:
        total = int(float(seconds or 0))
    except (TypeError, ValueError):
        total = 0
    if total < 0:
        total = 0
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def clock_stamp(when=None):
    return time.strftime("%H:%M:%S", time.localtime(when)) if when else time.strftime("%H:%M:%S")
