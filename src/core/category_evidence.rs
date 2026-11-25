//! Why one category was chosen over the others, so a screen can say why, not only what.
//!
//! Extracted from `core/constants.py` during a module split so the original file
//! stays under the size threshold.
//!
//! Frozen, with tuple fields, so it survives the copy that `StateStore::get()`
//! performs on every state read and cannot be edited once it is attached to a decision.
//! Every field is a `String`, an `i32`, or a `Vec` of those, which keeps the value
//! JSON-native: `serde_json::to_string(&evidence)` needs no custom encoder.
//!
//! `basis` is the closed vocabulary a screen reads in one word: "description" when a keyword
//! rule won on the title/description text, "tag" when the same rule won on tags or Steam
//! categories alone, "genre" when a Steam genre out-scored every rule, "fallback" when
//! nothing scored at all and the answer is Unsorted. `terms` are the keywords that fired, in
//! the order they were tested, and are empty for a genre win, where the genre name is the
//! reason. `runners_up` holds at most the next three candidates as `(name, score)` pairs,
//! sorted by score descending then name, so the output is deterministic; a candidate is one
//! category, so a category that scored in both passes appears once, with its better score.
//! `considered` counts the candidates that scored above zero, which is how a screen says
//! "nothing came close" when it is 0.
//!
//! 2026-11-24: Converted from `core/category_evidence.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use serde::{Deserialize, Serialize};

/// Why one category was chosen over the others.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct CategoryEvidence {
    pub chosen: String,
    pub score: i32,
    pub basis: String,
    pub terms: Vec<String>,
    pub runners_up: Vec<(String, i32)>,
    pub considered: i32,
}

/// The fallback evidence for every path that lands on Unsorted without scoring a single candidate:
/// no genres at all, or only ignored ones and no keyword hit anywhere.
pub fn unsorted_evidence() -> CategoryEvidence {
    CategoryEvidence {
        chosen: "Unsorted".to_string(),
        score: 0,
        basis: "fallback".to_string(),
        terms: Vec::new(),
        runners_up: Vec::new(),
        considered: 0,
    }
}
