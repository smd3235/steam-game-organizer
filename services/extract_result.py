"""Extracted from services/extract_service.py.

    ExtractResult was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

from dataclasses import dataclass


@dataclass
class ExtractResult:
    archive: object
    destination: object
    ok: bool
    message: str
    extracted_bytes: int = 0
    file_count: int = 0
    code: int = 0
    # True when the extracted contents were recognised as an installer layout and relocated into a
    # "Needs Install" folder. Carried separately so the batch view can flag the row without parsing the message.
    needs_install: bool = False

    @property
    def summary(self) -> str:
        return self.message
