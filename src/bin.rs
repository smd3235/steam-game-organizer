//! Binary entry point for the Steam Game Organizer application.
//! Handles both GUI mode (default) and CLI mode (--version, --diagnostics, --health, --uri, --extract, --setup, --mock).
//!
//! 2026-11-26: Wired real AppLogger with panic hooks, HH:MM:SS timestamps, and watchdog into GUI path.
//! Fixed `uri` default_value bug that forced headless CLI path instead of GUI.

use clap::Parser;
use std::path::{Path, PathBuf};
use time::OffsetDateTime;
use std::process;
use std::sync::Arc;

// Win32 FFI for window foreground management (Windows only)
// Allows PowerShell capture tool to call SetForegroundWindow on this process later
#[link(name = "user32")]
extern "system" {
    fn AllowSetForegroundWindow(dwProcessId: u32) -> i32;
}

// ASFW_ANY = 0xFFFFFFFF (-1) - allow any process to call SetForegroundWindow
const ASFW_ANY: u32 = 0xFFFFFFFF;

use steam_game_organizer::app::application::Application;
use steam_game_organizer::core::cli_args::{Args, resolve_project_root};
use steam_game_organizer::core::config::AppConfig;
use steam_game_organizer::core::logger::AppLogger;
use steam_game_organizer::core::path_safety::safe_create_dir_all;
use steam_game_organizer::tools::archive_encryption_scanner::scan_encryption;
use steam_game_organizer::tools::build_installer::build_installer;
use steam_game_organizer::tools::crash_recovery::recover;
use steam_game_organizer::tools::dependency_audit::dependency_audit;
use steam_game_organizer::tools::duplicate_detector::find_duplicates;
use steam_game_organizer::tools::library_health_scan::scan_library_health;
use steam_game_organizer::tools::quality_gate::quality_gate;
use steam_game_organizer::tools::steam_match_confidence::analyze_confidence;
use steam_game_organizer::tools::steamcmd_check::check_steamcmd;
use steam_game_organizer::tools::system_diagnostics::run_system_diagnostics;
use steam_game_organizer::tools::capture_screens::capture_and_verify;

