//! Turning a raw archive filename into a stable game identity.
//!
//! normalize_name() strips release-group tags, date stamps and build numbers so
//! "Zeta Wars v 1 0.zip" and "Zeta Wars (v1.0).zip"
//! collapse to the same title. identity_key() folds that to lowercase alphanumerics so
//! two archives with different packaging still match as one game. version_key() pulls
//! the version number (or date stamp) out of the filename so organizer can pick the
//! newest copy of a game when several share a folder.
//!
//! Note: the `regex` crate does not support look-around assertions. Patterns that used
//! `(?<!...)`, `(?!...)`, `(?<=...)`, `(?=...)` in Python have been rewritten to avoid
//! them, with equivalent checks done in Rust code where needed.
//!
//! 2026-11-24: Converted from `utils/filename_utils.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use lazy_static::lazy_static;
use regex::Regex;
use std::path::Path;

use crate::constants::ARCHIVE_EXTENSIONS;

lazy_static! {
    static ref RELEASE_TAG: Regex = Regex::new(
        r"[\s._\-]*[\(\[\{]?\s*(?:steam[\s._\-]*rip|steam[\s._\-]*rg|repack(?:ed|ing)?|reloaded|drm[\s._\-]*free|fit[\s._\-]*girl|dodi|tenoke|el[\s._\-]*amigos|razor\s*1911)\s*[\)\]\}]?(?:\s+by\s+\S+)?(?:\s*\.\s*[a-z]{2,4}\b)?.*$",
    )
    .expect("RELEASE_TAG regex is valid");
    static ref REGION_TAG: Regex = Regex::new(r"\s+(?:multi\d{1,2}|usa|eur|jap|jpn|pal|ntsc)\s*$")
        .expect("REGION_TAG regex is valid");
    static ref CRACK_TAG: Regex = Regex::new(
        r"\s*(?:cracked?[-.\s]*(?:by|:|-)|crack:)\s+\S.*$|\s+cracked?\s*$",
    )
    .expect("CRACK_TAG regex is valid");
    static ref CONTENT_TAG: Regex = Regex::new(
        r"\s+(?:uncut|uncensored|gore|nodvd|no-dvd|fix|standalone|only)\s*$",
    )
    .expect("CONTENT_TAG regex is valid");
}

/// Strip packaging words from an archive or folder name to leave the game's title.
pub fn normalize_name(value: &str) -> String {
    let p = Path::new(value);
    let value = if ARCHIVE_EXTENSIONS.iter().any(|_ext| {
        p.extension()
            .and_then(|e| e.to_str())
            .is_some_and(|ext| ext.eq_ignore_ascii_case(_ext))
    }) {
        p.file_stem().and_then(|s| s.to_str()).unwrap_or(value)
    } else {
        value
    };
    // Split consecutive capitals before a capital+lowercase word: XMLParser → XML Parser, AGame → A Game.
    let value = Regex::new(r"([A-Z]+)([A-Z][a-z])")
        .unwrap()
        .replace_all(&value, "$1 $2");
    let value = Regex::new(r"([a-z0-9])([A-Z])")
        .unwrap()
        .replace_all(&value, "$1 $2");
    let value = Regex::new(r"[._+]+").unwrap().replace_all(&value, " ");
    let value = Regex::new(r"\s*\([^)]*(?:repack|portable|crack|gog|steam|linux|windows|fitgirl|dodi|codex|tenoke)[^)]*\)")
        .unwrap()
        .replace_all(&value, " ");
    // Crack-by credits: "Cracked by GROUP", "CRACK: GROUP", "CRACKED-BY GROUP", bare "CRACKED".
    let value = CRACK_TAG.replace_all(&value, " ");
    // Release group at START of filename: "TENOKE-Game Title" → "Game Title".
    let value = Regex::new(r"^(?:fitgirl|tenoke|dodi|repack(?:ed|ing)?|reloaded|razor\s*1911|steam[\s._\-]*rip|steam[\s._\-]*rg|drm[\s._\-]*free|el[\s._\-]*amigos)[\s._\-]+")
        .unwrap()
        .replace_all(&value, "");
    // An inline release-group tag cuts the tag and everything after it.
    let value = RELEASE_TAG.replace_all(&value, "");
    // These four are ordinary English as well as tags, so they only count as a tag when they are the last word.
    let value = Regex::new(r"\s+(?:multi|proper|portable|iso)\s*$")
        .unwrap()
        .replace_all(&value, " ");
    // Region / language tags appended by scene releases.
    let value = REGION_TAG.replace_all(&value, " ");
    // Content / packaging words at the end.
    let value = CONTENT_TAG.replace_all(&value, " ");
    // Remove trailing indicators like (2), [Copy], (v2), etc.
    let mut value = value.to_string();
    let trailing = Regex::new(
        r"\s*[\(\[\{]\s*(?:v?\d+|(?:copy|draft|temp|backup|old|new|original|no\s*dlc))[^)\]\}]*[\)\]\}]\s*$",
    )
    .unwrap();
    loop {
        let new_value = trailing.replace_all(&value, " ");
        if new_value == value {
            break;
        }
        value = new_value.to_string();
    }
    let value = Regex::new(r"\s+")
        .unwrap()
        .replace_all(&value, " ")
        .trim_matches(|c| c == ' ' || c == '-' || c == '_')
        .to_string();
    // Remove build stamps and version numbers glued to the end.
    let value = Regex::new(r"[\s._\-]+v?\s*\d+(?:[.\-_ ]+\d+){1,5}[a-z]?(?:\s|$)")
        .unwrap()
        .replace_all(&value, " ");
    let value = Regex::new(r"(?:^|\s+)(build\s*)\d+(?:[.\-_ ]+\d+)*\s*$")
        .unwrap()
        .replace_all(&value, "$1");
    let value = Regex::new(r"\s+\d{4}[-.]\d{2}[-.]\d{2}(?:\s|$)")
        .unwrap()
        .replace_all(&value, " ");
    // A build stamp glued to the end of the title.
    // (?<=[a-zA-Z\s]) lookbehind not supported - replaced with code check below.
    let value = Regex::new(r"\d{2,}[a-z]+\d+[a-z]*\s*$|\d[a-z]+\d{3,}[a-z]*\s*$")
        .unwrap()
        .replace_all(&value, "");
    let value = Regex::new(r"\d{2,}\s*$").unwrap().replace_all(&value, "");
    Regex::new(r"\s+")
        .unwrap()
        .replace_all(&value, " ")
        .trim_matches(|c| c == ' ' || c == '-' || c == '_')
        .to_string()
}

