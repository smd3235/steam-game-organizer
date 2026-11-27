//! Entry point for the Steam Game Organizer application.
//! Stub conversion of `steam_game_organizer.py`.
//!
//! Holds URI handlers, setup wizard dispatch, extract dispatch, and the first-run setup check.
//!
//! 2026-11-25: Rust conversion from `steam_game_organizer.py` in the Rust conversion.

use std::path::{Path, PathBuf};
use std::sync::Arc;
use time::OffsetDateTime;

use crate::app::application::Application;
use crate::core::config::AppConfig;
use crate::core::logger::AppLogger;
use crate::core::path_safety::safe_create_dir_all;
use crate::services::catalog_service::CatalogService;
use crate::services::extract_service::ExtractService;
use crate::services::setup_service::SetupService;

const APP_NAME: &str = "Steam Game Organizer";

/// No-op logger callback for stub services.
fn noop_log(_cat: &str, _msg: &str) {}

/// Build a map of archive Path -> (steam_name, release_date) from catalog metadata.
pub fn build_name_map(
    _logger: &AppLogger,
    _library_root: &Path,
) -> std::collections::HashMap<PathBuf, (String, String)> {
    let name_map: std::collections::HashMap<PathBuf, (String, String)> =
        std::collections::HashMap::new();
    // Stub: CatalogService::_collect not yet implemented
    name_map
}

/// Open the three-folder setup wizard. Returns None on success, 0 if cancelled.
pub fn _open_setup(config: &AppConfig, _logger: &AppLogger, _prefill: Option<&str>) -> Option<i32> {
    let service = SetupService::new(Arc::new(noop_log), None, None);
    let (saved, _rows) = service.apply(
        config,
        config
            .library_root
            .as_deref()
            .and_then(|p| p.to_str())
            .unwrap_or(""),
        "",
        config.extract_folder().to_str().unwrap_or(""),
    );
    if saved {
        None
    } else {
        Some(0)
    }
}

/// Opens the extracted game/installer folder.
pub fn _handle_open_extracted_uri(_uri: &str, _config: &AppConfig, logger: &AppLogger) -> i32 {
    logger.warning(
        "EXTRACT",
        &format!("URI_REFUSED uri=[{}] reason=[not yet implemented]", _uri),
        "",
    );
    2
}

/// Regenerate catalog after a state-changing action and open it (best-effort).
pub fn _regenerate_catalog_and_open(config: &AppConfig, _logger: &AppLogger) {
    if let Some(library_root) = &config.library_root {
        let folders: Vec<PathBuf> = config.extract_folders();
        let extract_refs: Vec<&Path> = folders.iter().map(|p| p.as_path()).collect();
        let catalog = CatalogService::new(Arc::new(noop_log), &extract_refs);
        let _ = catalog.generate(library_root, false);
    }
}

/// Handles play URI - launches the game executable.
pub fn _handle_play_uri(_uri: &str, _config: &AppConfig, logger: &AppLogger) -> i32 {
    logger.warning(
        "PLAY",
        &format!("URI_REFUSED uri=[{}] reason=[not yet implemented]", _uri),
        "",
    );
    2
}

/// Handles mark installed URI - marks a game as installed in catalog status.
pub fn _handle_mark_installed_uri(_uri: &str, _config: &AppConfig, logger: &AppLogger) -> i32 {
    logger.warning(
        "SETUP_DONE",
        &format!("URI_REFUSED uri=[{}] reason=[not yet implemented]", _uri),
        "",
    );
    2
}

/// Cancel a scan or run in progress.
pub fn _cancel_planning() {
    // Stub: Job cancellation handled by JobContext::cancel()
}

/// The --extract command line: extract, print where it went, and exit.
pub fn _extract_to_disk(
    archive: &Path,
    dest: Option<PathBuf>,
    config: &AppConfig,
    _logger: &AppLogger,
    zip_password: &str,
) -> i32 {
    let destination = dest.unwrap_or_else(|| config.extract_folder());
    let suffix = archive
        .extension()
        .map(|e| e.to_string_lossy().to_string())
        .unwrap_or_default();
    let extractor = ExtractService::new(Some(Box::new(noop_log)));
    let result = extractor.extract(archive, destination.as_path(), &suffix, zip_password);
    println!("{}", result.message);
    if result.ok {
        0
    } else {
        1
    }
}

