//! Pure utility functions extracted from CatalogService.
//!
//! These functions have no dependency on CatalogService instance state and can be
//! imported and tested independently. They were previously methods on CatalogService
//! that took all their inputs as parameters.
//!
//! 2026-11-24: Converted from `core/catalog_utils.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::fs;
use std::path::{Path, PathBuf};

use crate::formatting::human_size;
use crate::uri_actions::SCHEME;

/// Priority order for banner image selection.
pub const BANNER_PRIORITY: [&str; 6] = [
    "header_image",
    "library_hero",
    "capsule_imagev5",
    "capsule_image",
    "library_capsule",
    "grid",
];

/// Sanitise a Steam game name into a filesystem-safe folder prefix.
///
/// Strips illegal Windows characters, collapses whitespace, and falls back to
/// "Unnamed Game" for empty input.
pub fn safe_name(value: &str) -> String {
    let forbidden: &[char] = &['<', '>', ':', '"', '/', '\\', '|', '?', '*'];
    let mut replaced = String::with_capacity(value.len());
    for c in value.chars() {
        if forbidden.contains(&c) || (c as u32) < 0x20 {
            replaced.push(' ');
        } else {
            replaced.push(c);
        }
    }
    let chunks: Vec<&str> = replaced.split(' ').filter(|s| !s.is_empty()).collect();
    let result: String = chunks.join(" ");
    let result = result.trim_end_matches('.');
    if result.is_empty() {
        "Unnamed Game".to_string()
    } else {
        result.to_string()
    }
}

/// Steam's tag list, as a list of non-empty, de-duplicated strings.
pub fn clean_tags(raw: Option<&[String]>) -> Vec<String> {
    let raw = match raw {
        Some(r) => r,
        None => return Vec::new(),
    };
    let mut seen: Vec<String> = Vec::new();
    for value in raw {
        let text = value.trim();
        if !text.is_empty() && !seen.iter().any(|s| s == text) {
            seen.push(text.to_string());
        }
    }
    seen
}

/// Size in bytes of the first archive found in a game folder.
pub fn archive_size(game_dir: &Path) -> u64 {
    match fs::read_dir(game_dir) {
        Ok(entries) => {
            for entry in entries.flatten() {
                let path = entry.path();
                if path.is_file() {
                    if let Some(ext) = path.extension() {
                        let ext = ext.to_string_lossy().to_lowercase();
                        if ext == "zip" || ext == "rar" || ext == "7z" {
                            return path.metadata().map_or(0, |m| m.len());
                        }
                    }
                }
            }
            0
        }
        Err(_) => 0,
    }
}

/// Archive file creation timestamp as an ISO string, or empty string.
pub fn archive_created(game_dir: &Path) -> String {
    match fs::read_dir(game_dir) {
        Ok(entries) => {
            for entry in entries.flatten() {
                let path = entry.path();
                if path.is_file() {
                    if let Some(ext) = path.extension() {
                        let ext = ext.to_string_lossy().to_lowercase();
                        if ext == "zip" || ext == "rar" || ext == "7z" {
                            if let Ok(st) = path.metadata() {
                                if let Ok(time) = st.created() {
                                    if let Ok(duration) = time.duration_since(std::time::UNIX_EPOCH)
                                    {
                                        let secs = duration.as_secs();
                                        let (days, rem) = (secs / 86400, secs % 86400);
                                        let (years, rem) = (days / 365, rem);
                                        let (months, days) = (rem / 30, rem % 30);
                                        let (hours, rem) = (rem / 3600, rem % 3600);
                                        let minutes = rem / 60;
                                        return format!(
                                            "{:04}-{:02}-{:02} {:02}:{:02}",
                                            1970 + years,
                                            1 + months,
                                            1 + days,
                                            hours,
                                            minutes
                                        );
                                    }
                                }
                            }
                        }
                    }
                }
            }
            String::new()
        }
        Err(_) => String::new(),
    }
}

