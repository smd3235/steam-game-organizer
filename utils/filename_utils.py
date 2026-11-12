"""Turning a raw archive filename into a stable game identity.

normalize_name() strips release-group tags, date stamps and build numbers so
"Zeta Wars v 1 0.zip" and "Zeta Wars (v1.0).zip"
collapse to the same title. identity_key() folds that to lowercase alphanumerics so
two archives with different packaging still match as one game. version_key() pulls
the version number (or date stamp) out of the filename so organizer can pick the
newest copy of a game when several share a folder.

2026-11-11: Added region/language tag stripping (MULTI5-13, USA, EUR, JAP, PAL, NTSC),
crack-by tags (CRACKED BY, CRACK:, CRACKED-BY), content tags (UNCUT, UNCENSORED, GORE,
NODVD, NO-DVD, FIX), and standalone/only removal so archives whose filenames carry
scene packaging still normalize to the Steam title. Reverted the `incremental`,
`complete`, and `final` additions to the trailing-word regex -
`incremental` is a legitimate game genre (idle/incremental games), so stripping it
would rename a game folder to something the player didn't name it. Kept the original
`multi|proper|portable|iso` list.
"""

import re
from pathlib import Path
from core.constants import ARCHIVE_EXTENSIONS

# Release groups write their name into the folder as a separator-delimited word, with anything after it being
# packaging rather than the game. The set is deliberately short and scene-specific: a tag only earns a place here
# if no real game title is built around it, because a false positive here renames a game folder.
RELEASE_TAG = re.compile(
    r"[\s._\-]*[\(\[\{]?\s*(?:"
    r"steam[\s._\-]*rip|steam[\s._\-]*rg|repack(?:ed|ing)?|reloaded|drm[\s._\-]*free"
    r"|fit[\s._\-]*girl|dodi|tenoke|el[\s._\-]*amigos|razor\s*1911"
    r")\s*[\)\]\}]?(?:\s+by\s+\S+)?(?:\s*\.\s*[a-z]{2,4}\b)?\s*.*$",
    re.I,
)

# Region / language tags that scene releases append to the title. These are always packaging,
# never part of the game's Steam title, so they are safe to strip from the end.
REGION_TAG = re.compile(r"\s+(?:multi\d{1,2}|usa|eur|jap|jpn|pal|ntsc)\s*$", re.I)

# Cracked-by / release-group credit tags that appear at the end of a filename and have nothing
# to do with the game title.
CRACK_TAG = re.compile(
    r"\s*(?:cracked?[-.\s]*(?:by|:|-)|crack:)\s+\S.*$|\s+cracked?\s*$",
    re.I,
)

# Content / packaging words that can appear at the end of a filename but are not part of the
# game's title on Steam.
CONTENT_TAG = re.compile(
    r"\s+(?:uncut|uncensored|gore|nodvd|no-dvd|fix|standalone|only)\s*$",
    re.I,
)

