//! Steam Game Organizer — Rust conversion (one file at a time).
//!
//! Pure `core/` and `utils/` modules are ported here first, then `services/`,
//! `app/`, and finally `ui/`. Each converted module keeps a comment explaining
//! what changed and why. Python files that have not yet been converted remain
//! the source of truth until their Rust replacement passes `cargo test` and is
//! lint-clean.

pub mod errors;
pub mod state;
pub mod category_evidence;
pub mod constants;
pub mod canonical_category;
pub mod suggest_category_with_evidence;
pub mod models;
pub mod naming_utils;
pub mod library_summary;
