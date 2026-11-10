"""Constants shared across the app, each with the reason it exists written beside it.

APP_NAME, ENTRY_POINT, VERSION and USER_AGENT identify the app; ARCHIVE_EXTENSIONS
is what the scanner treats as a game; NO_WINDOW keeps bundled 7z from flashing a
console; DEFAULT_CATEGORIES is the starting set the review screen can file under;
LOCK_MARKER, PROCESSING_DIRNAME and the TEMP_* names mark in-flight conversion
work so a scan never offers a half-built archive as a game; COMPRESSION_LEVEL and
friends tune 7-Zip against real memory headroom.
"""

from dataclasses import dataclass
import subprocess

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
    # "Survival" is the Minecraft-shaped one - gather, craft, build a base, try not to starve. "Bullet Heaven" is
    # the Vampire Survivors one - a horde closing in, auto-attacks, dodge everything. They are different genres
    # and stay apart; only the confusingly named "Survivors" entry is folded into "Survival", because that is
    # the same genre under a second name and two names for one genre is how games end up in two folders.
    "survivors": "Survival",
    "survivor": "Survival",
    "survival game": "Survival",
    "survival crafting": "Survival",
    "survival sim": "Survival",
    "voxel": "Survival",
    "vampire survivors": "Bullet Heaven",
    "vampire-survivors": "Bullet Heaven",
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


def canonical_category(value):
    text = " ".join(str(value or "").split()).strip()
    return CATEGORY_ALIASES.get(text.casefold(), text)


@dataclass(frozen=True)
class CategoryEvidence:
    """Why one category was chosen over the others, so a screen can say why, not only what.

    Frozen, with tuple fields, so it survives the copy.deepcopy() that StateStore.get()
    performs on every state read and cannot be edited once it is attached to a decision.
    Every field is a str, an int, or a tuple of those, which keeps the value JSON-native:
    json.dumps(dataclasses.asdict(evidence)) needs no custom encoder.

    basis is the closed vocabulary a screen reads in one word: "description" when a keyword
    rule won on the title/description text, "tag" when the same rule won on tags or Steam
    categories alone, "genre" when a Steam genre out-scored every rule, "fallback" when
    nothing scored at all and the answer is Unsorted. terms are the keywords that fired, in
    the order they were tested, and are empty for a genre win, where the genre name is the
    reason. runners_up holds at most the next three candidates as (name, score) pairs,
    sorted by score descending then name, so the output is deterministic; a candidate is one
    category, so a category that scored in both passes appears once, with its better score.
    considered counts the candidates that scored above zero, which is how a screen says
    "nothing came close" when it is 0.
    """

    chosen: str
    score: int
    basis: str
    terms: tuple[str, ...] = ()
    runners_up: tuple[tuple[str, int], ...] = ()
    considered: int = 0


# The evidence for every path that lands on Unsorted without scoring a single candidate:
# no genres at all, or only ignored ones and no keyword hit anywhere. One shared frozen
# instance, so the classifier's early return and the controller's "the Steam lookup
# found nothing" branch cannot drift apart.
UNSORTED_EVIDENCE = CategoryEvidence(chosen="Unsorted", score=0, basis="fallback")


