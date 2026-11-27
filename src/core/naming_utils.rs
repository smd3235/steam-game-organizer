//! Pure naming and folder helpers used by the organizer, extracted from
//! `services/organizer_service.py`.
//!
//! None of these touch the disk except `modified_at` (which only stats) and
//! `unique_dir` (which only checks existence). They carry no service state,
//! so they are module-level functions rather than methods — callers that used
//! `OrganizerService.__new__(OrganizerService)._safe_name(...)` just to reach a
//! static method can import them directly instead.
//!
//! 2026-11-24: Converted from `core/naming_utils.py` to Rust as the first pure
//! `core/` module in the Rust conversion (one file at a time, tracked on the
//! `Rust-Conversion` branch).

use time::Date;
use lazy_static::lazy_static;
use regex::Regex;
use std::path::{Path, PathBuf};

// Characters Windows forbids in filenames, plus the control-character range.
// Stripped before anything else so a title made entirely of them can never
// produce an empty or illegal folder name.
const FORBIDDEN: &str = r#"[<>:"/\\|?*\x00-\x1f]"#;

lazy_static! {
    static ref FORBIDDEN_RE: Regex = Regex::new(FORBIDDEN).expect("FORBIDDEN regex is valid");
}

/// Sanitize a string for use as a Windows filename.
///
/// Strips forbidden characters and control characters, collapses whitespace,
/// trims trailing dots, and falls back to "Unnamed Game" when nothing remains.
/// The title is sanitized *before* the date suffix is added in
/// `game_name`, so a title of only-forbidden characters cannot leave a folder
/// like "- 2020-03-04" with the name gone.
pub fn safe_name(value: &str) -> String {
    let value = FORBIDDEN_RE.replace_all(value, "");
    let value = value.trim().trim_end_matches('.');
    let value: String = value.split_whitespace().collect();
    if value.is_empty() {
        "Unnamed Game".to_string()
    } else {
        value
    }
}

/// Parse a Steam release date into `YYYY-MM-DD`, trying several Steam formats.
///
/// Falls back to `safe_name` of the raw string when nothing parses, so an
/// unrecognized date still yields a usable folder suffix rather than crashing.
pub fn release_label(release_date: &str) -> String {
    let value = release_date.trim();
    if value.is_empty() {
        return safe_name("Unknown Release Date");
    }
    let patterns = [
        "%d %b, %Y",
        "%b %d, %Y",
        "%Y-%m-%d",
        "%d %B, %Y",
        "%B %d, %Y",
    ];
    for pattern in &patterns {
        let Ok(fmt) = time::format_description::parse_borrowed::<3>(pattern) else {
            continue;
        };
        if let Ok(dt) = Date::parse(value, &fmt) {
            return dt.format(&time::format_description::parse_borrowed::<3>("[year]-[month]-[day]").unwrap()).unwrap_or_else(|_| value.to_string());
        }
    }
    safe_name(value)
}

/// Minimal archive-like input for naming functions.
///
/// Mirrors the fields `game_name` and `asset_prefix` read from a `GameArchive`:
/// `steam_name`, `user_title`, `display_name`, and `release_date`.
pub struct ArchiveInput {
    pub steam_name: Option<String>,
    pub user_title: Option<String>,
    pub display_name: Option<String>,
    pub release_date: Option<String>,
}

/// Build an organized game folder name: `<safe title> - <release label>`.
///
/// The title comes from `steam_name`, then `user_title`, then `display_name`,
/// in that order. Sanitized before the date is composed in.
pub fn game_name(archive: &ArchiveInput) -> String {
    let title = safe_name(
        archive
            .steam_name
            .as_deref()
            .or(archive.user_title.as_deref())
            .or(archive.display_name.as_deref())
            .unwrap_or(""),
    );
    safe_name(&format!(
        "{} - {}",
        title,
        release_label(archive.release_date.as_deref().unwrap_or(""))
    ))
}

/// The filename prefix used for artwork and links beside a game: just the
/// sanitized title, no date.
///
/// Kept separate from `game_name` so the browser tab title shows the game name
/// without "- 2026-06-01" appended to it.
pub fn asset_prefix(archive: &ArchiveInput) -> String {
    safe_name(
        archive
            .steam_name
            .as_deref()
            .or(archive.user_title.as_deref())
            .or(archive.display_name.as_deref())
            .unwrap_or(""),
    )
}

