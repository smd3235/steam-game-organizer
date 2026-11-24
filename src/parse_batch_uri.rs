//! `parse_batch_uri` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! 2026-11-24: Converted from `core/parse_batch_uri.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::path::{Path, PathBuf};

use crate::category_folder::category_folder;
use crate::configured_bases::configured_bases;
use crate::destination_parent::destination_parent;
use crate::setup_hint::setup_hint;
use crate::uri_actions::{BatchExtractRequest, UriRefused, SCHEME};

/// Returns a BatchExtractRequest naming a category, or raises UriRefused with a message for the user.
pub fn parse_batch_uri(
    uri: &str,
    library_root: &Path,
    extract_base: Option<Vec<&str>>,
) -> Result<BatchExtractRequest, UriRefused> {
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
    if action != "extract-all" && action != "extract-remaining" {
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
    let category = parse_query_param(rest, "category").trim().to_string();
    if !category.is_empty() {
        category_folder(Some(&category), library_root)?;
    }
    Ok(BatchExtractRequest {
        category,
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
        assert_eq!(
            parse_query_param("category=action&dest=x", "category"),
            "action"
        );
    }
}
