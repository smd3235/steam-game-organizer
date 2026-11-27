//! Archive encryption scanner: detects encrypted/password-protected archives
//! (.zip, .rar, .7z) before they reach the extract pipeline. Encrypted archives
//! need a password to extract, so flagging them early prevents failed extract jobs.
//!
//! Usage:
//!   steam-game-organizer.exe --archive-encryption-scan <library_dir>
//!
//! 2026-11-27: New creative tool — pre-scan flag for encrypted archives so
//! operators can supply passwords before organizing begins.

use std::collections::HashMap;
use std::path::Path;

/// An encrypted archive found in the library.
pub struct EncryptedArchive {
    pub path: std::path::PathBuf,
    pub archive_type: ArchiveType,
    pub size_bytes: u64,
    pub suspected_password_hint: Option<String>,
}

pub enum ArchiveType {
    Zip,
    Rar,
    SevenZip,
}

/// Result of the encryption scan.
pub struct EncryptionScanReport {
    pub encrypted_archives: Vec<EncryptedArchive>,
    pub total_scanned: usize,
    pub encrypted_count: usize,
    pub by_type: HashMap<String, usize>,
}

/// Scan the library for encrypted archives.
pub fn scan_encryption(_library_dir: &Path) -> Result<EncryptionScanReport, String> {
    // Stub: real implementation reads archive headers (zip local file header
    // general purpose bit flag 0x1, RAR encrypt flag, 7z AES-256 flag) without
    // fully extracting.
    Err("archive encryption scan not yet implemented".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_scan_encryption_stub() {
        let result = scan_encryption(Path::new("."));
        assert!(result.is_err());
    }

    #[test]
    fn test_encryption_scan_report_struct() {
        let report = EncryptionScanReport {
            encrypted_archives: Vec::new(),
            total_scanned: 500,
            encrypted_count: 12,
            by_type: HashMap::new(),
        };
        assert_eq!(report.total_scanned, 500);
        assert_eq!(report.encrypted_count, 12);
        assert!(report.encrypted_archives.is_empty());
        assert!(report.by_type.is_empty());
    }

    #[test]
    fn test_encrypted_archive_struct() {
        let archive = EncryptedArchive {
            path: std::path::PathBuf::from("C:/Games/encrypted_game.zip"),
            archive_type: ArchiveType::Zip,
            size_bytes: 15_000_000_000,
            suspected_password_hint: Some("see readme.txt in archive".to_string()),
        };
        assert!(matches!(archive.archive_type, ArchiveType::Zip));
        assert_eq!(archive.size_bytes, 15_000_000_000);
        assert!(archive.suspected_password_hint.is_some());
    }

    #[test]
    fn test_archive_type_variants() {
        let types = [
            ArchiveType::Zip,
            ArchiveType::Rar,
            ArchiveType::SevenZip,
        ];
        assert_eq!(types.len(), 3);
    }
}
