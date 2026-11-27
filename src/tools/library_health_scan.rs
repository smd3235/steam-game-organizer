//! Library health scan tool: diagnostics for missing, orphaned, and duplicate games.
//! Reports:
//!   - Archives in library with no Steam match (unidentified)
//!   - Steam matches with no archive file on disk (orphaned entries)
//!   - Categories with zero games (empty categories)
//!   - Archives larger than expected size (possible re-downloads)
//!
//! Usage:
//!   steam-game-organizer.exe --library-health-scan <library_dir>
//!
//! 2026-11-27: New creative tool — gives operators a health dashboard for their
//! game library so they know what's broken before they try to organize.

use std::path::Path;

/// A single health issue found in the library.
pub struct HealthIssue {
    pub severity: HealthSeverity,
    pub category: HealthCategory,
    pub description: String,
    pub path: Option<std::path::PathBuf>,
}

pub enum HealthSeverity {
    Info,
    Warning,
    Error,
}

pub enum HealthCategory {
    Unidentified,
    Orphaned,
    EmptyCategory,
    OversizedArchive,
    Duplicate,
}

/// Result of the library health scan.
pub struct HealthReport {
    pub issues: Vec<HealthIssue>,
    pub archives_scanned: usize,
    pub games_matched: usize,
    pub games_unidentified: usize,
}

/// Scan the library and produce a health report.
pub fn scan_library_health(_library_dir: &Path) -> Result<HealthReport, String> {
    // Stub: real implementation walks archives, checks Steam match status,
    // category assignments, and file sizes.
    Err("library health scan not yet implemented".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_scan_library_health_stub() {
        let result = scan_library_health(Path::new("."));
        assert!(result.is_err());
    }

    #[test]
    fn test_health_report_struct() {
        let report = HealthReport {
            issues: Vec::new(),
            archives_scanned: 150,
            games_matched: 142,
            games_unidentified: 8,
        };
        assert_eq!(report.archives_scanned, 150);
        assert_eq!(report.games_matched, 142);
        assert_eq!(report.games_unidentified, 8);
        assert!(report.issues.is_empty());
    }

    #[test]
    fn test_health_issue_severity() {
        let _info = HealthIssue {
            severity: HealthSeverity::Info,
            category: HealthCategory::EmptyCategory,
            description: "Category 'Indie' has no games".to_string(),
            path: None,
        };
        let _error = HealthIssue {
            severity: HealthSeverity::Error,
            category: HealthCategory::Orphaned,
            description: "Steam match exists but archive file missing".to_string(),
            path: Some(std::path::PathBuf::from("C:/Games/missing.zip")),
        };
    }
}
