"""Constants shared across the app, each with the reason it exists written beside it.

APP_NAME, ENTRY_POINT, VERSION and USER_AGENT identify the app; ARCHIVE_EXTENSIONS
is what the scanner treats as a game; NO_WINDOW keeps bundled 7z from flashing a
console; DEFAULT_CATEGORIES is the starting set the review screen can file under;
LOCK_MARKER, PROCESSING_DIRNAME and the TEMP_* names mark in-flight conversion
work so a scan never offers a half-built archive as a game; COMPRESSION_LEVEL and
friends tune 7-Zip against real memory headroom.
"""

import subprocess

# CategoryEvidence extracted to core\category_evidence.py — see that module for its definition.
from core.category_evidence import CategoryEvidence
APP_NAME = "Steam Game Organizer"
# The entry point's filename, in one place. It was spelled out in the protocol-handler installer and asserted by
# name in the release-structure tests, so it was two places to change and one place nobody remembered. Renaming
# the app is otherwise a change to this line alone.
ENTRY_POINT = "steam_game_organizer.py"
VERSION = "9.33"
# The one place a version is allowed to be written out. This string was hardcoded as ".../9.0" in five places
# and never moved again, so every request to Steam's API, to SteamGridDB, and every artwork fetch still
# identified the app as 9.0 long after the release it shipped in. Derived here so a version bump cannot leave
# it behind.
USER_AGENT = f"{APP_NAME}/{VERSION}"
ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z"}
# On Windows, pass this to subprocess.run/Popen so that console applications
# (7z.exe etc.) don't flash a CMD window when the app itself runs windowed.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DEFAULT_CATEGORIES = ["Action", "Adventure", "Casual", "Automation", "Idle", "Management", "RPG", "Simulation", "Strategy", "Survival", "Unsorted"]

SUPPLEMENTAL_CATEGORIES = [
    "Roguelike",
    "Soulslike",
    "Tidy Up",
    "Cozy",
    "Bullet Heaven",
    "Metroidvania",
    "Platformer",
    "First-Person Shooter",
    "Third-Person Shooter",
    "Fighting",
    "Horror",
    "Puzzle",
    "Tower Defense",
    "Deckbuilding",
    "Card Game",
    "Turn-Based",
    "Tactical",
    "Stealth",
    "Sandbox",
    "Open World",
    "Exploration",
    "Walking Sim",
    "Life Sim",
    "Tycoon",
    "Shop Management",
    "City Builder",
    "Fishing",
    "Cooking",
    "Farming",
    "Crafting",
    "Party Game",
    "Local Co-op",
    "Rhythm",
    "Visual Novel",
]

CATEGORY_ALIASES = {
    "factory": "Automation",
    "factory sim": "Automation",
    "automation": "Automation",
    "city builder": "City Builder",
    "city sim": "City Builder",
    "sim city": "City Builder",
    "city-building": "City Builder",
    "citybuilder": "City Builder",
    "town builder": "City Builder",
    "town sim": "City Builder",
    "colony sim": "City Builder",
    "colony builder": "City Builder",
    "rogue": "Roguelike",
    "roguelike": "Roguelike",
    "roguelite": "Roguelike",
    "rogue-like": "Roguelike",
    "rogue-lite": "Roguelike",
    "roguelikes": "Roguelike",
    # "Survival" is the block-crafting one - gather, craft, build a base, try not to starve. "Bullet Heaven" is
    # the horde auto-shooter one - a horde closing in, auto-attacks, dodge everything. They are different genres
    # and stay apart; only the confusingly named "Survivors" entry is folded into "Survival", because that is
    # the same genre under a second name and two names for one genre is how games end up in two folders.
    "survivors": "Survival",
    "survivor": "Survival",
    "survival game": "Survival",
    "survival crafting": "Survival",
    "survival sim": "Survival",
    "voxel": "Survival",
    "horde auto-shooter": "Bullet Heaven",
    "horde-auto-shooter": "Bullet Heaven",
    "horde shooter": "Bullet Heaven",
    "bullet hell survivor": "Bullet Heaven",
    "bullet-heaven": "Bullet Heaven",
    "bullet heaven survivors": "Bullet Heaven",
    # Every word this one has been filed under, including the category's own previous name. A saved decision or
    # a Steam genre that says "Cleanup" has to keep landing in the same folder, or eleven tidy-up games silently
    # split off into a folder the picker no longer offers.
    "cleanup": "Tidy Up",
    "clean up": "Tidy Up",
    "clean-up": "Tidy Up",
    "tidy up": "Tidy Up",
    "tidy-up": "Tidy Up",
    "tiding": "Tidy Up",
    "tidying": "Tidy Up",
    "decluttering": "Tidy Up",
    "souls-like": "Soulslike",
    "soulslike": "Soulslike",
    "tower defence": "Tower Defense",
    "turn based": "Turn-Based",
    "deck builder": "Deckbuilding",
    "deck-building": "Deckbuilding",
    "fps": "First-Person Shooter",
    "third person shooter": "Third-Person Shooter",
    "walking simulator": "Walking Sim",
    "life simulation": "Life Sim",
    "farming simulation": "Farming",
    "management sim": "Management",
    "idle": "Idle",
    "idle game": "Idle",
    "clicker": "Idle",
    "clicker game": "Idle",
    "incremental": "Idle",
    "incremental game": "Idle",
}

