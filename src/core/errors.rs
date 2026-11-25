//! Application errors.
//!
//! `OrganizerError` is the base; `CancellationError` is raised by `JobContext.checkpoint()`
//! when a run is cancelled, and every phase catches it separately so a cancel stops
//! the current game without aborting the whole run.
//!
//! 2026-11-24: Converted from `core/exceptions.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use thiserror::Error;

/// Base application error.
#[derive(Debug, Error)]
pub enum OrganizerError {
    #[error("{0}")]
    Message(String),
}

/// Raised when a run is cancelled; every phase catches it separately so a cancel
/// stops the current game without aborting the whole run.
#[derive(Debug, Error)]
pub struct CancellationError {
    #[source]
    pub inner: Option<Box<dyn std::error::Error + Send + Sync>>,
}

impl CancellationError {
    pub fn new() -> Self {
        CancellationError { inner: None }
    }
}

impl Default for CancellationError {
    fn default() -> Self {
        Self::new()
    }
}

impl std::fmt::Display for CancellationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "operation cancelled")
    }
}

impl From<OrganizerError> for CancellationError {
    fn from(_: OrganizerError) -> Self {
        CancellationError::new()
    }
}
