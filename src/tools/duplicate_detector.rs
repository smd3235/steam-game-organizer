//! Duplicate detector tool: finds duplicate archives across library folders.
//! Compares archives by normalized name (strips release groups, edition words,
//! subtitles) and file size to catch the same game downloaded twice under
//! different filenames.
//!
//! Usage:
//!   steam-game-organizer.exe --duplicate-detector <library_dir>
//!
//! 2026-11-27: Made functional — walks the library directory, normalizes archive
//! names using the same normalization logic as the scan pipeline, and groups
//! archives by (normalized_name, file_size) to find duplicates.

use std::collections::HashMap;
use std::path::Path;

/// A detected duplicate group: same game, multiple files.
pub struct DuplicateGroup {
    pub normalized_name: String,
    pub files: Vec<std::path::PathBuf>,
    pub total_size_bytes: u64,
}

/// Normalize an archive filename by stripping release groups, edition words,
/// subtitles, and file extensions. This mirrors the naming_utils::normalize_name
/// logic used in the scan pipeline.
fn normalize_archive_name(filename: &str) -> String {
    // Strip file extension first
    // Strip only the last file extension
    let name = if let Some(dot_pos) = filename.rfind('.') {
        &filename[..dot_pos]
    } else {
        filename
    }
    .to_lowercase();

    // Release groups commonly found at start or end of filenames
    let release_groups = [
        "tenoke", "dodi", "fitgirl", "xforce", "cpydark", "pc", "repack",
        "ripped", "steamrip", "fitgirl-repacks", "goldeberg", "taxi",
        "flt", "razor1911", "reloaded", "skidrow", "codex", "tpl",
        "hardlock", "solidworks", "autodesk", "adobe",
    ];

    let mut normalized = name.clone();

    // Strip release groups from start
    for group in &release_groups {
        if normalized.starts_with(group) {
            normalized = normalized[group.len()..].trim_start_matches(&['-', '.', '_', ' '][..]).to_string();
        }
    }

    // Strip release groups from end
    for group in &release_groups {
        if normalized.ends_with(group) {
            normalized = normalized[..normalized.len() - group.len()].trim_end_matches(&['-', '.', '_', ' '][..]).to_string();
        }
    }

    // Strip edition words
    let edition_words = [
        "ultimate", "deluxe", "gold", "premium", "collectors", "collector's",
        "game of the year", "goty", "definitive", "complete", "special",
        "standard", "basic", "regular",
    ];
    for word in &edition_words {
        if normalized.contains(word) {
            normalized = normalized.replace(word, "").trim().to_string();
        }
    }

    // Strip subtitles (everything after common separators)
    // Only split on " - " and ":" which are clearly subtitle separators,
    // not on "-" or "_" which are commonly part of names
    for sep in [" - ", ":"] {
        if let Some(pos) = normalized.find(sep) {
            let before = normalized[..pos].trim();
            // Only strip if the before part is substantial (not just a single word)
            if before.len() > 3 {
                normalized = before.to_string();
            }
        }
    }

    // Clean up extra whitespace and separators
    normalized = normalized
        .split(|c: char| !c.is_alphanumeric() && c != ' ')
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
        .trim()
        .to_string();

    if normalized.is_empty() {
        normalized = name;
    }

    normalized
}

