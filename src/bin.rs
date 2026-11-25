//! Binary entry point for the Steam Game Organizer application.
//! Handles both GUI mode (default) and CLI mode (--version, --diagnostics, --health, --uri, --extract, --setup, --mock).
//!
//! 2026-11-25: Wired real AppLogger (HH:MM:SS timestamps) into GUI path so every run writes to logs/.

use clap::Parser;
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
    #[arg(long, num_args = 0..=1, default_value = "")]
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
    let args = Args::parse();

    // If any headless flag is present, delegate to the CLI entry point
    if args.version || args.diagnostics || args.health || args.uri.is_some() || args.extract.is_some() || args.setup {
        process::exit(entry_main());
    }

    // Otherwise, run the GUI with real file logging
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([1400.0, 900.0])
            .with_min_inner_size([1100.0, 680.0]),
        ..Default::default()
    };

    let project_root = resolve_project_root();

    // Create a timestamped log file under logs/ with HH:MM:SS timestamps
    let log_dir = project_root.join("logs");
    let _ = std::fs::create_dir_all(&log_dir);
    let stamp = chrono::Utc::now().format("%Y%m%d-%H%M%S");
    let log_path = log_dir.join(format!("organizer-{}.log", stamp));
    let logger = Arc::new(
        AppLogger::new(&log_path, "DEBUG", true, false)
            .expect("failed to create log file"),
    );
    logger.info("APPLICATION", "START gui_mode=true", "");

    let _app = Application::new(project_root.as_path(), args.mock, Arc::clone(&logger));

    eframe::run_native(
        "Steam Game Organizer",
        options,
        Box::new(|_cc| {
            let logger_clone1 = Arc::clone(&logger);
            let logger_clone2 = Arc::clone(&logger);
            let logger_clone3 = Arc::clone(&logger);
            Ok(Box::new(steam_game_organizer::ui::main_window::MainWindow::new(
                std::sync::Arc::new(steam_game_organizer::app::controller::StateStore::new()),
                std::sync::Arc::new(steam_game_organizer::app::events::EventBus::new()),
                Arc::new(move |cat, msg| {
                    logger_clone1.info(cat, msg, "");
                }),
                std::sync::Arc::new(steam_game_organizer::app::controller::Services {
                    organizer: steam_game_organizer::services::organizer_service::OrganizerService::new(
                        Arc::new(move |cat, msg| {
                            logger_clone2.info(cat, msg, "");
                        }),
                        false,
                    ),
                }),
                steam_game_organizer::services::library_service::LibraryService::new(
                    Arc::new(move |cat, msg| {
                        logger_clone3.info(cat, msg, "");
                    }),
                    None,
                ),
                std::sync::Arc::new(steam_game_organizer::app::jobs::JobManager::new(4)),
            )))
        }),
    )
    .unwrap();

    logger.info("APPLICATION", "SHUTDOWN", "");
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
