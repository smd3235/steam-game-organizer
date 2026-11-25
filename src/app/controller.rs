//! Application controller: coordinates scan, verify, organize, undo operations between services and UI.
//!
//! Stub conversion of `app/controller.py`. All long-running operations (_submit-based scan, verify,
//! organize, undo) are stubs that complete immediately with empty results. The real implementations
//! depend on Tkinter messagebox dialogs and the service layer, which will be filled in incrementally
//! once a Rust GUI framework is chosen.
//!
//! 2026-11-25: Stub conversion from `app/controller.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

#![allow(clippy::all)]

use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use crate::core::config::AppConfig;
use crate::app::events::EventBus;
use crate::app::jobs::{JobContext, JobManager};
use crate::core::models::{ArtworkResult, GameArchive, ScanResult, SteamMatch};
use crate::services::organizer_service::OrganizerService;

pub struct Services {
    pub organizer: OrganizerService,
}

pub struct StateStore {
    state: Mutex<AppState>,
}

#[derive(Default)]
struct AppState {
    phase: String,
    cancel_requested: bool,
    job_id: String,
    scan_result: Option<ScanResult>,
}

impl StateStore {
    pub fn new() -> Self {
        StateStore {
            state: Mutex::new(AppState::default()),
        }
    }

    pub fn update(&self, phase: &str, cancel_requested: bool, job_id: &str, scan_result: Option<ScanResult>) {
        let mut s = self.state.lock().unwrap();
        s.phase = phase.to_string();
        s.cancel_requested = cancel_requested;
        s.job_id = job_id.to_string();
        s.scan_result = scan_result;
    }
}

pub struct AppController {
    pub state: Arc<StateStore>,
    pub bus: Arc<EventBus>,
    pub logger: Arc<dyn Fn(&str, &str) + Send + Sync>,
    pub services: Arc<Services>,
    pub jobs: Arc<JobManager>,
    config: Option<Arc<AppConfig>>,
}

impl AppController {
    pub fn new(
        state: Arc<StateStore>,
        bus: Arc<EventBus>,
        logger: Arc<dyn Fn(&str, &str) + Send + Sync>,
        services: Arc<Services>,
        jobs: Arc<JobManager>,
    ) -> Self {
        AppController {
            state,
            bus,
            logger,
            services,
            jobs,
            config: None,
        }
    }

    pub fn set_config(&mut self, config: Arc<AppConfig>) {
        self.config = Some(config);
    }

    // --- pure helpers (ported from controller.py) ---

    fn _category_file(&self) -> Option<PathBuf> {
        self.config.as_ref().map(|c| c.config_dir.clone().join("category-decisions.json"))
    }

    fn _saved_categories(&self) -> serde_json::Value {
        serde_json::json!({"identity": {}, "appid": {}})
    }

    fn _get_category_by_appid(&self, _appid: &str) -> Option<String> {
        None
    }

    pub fn remember_category(&self, _identity: &str, _category: &str, _appid: Option<&str>) {
        // Stub: no-op until category persistence is wired up.
    }

    pub fn scan(
        &self,
        _root: &Path,
        _done: Box<dyn Fn(ScanResult) + Send>,
        _progress: Option<Box<dyn Fn(serde_json::Value) + Send>>,
        _new_only: bool,
        _unlock_zip: bool,
        _preview_only: bool,
        _download_artwork: bool,
    ) -> Arc<JobContext> {
        // STUB: returns empty result immediately
        let (_id, ctx) = self.jobs.submit(
            |_ctx| ScanResult::default(),
            None::<fn(String, ScanResult)>,
            None::<fn(String)>,
        );
        ctx
    }

    pub fn scan_new_artwork(
        &self,
        _root: &Path,
        _scan_progress: Option<Box<dyn Fn(serde_json::Value) + Send>>,
        _verify_progress: Option<Box<dyn Fn(usize, usize, &GameArchive, &SteamMatch, Option<&ArtworkResult>, &serde_json::Value) + Send>>,
        _done: Box<dyn Fn(Vec<GameArchive>) + Send>,
        _download_artwork: bool,
    ) -> Arc<JobContext> {
        // STUB: returns empty result immediately
        let (_id, ctx) = self.jobs.submit(
            |_ctx| Vec::<GameArchive>::new(),
            None::<fn(String, Vec<GameArchive>)>,
            None::<fn(String)>,
        );
        ctx
    }

