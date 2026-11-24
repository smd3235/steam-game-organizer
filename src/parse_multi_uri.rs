//! `parse_multi_uri` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! 2026-11-24: Converted from `core/parse_multi_uri.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::path::{Path, PathBuf};

use crate::configured_bases::configured_bases;
use crate::constants::ARCHIVE_EXTENSIONS;
use crate::destination_parent::destination_parent;
use crate::safe_folder_name::safe_folder_name;
use crate::setup_hint::setup_hint;
use crate::uri_actions::{MultiBatchRequest, UriRefused, SCHEME};
use crate::within::within;

/// Returns a MultiBatchRequest of individually-validated archive paths, or raises.
pub fn parse_multi_uri(
    uri: &str,
    library_root: &Path,
    extract_base: Option<Vec<&str>>,
) -> Result<MultiBatchRequest, UriRefused> {
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
    if action != "extract-multi" {
        return Err(UriRefused::new(&format!("Unknown action: {}", action)));
    }
    if library_root.as_os_str().is_empty() {
        return Err(UriRefused::new(&format!(
            "No game library is configured, so there is nothing to extract from.{}",
            setup_hint()
        )));
    }
    let bases = configured_bases(extract_base);
    let raw_dest = parse_query_param(rest, "dest");
    let parent = destination_parent(
        if raw_dest.is_empty() {
            None
        } else {
            Some(&raw_dest)
        },
        &bases,
        library_root,
    )?;
    let raw_sources: Vec<String> = rest
        .split('&')
        .filter_map(|pair| {
            let mut kv = pair.splitn(2, '=');
            if let (Some(k), Some(v)) = (kv.next(), kv.next()) {
                if k == "src" {
                    return Some(v.to_string());
                }
            }
            None
        })
        .collect();
    if raw_sources.len() < 2 {
        return Err(UriRefused::new(
            "Select at least two games to multi-extract.",
        ));
    }
    let mut archives: Vec<(PathBuf, PathBuf)> = Vec::new();
    for raw in &raw_sources {
        let archive = PathBuf::from(raw);
        if !within(&archive, library_root) {
            return Err(UriRefused::new(&format!(
                "Refused: {} is outside the game library.{}",
                raw,
                setup_hint()
            )));
        }
        if !archive.is_file() {
            return Err(UriRefused::new(&format!(
                "That archive is not there any more: {}",
                archive.file_name().unwrap_or_default().to_string_lossy()
            )));
        }
        if !ARCHIVE_EXTENSIONS.iter().any(|ext| {
            archive
                .extension()
                .and_then(|e| e.to_str())
                .map_or(false, |e| e.eq_ignore_ascii_case(ext))
        }) {
            return Err(UriRefused::new(&format!(
                "Not an archive this can unpack: {}",
                archive.file_name().unwrap_or_default().to_string_lossy()
            )));
        }
        let leaf = safe_folder_name(
            &archive.file_stem().and_then(|s| s.to_str()).unwrap_or(""),
            "game",
        );
        archives.push((archive.clone(), parent.join(&leaf)));
    }
    if archives.is_empty() {
        return Err(UriRefused::new("No valid archives were selected."));
    }
    Ok(MultiBatchRequest {
        archives,
        destination: parent,
    })
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
        assert_eq!(parse_query_param("src=foo&src=bar&dest=x", "src"), "foo");
    }
}
