//! `parse_open_folder_uri` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! 2026-11-24: Converted from `core/parse_open_folder_uri.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::path::{Path, PathBuf};

use crate::core::setup_hint::setup_hint;
use crate::core::uri_actions::{UriRefused, SCHEME};
use crate::core::within::within;

/// Returns the library folder path a steamgameorganizer://open-folder link carries, or refuses.
pub fn parse_open_folder_uri(uri: &str, library_root: &Path) -> Result<PathBuf, UriRefused> {
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
    if action != "open-folder" {
        return Err(UriRefused::new(&format!("Unknown action: {}", action)));
    }
    if library_root.as_os_str().is_empty() {
        return Err(UriRefused::new(&format!(
            "No game library is configured.{}",
            setup_hint()
        )));
    }
    let raw = parse_query_param(rest, "path");
    if raw.is_empty() {
        return Err(UriRefused::new(
            "The link did not say which folder to open.",
        ));
    }
    let folder = PathBuf::from(&raw);
    if !within(&folder, library_root) {
        return Err(UriRefused::new(&format!(
            "Refused: {} is outside the game library.{}",
            raw,
            setup_hint()
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