/// The best banner image for a game folder, by priority then any image file.
pub fn find_banner(game_dir: &Path, prefix: &str) -> Option<PathBuf> {
    let marker = format!("{}_", prefix);
    let mut files: std::collections::HashMap<String, PathBuf> = std::collections::HashMap::new();
    if let Ok(entries) = fs::read_dir(game_dir) {
        for entry in entries.flatten() {
            let f = entry.path();
            if let Some(ext) = f.extension() {
                let ext = ext.to_string_lossy().to_lowercase();
                if ext == "jpg" || ext == "jpeg" || ext == "png" || ext == "webp" {
                    if let Some(stem) = f.file_stem().and_then(|s| s.to_str()) {
                        if stem.starts_with(&marker) {
                            let key = stem[marker.len()..].to_string();
                            files.insert(key, f);
                        }
                    }
                }
            }
        }
    }
    for key in BANNER_PRIORITY.iter() {
        if files.contains_key(*key) {
            return files.get(*key).cloned();
        }
    }
    if let Ok(entries) = fs::read_dir(game_dir) {
        let mut all_images: Vec<PathBuf> = Vec::new();
        for entry in entries.flatten() {
            let f = entry.path();
            if let Some(ext) = f.extension() {
                let ext = ext.to_string_lossy().to_lowercase();
                if ext == "jpg" || ext == "jpeg" || ext == "png" || ext == "webp" {
                    all_images.push(f);
                }
            }
        }
        all_images.sort();
        return all_images.into_iter().next();
    }
    None
}

/// Steam store page URL for an appid.
pub fn store_url(appid: &str) -> String {
    format!("https://store.steampowered.com/app/{}/", appid)
}

/// steam:// protocol link for an appid.
pub fn steam_protocol_url(appid: &str) -> String {
    format!("steam://store/{}", appid)
}

/// URL-safe anchor/fragment from a category or game name.
pub fn anchor(name: &str) -> String {
    let lower = name.to_lowercase();
    let s: String = lower
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() { c } else { '-' })
        .collect();
    let s: String = s
        .split('-')
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join("-");
    if s.is_empty() {
        "category".to_string()
    } else {
        s
    }
}

/// True when candidate resolves to root or lives somewhere beneath it.
pub fn path_within(candidate: &Path, root: &Path) -> bool {
    match (candidate.canonicalize(), root.canonicalize()) {
        (Ok(candidate), Ok(root)) => candidate == root || candidate.starts_with(&root),
        _ => false,
    }
}

/// Filesystem-safe asset prefix for a game folder.
pub fn asset_prefix(game_dir: &Path, metadata: Option<&serde_json::Value>) -> String {
    if let Some(metadata) = metadata {
        if let Some(name) = metadata.get("name").and_then(|v| v.as_str()) {
            return safe_name(name);
        }
    }
    let name = game_dir.file_name().and_then(|s| s.to_str()).unwrap_or("");
    let name = regex::Regex::new(r"\s*-\s*(?:\d{4}-\d{2}-\d{2}|Unknown Release Date)$")
        .unwrap()
        .replace_all(name, "")
        .trim()
        .to_string();
    if name.is_empty() {
        game_dir
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("")
            .to_string()
    } else {
        name
    }
}

/// steamgameorganizer:// link that unpacks a category, or the whole library when empty.
pub fn batch_uri(category: &str) -> String {
    if category.is_empty() {
        format!("{}://extract-all", SCHEME)
    } else {
        format!("{}://extract-all?category={}", SCHEME, url_encode(category))
    }
}

/// steamgameorganizer:// link that unpacks only games not already extracted.
pub fn remaining_uri() -> String {
    format!("{}://extract-remaining", SCHEME)
}

/// steamgameorganizer:// link that opens the setup wizard.
pub fn setup_uri() -> String {
    format!("{}://setup", SCHEME)
}

/// steamgameorganizer:// link that asks the app to regenerate the catalog.
pub fn refresh_uri() -> String {
    format!("{}://refresh-catalog", SCHEME)
}

