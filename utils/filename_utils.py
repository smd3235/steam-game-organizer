"""Turning a raw archive filename into a stable game identity.

normalize_name() strips release-group tags, date stamps and build numbers so
"Re Story Chill Electronics Repairs v 1 0.zip" and "Re Story - Chill Electronics Repairs (v1.0).zip"
collapse to the same title. identity_key() folds that to lowercase alphanumerics so
two archives with different packaging still match as one game. version_key() pulls
the version number (or date stamp) out of the filename so organizer can pick the
newest copy of a game when several share a folder.
"""
import re
from pathlib import Path
from core.constants import ARCHIVE_EXTENSIONS

# Release groups write their name into the folder as a separator-delimited word, with anything after it being
# packaging rather than the game. The set is deliberately short and scene-specific: a tag only earns a place here
# if no real game title is built around it, because a false positive here renames a game folder.
RELEASE_TAG=re.compile(
    r'[\s._\-]*[\(\[\{]?\s*(?:'
    r'steam[\s._\-]*rip|steam[\s._\-]*rg|repack(?:ed|ing)?|reloaded|drm[\s._\-]*free'
    r'|fit[\s._\-]*girl|dodi|tenoke|el[\s._\-]*amigos|razor\s*1911'
    r')\s*[\)\]\}]?(?:\s+by\s+\S+)?(?:\s*\.\s*[a-z]{2,4}\b)?\s*.*$',
    re.I,
)

def normalize_name(value:str)->str:
    """Strip packaging words from an archive or folder name to leave the game's title.

    Removes release-group tags (FitGirl, DODI, TENOKE…), trailing indicators
    ((2), [Copy], v2…), multi/proper/portable/ISO suffixes, dates glued to the
    last word, and build stamps. What remains should match what Steam's store
    calls the game.
    """
    p=Path(value)
    if p.suffix.lower() in ARCHIVE_EXTENSIONS: value=p.stem
    value=re.sub(r"([a-z0-9])([A-Z])",r"\1 \2",value)
    value=re.sub(r"[._+]+"," ",value)
    # value=re.sub(r"\s*\[[^\]]*\]\s*"," ",value)
    # value=value.replace("[", " ").replace("]", " ").replace("{", " ").replace("}", " ")
    value=re.sub(r"\s*\([^)]*(?:repack|portable|crack|gog|steam|linux|windows|fitgirl|dodi|codex|tenoke)[^)]*\)"," ",value,flags=re.I)
    # A release-group tag is a separator-delimited word, and everything from it on is packaging rather than the
    # game: "Brave.New.Wonders-SteamRIP.com" is Brave New Wonders, and so is anything tagged -RELOADED or
    # .REPACKED. Cutting at the first one is what makes the title matchable - the Steam query used to build its
    # variants from the tagged string, so it searched for "Mars Attracts-Steam" and never for "Mars Attracts".
    #
    # Both halves of that matter. Requiring a separator before the tag is what catches the hyphen and dot forms,
    # which the old \s+ anchor missed; requiring a word boundary after it is what stops it eating real titles,
    # which it used to do - "Some Game Multiplayer" became "Some Game player" and "Game Properly Done" became
    # "Game ly Done", because multi and proper were matched with no trailing boundary at all.
    value=RELEASE_TAG.sub("",value)
    # These four are ordinary English as well as tags, so they only count as a tag when they are the last word.
    value=re.sub(r"\s+(?:multi|proper|portable|iso)\s*$", " ", value, flags=re.I)
    # Remove trailing indicators like (2), [Copy], (v2), etc. that should not affect identity
    # Remove all such trailing indicators (there may be more than one)
    while True:
        new_value=re.sub(r"\s*[\(\[\{]\s*(?:v?\d+|(?:copy|draft|temp|backup|old|new|original|no\s*dlc))[^)\]\}]*[\)\]\}]\s*$", " ", value, flags=re.I)
        if new_value==value:
            break
        value=new_value
    value=re.sub(r"\s+"," ",value).strip(" -_")
    value=re.sub(r"[\s._\-]+v?\s*\d+(?:[.\-_ ]+\d+){1,5}[a-z]?(?:\s|$)"," ",value,flags=re.I)
    value=re.sub(r"(?:^|\s+)(build\s*)\d+(?:[.\-_ ]+\d+)*\s*$", r"\1", value, flags=re.I)
    value=re.sub(r"\s+\d{4}[-.]\d{2}[-.]\d{2}(?:\s|$)"," ",value)
    # A date or build stamp glued straight onto the last word - "FarmToTable10122" - is packaging, not title.
    # Four digits is the floor because "Portal2" and "GTA5" are titles, while a stamp is never that short. The
    # spaced form above is left alone on purpose: "Racing Series 20260916" is kept, and a test says so.
    value=re.sub(r"(?<=[A-Za-z])\d{4,}$", "", value)
    return re.sub(r"\s+"," ",value).strip(" -_")

def identity_key(value:str)->str:
    """Fold a name to lowercase alphanumerics so two spellings of one game match."""
    return re.sub(r"[^a-z0-9]+","",normalize_name(value).casefold())


def version_key(value:str)->tuple:
    """Pull the version number or date stamp out of a filename, or (0,) when there is none.

    Used to order several archives of the same game so the newest copy wins.
    """
    stem=Path(value).stem
    matches=re.findall(r"(?i)(?:\bv\s*)?(\d+(?:[.\-_]\d+){1,4})(?!\d)",stem)
    if matches:
        return tuple(int(x) for x in re.split(r"[.\-_]",matches[-1]))
    spaced=re.search(r"(?i)\bv\s*(\d+(?:\s+\d+){1,4})\s*$",stem)
    if spaced:return tuple(int(x) for x in spaced.group(1).split())
    date=re.search(r"(?:^|[^\d])(20\d{6,})(?:$|[^\d])",stem)
    if date:return (int(date.group(1)),)
    return (0,)



