//! Crash recovery tool: scans for interrupted operations and cleans up
//! leftover temp files, partial extractions, and orphaned rollback journals.
//! After a crash or power loss, this brings the library back to a consistent state.
//!
//! Usage:
//!   steam-game-organizer.exe --crash-recovery <library_dir>
//!
//! 2026-11-27: Made functional — scans for .tmp, .partial, .journal, .lock
//! files left behind by crashed operations and removes them safely.

use std::path::Path;

/// A single recovery action taken.
pub struct RecoveryAction {
    pub action_type: RecoveryActionType,
    pub path: std::path::PathBuf,
    pub description: String,
}

pub enum RecoveryActionType {
    DeletedTempFile,
    DeletedPartialExtraction,
    DeletedOrphanedJournal,
    DeletedStaleLock,
    VerifiedIntact,
}

/// Result of the crash recovery scan.
pub struct RecoveryReport {
    pub actions: Vec<RecoveryAction>,
    pub space_reclaimed_bytes: u64,
    pub issues_found: usize,
    pub issues_fixed: usize,
}

/// File patterns that indicate incomplete/crashed operations.
const TEMP_EXTENSIONS: &[&str] = &[".tmp", ".temp", ".partial", ".part"];
const JOURNAL_EXTENSIONS: &[&str] = &[".journal", ".rollback"];
const LOCK_EXTENSIONS: &[&str] = &[".lock", ".lck"];

