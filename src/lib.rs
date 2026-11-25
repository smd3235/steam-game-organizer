//! Steam Game Organizer — Rust conversion (one file at a time).
//!
//! Pure `core/` and `utils/` modules are ported here first, then `services/`,
//! `app/`, and finally `ui/`. Each converted module keeps a comment explaining
//! what changed and why. Python files that have not yet been converted remain
//! the source of truth until their Rust replacement passes `cargo test` and is
//! lint-clean.

pub mod canonical_category;
pub mod catalog_utils;
pub mod category_evidence;
pub mod category_folder;
pub mod clear_tool_cache;
pub mod configured_bases;
pub mod constants;
pub mod desktop;
pub mod destination_parent;
pub mod errors;
pub mod extract_result;
pub mod filename_utils;
pub mod formatting;
pub mod installer_detect;
pub mod library_summary;
pub mod library_utils;
pub mod logger;
pub mod models;
pub mod naming_utils;
pub mod organizer_utils;
pub mod parse_batch_uri;
pub mod parse_extract_root_action;
pub mod parse_mark_installed_uri;
pub mod parse_multi_uri;
pub mod parse_open_extracted_uri;
pub mod parse_open_folder_uri;
pub mod parse_pick_launcher_uri;
pub mod parse_setup_uri;
pub mod parse_uri;
pub mod path_safety;
pub mod prefill;
pub mod safe_folder_name;
pub mod scan_view_utils;
pub mod setup_hint;
pub mod shape_name;
pub mod sort_date;
pub mod state;
pub mod steam_query_utils;
pub mod suggest_category_with_evidence;
pub mod system_paths;
pub mod treewalk;
pub mod typed_destination;
pub mod uri_actions;
pub mod within;
