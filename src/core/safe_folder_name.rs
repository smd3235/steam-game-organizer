//! `safe_folder_name` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! 2026-11-24: Converted from `core/safe_folder_name.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use lazy_static::lazy_static;
use regex::Regex;

lazy_static! {
    static ref UNSAFE_CHARS: Regex =
        Regex::new(r#"[<>:"/\\|?*\x00-\x1f]"#).expect("UNSAFE_CHARS regex is valid");
    static ref RESERVED_NAMES: Vec<String> = {
        let mut names: Vec<String> = vec![
            "con".to_string(),
            "prn".to_string(),
            "aux".to_string(),
            "nul".to_string(),
        ];
        for i in 1..=9 {
            names.push(format!("com{i}"));
            names.push(format!("lpt{i}"));
        }
        names
    };
}

/// A single path component that is safe on every filesystem this can land on.
///
/// Windows reserved device names and a trailing dot or space are stripped too: the catalog that supplies
/// these names may sit on a synced or shared folder, and a folder named "CON" is unusable
/// the moment it reaches one.
pub fn safe_folder_name(text: &str, fallback: &str) -> String {
    let cleaned = UNSAFE_CHARS.replace_all(text, " ");
    let cleaned = cleaned.replace(|c: char| c.is_whitespace(), " ");
    let cleaned = cleaned.trim().trim_matches(|c| c == ' ' || c == '.');
    if cleaned.is_empty()
        || RESERVED_NAMES
            .iter()
            .any(|r| cleaned.eq_ignore_ascii_case(r))
    {
        return fallback.to_string();
    }
    cleaned.chars().take(120).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_safe_folder_name_normal() {
        assert_eq!(safe_folder_name("My Game", "Extracted"), "My Game");
    }

    #[test]
    fn test_safe_folder_name_unsafe_chars() {
        assert_eq!(safe_folder_name("My<Game>", "Extracted"), "My Game");
    }

    #[test]
    fn test_safe_folder_name_reserved() {
        assert_eq!(safe_folder_name("CON", "Extracted"), "Extracted");
        assert_eq!(safe_folder_name("COM1", "Extracted"), "Extracted");
    }

    #[test]
    fn test_safe_folder_name_empty() {
        assert_eq!(safe_folder_name("", "Extracted"), "Extracted");
    }

    #[test]
    fn test_safe_folder_name_trailing_dot_space() {
        assert_eq!(safe_folder_name("Game . ", "Extracted"), "Game");
    }
}
