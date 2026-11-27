//! Thread-safe in-memory application state.
//!
//! `StateStore` holds the single source of truth for what the UI is showing right now —
//! the current phase, the scan result, the selected game, and any error — and hands
//! callers cloned state so no caller can mutate the live state by accident.
//!
//! 2026-11-24: Converted from `core/state.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::sync::RwLock;

use crate::core::models::AppState;

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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_state_store_default() {
        let store = StateStore::default();
        let state = store.get();
        assert_eq!(state.phase, "");
        assert!(!state.cancel_requested);
    }

    #[test]
    fn test_state_store_get_returns_clone() {
        let store = StateStore::new();
        let state1 = store.get();
        store.update(|s| s.phase = "scan".to_string());
        let state2 = store.get();
        // state1 should be unchanged
        assert_eq!(state1.phase, "");
        // state2 should reflect the update
        assert_eq!(state2.phase, "scan");
    }

    #[test]
    fn test_state_store_update_changes_state() {
        let store = StateStore::new();
        store.update(|s| {
            s.cancel_requested = true;
            s.developer_mode = true;
            s.last_error = "test error".to_string();
        });
        let state = store.get();
        assert!(state.cancel_requested);
        assert!(state.developer_mode);
        assert_eq!(state.last_error, "test error");
    }

    #[test]
    fn test_state_store_multiple_updates_accumulate() {
        let store = StateStore::new();
        store.update(|s| s.selected_index = Some(5));
        store.update(|s| s.job_id = "job-123".to_string());
        let state = store.get();
        assert_eq!(state.selected_index, Some(5));
        assert_eq!(state.job_id, "job-123");
    }
}
