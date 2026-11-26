//! Binary entry point for the Steam Game Organizer application.
//! Handles both GUI mode (default) and CLI mode (--version, --diagnostics, --health, --uri, --extract, --setup, --mock).
//!
//! 2026-11-26: Wired real AppLogger with panic hooks, HH:MM:SS timestamps, and watchdog into GUI path.
//! Fixed `uri` default_value bug that forced headless CLI path instead of GUI.

use clap::Parser;
use std::io::Write;
use std::path::PathBuf;
use std::process;
use std::sync::Arc;

use steam_game_organizer::app::application::Application;
use steam_game_organizer::core::logger::AppLogger;

#[derive(Parser, Debug)]
#[command(author, version, about = "Steam Game Organizer", long_about = None)]
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
}

fn main() {
    // Install panic hook early so any panic gets logged to file (stderr may not exist for GUI apps)
    std::panic::set_hook(Box::new(|info| {
        let msg = format!(
            "PANIC at {}: {:?}\n",
            info.location().map(|l| l.to_string()).unwrap_or_default(),
            info.payload()
        );
        let log_dir = std::env::current_exe()
            .ok()
            .and_then(|p| p.parent().map(|p| p.to_path_buf()))
            .unwrap_or_default()
            .join("logs");
        let _ = std::fs::create_dir_all(&log_dir);
        let _ = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(log_dir.join("panic.log"))
            .and_then(|mut f| f.write_all(msg.as_bytes()));
        let _ = std::io::stderr().write_all(msg.as_bytes());
    }));

    let args = Args::parse();

    // If any headless flag is present, delegate to the CLI entry point
    if args.version || args.diagnostics || args.health || args.uri.is_some() || args.extract.is_some() || args.setup {
        process::exit(entry_main());
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

    // Create a timestamped log file under logs/ with HH:MM:SS timestamps
    let log_dir = project_root.join("logs");
    let _ = std::fs::create_dir_all(&log_dir);
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

    let _app = Application::new(project_root.as_path(), args.mock, Arc::clone(&logger));

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
                            false,
                        ),
                    }),
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
                )))
            }),
        )
    }));

    match run_result {
        Ok(Ok(())) => {
            logger_for_shutdown.info("APPLICATION", "SHUTDOWN", "");
        }
        Ok(Err(e)) => {
            logger_for_shutdown.error("APPLICATION", &format!("eframe::run_native error: {:?}", e), "");
        }
        Err(panic) => {
            logger_for_shutdown.error("APPLICATION", &format!("eframe::run_native panicked: {:?}", panic), "");
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
    root
}