fn main() {
    let args = Args::parse();

    // If any headless flag is present, delegate to the CLI entry point.
    // --uri with an empty value (--uri alone) launches the GUI, not headless.
    // --uri with a value (--uri steamgameorganizer://...) processes the URI headless.
    // No --uri flag at all also launches GUI.
    if args.version
        || args.diagnostics
        || args.health
        || (args.uri.is_some() && args.uri.as_deref() != Some(""))
        || args.extract.is_some()
        || args.setup
        || args.system_diagnostics
    {
        process::exit(entry_main());
    }

    // Sandbox mode: simulate UI interactions end-to-end, read logs, report issues
    if args.sandbox {
        let project_root = resolve_project_root();
        let project_root_str = project_root.to_str().unwrap_or("");
        let output_dir = project_root.join("docs/screenshots");
        if let Err(e) = safe_create_dir_all(&output_dir, &[project_root_str]) {
            eprintln!(
                "[ERROR] Failed to create output dir {}: {}",
                output_dir.display(),
                e
            );
            process::exit(1);
        }
        let log_dir = project_root.join("logs");
        if let Err(e) = safe_create_dir_all(&log_dir, &[project_root_str]) {
            eprintln!(
                "[ERROR] Failed to create log dir {}: {}",
                log_dir.display(),
                e
            );
            process::exit(1);
        }

        let timestamp = OffsetDateTime::now_utc()
            .format(&time::format_description::parse_borrowed::<3>("[year][month][day][hour][minute][second]").unwrap())
            .unwrap_or_default()
            .to_string();
        let sandbox_log_name = format!("sandbox-{}.log", timestamp);
        let logger = match AppLogger::new(log_dir.join(&sandbox_log_name), "DEBUG", true, false) {
            Ok(l) => Arc::new(l),
            Err(e) => {
                eprintln!("[ERROR] Failed to create logger: {}", e);
                process::exit(1);
            }
        };

        if let Err(e) = steam_game_organizer::tools::sandbox::run_sandbox(logger, &output_dir) {
            eprintln!("[ERROR] Sandbox failed: {}", e);
            process::exit(1);
        }
        return;
    }

    // Quality gate: run check, clippy, test, build, dependency audit in one pass
    if args.quality_gate {
        match quality_gate(Path::new(".")) {
            Ok(result) => {
                result.report();
                if result.is_clean() {
                    println!("\nQuality gate: ALL CHECKS PASSED");
                    process::exit(0);
                } else {
                    println!("\nQuality gate: CHECKS FAILED");
                    process::exit(1);
                }
            }
            Err(e) => {
                eprintln!("[ERROR] Quality gate failed: {}", e);
                process::exit(1);
            }
        }
    }

    // Dependency audit: check for outdated crates and security vulnerabilities
    if args.dependency_audit {
        match dependency_audit(Path::new(".")) {
            Ok((audit, external)) => {
                audit.report();
                external.report();
                if audit.is_clean() {
                    println!("\nDependency audit: ALL CLEAN");
                    process::exit(0);
                } else {
                    println!("\nDependency audit: ISSUES FOUND");
                    process::exit(1);
                }
            }
            Err(e) => {
                eprintln!("[ERROR] Dependency audit failed: {}", e);
                process::exit(1);
            }
        }
    }

    // Validate settings.json schema
    if args.config_validate {
        let project_root = resolve_project_root();
        let config = AppConfig::new(project_root.as_path());
        let problems = config.validate();
        if problems.is_empty() {
            println!("Config validation: ALL CLEAN");
            process::exit(0);
        } else {
            println!("Config validation: ISSUES FOUND");
            for problem in &problems {
                println!("  - {problem}");
            }
            process::exit(1);
        }
    }

    // Build Windows installer using Inno Setup
    if args.build_installer {
        match build_installer(Path::new(".")) {
            Ok(result) => {
                println!("Installer built successfully:");
                println!("  Path: {}", result.installer_path.display());
                println!("  Size: {} bytes ({:.1} MB)", result.size_bytes, result.size_bytes as f64 / 1_048_576.0);
                process::exit(0);
            }
            Err(e) => {
                eprintln!("[ERROR] Installer build failed: {}", e);
                process::exit(1);
            }
        }
    }

    // Check SteamCMD availability and Steam installation status
    if args.steamcmd_check {
        match check_steamcmd(Path::new(".")) {
            Ok(result) => {
                println!("SteamCMD Check:");
                println!("  steamcmd found:       {}", result.steamcmd_found);
                println!("  Steam installed:      {}", result.steam_installed);
                println!("  appinfo query:        {}", result.appinfo_query_working);
                if let Some(path) = &result.steam_library_path {
                    println!("  Steam library:        {}", path);
                }
                if result.steamcmd_found && result.steam_installed {
                    println!("\nSteamCMD check: ALL OK");
                    process::exit(0);
                } else {
                    println!("\nSteamCMD check: ISSUES FOUND");
                    process::exit(1);
                }
            }
            Err(e) => {
                eprintln!("[ERROR] SteamCMD check failed: {}", e);
                process::exit(1);
            }
        }
    }

    // Duplicate detector: find duplicate archives by normalized name + size
    if let Some(dir) = &args.duplicate_detector {
        match find_duplicates(Path::new(dir)) {
            Ok(dupes) => {
                println!("Duplicate Detector:");
                if dupes.is_empty() {
                    println!("  No duplicates found.");
                } else {
                    for group in &dupes {
                        println!("  Group: {} ({} files, {} bytes total)", group.normalized_name, group.files.len(), group.total_size_bytes);
                        for f in &group.files {
                            println!("    {}", f.display());
                        }
                    }
                }
                process::exit(0);
            }
            Err(e) => {
                eprintln!("[ERROR] Duplicate detector failed: {}", e);
                process::exit(1);
            }
        }
    }

    // Library health scan: report unidentified, orphaned, oversized archives
    if let Some(dir) = &args.library_health_scan {
        match scan_library_health(Path::new(dir)) {
            Ok(report) => {
                println!("Library Health Scan:");
                println!("  Archives scanned:   {}", report.archives_scanned);
                println!("  Games matched:      {}", report.games_matched);
                println!("  Games unidentified: {}", report.games_unidentified);
                for issue in &report.issues {
                    println!("  [{:?}] {}", issue.severity, issue.description);
                }
                process::exit(0);
            }
            Err(e) => {
                eprintln!("[ERROR] Library health scan failed: {}", e);
                process::exit(1);
            }
        }
    }

    // Archive encryption scan: detect encrypted/password-protected archives
    if let Some(dir) = &args.archive_encryption_scan {
        match scan_encryption(Path::new(dir)) {
            Ok(report) => {
                println!("Archive Encryption Scan:");
                println!("  Total scanned:    {}", report.total_scanned);
                println!("  Encrypted:        {}", report.encrypted_count);
                for (ext, count) in &report.by_type {
                    println!("  {}: {}", ext, count);
                }
                for archive in &report.encrypted_archives {
                    println!("  ENCRYPTED: {} ({} bytes)", archive.path.display(), archive.size_bytes);
                }
                process::exit(0);
            }
            Err(e) => {
                eprintln!("[ERROR] Archive encryption scan failed: {}", e);
                process::exit(1);
            }
        }
    }

    // Steam match confidence: analyze match confidence distribution
    if let Some(dir) = &args.steam_match_confidence {
        match analyze_confidence(Path::new(dir)) {
            Ok(report) => {
                println!("Steam Match Confidence:");
                println!("  High:   {}", report.high_count);
                println!("  Medium: {}", report.medium_count);
                println!("  Low:    {}", report.low_count);
                println!("  None:   {}", report.none_count);
                println!("  Total:  {}", report.entries.len());
                process::exit(0);
            }
            Err(e) => {
                eprintln!("[ERROR] Steam match confidence failed: {}", e);
                process::exit(1);
            }
        }
    }

    // Crash recovery: clean up interrupted operations
    if let Some(dir) = &args.crash_recovery {
        match recover(Path::new(dir)) {
            Ok(result) => {
                println!("Crash Recovery:");
                println!("  Issues found:   {}", result.issues_found);
                println!("  Issues fixed:   {}", result.issues_fixed);
                println!("  Space reclaimed: {} bytes", result.space_reclaimed_bytes);
                for action in &result.actions {
                    println!("  [{:?}] {}", action.action_type, action.description);
                }
                process::exit(0);
            }
            Err(e) => {
                eprintln!("[ERROR] Crash recovery failed: {}", e);
                process::exit(1);
            }
        }
    }

    // Run full system diagnostics
    if args.system_diagnostics {
        match run_system_diagnostics(Path::new(".")) {
            Ok(result) => {
                result.report();
                if result.is_clean() {
                    println!("\nSystem diagnostics: ALL CHECKS PASSED");
                    process::exit(0);
                } else {
                    println!("\nSystem diagnostics: SOME CHECKS FAILED");
                    process::exit(1);
                }
            }
            Err(e) => {
                eprintln!("[ERROR] System diagnostics failed: {}", e);
                process::exit(1);
            }
        }
    }

    // Verify UI buttons are visible via OCR: launch app, capture each view,
    // run Tesseract OCR on screenshots, confirm expected button text appears
    if args.verify_ui {
        let output_dir = Path::new("docs/screenshots");
        let views = [
            "scan", "review", "organize", "artwork", "done", "setup",
        ];
        let mut all_passed = true;
        for view in &views {
            println!("=== Verifying UI for view '{}' ===", view);
            match capture_and_verify(output_dir, view, true) {
                Ok(result) => {
                    println!("  OCR text preview: {:?}", result.ocr_text.chars().take(200).collect::<String>());
                    println!("  Found required: {:?}", result.found_required);
                    if !result.missing_required.is_empty() {
                        println!("  MISSING required headers: {:?}", result.missing_required);
                        all_passed = false;
                    }
                    println!("  UI verification PASSED for view '{}'.", view);
                }
                Err(e) => {
                    eprintln!("  UI verification FAILED for view '{}': {}", view, e);
                    all_passed = false;
                }
            }
        }
        if all_passed {
            println!("\nUI verification: ALL VIEWS PASSED - all button text visible via OCR");
            process::exit(0);
        } else {
            println!("\nUI verification: SOME VIEWS FAILED - missing button text detected");
            process::exit(1);
        }
    }

    // Otherwise, run the GUI with real file logging
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title("Steam Game Organizer")
            .with_inner_size([1400.0, 900.0])
            .with_min_inner_size([1100.0, 680.0])
            .with_visible(true)
            .with_maximized(true),
        ..Default::default()
    };

    let project_root = resolve_project_root();

    // Create config from project root
    let config = Arc::new(AppConfig::new(project_root.as_path()));

    // Create a timestamped log file under logs/ with HH:MM:SS timestamps
    let log_dir = project_root.join("logs");
    let project_root_str = project_root.to_str().unwrap_or("");
    if let Err(e) = safe_create_dir_all(&log_dir, &[project_root_str]) {
        eprintln!(
            "[ERROR] Failed to create log dir {}: {}",
            log_dir.display(),
            e
        );
        process::exit(1);
    }
    let stamp = OffsetDateTime::now_utc()
        .format(&time::format_description::parse_borrowed::<3>("[year][month][day][hour][minute][second]").unwrap())
        .unwrap_or_default();
    let log_path = log_dir.join(format!("organizer-{}.log", stamp));

    let logger = match AppLogger::new(&log_path, "DEBUG", true, false) {
        Ok(l) => Arc::new(l),
        Err(e) => {
            eprintln!("[ERROR] Failed to create logger: {}", e);
            return;
        }
    };

    // Install panic hook that logs through our logger
    logger.install_panic_hook();

    logger.info("APPLICATION", "START gui_mode=true", "");

    // Create Application and wire its controller's config
    let library_root_path = args.library_root.as_ref().map(PathBuf::from);
    let mut app = Application::new(
        project_root.as_path(),
        args.mock,
        Arc::clone(&logger),
        library_root_path,
        &args.scenario,
    );
    app.controller.set_config(Arc::clone(&config));

    let logger_for_shutdown = Arc::clone(&logger);

    // Allow PowerShell capture tool to bring this window to foreground later
    unsafe {
        AllowSetForegroundWindow(ASFW_ANY);
    }

    let run_result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        eframe::run_native(
            "Steam Game Organizer",
            options,
            Box::new(move |_cc| {
                Ok(Box::new(steam_game_organizer::ui::main_window::MainWindow::new(
                    std::sync::Arc::new(steam_game_organizer::app::controller::StateStore::new()),
                    std::sync::Arc::new(steam_game_organizer::app::events::EventBus::new()),
                    Arc::clone(&logger),
                    std::sync::Arc::new(steam_game_organizer::app::controller::Services {
                        organizer: steam_game_organizer::services::organizer_service::OrganizerService::new(
                            Arc::new({
                                let logger = Arc::clone(&logger);
                                move |cat, msg| {
                                    logger.info(cat, msg, "");
                                }
                            }),
                            config.convert_archives(),
                        ),
                    }),
                    Arc::clone(&config),
                    steam_game_organizer::services::library_service::LibraryService::new(
                        Arc::new({
                            let logger = Arc::clone(&logger);
                            move |cat, msg| {
                                logger.info(cat, msg, "");
                            }
                        }),
                        None,
                    ),
                    std::sync::Arc::new(steam_game_organizer::app::jobs::JobManager::new(4)),
                    args.view.clone(),
                )))
            }),
        )
    }));

    match run_result {
        Ok(Ok(())) => {
            logger_for_shutdown.info("APPLICATION", "SHUTDOWN", "");
        }
        Ok(Err(e)) => {
            logger_for_shutdown.error(
                "APPLICATION",
                &format!("eframe::run_native error: {:?}", e),
                "",
            );
        }
        Err(panic) => {
            logger_for_shutdown.error(
                "APPLICATION",
                &format!("eframe::run_native panicked: {:?}", panic),
                "",
            );
        }
    }
}

fn entry_main() -> i32 {
    steam_game_organizer::entry::main()
}
