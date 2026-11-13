"""Extracted from services/extract_service.py.

    clear_tool_cache was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""


def clear_tool_cache():
    """No-op retained for API compatibility.

    find_tool() re-scans on every call, so there is nothing to invalidate.
    """
    pass
