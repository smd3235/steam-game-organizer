"""Extracted from services/catalog_service.py.

    sort_date was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

# Month name to number, for sorting Steam release dates. Moved here from catalog_service
# to avoid a circular import (catalog_service imports sort_date).
MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
import re


def sort_date(text) -> str:
    """A sortable YYYYMMDD key from a Steam release date, or '00000000' when there is no usable date.

    Steam writes these in at least two shapes - "Jun 24, 2026" and "1 Jan, 2024" - and any part can be missing.
    Stripping the non-digits and taking the first four characters, which is what this did before, survives
    neither shape: it returned "6242" for "Jun 24, 2026", because the first digits in that string are the day.
    Sorting on that key was sorting on the day of the month.

    A missing month or day becomes '00', so a date with only a year still lands in the right year and ties with
    its neighbours instead of sorting to one end of the library.
    """
    raw = str(text or "")
    year = re.search(r"\b((?:19|20)\d{2})\b", raw)
    if not year:
        return "00000000"
    month = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", raw, re.IGNORECASE)
    day = re.search(r"\b(\d{1,2})\b", raw)
    day_value = int(day.group(1)) if day and int(day.group(1)) <= 31 else 0
    return f"{year.group(1)}{MONTHS[month.group(1).lower()]:02d}{day_value:02d}" if month else (f"{year.group(1)}00{day_value:02d}")