/// steamgameorganizer:// link for a game's archive, percent-encoded.
pub fn extract_uri(game: &serde_json::Value) -> String {
    let name = game.get("archive").and_then(|v| v.as_str()).unwrap_or("");
    if name.is_empty() {
        return String::new();
    }
    let folder = game.get("folder").and_then(|v| v.as_str()).unwrap_or("");
    let source = Path::new(folder).join(name);
    format!(
        "{}://extract?src={}",
        SCHEME,
        url_encode(&source.to_string_lossy())
    )
}

/// steamgameorganizer://open-folder link for a game's folder.
pub fn open_folder_uri(game: &serde_json::Value) -> String {
    let folder_rel = game
        .get("folder_rel")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    format!("{}://open-folder?path={}", SCHEME, url_encode(folder_rel))
}

/// HTML for a batch Extract link carrying a category name.
pub fn batch_button(
    category: &str,
    count: u32,
    total_bytes: u64,
    label: &str,
    title: &str,
    scope: &str,
) -> String {
    if count == 0 {
        return String::new();
    }
    let plural = if count == 1 { "" } else { "s" };
    let mut detail = format!("{} game{}", count, plural);
    if total_bytes > 0 {
        detail.push_str(&format!(", {}", human_size(Some(total_bytes as f64))));
    }
    let shown = if scope.is_empty() { category } else { scope };
    format!(
        r#"<a class="btn btn-batch" href="{}" data-batch="{}" data-batch-count="{}" data-batch-size="{}" data-batch-name="{}" data-batch-confirm="{} ({})">{label} {count}</a>"#,
        batch_uri(category),
        batch_uri(category),
        count,
        total_bytes,
        html_escape(shown),
        html_escape(title),
        html_escape(&detail),
    )
}

/// HTML for a batch Extract link that unpacks only not-yet-extracted games.
pub fn remaining_button(count: u32, label: &str, title: &str) -> String {
    if count == 0 {
        return String::new();
    }
    let plural = if count == 1 { "" } else { "s" };
    let detail = format!("{} game{}", count, plural);
    format!(
        r#"<a class="btn btn-batch" href="{}" data-batch="{}" data-batch-count="{}" data-batch-size="0" data-batch-name="{}" data-batch-confirm="{} ({})">{label} {count}</a>"#,
        remaining_uri(),
        remaining_uri(),
        count,
        html_escape("the remaining games"),
        html_escape(title),
        html_escape(&detail),
    )
}

fn url_encode(s: &str) -> String {
    // Simple percent-encoding for URI query values
    let mut result = String::new();
    for c in s.chars() {
        if c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.' | '~') {
            result.push(c);
        } else {
            for b in c.encode_utf8(&mut [0u8; 4]).bytes() {
                result.push('%');
                result.push_str(&format!("{:02X}", b));
            }
        }
    }
    result
}

fn html_escape(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&#39;")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_safe_name() {
        assert_eq!(safe_name("My Game"), "My Game");
        assert_eq!(safe_name("My<Game>"), "My Game");
        assert_eq!(safe_name(""), "Unnamed Game");
    }

    #[test]
    fn test_clean_tags() {
        let tags = clean_tags(Some(&[
            "Action".to_string(),
            "Action".to_string(),
            "".to_string(),
        ]));
        assert_eq!(tags, vec!["Action"]);
    }

    #[test]
    fn test_anchor() {
        assert_eq!(anchor("Action & Adventure"), "action-adventure");
        assert_eq!(anchor(""), "category");
    }

    #[test]
    fn test_batch_uri() {
        assert_eq!(
            batch_uri("Action"),
            "steamgameorganizer://extract-all?category=Action"
        );
        assert_eq!(batch_uri(""), "steamgameorganizer://extract-all");
    }

    #[test]
    fn test_batch_button_empty() {
        assert_eq!(batch_button("Action", 0, 0, "Extract", "Title", ""), "");
    }
}
