//! `suggest_category_with_evidence` was moved here during a module split so `constants.rs`
//! stays under the size threshold. Import it from here instead of defining it inline.
//!
//! 2026-11-24: Converted from `core/suggest_category_with_evidence.py` to Rust in the Rust
//! conversion (one file at a time, tracked on the `Rust-Conversion` branch).

use crate::category_evidence::CategoryEvidence;
use crate::canonical_category::canonical_category;
use crate::constants::IGNORED_AUTO_CATEGORIES;

/// Choose a specific Steam genre using genre, tag, category, title, and description evidence,
/// and return `(category, CategoryEvidence)`: the folder, the rule that won it, the keywords
/// that matched, the winning score, and the next-best candidates.
///
/// `suggest_category()` below is this function with the evidence discarded, so the two can
/// never disagree.
pub fn suggest_category_with_evidence(
    genres: Option<&[String]>,
    title: &str,
    description: &str,
    tags: Option<&[String]>,
    steam_categories: Option<&[String]>,
) -> (String, CategoryEvidence) {
    let text_context = format!("{} {}", title, description).to_lowercase();
    let tag_context = tags
        .map(|ts| ts.iter().map(|s| s.as_str()).collect::<Vec<_>>().join(" "))
        .unwrap_or_default()
        .to_lowercase();
    let category_context = steam_categories
        .map(|sc| sc.iter().map(|s| s.as_str()).collect::<Vec<_>>().join(" "))
        .unwrap_or_default()
        .to_lowercase();
    let genre_values: Vec<String> = genres
        .unwrap_or(&[])
        .iter()
        .filter(|v| !v.trim().is_empty())
        .map(|v| canonical_category(v))
        .collect();
    if genre_values.is_empty() {
        return ("Unsorted".to_string(), CategoryEvidence::default());
    }

    let specificity = [
        "rogue", "soulslike", "metroidvania", "tower defense", "turn-based", "visual novel",
        "card game", "deckbuilding", "walking simulator", "horror", "fighting", "shooter",
        "platformer", "puzzle", "racing", "sports",
    ];

    let evidence: [(&str, [&str; 3]); 8] = [
        ("horror", ["horror", "terrifying", "scary"]),
        ("puzzle", ["puzzle", "logic", "brain teaser"]),
        ("strategy", ["strategy", "tactical", "strategic"]),
        ("simulation", ["simulat", "management", "manager"]),
        ("rpg", ["rpg", "role-playing", "role playing"]),
        ("adventure", ["adventure", "explor", "quest"]),
        ("action", ["action", "combat", "fight"]),
        ("racing", ["racing", "race", "driving"]),
    ];

    let mut best = "Unsorted".to_string();
    let mut best_score: i32 = i32::MIN / 2;
    let mut best_basis = "fallback".to_string();
    let mut best_terms: Vec<String> = Vec::new();
    let mut scored: Vec<(String, i32)> = Vec::new();

    let inferred: [(&str, [&str; 8]); 37] = [
        ("Idle", ["idle", "clicker", "incremental", "", "", "", "", ""]),
        (
            "City Builder",
            [
                "city builder", "city-building", "city building", "build your city",
                "town builder", "floating city", "colony builder", "town builder",
            ],
        ),
        (
            "Automation",
            [
                "automation", "automate", "factory", "production line",
                "industrial production", "build and manage a factory", "logistics", "assembly line",
            ],
        ),
        (
            "Management",
            [
                "management", "manage your", "run your business", "business management",
                "hospital management", "prison management", "zoo management", "theme park management",
            ],
        ),
        ("Tycoon", ["tycoon", "business empire", "build your empire", "capitalism", "", "", "", ""]),
        (
            "Shop Management",
            [
                "shop management", "run your own shop", "store management", "run a store",
                "merchant", "trading", "economy", "",
            ],
        ),
        (
            "Tidy Up",
            [
                "tidy up", "clean up", "declutter", "decluttering", "tidying", "sorting",
                "organize", "organizing",
            ],
        ),
        (
            "Farming",
            [
                "farming", "farm simulator", "grow crops", "agriculture", "harvest", "crops",
                "livestock", "ranch simulator",
            ],
        ),
        ("Horror", ["horror", "terrifying", "scary", "survival horror", "", "", "", ""]),
        (
            "Survival",
            [
                "survival crafting", "craft and survive", "block crafting", "voxel",
                "try not to starve", "survival sim", "", "",
            ],
        ),
        (
            "Bullet Heaven",
            [
                "bullet hell", "horde auto-shooter", "survivors-like", "auto attack",
                "wave of enemies", "horde", "bullet heaven", "survivors like",
            ],
        ),
        (
            "Roguelike",
            [
                "roguelike", "roguelite", "run-based", "procedural dungeon",
                "randomly generated dungeon", "roguelite", "permadeath", "procedural generation",
            ],
        ),
        ("Soulslike", ["soulslike", "souls-like", "punishing combat", "boss-focused combat", "", "", "", ""]),
        (
            "Metroidvania",
            ["metroidvania", "interconnected map", "backtracking exploration", "", "", "", "", ""],
        ),
        ("Puzzle", ["puzzle", "logic game", "brain teaser", "puzzle game", "", "", "", ""]),
        (
            "Deckbuilding",
            ["deckbuilding", "deck-building", "build your deck", "deck builder", "", "", "", ""],
        ),
        (
            "Card Game",
            ["card game", "trading card", "collectible card", "ccg", "tcg", "", "", ""],
        ),
        (
            "Tower Defense",
            ["tower defense", "tower defence", "td game", "defend your base", "", "", "", ""],
        ),
        (
            "Turn-Based",
            [
                "turn-based", "turn based combat", "turn based strategy",
                "turn based tactics", "turn-based tactics", "", "", "",
            ],
        ),
        (
            "Strategy",
            [
                "strategy game", "strategic", "tactical", "grand strategy", "4x",
                "real-time strategy", "rts", "",
            ],
        ),
        (
            "RPG",
            [
                "role-playing", "role playing", "character progression", "character build",
                "rpg", "jrpg", "crpg", "action rpg",
            ],
        ),
        (
            "Adventure",
            [
                "adventure game", "explore", "quest", "point and click", "narrative",
                "story rich", "", "",
            ],
        ),
        (
            "Platformer",
            ["platformer", "jump across", "precision platformer", "3d platformer", "", "", "", ""],
        ),
        (
            "Fighting",
            [
                "fighting game", "versus fighting", "combo-based combat", "beat 'em up",
                "beat em up", "", "", "",
            ],
        ),
        (
            "First-Person Shooter",
            ["first-person shooter", "fps game", "boomer shooter", "arena shooter", "", "", "", ""],
        ),
        (
            "Third-Person Shooter",
            ["third-person shooter", "over-the-shoulder shooter", "third person shooter", "", "", "", "", ""],
        ),
        ("Stealth", ["stealth", "sneak past", "remain undetected", "stealth action", "", "", "", ""]),
        ("Sandbox", ["sandbox", "open-ended sandbox", "creative mode", "", "", "", "", ""]),
        (
            "Open World",
            ["open world", "open-world", "exploration", "", "", "", "", ""],
        ),
        ("Walking Sim", ["walking simulator", "narrative walking", "", "", "", "", "", ""]),
        ("Life Sim", ["life simulation", "life sim", "daily life simulator", "social sim", "", "", "", ""]),
        ("Fishing", ["fishing", "angling", "fishing simulator", "", "", "", "", ""]),
        (
            "Cooking",
            ["cooking game", "recipes", "restaurant management", "cooking simulator", "", "", "", ""],
        ),
        ("Crafting", ["crafting", "gathering and crafting", "crafting system", "", "", "", "", ""]),
        (
            "Party Game",
            ["party game", "local multiplayer party", "minigames", "party", "", "", "", ""],
        ),
        ("Rhythm", ["rhythm game", "music game", "beat-matching", "rhythm", "", "", "", ""]),
        (
            "Visual Novel",
            ["visual novel", "branching story", "dialogue-driven story", "vn", "kinetic novel", "", "", ""],
        ),
    ];

    let priority: [(&str, i32); 8] = [
        ("City Builder", 100), ("Automation", 95), ("Idle", 90), ("Survival", 90),
        ("Management", 88), ("Tycoon", 86), ("Shop Management", 84), ("Bullet Heaven", 84),
    ];

    for (category, terms) in &inferred {
        let terms: Vec<&str> = terms.iter().filter(|t| !t.is_empty()).copied().collect();
        let matched_text: Vec<&str> = terms.iter().filter(|t| text_context.contains(*t)).copied().collect();
        if !matched_text.is_empty() {
            let score = priority.iter().find(|(c, _)| *c == *category).map(|(_, s)| *s).unwrap_or(82)
                + matched_text.len() as i32 * 3;
            scored.push((category.to_string(), score));
            if score > best_score {
                best_score = score;
                best = category.to_string();
                best_basis = "description".to_string();
                best_terms = matched_text.iter().map(|s| s.to_string()).collect();
            }
        } else {
            let matched_tag: Vec<&str> = terms
                .iter()
                .filter(|t| tag_context.contains(*t) || category_context.contains(*t))
                .copied()
                .collect();
            if !matched_tag.is_empty() {
                let score = 38;
                scored.push((category.to_string(), score));
                if score > best_score {
                    best_score = score;
                    best = category.to_string();
                    best_basis = "tag".to_string();
                    best_terms = matched_tag.iter().map(|s| s.to_string()).collect();
                }
            }
        }
    }

    for (index, genre) in genre_values.iter().enumerate() {
        let normalized = genre.to_lowercase();
        let mut score = 50 - index as i32;
        if IGNORED_AUTO_CATEGORIES.contains(&normalized.as_str()) {
            continue;
        }
        if normalized == "indie" || normalized == "casual" {
            score -= 30;
        }
        if normalized == "simulation" || normalized == "strategy" || normalized == "rpg"
            || normalized == "action" || normalized == "adventure"
        {
            score += 4;
        }
        if normalized == "city builder" || normalized == "colony sim" || normalized == "town builder"
            || normalized == "farming sim" || normalized == "fishing sim" || normalized == "management"
        {
            score += 30;
        }
        if normalized == "automation" || normalized == "factory sim" || normalized == "logistics"
            || normalized == "production" || normalized == "industrial"
        {
            score += 30;
        }
        if normalized == "idle" || normalized == "clicker" || normalized == "incremental" {
            score += 30;
        }
        if normalized == "roguelike" || normalized == "roguelite" {
            score += 30;
        }
        if normalized == "tower defense" || normalized == "td" {
            score += 30;
        }
        if normalized == "bullet hell" || normalized == "horde auto-shooter" {
            score += 30;
        }
        if normalized == "deckbuilding" || normalized == "card game" || normalized == "trading card" {
            score += 30;
        }
        if normalized == "visual novel" {
            score += 30;
        }
        if normalized == "horror" || normalized == "survival horror" {
            score += 25;
        }
        if normalized == "puzzle" {
            score += 25;
        }
        if normalized == "fighting" || normalized == "beat 'em up" {
            score += 25;
        }
        if normalized == "racing" || normalized == "driving" {
            score += 25;
        }
        if normalized == "sports" || normalized == "football" || normalized == "baseball"
            || normalized == "basketball"
        {
            score += 25;
        }
        if normalized == "rhythm" || normalized == "music" {
            score += 25;
        }
        if normalized == "stealth" {
            score += 25;
        }
        if normalized == "sandbox" || normalized == "open world" {
            score += 20;
        }
        if specificity.iter().any(|s| normalized.contains(s)) {
            score += 22;
        }
        if evidence.iter().any(|(_, terms)| terms.iter().any(|t| text_context.contains(*t))) {
            score += 18;
        }
        if tag_context.contains(normalized.as_str()) || category_context.contains(normalized.as_str()) {
            score += 4;
        }
        scored.push((genre.clone(), score));
        if score > best_score {
            best_score = score;
            best = genre.clone();
            best_basis = "genre".to_string();
            best_terms = Vec::new();
        }
    }

    if best == "Unsorted" {
        return ("Unsorted".to_string(), CategoryEvidence::default());
    }

    let mut standings: Vec<(String, i32)> = Vec::new();
    for (category, score) in &scored {
        if let Some(existing) = standings.iter_mut().find(|(c, _)| c == category) {
            if *score > existing.1 {
                existing.1 = *score;
            }
        } else {
            standings.push((category.clone(), *score));
        }
    }
    let mut runners_up: Vec<(String, i32)> = standings
        .iter()
        .filter(|(c, _)| c != &best)
        .map(|(c, s)| (c.clone(), *s))
        .collect();
    runners_up.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
    runners_up.truncate(3);

    let considered = standings.iter().filter(|(_, s)| *s > 0).count() as i32;

    (
        best.clone(),
        CategoryEvidence {
            chosen: best,
            score: best_score,
            basis: best_basis,
            terms: best_terms,
            runners_up: runners_up.into_iter().collect(),
            considered,
        },
    )
}

/// Choose a specific Steam genre using genre, tag, category, title, and description evidence.
/// Returns just the category name (evidence discarded).
pub fn suggest_category(
    genres: Option<&[String]>,
    title: &str,
    description: &str,
    tags: Option<&[String]>,
    steam_categories: Option<&[String]>,
) -> String {
    suggest_category_with_evidence(genres, title, description, tags, steam_categories).0
}
