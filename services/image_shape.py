"""Extracted from services/artwork_service.py.

    image_shape was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

# JPEG frame headers: every marker from SOF0 to SOF15 except DHT (0xC4), JPG (0xC8) and DAC (0xCC).
_SOF_MARKERS = {marker for marker in range(0xC0, 0xD0)} - {0xC4, 0xC8, 0xCC}


def image_shape(path):
    """True if the image at path is portrait, False if it is wide, None if it cannot be read as a JPEG.

    Read from the file's own header rather than by shelling out to ffprobe, because that made the answer depend
    on whether ffmpeg happened to be installed on the machine. It was not: missing ffprobe raised, the failure
    was caught, and the function returned False - indistinguishable from "wide". Every caller below deletes what
    it is told is the wrong shape, so on a machine without ffmpeg the cache emptied itself at startup and every
    portrait download was thrown away the instant it landed. That is why the artwork worked on some machines and not
    on others. Unknown is now a third answer, and nothing is deleted on it: a cache is cheap to keep and
    expensive to lose, and an unreadable file is a reason to look again, not to delete.
    """
    try:
        with open(path, "rb") as handle:
            data = handle.read(65536)
    except OSError:
        return None
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        if marker == 0xD9 or index + 4 > len(data):
            return None
        length = int.from_bytes(data[index + 2 : index + 4], "big")
        if length < 2:
            return None
        if marker in _SOF_MARKERS:
            height = int.from_bytes(data[index + 5 : index + 7], "big")
            width = int.from_bytes(data[index + 7 : index + 9], "big")
            return bool(width and height and height > width and width / height < 0.85)
        index += 2 + length
    return None
