//! Pure utility functions extracted from SteamService.
//!
//! These functions have no dependency on SteamService instance state and can be
//! imported and tested independently. They were previously methods on SteamService
//! that took all their inputs as parameters.
//!
//! Note: Python's `difflib.SequenceMatcher` is not in the Rust standard library.
//! A simple `sequence_ratio()` is implemented here using dynamic programming for
//! longest common subsequence, which approximates SequenceMatcher.ratio() well
//! enough for scoring game-name matches.
//!
//! 2026-11-24: Converted from `core/steam_query_utils.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::collections::HashSet;

use crate::core::filename_utils::identity_key;

/// Expand common gaming acronyms that appear in filenames but not Steam titles.
pub fn expand_acronyms(title: &str) -> String {
    let acronyms: &[(&str, &str)] = &[
        (r"\bAiO\b", "All in One"),
        (r"\bVR\b", "Virtual Reality"),
        (r"\bFPS\b", "First Person Shooter"),
        (r"\bRPG\b", "Role Playing Game"),
        (r"\bMMO\b", "Massively Multiplayer Online"),
        (r"\bRTS\b", "Real Time Strategy"),
        (r"\bTBS\b", "Turn Based Strategy"),
        (r"\bARPG\b", "Action RPG"),
        (r"\bCRPG\b", "Computer RPG"),
        (r"\bJRPG\b", "Japanese RPG"),
        (r"\bMOBA\b", "Multiplayer Online Battle Arena"),
        (r"\bTCG\b", "Trading Card Game"),
        (r"\bCCG\b", "Collectible Card Game"),
        (r"\bF2P\b", "Free to Play"),
        (r"\bP2W\b", "Pay to Win"),
        (r"\bDLC\b", "Downloadable Content"),
        (r"\bGOTY\b", "Game of the Year"),
        (r"\bSotY\b", "Simulation of the Year"),
    ];
    let mut result = title.to_string();
    for (pattern, expansion) in acronyms {
        let re = regex::Regex::new(pattern).unwrap();
        result = re.replace_all(&result, *expansion).to_string();
    }
    if result == title {
        String::new()
    } else {
        result
    }
}

