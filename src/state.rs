//! Thread-safe in-memory application state.
//!
//! `StateStore` holds the single source of truth for what the UI is showing right now —
//! the current phase, the scan result, the selected game, and any error — and hands
//! callers cloned state so no caller can mutate the live state by accident.
//!
//! 2026-11-24: Converted from `core/state.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::sync::RwLock;

use crate::models::AppState;

/// Thread-safe in-memory application state.
///
/// `get` returns a clone so the caller can rearrange the returned state without
/// touching what the UI or a background job is reading at the same moment.
pub struct StateStore {
    state: RwLock<AppState>,
}

impl Default for StateStore {
    fn default() -> Self {
        Self::new()
    }
}

impl StateStore {
    pub fn new() -> Self {
        Self {
            state: RwLock::new(AppState::default()),
        }
    }

    /// Returns a clone of the current state.
    pub fn get(&self) -> AppState {
        self.state.read().expect("state read lock poisoned").clone()
    }

    /// Applies changes and returns a clone of the updated state.
    pub fn update<F>(&self, changes: F) -> AppState
    where
        F: FnOnce(&mut AppState),
    {
        let mut state = self.state.write().expect("state write lock poisoned");
        changes(&mut state);
        state.clone()
    }
}
