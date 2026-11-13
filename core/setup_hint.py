"""Extracted from core/uri_actions.py.

    _setup_hint was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""


def _setup_hint():
    """The pointer every fresh-PC refusal carries.

    The three folders the Extract links are checked against are set by the
    setup wizard, and the page that fired the link carries the button that
    opens it - so a refusal on a PC that has not been set up yet names the
    fix rather than only the rule.
    """
    return " The Set up on this PC button at the top of the catalog points this app at the library."
