//! Application entry point: owns config, logger, services, controller, and the UI window.
//!
//! Stub conversion of `app/application.py`. The `Application` struct is a stub that holds references
//! to services and controller but does not create a real Tk window. `run()` and `shutdown()` are no-ops
//! until a Rust GUI framework is chosen. The `_dispatch`/`_pump` thread-safe UI update mechanism is
//! represented by a channel that will be wired to the GUI event loop when one exists.
//!
//! 2026-11-25: Stub conversion from `app/application.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use crate::app::controller::{AppController, Services};
use crate::app::events::EventBus;
use crate::app::jobs::JobManager;
use crate::core::config::AppConfig;
use crate::core::logger::AppLogger;
use crate::services::library_service::LibraryService;
use crate::services::organizer_service::OrganizerService;

pub struct Application {
    pub config: AppConfig,
    pub logger: Arc<AppLogger>,
    pub state: Arc<crate::app::controller::StateStore>,
    pub bus: Arc<EventBus>,
    pub jobs: Arc<JobManager>,
    pub services: Arc<Services>,
    pub library_service: LibraryService,
    pub controller: AppController,
    _closed: Mutex<bool>,
}

impl Application {
    pub fn new(
        project_root: &Path,
        mock: bool,
        logger: Arc<AppLogger>,
        library_root: Option<PathBuf>,
        scenario: &str,
    ) -> Self {
        let mut config = AppConfig::new(project_root);
        if let Some(root) = library_root {
            config.library_root = Some(root);
        }
        config.mock_mode = mock;
        config.ensure_directories();

        // If mock mode with a scenario, create mock archives in library_root
        if let Some(lib_root) = config.library_root.clone() {
            if mock {
                if let Err(e) = std::fs::create_dir_all(&lib_root) {
                    logger.info(
                        "APPLICATION",
                        &format!(
                            "MOCK_LIBRARY_CREATE_FAILED path=[{}] error={}",
                            lib_root.display(),
                            e
                        ),
                        "",
                    );
                } else {
                    match scenario {
                        "empty" => {
                            // No archives - empty state
                        }
                        "populated" => {
                            create_mock_archives(&lib_root, true, logger.as_ref());
                        }
                        "error" => {
                            create_mock_archives(&lib_root, false, logger.as_ref());
                        }
                        "loading" => {
                            create_mock_archives(&lib_root, true, logger.as_ref());
                        }
                        _ => {
                            create_mock_archives(&lib_root, true, logger.as_ref());
                        }
                        "error" => {
                            create_mock_archives(&lib_root, false, logger.as_ref());
                        }
                        "loading" => {
                            create_mock_archives(&lib_root, true, logger.as_ref());
                        }
                        _ => {
                            create_mock_archives(&lib_root, true, logger.as_ref());
                        }
                    }
                }
            }
        }

        let logger_for_fn = Arc::clone(&logger);
        let logger_fn: Arc<dyn Fn(&str, &str) + Send + Sync> =
            Arc::new(move |category, message| {
                logger_for_fn.info(category, message, "");
            });
        let state = Arc::new(crate::app::controller::StateStore::new());
        state.update("idle", false, "", None);
        let bus = Arc::new(EventBus::new());
        let jobs = Arc::new(JobManager::new(4));

        let services = Arc::new(Services {
            organizer: OrganizerService::new(Arc::clone(&logger_fn), false),
        });

        let library_service = LibraryService::new(Arc::clone(&logger_fn), None);

        let controller = AppController::new(
            Arc::clone(&state),
            Arc::clone(&bus),
            Arc::clone(&logger_fn),
            Arc::clone(&services),
            Arc::clone(&jobs),
        );

        Application {
            config,
            logger,
            state,
            bus,
            jobs,
            services,
            library_service,
            controller,
            _closed: Mutex::new(false),
        }
    }

    /// Stub: no Tk window exists yet. Returns 0.
    pub fn run(&self) -> i32 {
        self.logger.info("APPLICATION", "START", "");
        0
    }

    /// Stub: cancels jobs and marks closed.
    pub fn shutdown(&self) {
        *self._closed.lock().unwrap_or_else(|e| e.into_inner()) = true;
        self.jobs.cancel_all();
        self.logger.info("APPLICATION", "SHUTDOWN_COMPLETE", "");
    }

    /// Sweep stale build directories (stub: delegates to organizer service).
    pub fn sweep_stale_build_dirs(&self) {
        if let Some(root) = self.config.library_root.as_ref() {
            let _removed = self
                .services
                .organizer
                .sweep_stale_build_dirs(Some(root), 900);
        }
    }
}

