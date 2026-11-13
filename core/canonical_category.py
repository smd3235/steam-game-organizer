"""Extracted from core/constants.py.

    canonical_category was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""


from core.constants import CATEGORY_ALIASES
def canonical_category(value):
    text = " ".join(str(value or "").split()).strip()
    return CATEGORY_ALIASES.get(text.casefold(), text)