def suggest_category_with_evidence(genres, title="", description="", tags=None, steam_categories=None):
    """Choose a specific Steam genre using genre, tag, category, title, and description evidence,
    and return (category, CategoryEvidence): the folder, the rule that won it, the keywords
    that matched, the winning score, and the next-best candidates. suggest_category() below is
    this function with the evidence discarded, so the two can never disagree."""
    text_context = " ".join(str(value) for value in (title, description)).casefold()
    tag_context = " ".join(str(value) for value in (tags or [])).casefold()
    category_context = " ".join(str(value) for value in (steam_categories or [])).casefold()
    genre_values = [canonical_category(value) for value in (genres or []) if str(value).strip()]
    if not genre_values:
        return "Unsorted", UNSORTED_EVIDENCE

    specificity = ("rogue", "soulslike", "metroidvania", "tower defense", "turn-based", "visual novel", "card game", "deckbuilding", "walking simulator", "horror", "fighting", "shooter", "platformer", "puzzle", "racing", "sports")
    evidence = {
        "horror": ("horror", "terrifying", "scary", "dark"),
        "puzzle": ("puzzle", "logic", "brain teaser"),
        "strategy": ("strategy", "tactical", "strategic", "colony", "automation"),
        "simulation": ("simulat", "management", "manager", "tycoon"),
        "rpg": ("rpg", "role-playing", "role playing", "character build"),
        "adventure": ("adventure", "explor", "quest"),
        "action": ("action", "combat", "fight", "battle"),
        "racing": ("racing", "race", "driving"),
        "sports": ("sport", "bowling", "football", "baseball", "fishing"),
        "platformer": ("platform", "jump"),
        "visual novel": ("visual novel", "story"),
        "card game": ("card", "deck"),
    }
    best = "Unsorted"
    best_score = -(10**9)
    best_basis = "fallback"
    best_terms = ()
    # Every candidate that scored at all, in the order it was tested: (category, score).
    # The standings below fold a category that scored in both passes into one entry, so
    # runners_up and considered count candidates rather than passes.
    scored = []
    inferred = {
        "Idle": ("idle", "clicker", "incremental"),
        "City Builder": ("city builder", "city-building", "city building", "build your city", "town builder", "floating city", "colony builder", "town builder"),
        "Automation": ("automation", "automate", "factory", "production line", "industrial production", "build and manage a factory", "logistics", "assembly line"),
        "Management": ("management", "manage your", "run your business", "business management", "company management", "hospital management", "prison management", "zoo management", "theme park management", "restaurant management", "hotel management", "sports management", "fleet management"),
        "Tycoon": ("tycoon", "business empire", "build your empire", "capitalism"),
        "Shop Management": ("shop management", "run your own shop", "store management", "run a store", "merchant", "trading", "economy"),
        "Tidy Up": ("tidy up", "clean up", "declutter", "decluttering", "tidying", "sorting", "organize", "organizing"),
        "Farming": ("farming", "farm simulator", "grow crops", "agriculture", "harvest", "crops", "livestock", "ranch", "ranch simulator"),
        "Horror": ("horror", "terrifying", "scary", "survival horror"),
        # Scored below Horror's default on purpose: "survival horror" contains "survival", and a survival-crafting
        # rule given the ordinary priority would outrank a horror game that says so outright.
        "Survival": ("survival crafting", "craft and survive", "minecraft", "voxel", "try not to starve", "survival sim"),
        "Bullet Heaven": ("bullet hell", "vampire survivors", "survivors-like", "auto attack", "wave of enemies", "horde", "bullet heaven", "survivors like"),
        "Roguelike": ("roguelike", "roguelite", "run-based", "procedural dungeon", "randomly generated dungeon", "roguelite", "permadeath", "procedural generation"),
        "Soulslike": ("soulslike", "souls-like", "punishing combat", "boss-focused combat"),
        "Metroidvania": ("metroidvania", "interconnected map", "backtracking exploration"),
        "Puzzle": ("puzzle", "logic game", "brain teaser", "puzzle game"),
        "Deckbuilding": ("deckbuilding", "deck-building", "build your deck", "deck builder"),
        "Card Game": ("card game", "trading card", "collectible card", "ccg", "tcg"),
        "Tower Defense": ("tower defense", "tower defence", "td game", "defend your base"),
        "Turn-Based": ("turn-based", "turn based combat", "turn based strategy", "turn based tactics", "turn-based tactics"),
        "Strategy": ("strategy game", "strategic", "tactical", "grand strategy", "4x", "real-time strategy", "rts"),
        "RPG": ("role-playing", "role playing", "character progression", "character build", "rpg", "jrpg", "crpg", "action rpg"),
        "Adventure": ("adventure game", "explore", "quest", "point and click", "narrative", "story rich"),
        "Platformer": ("platformer", "jump across", "precision platformer", "3d platformer"),
        "Fighting": ("fighting game", "versus fighting", "combo-based combat", "beat 'em up", "beat em up"),
        "First-Person Shooter": ("first-person shooter", "fps game", "boomer shooter", "arena shooter"),
        "Third-Person Shooter": ("third-person shooter", "over-the-shoulder shooter", "third person shooter"),
        "Stealth": ("stealth", "sneak past", "remain undetected", "stealth action"),
        "Sandbox": ("sandbox", "open-ended sandbox", "creative mode"),
        "Open World": ("open world", "open-world", "exploration"),
        "Walking Sim": ("walking simulator", "narrative walking"),
        "Life Sim": ("life simulation", "life sim", "daily life simulator", "social sim"),
        "Fishing": ("fishing", "angling", "fishing simulator"),
        "Cooking": ("cooking game", "recipes", "restaurant management", "cooking simulator"),
        "Crafting": ("crafting", "gathering and crafting", "crafting system"),
        "Party Game": ("party game", "local multiplayer party", "minigames", "party"),
        "Rhythm": ("rhythm game", "music game", "beat-matching", "rhythm"),
        "Visual Novel": ("visual novel", "branching story", "dialogue-driven story", "vn", "kinetic novel"),
    }
    priority = {"City Builder": 100, "Automation": 95, "Idle": 90, "Survival": 90, "Management": 88, "Tycoon": 86, "Shop Management": 84, "Bullet Heaven": 84}
    for category, terms in inferred.items():
        if any(term in text_context for term in terms):
            score = priority.get(category, 82) + sum(3 for term in terms if term in text_context)
            matched = tuple(term for term in terms if term in text_context)
            scored.append((category, score))
            if score > best_score:
                best_score = score
                best = category
                best_basis = "description"
                best_terms = matched
        elif any(term in tag_context or term in category_context for term in terms):
            score = 38
            matched = tuple(term for term in terms if term in tag_context or term in category_context)
            scored.append((category, score))
            if score > best_score:
                best_score = score
                best = category
                best_basis = "tag"
                best_terms = matched
    for index, genre in enumerate(genre_values):
        normalized = genre.casefold()
        score = 50 - index
        if normalized in IGNORED_AUTO_CATEGORIES:
            continue
        if normalized in {"indie", "casual"}:
            score -= 30
        if normalized in {"simulation", "strategy", "rpg", "action", "adventure"}:
            score += 4
        if normalized in {"city builder", "colony sim", "town builder", "farming sim", "fishing sim", "management"}:
            score += 30
        if normalized in {"automation", "factory sim", "logistics", "production", "industrial"}:
            score += 30
        if normalized in {"idle", "clicker", "incremental"}:
            score += 30
        if normalized in {"roguelike", "roguelite"}:
            score += 30
        if normalized in {"tower defense", "td"}:
            score += 30
        if normalized in {"bullet hell", "vampire survivors"}:
            score += 30
        if normalized in {"deckbuilding", "card game", "trading card"}:
            score += 30
        if normalized in {"visual novel"}:
            score += 30
        if normalized in {"horror", "survival horror"}:
            score += 25
        if normalized in {"puzzle"}:
            score += 25
        if normalized in {"fighting", "beat 'em up"}:
            score += 25
        if normalized in {"racing", "driving"}:
            score += 25
        if normalized in {"sports", "football", "baseball", "basketball"}:
            score += 25
        if normalized in {"rhythm", "music"}:
            score += 25
        if normalized in {"stealth"}:
            score += 25
        if normalized in {"sandbox", "open world"}:
            score += 20
        if any(term in normalized for term in specificity):
            score += 22
        if any(term in text_context for term in evidence.get(normalized, ())):
            score += 18
        if normalized in tag_context or normalized in category_context:
            score += 4
        scored.append((genre, score))
        if score > best_score:
            best_score = score
            best = genre
            best_basis = "genre"
            best_terms = ()
    if best == "Unsorted":
        return "Unsorted", UNSORTED_EVIDENCE
    standings = {}
    for category, score in scored:
        if category not in standings or score > standings[category]:
            standings[category] = score
    runners_up = tuple(sorted(((category, score) for category, score in standings.items() if category != best), key=lambda item: (-item[1], item[0]))[:3])
    return best, CategoryEvidence(chosen=best, score=best_score, basis=best_basis, terms=best_terms, runners_up=runners_up, considered=sum(1 for score in standings.values() if score > 0))


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