/// Convert an integer 1-39 to a Roman numeral. Returns "" out of range.
pub fn to_roman(value: u32) -> String {
    if !(1..=39).contains(&value) {
        return String::new();
    }
    let table = [(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")];
    let mut result = String::new();
    let mut remaining = value;
    for (amount, symbol) in table {
        while remaining >= amount {
            result.push_str(symbol);
            remaining -= amount;
        }
    }
    result
}

/// Convert a Roman numeral to an integer. Returns 0 out of range or invalid.
pub fn from_roman(text: &str) -> u32 {
    let values: &[(&str, u32)] = &[
        ("I", 1),
        ("V", 5),
        ("X", 10),
        ("L", 50),
        ("C", 100),
        ("D", 500),
        ("M", 1000),
    ];
    let mut total: u32 = 0;
    let mut previous: u32 = 0;
    for ch in text.to_uppercase().chars().rev() {
        let current = values
            .iter()
            .find(|(c, _)| c == &ch.to_string())
            .map(|(_, v)| *v)
            .unwrap_or(0);
        if current < previous {
            total -= current;
        } else {
            total += current;
        }
        previous = current;
    }
    if (1..=39).contains(&total) {
        total
    } else {
        0
    }
}

/// Swap a trailing Arabic numeral to a Roman numeral, or vice versa.
pub fn swap_trailing_numeral(title: &str) -> String {
    let words: Vec<&str> = title.split_whitespace().collect();
    if words.is_empty() {
        return String::new();
    }
    let last = words[words.len() - 1];
    if regex::Regex::new(r"^\d{1,2}$").unwrap().is_match(last) {
        if let Ok(n) = last.parse::<u32>() {
            let roman = to_roman(n);
            if !roman.is_empty() {
                let mut new_words = words[..words.len() - 1].to_vec();
                new_words.push(roman.as_str());
                return new_words.join(" ");
            }
        }
        return String::new();
    }
    if regex::Regex::new(r"(?i)^[ivxlcdm]+$")
        .unwrap()
        .is_match(last)
    {
        let value = from_roman(last.to_uppercase().as_str());
        if value > 0 {
            let value_str = value.to_string();
            let mut new_words = words[..words.len() - 1].to_vec();
            new_words.push(value_str.as_str());
            return new_words.join(" ");
        }
    }
    String::new()
}

/// Simple SequenceMatcher-like ratio using LCS dynamic programming.
fn sequence_ratio(a: &str, b: &str) -> f64 {
    let a_chars: Vec<char> = a.chars().collect();
    let b_chars: Vec<char> = b.chars().collect();
    let m = a_chars.len();
    let n = b_chars.len();
    if m == 0 || n == 0 {
        return 0.0;
    }
    // LCS dynamic programming
    let mut dp = vec![vec![0usize; n + 1]; m + 1];
    for i in 1..=m {
        for j in 1..=n {
            if a_chars[i - 1] == b_chars[j - 1] {
                dp[i][j] = dp[i - 1][j - 1] + 1;
            } else {
                dp[i][j] = dp[i - 1][j].max(dp[i][j - 1]);
            }
        }
    }
    let lcs = dp[m][n];
    let total = m + n;
    2.0 * lcs as f64 / total as f64
}

/// Score how well a query matches a Steam game name, 0.0 to 1.0.
pub fn score(query: &str, name: &str) -> f64 {
    let query_key = identity_key(query);
    let name_key = identity_key(name);
    if query_key.is_empty() || name_key.is_empty() {
        return 0.0;
    }
    if query_key == name_key {
        return 1.0;
    }
    let query_lower = query.to_lowercase();
    let name_lower = name.to_lowercase();
    let query_tokens: HashSet<&str> = regex::Regex::new(r"[a-z0-9]+")
        .unwrap()
        .find_iter(&query_lower)
        .map(|m| m.as_str())
        .collect();
    let name_tokens: HashSet<&str> = regex::Regex::new(r"[a-z0-9]+")
        .unwrap()
        .find_iter(&name_lower)
        .map(|m| m.as_str())
        .collect();
    if query_tokens.is_empty() || name_tokens.is_empty() {
        return 0.0;
    }
    let sequence = sequence_ratio(&query_key, &name_key);
    let query_sorted: Vec<&str> = {
        let mut v: Vec<&str> = query_tokens.iter().copied().collect();
        v.sort();
        v
    };
    let name_sorted: Vec<&str> = {
        let mut v: Vec<&str> = name_tokens.iter().copied().collect();
        v.sort();
        v
    };
    let token = sequence_ratio(&query_sorted.join(" "), &name_sorted.join(" "));
    let overlap = query_tokens.intersection(&name_tokens).count() as f64
        / query_tokens.union(&name_tokens).count() as f64;
    let mut result = sequence.max(token * 0.95).max(overlap * 0.96);
    if query_key.contains(&name_key) || name_key.contains(&query_key) {
        result = result.max(0.90);
    }
    let q_subset = query_tokens.is_subset(&name_tokens);
    let n_subset = name_tokens.is_subset(&query_tokens);
    if q_subset || n_subset {
        result = result.max(0.95);
    }
    if query_tokens.len() > 1 {
        let short_trailing: Vec<&&str> = query_tokens.iter().filter(|t| t.len() <= 4).collect();
        if !short_trailing.is_empty() {
            let short_set: HashSet<&str> = short_trailing.into_iter().copied().collect();
            let remainder: HashSet<&str> = query_tokens.difference(&short_set).copied().collect();
            if !remainder.is_empty() && remainder.is_subset(&name_tokens) {
                result = result.max(0.90);
            }
        }
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_to_roman() {
        assert_eq!(to_roman(1), "I");
        assert_eq!(to_roman(4), "IV");
        assert_eq!(to_roman(10), "X");
        assert_eq!(to_roman(39), "XXXIX");
        assert_eq!(to_roman(0), "");
        assert_eq!(to_roman(40), "");
    }

    #[test]
    fn test_from_roman() {
        assert_eq!(from_roman("I"), 1);
        assert_eq!(from_roman("IV"), 4);
        assert_eq!(from_roman("X"), 10);
        assert_eq!(from_roman("XXXIX"), 39);
        assert_eq!(from_roman("INVALID"), 0);
    }

    #[test]
    fn test_score_exact_match() {
        assert_eq!(score("Game Title", "Game Title"), 1.0);
    }

    #[test]
    fn test_score_no_match() {
        let s = score("Completely Different", "Game Title");
        assert!(
            s < 0.5,
            "score should be low for unrelated names, got {}",
            s
        );
    }

    #[test]
    fn test_expand_acronyms() {
        assert_eq!(expand_acronyms("VR Game"), "Virtual Reality Game");
        assert_eq!(expand_acronyms("No Acronym Here"), "");
    }

    #[test]
    fn test_swap_trailing_numeral() {
        assert_eq!(swap_trailing_numeral("Game 2"), "Game II");
        assert_eq!(swap_trailing_numeral("Game II"), "Game 2");
    }
}

