//! `write_extract_result` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! 2026-11-25: Converted from `services/write_extract_result.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use chrono::Utc;
use serde_json;
use std::path::{Path, PathBuf};

use crate::core::catalog_status::{status_javascript, STATUS_NAME};
use crate::core::extract_result::ExtractResult;

/// Write a single extract's outcome next to the catalog, so a headless handler leaves a durable answer.
///
/// The protocol handler runs with no window in the foreground: it prints to stdout and exits, and the
/// console the browser opened vanishes before the message is read. A file on disk outlives the window
/// and is where the reader can look when nothing appeared on screen. The page reads it the next time
/// the catalog is opened, so the result is visible without regenerating anything.
pub fn write_extract_result(
    library_root: &Path,
    archive: &Path,
    result: &ExtractResult,
    logger: Option<&dyn Fn(&str, &str)>,
) -> Option<PathBuf> {
    let path = Path::new(library_root).join(STATUS_NAME);
    let status = serde_json::json!({
        "ran_at": Utc::now().format("%Y-%m-%d %H:%M").to_string(),
        "category": "",
        "destination": result.destination.to_string_lossy(),
        "total": 1,
        "extracted": if result.ok { 1 } else { 0 },
        "skipped": 0,
        "failed": if result.ok { 0 } else { 1 },
        "cancelled": 0,
        "already_done": 0,
        "needs_install": 0,
        "elapsed": "",
        "single_archive": archive.to_string_lossy(),
        "single_message": result.message,
    });
    match std::fs::write(&path, status_javascript(&status)) {
        Ok(()) => {
            if let Some(logger) = logger {
                logger(
                    "CATALOG",
                    &format!(
                        "SINGLE_EXTRACT_STATUS_WRITTEN path=[{}] ok={}",
                        path.display(),
                        result.ok
                    ),
                );
            }
            Some(path)
        }
        Err(exc) => {
            if let Some(logger) = logger {
                logger(
                    "CATALOG",
                    &format!(
                        "STATUS_WRITE_FAILED path=[{}] error={}",
                        path.display(),
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
    fn test_write_extract_result_status_fields() {
        let result = ExtractResult {
            ok: true,
            message: "Extracted OK".to_string(),
            ..ExtractResult::default()
        };
        let status = serde_json::json!({
            "ran_at": Utc::now().format("%Y-%m-%d %H:%M").to_string(),
            "category": "",
            "destination": result.destination.to_string_lossy(),
            "total": 1,
            "extracted": 1,
            "skipped": 0,
            "failed": 0,
            "cancelled": 0,
            "already_done": 0,
            "needs_install": 0,
            "elapsed": "",
            "single_archive": "test.zip",
            "single_message": "Extracted OK",
        });
        assert_eq!(status["extracted"], 1);
        assert_eq!(status["failed"], 0);
    }
}

