//! Shared CLI argument definitions used by both `src/bin.rs` (GUI binary entry)
//! and `src/entry.rs` (headless CLI entry). Defining `Args` in one place
//! prevents the two entry points from diverging as new flags are added.

use clap::Parser;
use std::path::PathBuf;

/// CLI arguments for the Steam Game Organizer application.
///
/// Used by both the GUI binary (`src/bin.rs`) and the headless entry point
/// (`src/entry.rs`). Every flag must be handled in both entry points or the
/// behavior will differ between GUI and CLI invocation.
#[derive(Parser, Debug)]
#[command(author, version, about = "Steam Game Organizer", long_about = None)]
pub struct Args {
    /// Run deterministic mock data; no real library changes
    #[arg(long)]
    pub mock: bool,

    /// Run sandbox mode: simulate UI interactions end-to-end, read logs, report issues
    #[arg(long)]
    pub sandbox: bool,

    /// Run the full quality gate: check, clippy, test, build, dependency audit
    #[arg(long)]
    pub quality_gate: bool,

    /// Run dependency audit: check for outdated crates and security vulnerabilities
    #[arg(long)]
    pub dependency_audit: bool,

    /// Build a Windows installer using Inno Setup
    #[arg(long)]
    pub build_installer: bool,

    /// Check SteamCMD availability and Steam installation status
    #[arg(long)]
    pub steamcmd_check: bool,

    /// Scan library for duplicate archives by normalized name + file size
    #[arg(long)]
    pub duplicate_detector: Option<String>,

    /// Scan library for health issues (unidentified, orphaned, oversized)
    #[arg(long)]
    pub library_health_scan: Option<String>,

    /// Scan archives for encryption/password protection
    #[arg(long)]
    pub archive_encryption_scan: Option<String>,

    /// Analyze Steam match confidence distribution across archives
    #[arg(long)]
    pub steam_match_confidence: Option<String>,

    /// Scan for interrupted operations and clean up temp/journal/lock files
    #[arg(long)]
    pub crash_recovery: Option<String>,

    /// Run full system diagnostics: dependency audit, library health,
    /// Steam match confidence, archive encryption, duplicates, crash recovery,
    /// SteamCMD, and installer build readiness
    #[arg(long)]
    pub system_diagnostics: bool,

    /// Verify UI buttons are visible via OCR: launch app, capture all views,
    /// run Tesseract OCR on each screenshot, confirm expected button text appears
    #[arg(long)]
    pub verify_ui: bool,

    /// Print diagnostics report and exit
    #[arg(long)]
    pub diagnostics: bool,

    /// Print health text and exit
    #[arg(long)]
    pub health: bool,

    /// Print version and exit
    #[arg(short, long)]
    pub version: bool,

    /// Handle a steamgameorganizer:// link. Empty means launch the GUI.
    #[arg(long, num_args = 0..=1)]
    pub uri: Option<String>,

    /// Extract an archive to the extract folder, then exit
    #[arg(long)]
    pub extract: Option<String>,

    /// Open the setup wizard, then exit
    #[arg(long)]
    pub setup: bool,

    /// Destination folder for --extract (default: the extract folder)
    #[arg(long)]
    pub dest: Option<String>,

    /// Password for an encrypted .zip or .rar
    #[arg(long, default_value = "")]
    pub zip_password: String,

    /// Launch a single UI view in isolation (scan, review, organize, artwork, done, setup) for testing/screenshots
    #[arg(long)]
    pub view: Option<String>,

    /// Library root directory for mock mode (overrides config)
    #[arg(long)]
    pub library_root: Option<String>,

    /// Mock scenario: empty, populated, error, loading
    #[arg(long, default_value = "populated")]
    pub scenario: String,

    /// Validate settings.json schema and report unknown keys / bad types
    #[arg(long)]
    pub config_validate: bool,
}

/// Resolve the project root by searching upward from the exe directory for Cargo.toml.
///
/// Shared by both `src/bin.rs` (GUI entry) and `src/entry.rs` (headless CLI entry)
/// so the two entry points cannot diverge in how they locate the project root.
pub fn resolve_project_root() -> PathBuf {
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_default());

    let mut root = exe_dir.clone();
    for candidate in exe_dir.ancestors() {
        if candidate.join("Cargo.toml").is_file() {
            root = candidate.to_path_buf();
            break;
        }
    }

    // Refuse to resolve to a drive root (e.g. C:\, C:\\) — creating config/logs there
    // would pollute the drive root instead of the project directory.
    let root_str = root.to_string_lossy().to_string();
    let is_drive_root = root_str.len() >= 2
        && root_str.as_bytes()[1] == b':'
        && (root_str.len() == 3 || root_str.as_bytes()[2] == b'\\');
    if is_drive_root {
        return exe_dir
            .parent()
            .unwrap_or(&std::env::current_dir().unwrap_or_default())
            .to_path_buf();
    }
    root
}