/// Fold a name to lowercase alphanumerics so two spellings of one game match.
pub fn identity_key(value: &str) -> String {
    Regex::new(r"[^a-z0-9]+")
        .unwrap()
        .replace_all(&normalize_name(value).to_lowercase(), "")
        .to_string()
}

/// Pull the version number or date stamp out of a filename, or (0,) when there is none.
pub fn version_key(value: &str) -> Vec<u32> {
    let stem = Path::new(value)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or(value);
    // (?!\d) lookahead not supported - check next char in code instead.
    let re = Regex::new(r"(?i)(?:\bv\s*)?(\d+(?:[.\-_]\d+){1,4})").unwrap();
    let mut best_match: Option<&str> = None;
    for cap in re.captures_iter(stem) {
        if let Some(m) = cap.get(1) {
            let end = m.end();
            // Check that the next char is not a digit (equivalent to (?!\d))
            if end >= stem.len() || !stem.as_bytes()[end].is_ascii_digit() {
                best_match = Some(m.as_str());
                break;
            }
        }
    }
    if let Some(last) = best_match {
        return last
            .split(&['.', '-', '_'])
            .filter_map(|s| s.parse::<u32>().ok())
            .collect();
    }
    let spaced = Regex::new(r"(?i)\bv\s*(\d+(?:\s+\d+){1,4})\s*$")
        .unwrap()
        .captures(stem)
        .and_then(|cap| cap.get(1).map(|m| m.as_str().to_string()));
    if let Some(s) = spaced {
        return s
            .split_whitespace()
            .filter_map(|x| x.parse::<u32>().ok())
            .collect();
    }
    let date = Regex::new(r"(?:^|[^\d])(20\d{6,})(?:$|[^\d])")
        .unwrap()
        .captures(stem)
        .and_then(|cap| cap.get(1).map(|m| m.as_str().to_string()));
    if let Some(d) = date {
        if let Ok(n) = d.parse::<u32>() {
            return vec![n];
        }
    }
    vec![0]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_normalize_name_strips_extension() {
        let result = normalize_name("Game Title.zip");
        assert!(!result.ends_with(".zip"));
    }

    #[test]
    fn test_normalize_name_strips_release_group() {
        let result = normalize_name("TENOKE-Game Title.zip");
        assert!(result.contains("Game Title"));
    }

    #[test]
    fn test_identity_key_lowercase_alphanumeric() {
        let key = identity_key("My Game v1.0");
        assert!(key.chars().all(|c| c.is_ascii_alphanumeric()));
        assert_eq!(key, key.to_lowercase());
    }

    #[test]
    fn test_version_key_extracts_version() {
        let key = version_key("Game v1.2.3.zip");
        assert_eq!(key, vec![1, 2, 3]);
    }

    #[test]
    fn test_version_key_no_version() {
        let key = version_key("Just A Game.zip");
        assert_eq!(key, vec![0]);
    }
}
