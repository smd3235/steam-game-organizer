//! Validate game names tool: scans for real Steam game names and appids
//! that must not be committed.
//! Conversion of `tools/validate_game_names.py`.
//!
//! 2026-11-25: Rust conversion from `tools/validate_game_names.py` in the Rust conversion.

use std::path::{Path, PathBuf};

/// Directories that are never scanned: frozen outputs, bundled runtime, git.
#[allow(dead_code)]
const SKIP_DIRS: &[&str] = &[".git", "dist", "build", "runtime", "__pycache__", ".pytest_cache"];

/// Real Steam game names that were replaced with fictional equivalents.
/// Each entry is a lowercase substring; any file containing it (case-insensitive)
/// is a violation. appids are also scanned as bare digits.
#[allow(dead_code)]
const REAL_NAMES: &[&str] = &[
    "doom",
    "the witcher 3",
    "witcher 3",
    "prison architect",
    "fell & sell",
    "incremedieval",
    "elder scrolls",
    "baldur's gate 3",
    "portal 2",
    "gta5",
    "grand theft auto",
    "half-life 2",
    "halflife 2",
    "rust",
    "brave new wonders",
    "my summer car",
    "sintopia",
    "nivalis nights",
    "mars attracts",
    "star trek",
    "kingdoms and castles",
    "lawn mowing simulator",
    "crystal realms",
    "nova launcher",
    "epsilon online",
    "divinity original sin 2",
    "cities skylines",
    "cities skylines ii",
    "dark souls iii",
    "resident evil 4",
    "star trek voyager",
    "meow tower doomsguard",
    "skyrim",
    "fallout",
    "minecraft",
    "vampire survivors",
    "stardew valley",
    "terraria",
    "factorio",
    "rimworld",
    "civilization",
    "elden ring",
    "cyberpunk",
];

/// Real Steam appids that were replaced with fakes. Scanned as standalone digit
/// tokens bounded by non-digits.
#[allow(dead_code)]
const REAL_APPIDS: &[&str] = &["1128810"];

/// Project root is the parent of the tools/ directory.
pub fn project_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

/// Validate game names: scans for real Steam game names and appids.
pub fn validate_game_names(_root: &Path) -> Result<(), String> {
    // Stub: game name validation not yet implemented in Rust.
    Err("game name validation not yet implemented".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_validate_game_names_stub() {
        let result = validate_game_names(Path::new("."));
        assert!(result.is_err());
    }
}
