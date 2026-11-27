//! Binary entry point for the Steam Game Organizer application.
//! Handles both GUI mode (default) and CLI mode (--version, --diagnostics, --health, --uri, --extract, --setup, --mock).
//!
//! 2026-11-26: Wired real AppLogger with panic hooks, HH:MM:SS timestamps, and watchdog into GUI path.
//! Fixed `uri` default_value bug that forced headless CLI path instead of GUI.

use clap::Parser;
use chrono::Local;
use std::path::{Path, PathBuf};
use std::process;
use std::sync::Arc;

use steam_game_organizer::app::application::Application;
use steam_game_organizer::core::config::AppConfig;
use steam_game_organizer::core::logger::AppLogger;
use steam_game_organizer::core::path_safety::safe_create_dir_all;
use steam_game_organizer::tools::dependency_audit::dependency_audit;
use steam_game_organizer::tools::quality_gate::quality_gate;

#[derive(Parser, Debug)]
#[command(author, version, about = "Steam Game Organizer", long_about = None)]
struct Args {
    /// Run deterministic mock data; no real library changes
    #[arg(long)]
    mock: bool,

    /// Run sandbox mode: simulate UI interactions end-to-end, read logs, report issues
    #[arg(long)]
    sandbox: bool,

    /// Run the full quality gate: check, clippy, test, build, dependency audit
    #[arg(long)]
    quality_gate: bool,

    /// Run dependency audit: check for outdated crates and security vulnerabilities
    #[arg(long)]
    dependency_audit: bool,

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
    extract: Option<String>,

    /// Open the setup wizard, then exit
    #[arg(long)]
    setup: bool,

    /// Destination folder for --extract (default: the extract folder)
    #[arg(long)]
    dest: Option<String>,

    /// Password for an encrypted .zip or .rar
    #[arg(long, default_value = "")]
    zip_password: String,

    /// Launch a single UI view in isolation (scan, review, organize, artwork, done, setup) for testing/screenshots
    #[arg(long)]
    view: Option<String>,
}

fn main() {
    let args = Args::parse();

    // If any headless flag is present, delegate to the CLI entry point
    if args.version
        || args.diagnostics
        || args.health
        || args.uri.is_some()
        || args.extract.is_some()
        || args.setup
    {
        process::exit(entry_main());
    }

    // Sandbox mode: simulate UI interactions end-to-end, read logs, report issues
    if args.sandbox {
        let project_root = resolve_project_root();
        let project_root_str = project_root.to_str().unwrap_or("");
        let output_dir = project_root.join("docs/screenshots");
        let _ = safe_create_dir_all(&output_dir, &[project_root_str]);
        let log_dir = project_root.join("logs");
        let _ = safe_create_dir_all(&log_dir, &[project_root_str]);

        let timestamp = Local::now().format("%Y%m%d-%H%M%S").to_string();
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
            Ok(audit) => {
                audit.report();
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

    // Otherwise, run the GUI with real file logging
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([1400.0, 900.0])
            .with_min_inner_size([1100.0, 680.0])
            .with_visible(true),
        ..Default::default()
    };

    let project_root = resolve_project_root();

    // Create config from project root
    let config = Arc::new(AppConfig::new(project_root.as_path()));

    // Create a timestamped log file under logs/ with HH:MM:SS timestamps
    let log_dir = project_root.join("logs");
    let project_root_str = project_root.to_str().unwrap_or("");
    let _ = safe_create_dir_all(&log_dir, &[project_root_str]);
    let stamp = chrono::Utc::now().format("%Y%m%d-%H%M%S");
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
    let mut app = Application::new(project_root.as_path(), args.mock, Arc::clone(&logger));
    app.controller.set_config(Arc::clone(&config));

    let logger_for_shutdown = Arc::clone(&logger);

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

/// Find the project root by walking up from the exe directory looking for Cargo.toml.
fn resolve_project_root() -> PathBuf {
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

    // Refuse to resolve to a drive root (e.g. C:\, E:\) — creating config/logs there
    // would pollute the drive root instead of the project directory.
    let root_str = root.to_string_lossy().to_string();
    if root_str.len() <= 3 && root_str.ends_with('\\') {
        return exe_dir.parent().unwrap_or(&std::env::current_dir().unwrap_or_default()).to_path_buf();
    }
    root
}