/// Extracts an archive with a password.
pub fn _extract(
    archive: &Path,
    destination: &Path,
    config: &AppConfig,
    _logger: &AppLogger,
    args_password: &str,
) -> crate::core::extract_result::ExtractResult {
    let suffix = archive
        .extension()
        .map(|e| e.to_string_lossy().to_string())
        .unwrap_or_default();
    let password = if args_password.is_empty() {
        config
            .settings
            .get("zip_password")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string()
    } else {
        args_password.to_string()
    };
    let extractor = ExtractService::new(Some(Box::new(noop_log)));
    extractor.extract(archive, destination, &suffix, &password)
}

/// Whether this PC has ever been configured: a saved library root that exists on disk.
pub fn _needs_setup(config: &AppConfig) -> bool {
    if !config.settings_file.is_file() {
        return true;
    }
    match &config.library_root {
        Some(root) => !root.is_dir(),
        None => true,
    }
}

/// Entry point, imported lazily from core.main.
pub fn main() -> i32 {
    use clap::Parser;

    #[derive(Parser, Debug)]
    #[command(author, version, about = APP_NAME, long_about = None)]
    struct Args {
        /// Run deterministic mock data; no real library changes
        #[arg(long)]
        mock: bool,

        /// Print diagnostics report and exit
        #[arg(long)]
        diagnostics: bool,

        /// Print health text and exit
        #[arg(long)]
        health: bool,

        /// Print version and exit
        #[arg(short, long)]
        version: bool,

        /// Handle a steamgameorganizer:// link. Empty means launch the GUI.
        #[arg(long, num_args = 0..=1)]
        uri: Option<String>,

        /// Extract an archive to the extract folder, then exit
        #[arg(long)]
        extract: Option<PathBuf>,

        /// Open the setup wizard, then exit
        #[arg(long)]
        setup: bool,

        /// Destination folder for --extract (default: the extract folder)
        #[arg(long)]
        dest: Option<PathBuf>,

        /// Password for an encrypted .zip or .rar
        #[arg(long, default_value = "")]
        zip_password: String,
    }

    let args = Args::parse();

    if args.version {
        println!("{}", APP_NAME);
        return 0;
    }

    let root_path = resolve_project_root();
    let headless = args.diagnostics || args.health || args.uri.is_some() || args.extract.is_some();

    let log_file = if headless {
        let log_dir = root_path.join("logs");
        find_recent_log(&log_dir)
    } else {
        None
    };

    let mut config = AppConfig::new(&root_path);
    config.mock_mode = args.mock;
    config.ensure_directories();

    let log_path = log_file.as_deref().unwrap_or_else(|| Path::new(""));
    let logger = match AppLogger::new(log_path, "INFO", headless, false) {
        Ok(l) => Arc::new(l),
        Err(_) => {
            eprintln!("Failed to initialize logger.");
            return 1;
        }
    };
    logger.install_panic_hook();

    if args.diagnostics {
        println!("Diagnostics not yet available in Rust.");
        return 0;
    }

    if args.health {
        use crate::core::debug::print_health_report;
        print_health_report(&logger);
        return 0;
    }

    // URI handler
    if let Some(ref uri) = args.uri {
        if !uri.is_empty() {
            eprintln!("URI handling not yet implemented in CLI");
            return 2;
        }
    }

    // Extract
    if let Some(ref archive) = args.extract {
        return _extract_to_disk(
            archive,
            args.dest.clone(),
            &config,
            &logger,
            &args.zip_password,
        );
    }

    // Setup wizard
    if args.setup {
        let service = SetupService::new(Arc::new(noop_log), None, None);
        let (saved, rows) = service.apply(
            &config,
            config
                .library_root
                .as_deref()
                .and_then(|p| p.to_str())
                .unwrap_or(""),
            std::env::current_exe()
                .ok()
                .and_then(|p| p.parent().map(|p| p.to_path_buf()))
                .unwrap_or_default()
                .to_str()
                .unwrap_or(""),
            config.extract_folder().to_str().unwrap_or(""),
        );
        for (level, msg) in &rows {
            eprintln!("[SETUP] [{}] {}", level, msg);
        }
        return if saved { 0 } else { 1 };
    }

    // First-run setup if needed
    let needed_setup = config
        .library_root
        .as_ref()
        .map(|p| !p.exists())
        .unwrap_or(true);
    if needed_setup {
        config.save();
        if let Some(library_root) = &config.library_root {
            let folders: Vec<PathBuf> = config.extract_folders();
            let extract_refs: Vec<&Path> = folders.iter().map(|p| p.as_path()).collect();
            type NoopLogFn = Arc<dyn Fn(&str, &str) + Send + Sync>;
            let noop_catalog: NoopLogFn = Arc::new(noop_log);
            let _ = CatalogService::new(noop_catalog, &extract_refs).generate(library_root, false);
        }
    }

    // Launch GUI (egui)
    let log_dir = root_path.join("logs");
    let root_path_str = root_path.to_str().unwrap_or("");
    let _ = safe_create_dir_all(&log_dir, &[root_path_str]);
    let stamp = OffsetDateTime::now_utc()
        .format(&time::format_description::parse_borrowed::<3>("[year][month][day][hour][minute][second]").unwrap())
        .unwrap_or_default();
    let log_path = log_dir.join(format!("organizer-{}.log", stamp));
    let logger = Arc::new(
        AppLogger::new(&log_path, "INFO", true, false).expect("failed to create log file"),
    );
    logger.info("APPLICATION", "START gui_mode=true", "");
    let _ = Application::new(&root_path, args.mock, Arc::clone(&logger));
    logger.info("APPLICATION", "SHUTDOWN", "");
    0
}