/// Create mock ZIP archives in the library root directory for different scenarios.
/// `populated` creates valid archives with Steam AppIDs in filenames.
/// `error` creates archives with problematic names (path traversal, empty categories).
fn create_mock_archives(lib_root: &Path, populated: bool, logger: &AppLogger) {
    let archives = if populated {
        vec![
            ("Alpha Forge", "12345", "Action", 5_000_000_000),
            ("Gamma Quest", "67890", "RPG", 8_000_000_000),
            ("Delta Realm", "11111", "Strategy", 3_000_000_000),
            ("Nebula Online", "22222", "Simulation", 4_000_000_000),
            ("Zenith Edge", "33333", "Shooter", 6_000_000_000),
        ]
    } else {
        // Error scenario: archives with problematic names
        vec![
            ("../escape", "99991", "Action", 1_000_000_000),
            ("..\\..\\..\\escape", "99992", "RPG", 1_000_000_000),
            ("CON", "99993", "Strategy", 1_000_000_000),
            ("", "99994", "Simulation", 1_000_000_000),
        ]
    };

    for (name, appid, category, size) in archives {
        // Reject path traversal and reserved Windows names
        if name.contains("..") || name.contains('\\') || name.contains('/') || name.is_empty() {
            logger.info(
                "APPLICATION",
                &format!(
                    "MOCK_ARCHIVE_SKIPPED name=[{}] reason=[invalid name]",
                    name
                ),
                "",
            );
            continue;
        }
        if name.eq_ignore_ascii_case("CON") || name.eq_ignore_ascii_case("PRN")
            || name.eq_ignore_ascii_case("AUX") || name.eq_ignore_ascii_case("NUL")
        {
            logger.info(
                "APPLICATION",
                &format!(
                    "MOCK_ARCHIVE_SKIPPED name=[{}] reason=[reserved Windows name]",
                    name
                ),
                "",
            );
            continue;
        }
        let zip_path = lib_root.join(format!("{}.zip", name));
        if zip_path.exists() {
            continue;
        }
        // Create a minimal ZIP file with a steam_appid.txt inside
        match create_zip_with_appid(&zip_path, appid.to_string(), category.to_string(), size) {
            Ok(_) => {}
            Err(e) => {
                logger.info(
                    "APPLICATION",
                    &format!(
                        "MOCK_ARCHIVE_CREATE_FAILED name=[{}] path=[{}] error={}",
                        name,
                        zip_path.display(),
                        e
                    ),
                    "",
                );
            }
        }
    }
}

/// Create a ZIP file containing steam_appid.txt and a dummy file of approximate size.
fn create_zip_with_appid(
    zip_path: &Path,
    appid: String,
    category: String,
    _size: u64,
) -> Result<(), Box<dyn std::error::Error>> {
    use std::io::Write;
    use zip::write::FileOptions;

    let file = std::fs::File::create(zip_path)?;
    let mut zip = zip::ZipWriter::new(file);
    let options: zip::write::FileOptions<'_, '_, ()> =
        FileOptions::default().compression_method(zip::CompressionMethod::Stored);

    zip.start_file("steam_appid.txt", options)?;
    zip.write_all(appid.as_bytes())?;

    zip.start_file("category.txt", options)?;
    zip.write_all(category.as_bytes())?;

    zip.finish()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn test_logger() -> Arc<AppLogger> {
        let path = std::env::temp_dir().join(format!("test_app_{}.log", std::process::id()));
        Arc::new(AppLogger::new(&path, "INFO", false, false).unwrap())
    }

    #[test]
    fn test_application_new() {
        let _app = Application::new(Path::new("/tmp"), false, test_logger(), None, "populated");
        // Should not panic
    }

    #[test]
    fn test_application_run_returns_zero() {
        let app = Application::new(Path::new("/tmp"), false, test_logger(), None, "populated");
        assert_eq!(app.run(), 0);
    }

    #[test]
    fn test_application_shutdown() {
        let app = Application::new(Path::new("/tmp"), false, test_logger(), None, "populated");
        app.shutdown();
        assert!(*app._closed.lock().unwrap());
    }

    #[test]
    fn test_application_sweep_stale_build_dirs_nonexistent() {
        let app = Application::new(Path::new("/nonexistent"), false, test_logger(), None, "populated");
        // Should not panic
        app.sweep_stale_build_dirs();
    }

    #[test]
    fn test_library_root_method() {
        let app = Application::new(PathBuf::from("/tmp").as_path(), false, test_logger(), None, "populated");
        // library_root is a field (Option<PathBuf>), not a method. Just ensure it doesn't panic.
        let _ = app.config.library_root;
    }
}