/// Scan a directory tree for duplicate archives.
/// Groups archives by (normalized_name, file_size); returns groups with >1 file.
pub fn find_duplicates(library_dir: &Path) -> Result<Vec<DuplicateGroup>, String> {
    if !library_dir.exists() {
        return Err(format!(
            "Library directory does not exist: {}",
            library_dir.display()
        ));
    }

    // Map: (normalized_name, size) -> list of file paths
    let mut groups: HashMap<(String, u64), Vec<std::path::PathBuf>> = HashMap::new();

    const ARCHIVE_EXTENSIONS: &[&str] = &["zip", "rar", "7z"];

    for entry in walkdir::WalkDir::new(library_dir)
        .into_iter()
        .filter_entry(|e| {
            !e.file_name()
                .to_string_lossy()
                .starts_with('.')
                && e.file_name() != "steamapps"
        })
        .filter_map(|e| e.ok())
    {
        let path = entry.path();
        if path.is_file() {
            if let Some(ext) = path.extension().and_then(|e| e.to_str()) {
                if ARCHIVE_EXTENSIONS.contains(&ext.to_lowercase().as_str()) {
                    if let Ok(metadata) = std::fs::metadata(path) {
                        let size = metadata.len();
                        let filename = path
                            .file_name()
                            .and_then(|n| n.to_str())
                            .unwrap_or("")
                            .to_string();
                        let normalized = normalize_archive_name(&filename);
                        groups
                            .entry((normalized, size))
                            .or_default()
                            .push(path.to_path_buf());
                    }
                }
            }
        }
    }

    // Filter to only groups with >1 file (actual duplicates)
    let mut duplicates: Vec<DuplicateGroup> = groups
        .into_iter()
        .filter(|(_, files)| files.len() > 1)
        .map(|((normalized_name, _), files)| {
            let total_size_bytes: u64 = files.iter().filter_map(|p| std::fs::metadata(p).ok().map(|m| m.len())).sum();
            DuplicateGroup {
                normalized_name,
                files,
                total_size_bytes,
            }
        })
        .collect();

    // Sort by total size descending (largest duplicates first)
    duplicates.sort_by_key(|a| std::cmp::Reverse(a.total_size_bytes));

    Ok(duplicates)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_find_duplicates_nonexistent_dir() {
        let result = find_duplicates(Path::new("/nonexistent/path/12345"));
        assert!(result.is_err());
    }

    #[test]
    fn test_find_duplicates_empty_dir() {
        let dir = tempfile::tempdir().unwrap();
        let result = find_duplicates(dir.path());
        assert!(result.is_ok());
        assert!(result.unwrap().is_empty());
    }

    #[test]
    fn test_find_duplicates_detects_duplicates() {
        let dir = tempfile::tempdir().unwrap();

        // Create two archives with same normalized name and size
        std::fs::write(dir.path().join("game_12345.tenoke.zip"), b"fake zip content here").unwrap();
        std::fs::write(dir.path().join("Game.12345.fitgirl.zip"), b"fake zip content here").unwrap();

        // Create a non-duplicate
        std::fs::write(dir.path().join("other_game_67890.zip"), b"different content").unwrap();

        let result = find_duplicates(dir.path());
        assert!(result.is_ok());
        let duplicates = result.unwrap();
        assert_eq!(duplicates.len(), 1);
        assert_eq!(duplicates[0].files.len(), 2);
        assert_eq!(duplicates[0].normalized_name, "game 12345");
    }

    #[test]
    fn test_find_duplicates_no_duplicates() {
        let dir = tempfile::tempdir().unwrap();

        std::fs::write(dir.path().join("game_12345.zip"), b"content a").unwrap();
        std::fs::write(dir.path().join("game_67890.zip"), b"content b").unwrap();

        let result = find_duplicates(dir.path());
        assert!(result.is_ok());
        assert!(result.unwrap().is_empty());
    }

    #[test]
    fn test_normalize_archive_name_strips_release_groups() {
        assert_eq!(normalize_archive_name("tenoke-game_name.zip"), "game name");
        assert_eq!(normalize_archive_name("game_name.fitgirl.zip"), "game name");
        assert_eq!(normalize_archive_name("game_name.dodi.zip"), "game name");
    }

    #[test]
    fn test_normalize_archive_name_strips_edition_words() {
        assert_eq!(normalize_archive_name("game_name.ultimate.zip"), "game name");
        assert_eq!(normalize_archive_name("game_name.deluxe.zip"), "game name");
        assert_eq!(normalize_archive_name("game_name.gold.zip"), "game name");
    }

    #[test]
    fn test_normalize_archive_name_strips_extensions() {
        assert_eq!(normalize_archive_name("game_name.zip"), "game name");
        assert_eq!(normalize_archive_name("game_name.rar"), "game name");
        assert_eq!(normalize_archive_name("game_name.7z"), "game name");
    }

    #[test]
    fn test_normalize_archive_name_strips_subtitles() {
        // " - " separator with substantial text before it
        assert_eq!(normalize_archive_name("game name - subtitle.zip"), "game name");
        assert_eq!(normalize_archive_name("game name: subtitle.zip"), "game name");
    }

    #[test]
    fn test_duplicate_group_struct() {
        let group = DuplicateGroup {
            normalized_name: "resident evil 4".to_string(),
            files: vec![
                std::path::PathBuf::from("C:/Games/resident.evil.4.tenoke.zip"),
                std::path::PathBuf::from("C:/Games/RE4.fitgirl.repack.rar"),
            ],
            total_size_bytes: 45_000_000_000,
        };
        assert_eq!(group.files.len(), 2);
        assert_eq!(group.normalized_name, "resident evil 4");
        assert!(group.total_size_bytes > 0);
    }
}