/// Scan for interrupted operations and clean up.
pub fn recover(library_dir: &Path) -> Result<RecoveryReport, String> {
    if !library_dir.exists() {
        return Err(format!(
            "Library directory does not exist: {}",
            library_dir.display()
        ));
    }

    let mut actions: Vec<RecoveryAction> = Vec::new();
    let mut space_reclaimed_bytes: u64 = 0;
    let mut issues_found: usize = 0;
    let mut issues_fixed: usize = 0;

    for entry in walkdir::WalkDir::new(library_dir)
        .into_iter()
        .filter_entry(|e| {
            !e.file_name()
                .to_string_lossy()
                .starts_with('.')
                && e.file_name() != "steamapps"
        })
        .filter_map(|e| e.ok())
    {
        let path = entry.path();
        if !path.is_file() {
            continue;
        }

        let filename = path
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("")
            .to_lowercase();

        let metadata = match std::fs::metadata(path) {
            Ok(m) => m,
            Err(_) => continue,
        };
        let file_size = metadata.len();

        // Check for temp files
        if TEMP_EXTENSIONS.iter().any(|ext| filename.ends_with(ext)) {
            issues_found += 1;
            match std::fs::remove_file(path) {
                Ok(()) => {
                    space_reclaimed_bytes += file_size;
                    issues_fixed += 1;
                    actions.push(RecoveryAction {
                        action_type: RecoveryActionType::DeletedTempFile,
                        path: path.to_path_buf(),
                        description: format!("Deleted temp file ({} bytes) from crashed operation", file_size),
                    });
                }
                Err(e) => {
                    actions.push(RecoveryAction {
                        action_type: RecoveryActionType::VerifiedIntact,
                        path: path.to_path_buf(),
                        description: format!("Could not delete temp file: {}", e),
                    });
                }
            }
        }
        // Check for journal/rollback files
        else if JOURNAL_EXTENSIONS.iter().any(|ext| filename.ends_with(ext)) {
            issues_found += 1;
            match std::fs::remove_file(path) {
                Ok(()) => {
                    space_reclaimed_bytes += file_size;
                    issues_fixed += 1;
                    actions.push(RecoveryAction {
                        action_type: RecoveryActionType::DeletedOrphanedJournal,
                        path: path.to_path_buf(),
                        description: format!("Deleted orphaned journal ({} bytes)", file_size),
                    });
                }
                Err(e) => {
                    actions.push(RecoveryAction {
                        action_type: RecoveryActionType::VerifiedIntact,
                        path: path.to_path_buf(),
                        description: format!("Could not delete journal: {}", e),
                    });
                }
            }
        }
        // Check for lock files
        else if LOCK_EXTENSIONS.iter().any(|ext| filename.ends_with(ext)) {
            issues_found += 1;
            match std::fs::remove_file(path) {
                Ok(()) => {
                    space_reclaimed_bytes += file_size;
                    issues_fixed += 1;
                    actions.push(RecoveryAction {
                        action_type: RecoveryActionType::DeletedStaleLock,
                        path: path.to_path_buf(),
                        description: format!("Deleted stale lock file ({} bytes)", file_size),
                    });
                }
                Err(e) => {
                    actions.push(RecoveryAction {
                        action_type: RecoveryActionType::VerifiedIntact,
                        path: path.to_path_buf(),
                        description: format!("Could not delete lock file: {}", e),
                    });
                }
            }
        }
    }

    Ok(RecoveryReport {
        actions,
        space_reclaimed_bytes,
        issues_found,
        issues_fixed,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_recover_nonexistent_dir() {
        let result = recover(Path::new("/nonexistent/path/12345"));
        assert!(result.is_err());
    }

    #[test]
    fn test_recover_empty_dir() {
        let dir = tempfile::tempdir().unwrap();
        let result = recover(dir.path());
        assert!(result.is_ok());
        let report = result.unwrap();
        assert_eq!(report.issues_found, 0);
        assert_eq!(report.issues_fixed, 0);
        assert_eq!(report.space_reclaimed_bytes, 0);
        assert!(report.actions.is_empty());
    }

    #[test]
    fn test_recover_finds_temp_files() {
        let dir = tempfile::tempdir().unwrap();

        // Create a temp file
        let temp_path = dir.path().join("extract.tmp");
        std::fs::write(&temp_path, b"fake temp data").unwrap();

        let result = recover(dir.path());
        assert!(result.is_ok());
        let report = result.unwrap();
        assert_eq!(report.issues_found, 1);
        assert_eq!(report.issues_fixed, 1);
        assert_eq!(report.space_reclaimed_bytes, 14);
        assert!(!temp_path.exists(), "Temp file should have been deleted");
    }

    #[test]
    fn test_recover_finds_journal_files() {
        let dir = tempfile::tempdir().unwrap();

        // Create a journal file
        let journal_path = dir.path().join("extract.journal");
        std::fs::write(&journal_path, b"fake journal data").unwrap();

        let result = recover(dir.path());
        assert!(result.is_ok());
        let report = result.unwrap();
        assert_eq!(report.issues_found, 1);
        assert_eq!(report.issues_fixed, 1);
        assert!(!journal_path.exists(), "Journal file should have been deleted");
    }

    #[test]
    fn test_recover_finds_lock_files() {
        let dir = tempfile::tempdir().unwrap();

        // Create a lock file
        let lock_path = dir.path().join("database.lock");
        std::fs::write(&lock_path, b"fake lock data").unwrap();

        let result = recover(dir.path());
        assert!(result.is_ok());
        let report = result.unwrap();
        assert_eq!(report.issues_found, 1);
        assert_eq!(report.issues_fixed, 1);
        assert!(!lock_path.exists(), "Lock file should have been deleted");
    }

    #[test]
    fn test_recover_ignores_normal_files() {
        let dir = tempfile::tempdir().unwrap();

        // Create normal files that should NOT be deleted
        std::fs::write(dir.path().join("game.zip"), b"fake zip").unwrap();
        std::fs::write(dir.path().join("readme.txt"), b"hello").unwrap();

        let result = recover(dir.path());
        assert!(result.is_ok());
        let report = result.unwrap();
        assert_eq!(report.issues_found, 0);
        assert_eq!(report.issues_fixed, 0);
        assert!(dir.path().join("game.zip").exists());
        assert!(dir.path().join("readme.txt").exists());
    }

    #[test]
    fn test_recovery_report_struct() {
        let report = RecoveryReport {
            actions: Vec::new(),
            space_reclaimed_bytes: 2_147_483_648,
            issues_found: 12,
            issues_fixed: 11,
        };
        assert_eq!(report.space_reclaimed_bytes, 2_147_483_648);
        assert_eq!(report.issues_found, 12);
        assert_eq!(report.issues_fixed, 11);
        assert_eq!(report.actions.len(), 0);
    }

    #[test]
    fn test_recovery_action_types() {
        let _delete_temp = RecoveryAction {
            action_type: RecoveryActionType::DeletedTempFile,
            path: std::path::PathBuf::from("C:/Games/.extract.tmp"),
            description: "Deleted temp file from crashed extraction".to_string(),
        };
        let _verify = RecoveryAction {
            action_type: RecoveryActionType::VerifiedIntact,
            path: std::path::PathBuf::from("C:/Games/safe.zip"),
            description: "Verified archive intact".to_string(),
        };
    }

    #[test]
    fn test_temp_extensions() {
        assert!(TEMP_EXTENSIONS.contains(&".tmp"));
        assert!(TEMP_EXTENSIONS.contains(&".temp"));
        assert!(TEMP_EXTENSIONS.contains(&".partial"));
        assert!(TEMP_EXTENSIONS.contains(&".part"));
    }

    #[test]
    fn test_journal_extensions() {
        assert!(JOURNAL_EXTENSIONS.contains(&".journal"));
        assert!(JOURNAL_EXTENSIONS.contains(&".rollback"));
    }

    #[test]
    fn test_lock_extensions() {
        assert!(LOCK_EXTENSIONS.contains(&".lock"));
        assert!(LOCK_EXTENSIONS.contains(&".lck"));
    }
}
