//! `_parse_extract_root_action` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! 2026-11-24: Converted from `core/parse_extract_root_action.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::path::PathBuf;

use crate::configured_bases::configured_bases;
use crate::setup_hint::setup_hint;
use crate::uri_actions::{UriRefused, SCHEME};
use crate::within::within;

/// Validates an extract-root/marker directory URI.
pub fn parse_extract_root_action(
    uri: &str,
    extract_folders: Option<Vec<&str>>,
    expected_action: &str,
    must_have_marker: bool,
) -> Result<PathBuf, UriRefused> {
    let (scheme, rest) = uri
        .split_once("://")
        .ok_or_else(|| UriRefused::new("Unsupported link type: none"))?;
    if scheme.to_lowercase() != SCHEME {
        return Err(UriRefused::new(&format!(
            "Unsupported link type: {}",
            scheme
        )));
    }
    let (path_part, _query) = rest.split_once('?').unwrap_or((rest, ""));
    let action = path_part.trim().to_lowercase();
    if action != expected_action {
        return Err(UriRefused::new(&format!("Unknown action: {}", action)));
    }
    let bases = configured_bases(extract_folders);
    if bases.is_empty() {
        return Err(UriRefused::new(&format!(
            "No extract folder is configured.{}",
            setup_hint()
        )));
    }
    let raw = parse_query_param(rest, "path");
    if raw.is_empty() {
        return Err(UriRefused::new("The link did not say which folder to use."));
    }
    let folder = PathBuf::from(&raw);
    if !bases.iter().any(|b| within(&folder, b)) {
        return Err(UriRefused::new(&format!(
            "Refused: {} is outside the configured extract folders.",
            raw
        )));
    }
    let folder = folder
        .canonicalize()
        .map_err(|exc| UriRefused::new(&format!("That folder cannot be opened: {}", exc)))?;
    if !folder.is_dir() {
        return Err(UriRefused::new(&format!(
            "That folder is not there any more: {}",
            folder.file_name().unwrap_or_default().to_string_lossy()
        )));
    }
    if must_have_marker && !folder.join(".sgo-extract-info").is_file() {
        return Err(UriRefused::new(&format!(
            "That extracted folder has no marker information: {}",
            folder.file_name().unwrap_or_default().to_string_lossy()
        )));
    }
    Ok(folder)
}

fn parse_query_param(query: &str, key: &str) -> String {
    for pair in query.split('&') {
        let mut kv = pair.splitn(2, '=');
        if let (Some(k), Some(v)) = (kv.next(), kv.next()) {
            if k == key {
                return v.to_string();
            }
        }
    }
    String::new()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_query_param() {
        assert_eq!(parse_query_param("path=foo&other=bar", "path"), "foo");
    }
}
