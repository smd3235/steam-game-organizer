"""Extracted from services/artwork_service.py.

    shape_name was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""


def shape_name(shape):
    return "portrait" if shape else "wide" if shape is False else "unknown"
