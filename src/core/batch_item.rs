//! `BatchItem` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! State constants (QUEUED, DONE, FAILED, SKIPPED, CANCELLED) live here inline
//! because `batch_extract_service.rs` has not been converted yet. When it is,
//! these should move there and be imported.
//!
//! 2026-11-25: Converted from `services/batch_item.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use serde::{Deserialize, Serialize};
use std::path::PathBuf;

pub const QUEUED: &str = "queued";
pub const EXTRACTING: &str = "extracting";
pub const DONE: &str = "done";
pub const FAILED: &str = "failed";
pub const SKIPPED: &str = "skipped";
pub const CANCELLED: &str = "cancelled";

/// One game in the queue, and where it stands.
///
/// 2026-11-20: Changed archive/destination annotations from Path to Option<Path>
/// to match the constructor accepting Option<Path>. mypy flagged assigning
/// Option[Path] to Path-typed attributes.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BatchItem {
    pub archive: Option<PathBuf>,
    pub destination: Option<PathBuf>,
    pub name: String,
    pub size: u64,
    pub state: String,
    pub detail: String,
    pub percent: u32,
    pub written: u64,
    pub files: u32,
}

impl BatchItem {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        archive: Option<PathBuf>,
        destination: Option<PathBuf>,
        name: String,
        size: u64,
        state: String,
        detail: String,
        percent: u32,
        written: u64,
        files: u32,
    ) -> Self {
        BatchItem {
            archive,
            destination,
            name,
            size,
            state,
            detail,
            percent,
            written,
            files,
        }
    }

    pub fn finished(&self) -> bool {
        matches!(self.state.as_str(), DONE | FAILED | SKIPPED | CANCELLED)
    }
}

impl Default for BatchItem {
    fn default() -> Self {
        BatchItem {
            archive: None,
            destination: None,
            name: String::new(),
            size: 0,
            state: QUEUED.to_string(),
            detail: String::new(),
            percent: 0,
            written: 0,
            files: 0,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_batch_item_default() {
        let item = BatchItem::default();
        assert_eq!(item.state, QUEUED);
        assert!(!item.finished());
        assert_eq!(item.name, "");
        assert_eq!(item.size, 0);
    }

    #[test]
    fn test_batch_item_finished_done() {
        let item = BatchItem {
            state: DONE.to_string(),
            ..Default::default()
        };
        assert!(item.finished());
    }

    #[test]
    fn test_batch_item_finished_failed() {
        let item = BatchItem {
            state: FAILED.to_string(),
            ..Default::default()
        };
        assert!(item.finished());
    }

    #[test]
    fn test_batch_item_finished_skipped() {
        let item = BatchItem {
            state: SKIPPED.to_string(),
            ..Default::default()
        };
        assert!(item.finished());
    }

    #[test]
    fn test_batch_item_finished_cancelled() {
        let item = BatchItem {
            state: CANCELLED.to_string(),
            ..Default::default()
        };
        assert!(item.finished());
    }

    #[test]
    fn test_batch_item_not_finished_queued() {
        let item = BatchItem {
            state: QUEUED.to_string(),
            ..Default::default()
        };
        assert!(!item.finished());
    }
}
