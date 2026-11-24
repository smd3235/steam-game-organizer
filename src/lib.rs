//! Steam Game Organizer — Rust conversion (one file at a time).
//!
//! Pure `core/` and `utils/` modules are ported here first, then `services/`,
//! `app/`, and finally `ui/`. Each converted module keeps a comment explaining
//! what changed and why. Python files that have not yet been converted remain
//! the source of truth until their Rust replacement passes `cargo test` and is
//! lint-clean.

pub mod canonical_category;
pub mod category_evidence;
pub mod configured_bases;
pub mod constants;
pub mod errors;
pub mod library_summary;
pub mod logger;
pub mod models;
pub mod naming_utils;
pub mod safe_folder_name;
pub mod state;
pub mod suggest_category_with_evidence;
pub mod system_paths;
pub mod within;
