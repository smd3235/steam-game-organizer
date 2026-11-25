//! Application entry point: owns config, logger, services, controller, and the UI window.
//!
//! Stub conversion of `app/application.py`. The `Application` struct is a stub that holds references
//! to services and controller but does not create a real Tk window. `run()` and `shutdown()` are no-ops
//! until a Rust GUI framework is chosen. The `_dispatch`/`_pump` thread-safe UI update mechanism is
//! represented by a channel that will be wired to the GUI event loop when one exists.
//!
//! 2026-11-25: Stub conversion from `app/application.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

#![allow(clippy::all)]

use std::path::Path;
use std::sync::{Arc, Mutex};

use crate::core::config::AppConfig;
use crate::core::logger::AppLogger;
use crate::app::controller::{AppController, Services};
use crate::app::events::EventBus;
use crate::app::jobs::JobManager;
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
    pub fn new(project_root: &Path, mock: bool, logger: Arc<AppLogger>) -> Self {
        let config = AppConfig::new(project_root);
        let _ = mock;
        config.ensure_directories();

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
        *self._closed.lock().unwrap() = true;
        self.jobs.cancel_all();
        self.logger.info("APPLICATION", "SHUTDOWN_COMPLETE", "");
    }

    /// Sweep stale build directories (stub: delegates to organizer service).
    pub fn sweep_stale_build_dirs(&self) {
        if let Some(root) = self.config.library_root.as_ref() {
            let _removed = self.services.organizer.sweep_stale_build_dirs(Some(root), 900);
        }
    }
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
        let _app = Application::new(Path::new("/tmp"), false, test_logger());
        // Should not panic
    }

    #[test]
    fn test_application_run_returns_zero() {
        let app = Application::new(Path::new("/tmp"), false, test_logger());
        assert_eq!(app.run(), 0);
    }

    #[test]
    fn test_application_shutdown() {
        let app = Application::new(Path::new("/tmp"), false, test_logger());
        app.shutdown();
        assert!(*app._closed.lock().unwrap());
    }

    #[test]
    fn test_application_sweep_stale_build_dirs_nonexistent() {
        let app = Application::new(Path::new("/nonexistent"), false, test_logger());
        // Should not panic
        app.sweep_stale_build_dirs();
    }

    #[test]
    fn test_library_root_method() {
        let app = Application::new(PathBuf::from("/tmp").as_path(), false, test_logger());
        // library_root is a field (Option<PathBuf>), not a method. Just ensure it doesn't panic.
        let _ = app.config.library_root;
    }
}