def normalize_name(value: str) -> str:
    """Strip packaging words from an archive or folder name to leave the game's title.

    Removes release-group tags (FitGirl, DODI, TENOKE…), region/language tags
    (MULTI5, USA, EUR, JAP…), crack-by credits (CRACKED BY GROUP), content tags
    (UNCUT, UNCENSORED, GORE, NODVD…), standalone/only markers, trailing indicators
    ((2), [Copy], v2…), multi/proper/portable/ISO suffixes, dates glued to the
    last word, and build stamps. What remains should match what Steam's store
    calls the game.
    """
    p = Path(value)
    if p.suffix.lower() in ARCHIVE_EXTENSIONS:
        value = p.stem
    # Split consecutive capitals before a capital+lowercase word: XMLParser → XML Parser, AGame → A Game.
    # This runs before the lowercase-to-uppercase split so both halves of "AGameAboutOpeningAChest" are
    # separated: A Game About Opening A Chest.
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    value = re.sub(r"[._+]+", " ", value)
    # value=re.sub(r"\s*\[[^\]]*\]\s*"," ",value)
    # value=value.replace("[", " ").replace("]", " ").replace("{", " ").replace("}", " ")
    value = re.sub(r"\s*\([^)]*(?:repack|portable|crack|gog|steam|linux|windows|fitgirl|dodi|codex|tenoke)[^)]*\)", " ", value, flags=re.I)
    # Crack-by credits: "Cracked by GROUP", "CRACK: GROUP", "CRACKED-BY GROUP", bare "CRACKED" - release
    # group attribution that has nothing to do with the game title. Runs before RELEASE_TAG so that
    # "CRACK: TENOKE" is stripped as a whole rather than RELEASE_TAG eating "TENOKE" and leaving "CRACK:" behind.
    value = CRACK_TAG.sub(" ", value)
    # A release-group tag is a separator-delimited word, and everything from it on is packaging rather than the
    # game: "Stellar.Squirrel-SteamRIP.com" is Stellar Squirrel, and so is anything tagged -RELOADED or
    # .REPACKED. Cutting at the first one is what makes the title matchable - the Steam query used to build its
    # variants from the tagged string, so it searched for "Neon Overdrive-Steam" and never for "Neon Overdrive".
    #
    # Both halves of that matter. Requiring a separator before the tag is what catches the hyphen and dot forms,
    # which the old \s+ anchor missed; requiring a word boundary after it is what stops it eating real titles,
    # which it used to do - "Some Game Multiplayer" became "Some Game player" and "Game Properly Done" became
    # "Game ly Done", because multi and proper were matched with no trailing boundary at all.
    value = RELEASE_TAG.sub("", value)
    # These four are ordinary English as well as tags, so they only count as a tag when they are the last word.
    # "multi", "proper", "portable", "iso" are release/packaging states, not title words.
    # Do not add genre words here - "incremental" is a real genre (idle/incremental games), and
    # stripping it would rename a game folder to something the player didn't name it.
    value = re.sub(r"\s+(?:multi|proper|portable|iso)\s*$", " ", value, flags=re.I)
    # Region / language tags appended by scene releases - MULTI5 through MULTI13, USA, EUR,
    # JAP, JPN, PAL, NTSC. Always packaging, never part of the Steam title.
    value = REGION_TAG.sub(" ", value)
    # Content / packaging words at the end: UNCUT, UNCENSORED, GORE, NODVD, NO-DVD, FIX,
    # STANDALONE, ONLY - describe the release, not the game.
    value = CONTENT_TAG.sub(" ", value)
    # Content / packaging words at the end: UNCUT, UNCENSORED, GORE, NODVD, NO-DVD, FIX,
    # STANDALONE, ONLY - describe the release, not the game.
    value = CONTENT_TAG.sub(" ", value)
    # Remove trailing indicators like (2), [Copy], (v2), etc. that should not affect identity
    # Remove all such trailing indicators (there may be more than one)
    while True:
        new_value = re.sub(r"\s*[\(\[\{]\s*(?:v?\d+|(?:copy|draft|temp|backup|old|new|original|no\s*dlc))[^)\]\}]*[\)\]\}]\s*$", " ", value, flags=re.I)
        if new_value == value:
            break
        value = new_value
    value = re.sub(r"\s+", " ", value).strip(" -_")
    value = re.sub(r"[\s._\-]+v?\s*\d+(?:[.\-_ ]+\d+){1,5}[a-z]?(?:\s|$)", " ", value, flags=re.I)
    value = re.sub(r"(?:^|\s+)(build\s*)\d+(?:[.\-_ ]+\d+)*\s*$", r"\1", value, flags=re.I)
    value = re.sub(r"\s+\d{4}[-.]\d{2}[-.]\d{2}(?:\s|$)", " ", value)
    # A build stamp glued to the end of the title: alphanumeric mixes like "2v10112645585273" or
    # "123r6s" (preceded by a letter or a space), or short pure digits like "10" or "171" glued to
    # a letter. Single-digit stamps (Tunnel Runner2, Grand Crime City5) and short codes like "7x9b" are kept because
    # they are part of the title, not a version.
    value = re.sub(r"(?<=[a-zA-Z\s])(?:\d{2,}[a-z]+\d+[a-z]*|\d[a-z]+\d{3,}[a-z]*)\s*$", "", value)
    value = re.sub(r"(?<=[a-zA-Z])\d{2,}\s*$", "", value)
    return re.sub(r"\s+", " ", value).strip(" -_")


def identity_key(value: str) -> str:
    """Fold a name to lowercase alphanumerics so two spellings of one game match."""
    return re.sub(r"[^a-z0-9]+", "", normalize_name(value).casefold())


def version_key(value: str) -> tuple:
    """Pull the version number or date stamp out of a filename, or (0,) when there is none.

    Used to order several archives of the same game so the newest copy wins.
    """
    stem = Path(value).stem
    matches = re.findall(r"(?i)(?:\bv\s*)?(\d+(?:[.\-_]\d+){1,4})(?!\d)", stem)
    if matches:
        return tuple(int(x) for x in re.split(r"[.\-_]", matches[-1]))
    spaced = re.search(r"(?i)\bv\s*(\d+(?:\s+\d+){1,4})\s*$", stem)
    if spaced:
        return tuple(int(x) for x in spaced.group(1).split())
    date = re.search(r"(?:^|[^\d])(20\d{6,})(?:$|[^\d])", stem)
    if date:
        return (int(date.group(1)),)
    return (0,)
