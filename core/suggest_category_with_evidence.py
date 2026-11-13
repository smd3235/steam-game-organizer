"""Extracted from core/constants.py.

    suggest_category_with_evidence was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""


from core.category_evidence import CategoryEvidence
from core.constants import IGNORED_AUTO_CATEGORIES
from core.constants import UNSORTED_EVIDENCE
def suggest_category_with_evidence(genres, title="", description="", tags=None, steam_categories=None):
    """Choose a specific Steam genre using genre, tag, category, title, and description evidence,
    and return (category, CategoryEvidence): the folder, the rule that won it, the keywords
    that matched, the winning score, and the next-best candidates. suggest_category() below is
    this function with the evidence discarded, so the two can never disagree."""
    # Local import to break the circular import: core.suggest_category_with_evidence -> core.canonical_category
    # -> core.constants -> core.suggest_category_with_evidence.
    from core.canonical_category import canonical_category
    text_context = " ".join(str(value) for value in (title, description)).casefold()
    tag_context = " ".join(str(value) for value in (tags or [])).casefold()
    category_context = " ".join(str(value) for value in (steam_categories or [])).casefold()
    genre_values = [canonical_category(value) for value in (genres or []) if str(value).strip()]
    if not genre_values:
        return "Unsorted", UNSORTED_EVIDENCE

    specificity = (
        "rogue",
        "soulslike",
        "metroidvania",
        "tower defense",
        "turn-based",
        "visual novel",
        "card game",
        "deckbuilding",
        "walking simulator",
        "horror",
        "fighting",
        "shooter",
        "platformer",
        "puzzle",
        "racing",
        "sports",
    )
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
        "Management": (
            "management",
            "manage your",
            "run your business",
            "business management",
            "company management",
            "hospital management",
            "prison management",
            "zoo management",
            "theme park management",
            "restaurant management",
            "hotel management",
            "sports management",
            "fleet management",
        ),
        "Tycoon": ("tycoon", "business empire", "build your empire", "capitalism"),
        "Shop Management": ("shop management", "run your own shop", "store management", "run a store", "merchant", "trading", "economy"),
        "Tidy Up": ("tidy up", "clean up", "declutter", "decluttering", "tidying", "sorting", "organize", "organizing"),
        "Farming": ("farming", "farm simulator", "grow crops", "agriculture", "harvest", "crops", "livestock", "ranch", "ranch simulator"),
        "Horror": ("horror", "terrifying", "scary", "survival horror"),
        # Scored below Horror's default on purpose: "survival horror" contains "survival", and a survival-crafting
        # rule given the ordinary priority would outrank a horror game that says so outright.
        "Survival": ("survival crafting", "craft and survive", "block crafting", "voxel", "try not to starve", "survival sim"),
        "Bullet Heaven": ("bullet hell", "horde auto-shooter", "survivors-like", "auto attack", "wave of enemies", "horde", "bullet heaven", "survivors like"),
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
        if normalized in {"bullet hell", "horde auto-shooter"}:
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
