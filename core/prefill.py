"""Extracted from core/uri_actions.py.

    _prefill was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""


def _prefill(values):
    """One query value, cleaned for a text box: control characters dropped, length capped.

    A path box holds a path, and a path is neither a megabyte long nor full of newlines;
    the cap is what keeps a hostile link from stuffing something enormous into the
    wizard's fields.
    """
    text = (values or [""])[0]
    text = "".join(ch for ch in text if ch >= " ")
    return text.strip()[:1000]
