//! Diagnostics module: project layout, config state, and health checks.
//! Stub conversion of `debug/diagnostics.py`.
//!
//! 2026-11-25: Rust conversion from `debug/diagnostics.py` in the Rust conversion.

use crate::core::config::AppConfig;
use crate::core::logger::AppLogger;
use crate::core::state::StateStore;

pub struct Diagnostics<'a> {
    config: &'a AppConfig,
    state: &'a StateStore,
    logger: &'a AppLogger,
}

impl<'a> Diagnostics<'a> {
    pub fn new(config: &'a AppConfig, state: &'a StateStore, logger: &'a AppLogger) -> Self {
        Diagnostics { config, state, logger }
    }

    /// A multi-line text report suitable for pasting into a support ticket.
    pub fn report(&self) -> String {
        let mut lines: Vec<String> = Vec::new();
        lines.push("DIAGNOSTIC REPORT".to_string());
        lines.push("========================================".to_string());
        lines.push(String::new());
        lines.push(format!("App: Steam Game Organizer"));
        lines.push(format!("Project root: {}", self.config.project_root.display()));
        lines.push(format!(
            "Config dir: {}",
            self.config.config_dir.display()
        ));
        lines.push(format!(
            "Library root: {}",
            self.config
                .library_root
                .as_deref()
                .map_or("None".to_string(), |p| p.display().to_string())
        ));
        lines.push(format!(
            "Library exists: {}",
            self.config
                .library_root
                .as_deref()
                .map_or(false, |p| p.is_dir())
        ));
        lines.push(format!(
            "Developer mode: {}",
            self.config.developer_mode
        ));
        lines.push(String::new());
        lines.push("Settings:".to_string());
        if let Some(settings) = self.config.settings.as_object() {
            for (key, value) in settings {
                lines.push(format!("  {}: {}", key, value));
            }
        }
        lines.push(String::new());
        lines.push("State:".to_string());
        // Stub: StateStore::get() not yet implemented
        lines.push("  scan: n/a".to_string());
        lines.push("  organize: n/a".to_string());
        lines.push("  extract: n/a".to_string());
        lines.push(String::new());
        lines.push(format!(
            "Log file: {}",
            self.config
                .log_file
                .as_deref()
                .map_or("n/a".to_string(), |p| p.display().to_string())
        ));
        lines.push(String::new());
        lines.push("End of report".to_string());
        lines.join("\n")
    }

    /// A dict of health-check results keyed by concern.
    pub fn health(&self) -> serde_json::Value {
        let project_root = &self.config.project_root;
        let library_root = self.config.library_root.as_deref();
        serde_json::json!({
            "project_root": project_root.display().to_string(),
            "project_root_exists": project_root.is_dir(),
            "library_root": library_root.map_or(None, |p| Some(p.display().to_string())),
            "library_root_exists": library_root.map_or(false, |p| p.is_dir()),
        })
    }

    /// A single-line health summary.
    pub fn health_text(&self) -> String {
        let h = self.health();
        let mut parts: Vec<String> = Vec::new();
        parts.push(format!(
            "project_root={}",
            if h["project_root_exists"].as_bool().unwrap_or(false) {
                "ok"
            } else {
                "missing"
            }
        ));
        parts.push(format!(
            "library={}",
            if h["library_root_exists"].as_bool().unwrap_or(false) {
                "ok"
            } else {
                "missing"
            }
        ));
        parts.join(" | ")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_diagnostics_health() {
        let config = AppConfig::new(std::path::Path::new("/tmp"));
        let state = StateStore::new();
        let log_path = std::env::temp_dir().join(format!("test_diag_{}.log", std::process::id()));
        let logger = AppLogger::new(&log_path, "INFO", false, false).unwrap();
        let diag = Diagnostics::new(&config, &state, &logger);
        let text = diag.health_text();
        assert!(text.contains("project_root="));
        assert!(text.contains("library="));
        let _ = std::fs::remove_file(&log_path);
    }

    #[test]
    fn test_diagnostics_report() {
        let config = AppConfig::new(std::path::Path::new("/tmp"));
        let state = StateStore::new();
        let log_path = std::env::temp_dir().join(format!("test_diag2_{}.log", std::process::id()));
        let logger = AppLogger::new(&log_path, "INFO", false, false).unwrap();
        let diag = Diagnostics::new(&config, &state, &logger);
        let report = diag.report();
        assert!(report.contains("DIAGNOSTIC REPORT"));
        assert!(report.contains("End of report"));
        let _ = std::fs::remove_file(&log_path);
    }
}
