//! `update_extract_marker` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! 2026-11-25: Converted from `services/update_extract_marker.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use serde_json;
use std::path::Path;

use crate::core::catalog_status::{extract_marker_path, read_extract_marker};

/// Merge updates into an existing `.sgo-extract-info` marker.
///
/// Best-effort and non-destructive: preserves existing fields and only writes when the
/// marker already exists or `create_if_missing=true` is passed. Returns the updated
/// marker dict on success, else None.
pub fn update_extract_marker(
    destination: &Path,
    logger: Option<&dyn Fn(&str, &str)>,
    create_if_missing: bool,
    updates: &[(&str, serde_json::Value)],
) -> Option<serde_json::Value> {
    let dest = destination.to_path_buf();
    let marker = extract_marker_path(&dest);
    let mut data = read_extract_marker(&dest);
    if data.is_none() {
        if !create_if_missing || !dest.is_dir() {
            return None;
        }
        data = Some(serde_json::json!({ "extracted_root": dest.to_string_lossy() }));
    }
    let mut changed = false;
    let Some(value) = data.as_mut() else {
        return None;
    };
    let Some(obj) = value.as_object_mut() else {
        return None;
    };
    for (key, value) in updates {
        if value.is_null() {
            if obj.contains_key(*key) {
                obj.remove(*key);
                changed = true;
            }
            continue;
        }
        if obj.get(*key) != Some(value) {
            obj.insert(key.to_string(), value.clone());
            changed = true;
        }
    }
    if !changed && marker.exists() {
        return data;
    }
    match std::fs::write(&marker, serde_json::to_string_pretty(&data).ok()?) {
        Ok(()) => data,
        Err(exc) => {
            if let Some(logger) = logger {
                logger(
                    "CATALOG",
                    &format!(
                        "MARKER_UPDATE_FAILED path=[{}] error={}",
                        marker.display(),
                        exc
                    ),
                );
            }
            None
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_update_extract_marker_create_if_missing_false() {
        use std::env;
        let temp = env::temp_dir().join(format!("test_update_{}", std::process::id()));
        std::fs::create_dir_all(&temp).ok();
        let result = update_extract_marker(&temp, None, false, &[]);
        assert!(result.is_none());
        let _ = std::fs::remove_dir_all(&temp);
    }
}