IGNORED_AUTO_CATEGORIES = {"indie", "early access", "free to play", "multiplayer", "single-player", "single player", "online co-op", "co-op", "massively multiplayer"}

# The evidence for every path that lands on Unsorted without scoring a single candidate:
# no genres at all, or only ignored ones and no keyword hit anywhere. One shared frozen
# instance, so the classifier's early return and the controller's "the Steam lookup
# found nothing" branch cannot drift apart.
UNSORTED_EVIDENCE = CategoryEvidence(chosen="Unsorted", score=0, basis="fallback")

# suggest_category_with_evidence extracted to core\suggest_category_with_evidence.py — see that module for its definition.
# Imported after CATEGORY_ALIASES, IGNORED_AUTO_CATEGORIES and UNSORTED_EVIDENCE because that module imports
# canonical_category (which needs CATEGORY_ALIASES) and references IGNORED_AUTO_CATEGORIES and UNSORTED_EVIDENCE.
# Placing it here avoids a circular import at module load time.
from core.suggest_category_with_evidence import suggest_category_with_evidence

def suggest_category(genres, title="", description="", tags=None, steam_categories=None):
    """Choose a specific Steam genre using genre, tag, category, title, and description evidence."""
    return suggest_category_with_evidence(genres, title, description, tags, steam_categories)[0]

# Marker file written into a repack folder recording the owning process, so an abandoned extraction can be
# told apart from one a conversion is still writing into.
LOCK_MARKER = ".organizer-lock"

# Where in-flight conversions are built. A rebuild used to write its output into the game folder under a
# temp name, so a folder being converted held the source plus a partial replacement. Anything reading the
# folder had to know that temp convention to tell a real archive from a half-written one - and dedupe,
# which trusts .7z over .zip/.rar, once archived an intact source in favour of a partial .7z built by a
# conversion running at the same moment. Staging outside the game folders makes a converted game folder
# hold exactly one thing at all times: its source, untouched, until the replacement is verified and moved
# in. The rename is still atomic because this lives under the same library root, i.e. the same filesystem.
PROCESSING_DIRNAME = "Processing"
# Directories the library owns for its own bookkeeping and never treats as game categories.
LIBRARY_RESERVED_DIRS = frozenset({"Archive", PROCESSING_DIRNAME})

# Names for the app's own in-flight work, wherever it happens to be written. The extraction folder sits inside
# the game folder (the build needs the free space there) and the no-library-root fallback puts the build
# beside the source, so both have to be recognisable from the outside: a scan must not offer their contents as
# games, and the cleanup pass must not delete a build that is still being written.
TEMP_DIR_PREFIX = ".organizer-repack-"
TEMP_FILE_TAG = ".organizer-temp"

# 7z compression level ceiling for rebuilt archives, and the floor the adaptive step-down will not go below.
# v9.0 pinned -mx=9, whose 64 MB LZMA2 dictionary grows to ~2.5 GB of match finder on this library's
# archives. Against anything else running that exhausts RAM and swap and kills 7z mid-write, so the
# level is now chosen per archive against real headroom and stepped down if a build fails anyway.
COMPRESSION_LEVEL = 9
MIN_COMPRESSION_LEVEL = 5
# Peak RSS measured for each level on a 354 MB extraction. Usage tracks the LZMA2 dictionary almost
# linearly, which is why 8 and 9 cost the same: both use a 64 MB dictionary, and 9 squeezes more.
LEVEL_RAM_BYTES = {9: 2561 * 1024 * 1024, 8: 2561 * 1024 * 1024, 7: 1400 * 1024 * 1024, 6: 702 * 1024 * 1024, 5: 400 * 1024 * 1024}
# Memory held back for the desktop even when it looks free, so a repack cannot starve the session it is
# running inside. Also the threshold below which existing swap pressure forces a step down.
RAM_HEADROOM_BYTES = 768 * 1024 * 1024
# Thread count for the compressor. Each 7z thread holds its own match finder, so the default thread count
# multiplies the level's memory cost. Two keeps a multi-hour unattended run predictable.
COMPRESSION_THREADS = 2

# The default password for WinZip AES-encrypted game zips in this library. Every archive that ships
# password-protected uses the same value, so it lives here in one place instead of being spelled out
# in archive_service.py, organizer_service.py, controller.py, and the repair tools.
DEFAULT_ZIP_PASSWORD = "123"
