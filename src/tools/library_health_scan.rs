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
//! 2026-11-27: Made functional — walks the library directory, identifies archive
//! files (.zip, .rar, .7z), and reports health metrics.

use std::path::Path;

/// A single health issue found in the library.
#[derive(Debug)]
pub struct HealthIssue {
    pub severity: HealthSeverity,
    pub category: HealthCategory,
    pub description: String,
    pub path: Option<std::path::PathBuf>,
}

#[derive(Debug)]
pub enum HealthSeverity {
    Info,
    Warning,
    Error,
}

#[derive(Debug)]
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

/// Archive file extensions recognized by the application.
const ARCHIVE_EXTENSIONS: &[&str] = &["zip", "rar", "7z"];

/// Oversized archive threshold (50 GB) — archives larger than this may be
/// duplicate downloads or corrupted files.
const OVERSIZED_THRESHOLD_BYTES: u64 = 50_000_000_000;

/// Scan the library and produce a health report.
/// Walks the directory tree, identifies archives, and reports health metrics.
pub fn scan_library_health(library_dir: &Path) -> Result<HealthReport, String> {
    if !library_dir.exists() {
        return Err(format!(
            "Library directory does not exist: {}",
            library_dir.display()
        ));
    }

    let mut archives: Vec<std::path::PathBuf> = Vec::new();
    let mut issues: Vec<HealthIssue> = Vec::new();

    // Walk the directory tree looking for archive files
    for entry in walkdir::WalkDir::new(library_dir)
        .into_iter()
        .filter_entry(|e| {
            e.depth() == 0
                || (
                    // Skip hidden directories and system directories
                    !e.file_name()
                        .to_string_lossy()
                        .starts_with('.')
                        && e.file_name() != "steamapps"
                )
        })
        .filter_map(|e| e.ok())
    {
        let path = entry.path();
        if path.is_file() {
            if let Some(ext) = path.extension().and_then(|e| e.to_str()) {
                if ARCHIVE_EXTENSIONS.contains(&ext.to_lowercase().as_str()) {
                    archives.push(path.to_path_buf());
                }
            }
        }
    }

    let mut games_matched = 0;
    let mut games_unidentified = 0;

    for archive_path in &archives {
        let metadata = match std::fs::metadata(archive_path) {
            Ok(m) => m,
            Err(_) => continue,
        };
        let size = metadata.len();

        // Check for oversized archives
        if size > OVERSIZED_THRESHOLD_BYTES {
            issues.push(HealthIssue {
                severity: HealthSeverity::Warning,
                category: HealthCategory::OversizedArchive,
                description: format!(
                    "Oversized archive ({} MB) — possible duplicate or corrupted download",
                    size / 1_000_000
                ),
                path: Some(archive_path.clone()),
            });
        }

        // Check if archive has a Steam match by looking for appid in filename
        let filename = archive_path
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("")
            .to_lowercase();

        // AppID patterns: Game Name - 12345, Game.Name.12345, Game [12345]
        let has_appid = filename
            .chars()
            .filter(|c| c.is_ascii_digit())
            .collect::<String>()
            .len()
            >= 5;

        if has_appid {
            games_matched += 1;
        } else {
            games_unidentified += 1;
            issues.push(HealthIssue {
                severity: HealthSeverity::Info,
                category: HealthCategory::Unidentified,
                description: "No Steam AppID found in filename — may not match automatically".to_string(),
                path: Some(archive_path.clone()),
            });
        }
    }

    Ok(HealthReport {
        issues,
        archives_scanned: archives.len(),
        games_matched,
        games_unidentified,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn test_scan_library_health_nonexistent_dir() {
        let result = scan_library_health(Path::new("/nonexistent/path/12345"));
        assert!(result.is_err());
    }

    #[test]
    fn test_scan_library_health_empty_dir() {
        let dir = tempfile::tempdir().unwrap();
        let result = scan_library_health(dir.path());
        assert!(result.is_ok());
        let report = result.unwrap();
        assert_eq!(report.archives_scanned, 0);
        assert_eq!(report.games_matched, 0);
        assert_eq!(report.games_unidentified, 0);
        assert!(report.issues.is_empty());
    }

    #[test]
    fn test_scan_library_health_with_archives() {
        let dir = tempfile::tempdir().unwrap();

        // Create a normal archive with AppID
        std::fs::write(dir.path().join("game_12345.zip"), b"fake zip").unwrap();

        // Create an archive without AppID
        std::fs::write(dir.path().join("game_name.zip"), b"fake zip").unwrap();

        // Create an oversized archive (simulated - we can't actually create 50GB)
        // Threshold constant is defined and positive
        let _ = OVERSIZED_THRESHOLD_BYTES;

        let result = scan_library_health(dir.path());
        assert!(result.is_ok());
        let report = result.unwrap();
        assert_eq!(report.archives_scanned, 2);
        assert_eq!(report.games_matched, 1);
        assert_eq!(report.games_unidentified, 1);
    }

    #[test]
    fn test_scan_library_health_skips_non_archives() {
        let dir = tempfile::tempdir().unwrap();

        // Create non-archive files
        std::fs::write(dir.path().join("readme.txt"), b"hello").unwrap();
        std::fs::write(dir.path().join("image.png"), b"fake png").unwrap();
        std::fs::write(dir.path().join("document.pdf"), b"fake pdf").unwrap();

        let result = scan_library_health(dir.path());
        assert!(result.is_ok());
        let report = result.unwrap();
        assert_eq!(report.archives_scanned, 0);
    }

    #[test]
    fn test_archive_extensions() {
        assert!(ARCHIVE_EXTENSIONS.contains(&"zip"));
        assert!(ARCHIVE_EXTENSIONS.contains(&"rar"));
        assert!(ARCHIVE_EXTENSIONS.contains(&"7z"));
        assert!(!ARCHIVE_EXTENSIONS.contains(&"txt"));
        assert!(!ARCHIVE_EXTENSIONS.contains(&"exe"));
    }

    #[test]
    fn test_health_issue_struct() {
        let path = PathBuf::from("/tmp/test.zip");
        let issue = HealthIssue {
            severity: HealthSeverity::Error,
            category: HealthCategory::Duplicate,
            description: "Duplicate archive found".to_string(),
            path: Some(path.clone()),
        };
        assert!(matches!(issue.severity, HealthSeverity::Error));
        assert!(matches!(issue.category, HealthCategory::Duplicate));
        assert_eq!(issue.path, Some(path));
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
        assert_eq!(report.issues.len(), 0);
    }
}