    pub fn verify_all(
        &self,
        _archives: Vec<GameArchive>,
        _on_progress: Box<dyn Fn(usize, usize, &GameArchive, &SteamMatch, Option<&ArtworkResult>, &serde_json::Value) + Send>,
        _done: Box<dyn Fn(Vec<GameArchive>) + Send>,
        _download_artwork: bool,
    ) -> Arc<JobContext> {
        // STUB: returns empty result immediately
        let (_id, ctx) = self.jobs.submit(
            |_ctx| Vec::<GameArchive>::new(),
            None::<fn(String, Vec<GameArchive>)>,
            None::<fn(String)>,
        );
        ctx
    }

    pub fn verify_one(
        &self,
        _archive: GameArchive,
        _title: &str,
        _done: Box<dyn Fn(GameArchive) + Send>,
    ) -> Arc<JobContext> {
        // STUB: returns the archive unchanged immediately
        let (_id, ctx) = self.jobs.submit(
            move |_ctx| _archive,
            None::<fn(String, GameArchive)>,
            None::<fn(String)>,
        );
        ctx
    }

    pub fn organize(
        &self,
        _archives: Vec<GameArchive>,
        _destination: &Path,
        _done: Box<dyn Fn(Vec<GameArchive>) + Send>,
        _on_progress: Option<Box<dyn Fn(serde_json::Value) + Send>>,
    ) -> Arc<JobContext> {
        // STUB: returns empty result immediately
        let (_id, ctx) = self.jobs.submit(
            |_ctx| Vec::<GameArchive>::new(),
            None::<fn(String, Vec<GameArchive>)>,
            None::<fn(String)>,
        );
        ctx
    }

    pub fn undo_last(
        &self,
        _library_root: &Path,
        _done: Box<dyn Fn(serde_json::Value) + Send>,
    ) -> Arc<JobContext> {
        // STUB: returns empty result immediately
        let (_id, ctx) = self.jobs.submit(
            |_ctx| serde_json::json!({}),
            None::<fn(String, serde_json::Value)>,
            None::<fn(String)>,
        );
        ctx
    }

    // --- thin wrappers over controller_utils (pure functions) ---

    pub fn _artwork_present(&self, _archive: &GameArchive) -> bool {
        false
    }

    pub fn _primary<'a>(&self, _group: &'a [GameArchive]) -> Option<&'a GameArchive> {
        _group.first()
    }

    pub fn _needs_conversion(&self, _archive: &GameArchive) -> bool {
        false
    }

    pub fn _primary_size(&self, _group: &[GameArchive]) -> u64 {
        0
    }

    pub fn _prune_rolled_back_folder(&self, _game_dir: &Path, _owned: bool, _library_root: Option<&Path>) {
        // Stub: no-op
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn dummy_logger(_: &str, _: &str) {}

    #[test]
    fn test_controller_new() {
        let state = Arc::new(StateStore::new());
        let bus = Arc::new(EventBus::new());
        let logger = Arc::new(dummy_logger);
        let services = Arc::new(Services {
            organizer: OrganizerService::new(Arc::new(dummy_logger), true),
        });
        let jobs = Arc::new(JobManager::new(2));
        let _controller = AppController::new(state, bus, logger, services, jobs);
    }

    #[test]
    fn test_controller_remember_category_stub() {
        let state = Arc::new(StateStore::new());
        let bus = Arc::new(EventBus::new());
        let logger = Arc::new(dummy_logger);
        let services = Arc::new(Services {
            organizer: OrganizerService::new(Arc::new(dummy_logger), true),
        });
        let jobs = Arc::new(JobManager::new(2));
        let controller = AppController::new(state, bus, logger, services, jobs);
        controller.remember_category("test-identity", "Action", Some("12345"));
        // Should not panic
    }

    #[test]
    fn test_controller_state_update() {
        let state = Arc::new(StateStore::new());
        state.update("scanning", false, "", None);
        // Should not panic
    }
}

