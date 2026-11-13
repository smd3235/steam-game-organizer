"""Pure utility functions extracted from ScanView.

These functions have no dependency on ScanView instance state and can be
imported and tested independently. They were previously methods on ScanView
that took all their inputs as parameters.
"""

from __future__ import annotations

import time

from utils.formatting import human_size


def ago(stamp) -> str:
    """How long ago a scan ran, in the largest unit worth naming.

    Previously ScanView._ago.
    """
    try:
        seconds = max(0, int(time.time() - float(stamp)))
    except (TypeError, ValueError):
        return ""
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def space_delta(event) -> str:
    """Formats "what it was, what it became, and the difference" for one finished conversion.

    Returns '' unless the event carries both sizes, so a stage that has not got a target yet is left
    alone rather than shown as a misleading zero.

    Previously ScanView._space_delta.
    """
    source = int(event.get("source_bytes") or 0)
    target = int(event.get("target_bytes") or 0)
    if not source or not target:
        return ""
    delta = target - source
    sign = "+" if delta > 0 else "-"
    share = (abs(delta) / source * 100.0) if source else 0.0
    source_format = str(event.get("source_format") or "").upper()
    target_format = str(event.get("target_format") or "7Z").upper()
    lead = f"{source_format} " if source_format else ""
    # A .7z rebuilt over an already-compressed .7z is not a conversion, and the size line would otherwise
    # imply a format change that did not happen.
    return f"{lead}{human_size(source)} → {target_format} {human_size(target)}   ({sign}{human_size(abs(delta))}, {sign}{share:.1f}%)"


def size(n) -> str:
    """Format a byte count as a human-readable string.

    Previously ScanView._size.
    """
    return human_size(n)