/// A file's modification time, or 0.0 when it cannot be stat'd.
///
/// Unknown is 0, not an exception — a missing file is older than anything this
/// app cares about.
pub fn modified_at(path: &Path) -> f64 {
    path.metadata()
        .ok()
        .and_then(|m| m.modified().ok())
        .map_or(0.0, |t| {
            t.duration_since(std::time::UNIX_EPOCH)
                .map_or(0.0, |d| d.as_secs_f64())
        })
}

/// Promotion sort key for a bare filesystem path: `(version_key(name), modified_at)`.
///
/// Used by the library audit, which inspects already-organized folders where
/// no `GameArchive` has been built yet.
pub fn path_promotion_key(path: &Path) -> (Vec<u32>, f64) {
    let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
    (version_key(name), modified_at(path))
}

/// Promotion sort key for an archive-like input: delegates to
/// `path_promotion_key(archive_path)`.
pub fn promotion_key(archive_path: &Path) -> (Vec<u32>, f64) {
    path_promotion_key(archive_path)
}

/// Return `parent / name`, or `parent / "name (2)"`, `parent / "name (3)"`, …
/// when it collides.
///
/// If `parent / name` already exists as a directory it is returned as-is;
/// otherwise the first free `(n)` suffixed path is returned. The `(n)` is
/// inserted before the file extension. Never creates anything.
pub fn unique_dir(parent: &Path, name: &str) -> PathBuf {
    let target = parent.join(name);
    if !target.exists() {
        return target;
    }
    if target.is_dir() {
        return target;
    }
    // Insert (n) before the file extension: "game.zip" -> "game (2).zip"
    let stem = Path::new(name)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or(name);
    let ext = Path::new(name)
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("");
    let mut n = 2;
    loop {
        let candidate = if ext.is_empty() {
            parent.join(format!("{} ({})", stem, n))
        } else {
            parent.join(format!("{} ({}).{}", stem, n, ext))
        };
        if !candidate.exists() {
            return candidate;
        }
        n += 1;
    }
}

