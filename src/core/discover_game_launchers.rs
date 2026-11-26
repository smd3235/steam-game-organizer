//! `discover_game_launchers` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! 2026-11-25: Converted from `services/discover_game_launchers.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::path::{Path, PathBuf};

use crate::core::catalog_status::{
    LAUNCHER_IGNORE_TOKENS, LAUNCHER_MAX_CANDIDATES, LAUNCHER_MAX_DEPTH, LAUNCHER_PREFER_TOKENS,
};

/// Conservative playable-exe candidates under an extracted game root.
///
/// Excludes obvious setup/installer/uninstall/redistributable/crash/helper names.
/// Returns a list of absolute Paths sorted by a simple confidence heuristic. This is
/// intentionally conservative: multiple plausible exes should be presented for user
/// choice rather than guessed.
pub fn discover_game_launchers(extracted_root: &Path) -> Vec<PathBuf> {
    let root = extracted_root.to_path_buf();
    if !root.is_dir() {
        return Vec::new();
    }
    let mut found: Vec<((i64, i64, String), PathBuf)> = Vec::new();
    for entry in walkdir::WalkDir::new(&root)
        .into_iter()
        .filter_entry(|e| {
            !e.file_name().to_string_lossy().starts_with(".git")
                && !e.file_name().to_string_lossy().ends_with("__pycache__")
        })
        .filter_map(|e| e.ok())
    {
        let current_path = entry.path();
        let rel = current_path.strip_prefix(&root).unwrap_or(Path::new("."));
        let depth = if rel.as_os_str().is_empty() || rel == Path::new(".") {
            0
        } else {
            rel.components().count() as i64
        };
        if depth >= LAUNCHER_MAX_DEPTH as i64 {
            continue;
        }
        let file_name = match current_path.file_name() {
            Some(n) => n.to_string_lossy().to_string(),
            None => continue,
        };
        if !file_name.to_lowercase().ends_with(".exe") {
            continue;
        }
        let low = file_name.to_lowercase();
        if LAUNCHER_IGNORE_TOKENS.iter().any(|t| low.contains(*t)) {
            continue;
        }
        let mut score: i64 = 0;
        if depth == 0 {
            score += 4;
        } else if depth == 1 {
            score += 2;
        }
        if LAUNCHER_PREFER_TOKENS.iter().any(|t| low.contains(*t)) {
            score += 2;
        }
        if low.contains("launcher") {
            score -= 1;
        }
        let size = current_path.metadata().map_or(0, |m| m.len());
        if size >= 1024 * 1024 {
            score += 1;
        }
        found.push((
            (-score, depth, low),
            current_path
                .canonicalize()
                .unwrap_or_else(|_| current_path.to_path_buf()),
        ));
        if found.len() >= LAUNCHER_MAX_CANDIDATES {
            break;
        }
    }
    found.sort_by(|a, b| a.0.cmp(&b.0));
    found.into_iter().map(|(_, p)| p).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_discover_game_launchers_nonexistent() {
        let result = discover_game_launchers(Path::new("/nonexistent"));
        assert!(result.is_empty());
    }
}
