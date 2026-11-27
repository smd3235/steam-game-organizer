//! Tools modules: build and utility scripts.
//!
//! Ported from `tools/*.py`.
//!
//! 2026-11-25: Rust conversion from `tools/*.py` in the Rust conversion.

pub mod analyze_screenshot;
pub mod archive_encryption_scanner;
pub mod audit_module_splits;
pub mod auto_backup;
pub mod build_icon;
pub mod build_installer;
pub mod bundle_runtime;
pub mod capture_screens;
pub mod compare_backups;
pub mod crash_recovery;
pub mod dependency_audit;
pub mod dead_space_audit;
pub mod duplicate_detector;
pub mod install_protocol_handler;
pub mod layout_audit;
pub mod library_health_scan;
pub mod log_audit;
pub mod ocr_test;
pub mod overnight_repair;
pub mod quality_gate;
pub mod restore_backup;
pub mod sandbox;
pub mod search_backups;
pub mod steam_match_confidence;
pub mod steamcmd_check;
pub mod tk_probe;
pub mod validate_game_names;
pub mod verify_archives;