/// Resolve the project root by searching upward for Cargo.toml.
fn resolve_project_root() -> PathBuf {
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_default());

    let mut root_path = exe_dir.clone();
    for candidate in exe_dir.ancestors() {
        if candidate.join("Cargo.toml").is_file() {
            root_path = candidate.to_path_buf();
            break;
        }
    }
    root_path
}

/// Find the most recent log file in a directory.
fn find_recent_log(log_dir: &Path) -> Option<PathBuf> {
    if !log_dir.is_dir() {
        return None;
    }
    let mut entries: Vec<_> = std::fs::read_dir(log_dir)
        .ok()?
        .filter_map(|e| e.ok())
        .filter(|e| {
            e.file_name().to_string_lossy().starts_with("organizer-")
                && e.file_name().to_string_lossy().ends_with(".log")
        })
        .collect();
    entries.sort_by(|a, b| {
        let a_time = a
            .metadata()
            .and_then(|m| m.modified())
            .unwrap_or(std::time::SystemTime::UNIX_EPOCH);
        let b_time = b
            .metadata()
            .and_then(|m| m.modified())
            .unwrap_or(std::time::SystemTime::UNIX_EPOCH);
        b_time.cmp(&a_time)
    });
    entries.first().map(|e| e.path())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json;

    #[test]
    fn test_build_name_map_empty() {
        let log_path = std::env::temp_dir().join(format!("test_entry_{}.log", std::process::id()));
        let logger = AppLogger::new(&log_path, "INFO", false, false).unwrap();
        let name_map = build_name_map(&logger, std::path::Path::new("/lib"));
        assert!(name_map.is_empty());
        let _ = std::fs::remove_file(&log_path);
    }

    #[test]
    fn test_needs_setup_no_settings() {
        // After AppConfig::new, library_root is set to default which may exist.
        // Test with a manually constructed config where library_root is None.
        let config = AppConfig {
            project_root: std::path::PathBuf::from("/tmp"),
            library_root: None,
            developer_mode: false,
            mock_mode: false,
            settings: serde_json::json!({}),
            settings_version: 0,
            log_file: None,
            config_dir: std::path::PathBuf::from("/tmp/config"),
            cache_dir: std::path::PathBuf::from("/tmp/cache"),
            artwork_dir: std::path::PathBuf::from("/tmp/cache/artwork"),
            log_dir: std::path::PathBuf::from("/tmp/logs"),
            debug_dir: std::path::PathBuf::from("/tmp/debug"),
            settings_file: std::path::PathBuf::from("/tmp/config/settings.json"),
            state_file: std::path::PathBuf::from("/tmp/config/scan-state.json"),
        };
        assert!(_needs_setup(&config));
    }

    #[test]
    fn test_open_setup_stub() {
        let config = AppConfig::new(std::path::Path::new("/tmp"));
        let log_path = std::env::temp_dir().join(format!("test_entry2_{}.log", std::process::id()));
        let logger = AppLogger::new(&log_path, "INFO", false, false).unwrap();
        let result = _open_setup(&config, &logger, None);
        // Should not panic
        assert!(result.is_none() || result == Some(0));
        let _ = std::fs::remove_file(&log_path);
    }
}