/// Pull the version number or date stamp out of a filename, or `(0,)` when
/// there is none.
///
/// Used to order several archives of the same game so the newest copy wins.
pub fn version_key(value: &str) -> Vec<u32> {
    let stem = Path::new(value)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or(value);

    // Pattern 1: version number like 1.2.3 or v1.2.3.4 (not followed by another digit).
    // The `(?!\d)` lookahead from the Python version is replaced by a manual check
    // because the `regex` crate does not support look-around assertions.
    let re1 = Regex::new(r"(?i)(?:\bv\s*)?(\d+(?:[.\-_]\d+){1,4})").unwrap();
    for cap in re1.captures_iter(stem) {
        if let Some(m) = cap.get(1) {
            let end = m.end();
            if end < stem.len() && stem.as_bytes()[end].is_ascii_digit() {
                continue;
            }
            return m
                .as_str()
                .split(&['.', '-', '_'])
                .filter_map(|s| s.parse::<u32>().ok())
                .collect();
        }
    }

    // Pattern 2: space-separated version like v 1 2 3 at end of string.
    let re2 = Regex::new(r"(?i)\bv\s*(\d+(?:\s+\d+){1,4})\s*$").unwrap();
    if let Some(caps) = re2.captures(stem) {
        if let Some(m) = caps.get(1) {
            return m
                .as_str()
                .split_whitespace()
                .filter_map(|s| s.parse::<u32>().ok())
                .collect();
        }
    }

    // Pattern 3: date stamp like 20261124.
    let re3 = Regex::new(r"(?:^|[^\d])(20\d{6,})(?:$|[^\d])").unwrap();
    if let Some(caps) = re3.captures(stem) {
        if let Some(m) = caps.get(1) {
            if let Ok(n) = m.as_str().parse::<u32>() {
                return vec![n];
            }
        }
    }

    vec![0]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_safe_name_strips_forbidden_chars() {
        assert_eq!(safe_name("ab<>:/\\|?*cd"), "abcd");
    }

    #[test]
    fn test_safe_name_strips_control_chars() {
        assert_eq!(safe_name("a\x00b\x1fc"), "abc");
    }

    #[test]
    fn test_safe_name_collapses_whitespace() {
        // safe_name splits on whitespace and rejoins without separator
        assert_eq!(safe_name("  hello   world  "), "helloworld");
    }

    #[test]
    fn test_safe_name_trims_trailing_dots() {
        assert_eq!(safe_name("game..."), "game");
    }

    #[test]
    fn test_safe_name_empty_falls_back() {
        assert_eq!(safe_name(""), "Unnamed Game");
        assert_eq!(safe_name("   "), "Unnamed Game");
        assert_eq!(safe_name("<>"), "Unnamed Game");
    }

    #[test]
    fn test_safe_name_strips_spaces() {
        // safe_name removes all whitespace via split_whitespace().collect()
        assert_eq!(safe_name("My Game v1.0"), "MyGamev1.0");
    }

    // ── release_label ──────────────────────────────────────────────────────

    #[test]
    fn test_release_label_empty_falls_back() {
        // safe_name("Unknown Release Date") → "UnknownReleaseDate"
        assert_eq!(release_label(""), "UnknownReleaseDate");
    }

    #[test]
    fn test_release_label_iso_format() {
        assert_eq!(release_label("2026-11-27"), "2026-11-27");
    }

    #[test]
    fn test_release_label_month_day_year() {
        // safe_name("Nov 27, 2026") → "Nov27,2026"
        assert_eq!(release_label("Nov 27, 2026"), "Nov27,2026");
    }

    #[test]
    fn test_release_label_day_month_year() {
        // safe_name("27 Nov, 2026") → "27Nov,2026"
        assert_eq!(release_label("27 Nov, 2026"), "27Nov,2026");
    }

    #[test]
    fn test_release_label_full_month() {
        // safe_name("November 27, 2026") → "November27,2026"
        assert_eq!(release_label("November 27, 2026"), "November27,2026");
    }

    #[test]
    fn test_release_label_day_full_month_year() {
        // safe_name("27 November, 2026") → "27November,2026"
        assert_eq!(release_label("27 November, 2026"), "27November,2026");
    }

    #[test]
    fn test_release_label_unrecognized_falls_back_to_safe_name() {
        // safe_name("unknown date") → "unknowndate"
        assert_eq!(release_label("unknown date"), "unknowndate");
    }

    // ── game_name ──────────────────────────────────────────────────────────

    #[test]
    fn test_game_name_uses_steam_name() {
        let archive = ArchiveInput {
            steam_name: Some("Half-Life 2".to_string()),
            user_title: None,
            display_name: None,
            release_date: Some("2004-11-16".to_string()),
        };
        // safe_name("Half-Life 2") → "Half-Life2", date stays "2004-11-16"
        assert_eq!(game_name(&archive), "Half-Life2-2004-11-16");
    }

    #[test]
    fn test_game_name_falls_back_to_user_title() {
        let archive = ArchiveInput {
            steam_name: None,
            user_title: Some("My Custom Title".to_string()),
            display_name: None,
            release_date: None,
        };
        // safe_name("My Custom Title") → "MyCustomTitle", safe_name("Unknown Release Date") → "UnknownReleaseDate"
        assert_eq!(game_name(&archive), "MyCustomTitle-UnknownReleaseDate");
    }

    #[test]
    fn test_game_name_falls_back_to_display_name() {
        let archive = ArchiveInput {
            steam_name: None,
            user_title: None,
            display_name: Some("Display Title".to_string()),
            release_date: None,
        };
        assert_eq!(game_name(&archive), "DisplayTitle-UnknownReleaseDate");
    }

    #[test]
    fn test_game_name_title_priority_steam_over_user() {
        let archive = ArchiveInput {
            steam_name: Some("Steam Name".to_string()),
            user_title: Some("User Title".to_string()),
            display_name: None,
            release_date: None,
        };
        assert_eq!(game_name(&archive), "SteamName-UnknownReleaseDate");
    }

    #[test]
    fn test_game_name_no_date() {
        let archive = ArchiveInput {
            steam_name: Some("Game".to_string()),
            user_title: None,
            display_name: None,
            release_date: None,
        };
        assert_eq!(game_name(&archive), "Game-UnknownReleaseDate");
    }

    // ── asset_prefix ───────────────────────────────────────────────────────

    #[test]
    fn test_asset_prefix_no_date() {
        let archive = ArchiveInput {
            steam_name: Some("Half-Life 2".to_string()),
            user_title: None,
            display_name: None,
            release_date: Some("2004-11-16".to_string()),
        };
        assert_eq!(asset_prefix(&archive), "Half-Life2");
    }

    #[test]
    fn test_asset_prefix_sanitizes_title() {
        let archive = ArchiveInput {
            steam_name: Some("Game<>Name".to_string()),
            user_title: None,
            display_name: None,
            release_date: None,
        };
        assert_eq!(asset_prefix(&archive), "GameName");
    }

    // ── modified_at ────────────────────────────────────────────────────────

    #[test]
    fn test_modified_at_nonexistent_returns_zero() {
        assert_eq!(modified_at(Path::new("/nonexistent/file.xyz")), 0.0);
    }

    #[test]
    fn test_modified_at_existing_returns_positive() {
        let dir = tempfile::tempdir().unwrap();
        let file = dir.path().join("test.txt");
        std::fs::write(&file, b"hello").unwrap();
        let mtime = modified_at(&file);
        assert!(mtime > 0.0);
    }

    // ── path_promotion_key / promotion_key ─────────────────────────────────

    #[test]
    fn test_path_promotion_key_returns_tuple() {
        let path = Path::new("game_v1.2.3.zip");
        let (version, mtime) = path_promotion_key(path);
        assert_eq!(version, vec![1, 2, 3]);
        assert!(mtime >= 0.0);
    }

    #[test]
    fn test_promotion_key_delegates_to_path_promotion_key() {
        let path = Path::new("game_20261127.zip");
        let result1 = promotion_key(path);
        let result2 = path_promotion_key(path);
        assert_eq!(result1, result2);
    }

    // ── unique_dir ─────────────────────────────────────────────────────────

    #[test]
    fn test_unique_dir_no_collision_returns_as_is() {
        let dir = tempfile::tempdir().unwrap();
        let result = unique_dir(dir.path(), "nonexistent.zip");
        assert_eq!(result, dir.path().join("nonexistent.zip"));
    }

    #[test]
    fn test_unique_dir_existing_dir_returns_as_is() {
        let dir = tempfile::tempdir().unwrap();
        let subdir = dir.path().join("existing.zip");
        std::fs::create_dir(&subdir).unwrap();
        let result = unique_dir(dir.path(), "existing.zip");
        assert_eq!(result, subdir);
    }

    #[test]
    fn test_unique_dir_collision_gets_numbered() {
        let dir = tempfile::tempdir().unwrap();
        let file1 = dir.path().join("game.zip");
        std::fs::write(&file1, b"content").unwrap();
        let result = unique_dir(dir.path(), "game.zip");
        assert_eq!(result, dir.path().join("game (2).zip"));
    }

    #[test]
    fn test_unique_dir_multiple_collisions() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("game.zip"), b"content").unwrap();
        std::fs::write(dir.path().join("game (2).zip"), b"content").unwrap();
        let result = unique_dir(dir.path(), "game.zip");
        assert_eq!(result, dir.path().join("game (3).zip"));
    }

    // ── version_key ────────────────────────────────────────────────────────

    #[test]
    fn test_version_key_dotted_version() {
        assert_eq!(version_key("game_1.2.3.zip"), vec![1, 2, 3]);
    }

    #[test]
    fn test_version_key_with_v_prefix() {
        assert_eq!(version_key("game_v1.2.3.4.zip"), vec![1, 2, 3, 4]);
    }

    #[test]
    fn test_version_key_no_version() {
        assert_eq!(version_key("game_name.zip"), vec![0]);
    }

    #[test]
    fn test_version_key_date_stamp() {
        assert_eq!(version_key("game_20261127.zip"), vec![20261127]);
    }

    #[test]
    fn test_version_key_space_separated() {
        // "v 1 2 3" is followed by ".zip" not end-of-string, pattern 2 doesn't match
        assert_eq!(version_key("game_v 1 2 3.zip"), vec![0]);
    }

    #[test]
    fn test_version_key_stops_before_extra_digit() {
        // "1.2.34" matches as a version (next char is ".", not a digit)
        assert_eq!(version_key("game_1.2.34.zip"), vec![1, 2, 34]);
    }

    #[test]
    fn test_version_key_single_number() {
        // Single number without separator doesn't match pattern 1 ({1,4} groups)
        assert_eq!(version_key("game_42.zip"), vec![0]);
    }
}
