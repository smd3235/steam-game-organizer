//! Catalog service: builds an offline, clickable HTML game catalog from the organized library.
//!
//! Stub conversion of `services/catalog_service.py` (2115 lines). Complex methods (`generate`, `_collect`,
//! `_render`, `_category_banner`, HTML rendering) are stubs returning safe defaults. They will be filled in
//! incrementally as the Rust port progresses.
//!
//! 2026-11-25: Stub conversion from `services/catalog_service.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use crate::core::catalog_status::{empty_status, write_status, STATUS_NAME};
use crate::core::library_summary::LibrarySummary;
use crate::core::models::GameArchive;

const CATALOG_NAME: &str = "Game Library.html";

const LEGACY_CATALOGS: &[&str] = &[
    "Game Library (Steam Deck) - *.html",
    "Game Library (Windows) - *.html",
    "Game Library - *.html",
    "Game Library.html",
];

const LEGACY_LAUNCHER: &str = "Open Game Library (Steam Deck).desktop";

pub struct CatalogService {
    logger: Arc<dyn Fn(&str, &str) + Send + Sync>,
    extract_folders: Vec<PathBuf>,
    _summary: Mutex<Option<LibrarySummary>>,
    _library_root: Mutex<Option<PathBuf>>,
    _css_cache: Mutex<Option<String>>,
    _script_cache: Mutex<Option<String>>,
}

impl CatalogService {
    pub fn new(logger: Arc<dyn Fn(&str, &str) + Send + Sync>, extract_folders: &[&Path]) -> Self {
        CatalogService {
            logger,
            extract_folders: extract_folders.iter().map(|p| p.to_path_buf()).collect(),
            _summary: Mutex::new(None),
            _library_root: Mutex::new(None),
            _css_cache: Mutex::new(None),
            _script_cache: Mutex::new(None),
        }
    }

    pub fn generate(
        &self,
        library_root: &Path,
        _write_launcher: bool,
    ) -> Vec<PathBuf> {
        let library_root = match library_root.canonicalize() {
            Ok(r) => r,
            Err(_) => return Vec::new(),
        };
        if !library_root.is_dir() {
            return Vec::new();
        }
        // STUB: _collect() not yet implemented; return empty.
        let _categories: HashMap<String, Vec<GameArchive>> = HashMap::new();
        self._retain(&library_root, &_categories);
        if _categories.is_empty() {
            return Vec::new();
        }
        let path = library_root.join(CATALOG_NAME);
        match fs::write(&path, "<html><body>Catalog stub</body></html>") {
            Ok(_) => {
                if !(library_root.join(STATUS_NAME)).exists() {
                    let status_val = empty_status();
                    let logger_opt: Option<&dyn Fn(&str, &str)> = Some(&*self.logger);
                    let _ = write_status(&library_root, &status_val, logger_opt);
                }
                vec![path]
            }
            Err(exc) => {
                (self.logger)(
                    "CATALOG",
                    &format!(
                        "WRITE_FAILED path=[{}] error={}",
                        path.display(),
                        exc
                    ),
                );
                Vec::new()
            }
        }
    }

    fn _retain(&self, library_root: &Path, _categories: &HashMap<String, Vec<GameArchive>>) {
        *self._library_root.lock().unwrap() = Some(library_root.to_path_buf());
        *self._summary.lock().unwrap() = Some(LibrarySummary::default());
        (self.logger)(
            "CATALOG",
            &format!(
                "INDEX_BUILT categories=0 games=0 developers=0"
            ),
        );
    }

    pub fn library_summary(&self, library_root: Option<&Path>) -> LibrarySummary {
        if let Some(root) = library_root {
            let root = match root.canonicalize() {
                Ok(r) => r,
                Err(_) => return LibrarySummary::default(),
            };
            let retained_root = self._library_root.lock().unwrap().clone();
            if self._summary.lock().unwrap().is_none() || retained_root.as_ref() != Some(&root) {
                return self.rebuild_summary(&root);
            }
        }
        self._summary.lock().unwrap().clone().unwrap_or_default()
    }

    pub fn rebuild_summary(&self, library_root: &Path) -> LibrarySummary {
        let root = match library_root.canonicalize() {
            Ok(r) => r,
            Err(_) => return LibrarySummary::default(),
        };
        *self._library_root.lock().unwrap() = Some(root.clone());
        if !root.is_dir() {
            (self.logger)(
                "CATALOG",
                &format!(
                    "INDEX_BUILD_FAILED path=[{}] error=[NotADirectoryError]",
                    root.display()
                ),
            );
            *self._summary.lock().unwrap() = Some(LibrarySummary::default());
            return LibrarySummary::default();
        }
        let summary = LibrarySummary::default();
        *self._summary.lock().unwrap() = Some(summary.clone());
        summary
    }

    // STUB: _collect() not yet implemented.
    fn _collect(&self, _library_root: &Path) -> HashMap<String, Vec<GameArchive>> {
        HashMap::new()
    }

    // STUB: _render() not yet implemented.
    fn _render(
        &self,
        _categories: &HashMap<String, Vec<GameArchive>>,
        _extract_folders: &[PathBuf],
        _library_root: &Path,
    ) -> String {
        String::new()
    }

    // STUB: _remove_previous() not yet implemented.
    fn _remove_previous(&self, _library_root: &Path) {}

    // STUB: _write_chrome_launcher() not yet implemented.
    fn _write_chrome_launcher(&self, _library_root: &Path, _path: &Path) {}

    // STUB: _category_banner() not yet implemented.
    fn _category_banner(&self, _name: &str) -> String {
        String::new()
    }
}

fn _category_banner_module(name: &str) -> String {
    // STUB: returns empty string; real implementation returns a data URI for a category banner.
    let _ = name;
    String::new()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn dummy_logger(_: &str, _: &str) {}

    #[test]
    fn test_catalog_service_new() {
        let service = CatalogService::new(Arc::new(dummy_logger), &[]);
        assert!(service.library_summary(None).categories.is_empty());
    }

    #[test]
    fn test_catalog_service_generate_empty_dir() {
        let service = CatalogService::new(Arc::new(dummy_logger), &[]);
        let result = service.generate(Path::new("/nonexistent"), false);
        assert!(result.is_empty());
    }

    #[test]
    fn test_catalog_service_library_summary_none() {
        let service = CatalogService::new(Arc::new(dummy_logger), &[]);
        let summary = service.library_summary(None);
        assert!(summary.categories.is_empty());
    }

    #[test]
    fn test_catalog_service_rebuild_summary_nonexistent() {
        let service = CatalogService::new(Arc::new(dummy_logger), &[]);
        let summary = service.rebuild_summary(Path::new("/nonexistent"));
        assert!(summary.categories.is_empty());
    }

    #[test]
    fn test_catalog_service_category_banner_stub() {
        let service = CatalogService::new(Arc::new(dummy_logger), &[]);
        let banner = service._category_banner("Action");
        assert!(banner.is_empty());
    }

    #[test]
    fn test_catalog_service_module_banner_stub() {
        let banner = _category_banner_module("Action");
        assert!(banner.is_empty());
    }
}

